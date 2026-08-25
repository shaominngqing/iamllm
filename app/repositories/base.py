from __future__ import annotations

from typing import Any, Protocol


class HumanRequestRepository(Protocol):
    """Storage operations required by request creation and live streaming."""

    def get_conversation(
        self, conversation_id: str, *, owner_token: str | None = None
    ) -> dict[str, Any] | None: ...

    def add_conversation_message(
        self,
        *,
        message_id: str,
        conversation_id: str,
        role: str,
        content: Any,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        request_id: str | None = None,
    ) -> None: ...

    def conversation_messages_for_api(
        self, conversation_id: str
    ) -> list[dict[str, Any]]: ...

    def conversation_has_pending(self, conversation_id: str) -> bool: ...

    def create_request(
        self,
        *,
        request_id: str,
        model: str,
        messages: list[dict[str, Any]],
        mode: str,
        expires_at: int,
        conversation_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        source: str = "api",
        stream_requested: bool = False,
        api_key_id: str | None = None,
    ) -> dict[str, Any]: ...

    def get_request(self, request_id: str) -> dict[str, Any] | None: ...

    def touch_client_connection(self, request_id: str) -> None: ...

    def list_stream_chunks(
        self, request_id: str, *, after_position: int = 0
    ) -> list[dict[str, Any]]: ...

    def finalize_stream_request(
        self,
        request_id: str,
        message_id: str,
        *,
        answer_source: str = "human_stream",
        owner_id: str | None = None,
    ) -> bool: ...

    def answer_request(
        self,
        request_id: str,
        response_message: dict[str, Any],
        message_id: str,
        *,
        answer_source: str = "human",
        owner_id: str | None = None,
    ) -> bool: ...

    def expire_request(self, request_id: str) -> None: ...
