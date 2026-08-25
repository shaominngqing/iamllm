from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any

from fastapi import HTTPException, status

from app.config import Settings
from app.notifications import build_new_request_notification
from app.repositories import HumanRequestRepository
from app.schemas import ChatCompletionRequest, ChatMessage


logger = logging.getLogger("iamllm.human_requests")


class HumanRequestService:
    """Create human jobs and publish their arrival to optional notifications."""

    def __init__(
        self,
        settings: Settings,
        database: HumanRequestRepository,
        notification_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        self.settings = settings
        self.database = database
        self.notification_queue = notification_queue

    def enqueue_notification(self, payload: dict[str, Any]) -> bool:
        if not self.settings.notification_webhook_url:
            return False
        try:
            self.notification_queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            logger.warning("notification queue is full; dropping notification")
            return False

    def enqueue_new_request_notification(self, row: dict[str, Any]) -> None:
        self.enqueue_notification(
            build_new_request_notification(
                row, public_base_url=self.settings.public_base_url
            )
        )

    @staticmethod
    def _internal_auto_reply(row: dict[str, Any]) -> str | None:
        """Return a protocol-safe default for Codex client housekeeping calls."""
        if row.get("source") != "openai_responses":
            return None
        kind = row.get("request_kind")
        replies = {
            "memory": (
                '{"raw_memory":"","rollout_summary":"本轮没有需要长期保存的记忆。",'
                '"rollout_slug":""}'
            ),
            "suggestions": "[]",
            "title": "新对话",
            "utility": "[]",
            "recap": (
                "Continue the current task using the existing conversation context. "
                "Await the user's next instruction."
            ),
            "bootstrap": "Ready.",
        }
        return replies.get(str(kind))

    def _auto_answer_internal(self, row: dict[str, Any]) -> dict[str, Any]:
        content = self._internal_auto_reply(row)
        if content is None or row.get("status") != "pending":
            return row
        answered = self.database.answer_request(
            str(row["id"]),
            {"role": "assistant", "content": content},
            f"msg_internal_{secrets.token_urlsafe(10)}",
            answer_source="internal_automation",
        )
        if not answered:
            return row
        return self.database.get_request(str(row["id"])) or row

    def process_internal_requests(self, *, limit: int = 300) -> int:
        """Settle housekeeping calls created before this process started."""
        completed = 0
        for row in self.database.list_request_summaries(
            status="pending", limit=limit
        ):
            if self._internal_auto_reply(row) is None:
                continue
            result = self._auto_answer_internal(row)
            if result.get("status") == "answered":
                completed += 1
        return completed

    def _validate_model(
        self, payload: ChatCompletionRequest, *, allow_model_alias: bool
    ) -> None:
        if allow_model_alias:
            if not payload.model.strip():
                raise HTTPException(status_code=400, detail="model must not be empty")
            return
        if payload.model != self.settings.model_name:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown model: {payload.model}",
            )

    def _add_messages_to_conversation(
        self, conversation_id: str, messages: list[ChatMessage]
    ) -> None:
        for message in messages:
            self.database.add_conversation_message(
                message_id=f"msg_{secrets.token_urlsafe(10)}",
                conversation_id=conversation_id,
                role=message.role,
                content=message.model_dump(mode="json")["content"],
                tool_call_id=message.tool_call_id,
                tool_calls=message.tool_calls,
            )

    def create(
        self,
        payload: ChatCompletionRequest,
        *,
        mode: str,
        ttl_seconds: int,
        source: str = "api",
        stream_requested: bool = False,
        request_prefix: str = "chatcmpl",
        allow_model_alias: bool = False,
        api_key_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_model(payload, allow_model_alias=allow_model_alias)
        incoming = [message.model_dump(mode="json") for message in payload.messages]
        conversation_id = payload.conversation_id
        if conversation_id:
            conversation = self.database.get_conversation(
                conversation_id, owner_token="api"
            )
            if not conversation:
                raise HTTPException(status_code=404, detail="Conversation not found")
            if self.database.conversation_has_pending(conversation_id):
                raise HTTPException(
                    status_code=409,
                    detail="This conversation already has a pending human response",
                )
            self._add_messages_to_conversation(conversation_id, payload.messages)
            messages = self.database.conversation_messages_for_api(conversation_id)
        else:
            messages = incoming

        request_id = f"{request_prefix}_{secrets.token_urlsafe(12)}"
        row = self.database.create_request(
            request_id=request_id,
            model=payload.model,
            messages=messages,
            mode=mode,
            expires_at=int(time.time()) + ttl_seconds,
            conversation_id=conversation_id,
            tools=[tool.model_dump(mode="json") for tool in payload.tools],
            source=source,
            stream_requested=stream_requested,
            api_key_id=api_key_id,
        )
        row = self._auto_answer_internal(row)
        if row["status"] == "pending":
            self.enqueue_new_request_notification(row)
        return row
