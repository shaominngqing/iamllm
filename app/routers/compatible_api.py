from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import ValidationError

from app.config import Settings
from app.database import Database
from app.protocols import (
    AnthropicMessagesRequest,
    GeminiCountTokensRequest,
    GeminiGenerateRequest,
    ResponsesCreateRequest,
    anthropic_message_payload,
    gemini_response_payload,
    normalize_anthropic_messages,
    normalize_anthropic_tools,
    normalize_gemini_messages,
    normalize_gemini_tools,
    normalize_responses_messages,
    normalize_responses_tools,
    openai_response_payload,
    rough_token_count,
)
from app.schemas import ChatCompletionRequest
from app.security import (
    require_api_key,
    require_compatible_api_key,
    require_google_api_key,
)
from app.services.human_requests import HumanRequestService
from app.services.streaming import (
    anthropic_stream,
    chat_completion,
    completion_stream,
    gemini_stream,
    pick_timeout_fallback,
    responses_stream,
    wait_for_human_answer,
)


def create_compatible_api_router(
    settings: Settings,
    database: Database,
    human_requests: HumanRequestService,
) -> APIRouter:
    application = APIRouter()
    create_human_request = human_requests.create

    @application.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/chat", status_code=status.HTTP_303_SEE_OTHER)

    @application.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model": settings.model_name,
            "pending": database.pending_count(),
            "capabilities": [
                "text",
                "image_input",
                "conversation_state",
                "streaming",
                "function_calling",
                "human_skills",
                "quick_replies",
                "scheduled_auto_replies",
                "openai_responses",
                "anthropic_messages",
                "gemini_generate_content",
            ],
        }

    def model_record(model_id: str | None = None) -> dict[str, Any]:
        profile = database.get_profile()
        return {
            "id": model_id or settings.model_name,
            "object": "model",
            "created": 0,
            "owned_by": "human",
            "metadata": {
                "display_name": profile["display_name"],
                "bio": profile["bio"],
                "availability": profile["availability"],
                "skills": profile["skills"],
                "capabilities": [
                    "text",
                    "vision",
                    "stateful_conversations",
                    "streaming",
                    "function_calling",
                    "openai_responses",
                    "anthropic_messages",
                    "gemini_generate_content",
                ],
            },
        }

    @application.get(
        "/v1/models", dependencies=[Depends(require_compatible_api_key)]
    )
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": [model_record()]}

    @application.get(
        "/v1/models/{model_name}",
        dependencies=[Depends(require_compatible_api_key)],
    )
    async def retrieve_model(model_name: str) -> dict[str, Any]:
        if not model_name.strip():
            raise HTTPException(status_code=404, detail="Model not found")
        return model_record(model_name)

    @application.post(
        "/v1/chat/completions", dependencies=[Depends(require_api_key)]
    )
    async def chat_completions(payload: ChatCompletionRequest, request: Request):
        row = create_human_request(
            payload,
            mode="sync",
            ttl_seconds=settings.response_timeout_seconds,
            stream_requested=payload.stream,
            allow_model_alias=True,
            api_key_id=getattr(request.state, "api_key_id", None),
        )
        if payload.stream:
            return StreamingResponse(
                completion_stream(database, row, settings),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "X-Human-Request-ID": row["id"],
                },
            )
        answered = await wait_for_human_answer(database, row, settings)
        if answered:
            return chat_completion(answered)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "message": "The human did not answer before the request timed out",
                "request_id": row["id"],
            },
            headers={"X-Human-Request-ID": row["id"]},
        )

    def normalized_chat_request(
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        stream: bool,
        conversation_id: str | None = None,
    ) -> ChatCompletionRequest:
        try:
            return ChatCompletionRequest.model_validate(
                {
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "stream": stream,
                    "conversation_id": conversation_id,
                }
            )
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {"msg": "Invalid request"}
            raise HTTPException(status_code=400, detail=first.get("msg")) from exc

    def response_conversation_id(payload: ResponsesCreateRequest) -> str | None:
        if payload.previous_response_id and payload.conversation:
            raise HTTPException(
                status_code=400,
                detail="previous_response_id and conversation cannot be used together",
            )
        if not payload.conversation:
            return None
        conversation_id = (
            payload.conversation
            if isinstance(payload.conversation, str)
            else payload.conversation.get("id")
        )
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise HTTPException(status_code=400, detail="conversation.id is required")
        existing = database.get_conversation(conversation_id, owner_token="api")
        if not existing:
            database.create_conversation(
                conversation_id=conversation_id,
                owner_token="api",
                title="Responses API 对话",
            )
        return conversation_id

    def response_messages(payload: ResponsesCreateRequest) -> list[dict[str, Any]]:
        current_messages = normalize_responses_messages(payload)
        if not payload.previous_response_id:
            return current_messages

        previous = database.get_request(payload.previous_response_id)
        if not previous or not payload.previous_response_id.startswith("resp_"):
            raise HTTPException(status_code=404, detail="Previous response not found")
        if previous["status"] != "answered":
            raise HTTPException(
                status_code=409,
                detail="Previous response has not completed yet",
            )
        instructions = [
            message
            for message in current_messages
            if message.get("role") in {"system", "developer"}
        ]
        new_input = [
            message
            for message in current_messages
            if message.get("role") not in {"system", "developer"}
        ]
        history = [
            message
            for message in previous["messages"]
            if message.get("role") not in {"system", "developer"}
        ]
        previous_answer = previous["response"] or {
            "role": "assistant",
            "content": previous["answer"],
        }
        return [*instructions, *history, previous_answer, *new_input]

    def unsupported_tool_note(
        requested: list[dict[str, Any]], normalized: list[dict[str, Any]], label: str
    ) -> dict[str, Any] | None:
        if len(requested) == len(normalized):
            return None
        unsupported = [
            str(tool.get("type") or tool.get("name") or "unknown")
            for tool in requested
            if not (
                (label == "Responses" and tool.get("type") == "function" and tool.get("name"))
                or (
                    label == "Claude"
                    and tool.get("name")
                    and isinstance(tool.get("input_schema"), dict)
                )
            )
        ]
        return {
            "role": "system",
            "content": (
                f"调用方还声明了 {label} 原生服务端工具："
                f"{', '.join(unsupported)}。真人后端不会冒充这些托管工具执行，"
                "但可以直接根据现有上下文回答。"
            ),
        }

    @application.post(
        "/v1/responses", dependencies=[Depends(require_api_key)]
    )
    async def create_response(payload: ResponsesCreateRequest, request: Request):
        messages = response_messages(payload)
        tools = normalize_responses_tools(payload.tools)
        note = unsupported_tool_note(payload.tools, tools, "Responses")
        if note:
            messages.insert(0, note)
        if not messages:
            raise HTTPException(status_code=400, detail="input is required")
        conversation_id = response_conversation_id(payload)
        normalized = normalized_chat_request(
            model=payload.model,
            messages=messages,
            tools=tools,
            stream=payload.stream,
            conversation_id=conversation_id,
        )
        if payload.background and payload.stream:
            raise HTTPException(
                status_code=400,
                detail="This human backend does not combine background and stream",
            )
        row = create_human_request(
            normalized,
            mode="async" if payload.background else "sync",
            ttl_seconds=(
                settings.job_ttl_seconds
                if payload.background
                else settings.response_timeout_seconds
            ),
            source="openai_responses",
            stream_requested=payload.stream,
            request_prefix="resp",
            allow_model_alias=True,
            api_key_id=getattr(request.state, "api_key_id", None),
        )
        response_headers = {
            "X-Request-ID": row["id"],
            "X-Human-Request-ID": row["id"],
        }
        if payload.background:
            return JSONResponse(
                content=openai_response_payload(
                    row,
                    previous_response_id=payload.previous_response_id,
                    instructions=payload.instructions,
                    background=True,
                    metadata=payload.metadata,
                    store=payload.store,
                    max_output_tokens=payload.max_output_tokens,
                ),
                headers=response_headers,
            )
        if payload.stream:
            return StreamingResponse(
                responses_stream(database, row, settings, payload),
                media_type="text/event-stream",
                headers={
                    **response_headers,
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        answered = await wait_for_human_answer(database, row, settings)
        if answered:
            return JSONResponse(
                content=openai_response_payload(
                    answered,
                    previous_response_id=payload.previous_response_id,
                    instructions=payload.instructions,
                    metadata=payload.metadata,
                    store=payload.store,
                    max_output_tokens=payload.max_output_tokens,
                ),
                headers=response_headers,
            )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The human did not answer before the request timed out",
            headers=response_headers,
        )

    @application.get(
        "/v1/responses/{response_id}", dependencies=[Depends(require_api_key)]
    )
    async def retrieve_response(response_id: str) -> JSONResponse:
        row = database.get_request(response_id)
        if not row or not response_id.startswith("resp_"):
            raise HTTPException(status_code=404, detail="Response not found")
        return JSONResponse(
            content=openai_response_payload(row),
            headers={
                "X-Request-ID": row["id"],
                "X-Human-Request-ID": row["id"],
            },
        )

    @application.post(
        "/v1/messages/count_tokens",
        dependencies=[Depends(require_compatible_api_key)],
    )
    async def count_anthropic_tokens(
        payload: AnthropicMessagesRequest,
    ) -> dict[str, int]:
        messages = normalize_anthropic_messages(payload)
        return {"input_tokens": rough_token_count(messages)}

    @application.post(
        "/v1/messages", dependencies=[Depends(require_compatible_api_key)]
    )
    async def anthropic_messages(
        payload: AnthropicMessagesRequest, request: Request
    ):
        messages = normalize_anthropic_messages(payload)
        tools = normalize_anthropic_tools(payload.tools)
        note = unsupported_tool_note(payload.tools, tools, "Claude")
        if note:
            messages.insert(0, note)
        if not messages:
            raise HTTPException(status_code=400, detail="messages are required")
        normalized = normalized_chat_request(
            model=payload.model,
            messages=messages,
            tools=tools,
            stream=payload.stream,
        )
        row = create_human_request(
            normalized,
            mode="sync",
            ttl_seconds=settings.response_timeout_seconds,
            source="anthropic_messages",
            stream_requested=payload.stream,
            request_prefix="msg",
            allow_model_alias=True,
            api_key_id=getattr(request.state, "api_key_id", None),
        )
        response_headers = {
            "request-id": row["id"],
            "X-Human-Request-ID": row["id"],
        }
        if payload.stream:
            return StreamingResponse(
                anthropic_stream(database, row, settings),
                media_type="text/event-stream",
                headers={
                    **response_headers,
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        answered = await wait_for_human_answer(database, row, settings)
        if answered:
            return JSONResponse(
                content=anthropic_message_payload(answered),
                headers=response_headers,
            )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The human did not answer before the request timed out",
            headers=response_headers,
        )

    def create_gemini_human_request(
        model_name: str,
        payload: GeminiGenerateRequest,
        *,
        stream: bool,
        api_key_id: str | None,
    ) -> dict[str, Any]:
        messages = normalize_gemini_messages(payload)
        tools = normalize_gemini_tools(payload.tools)
        unsupported_groups = [
            key
            for group in payload.tools
            for key in group
            if key not in {"functionDeclarations", "function_declarations"}
        ]
        if unsupported_groups:
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "调用方还声明了 Gemini 原生服务端工具："
                        f"{', '.join(unsupported_groups)}。真人后端不会冒充托管工具执行，"
                        "但可以直接根据现有上下文回答。"
                    ),
                },
            )
        if not messages:
            raise HTTPException(status_code=400, detail="contents are required")
        normalized = normalized_chat_request(
            model=model_name,
            messages=messages,
            tools=tools,
            stream=stream,
        )
        return create_human_request(
            normalized,
            mode="sync",
            ttl_seconds=settings.response_timeout_seconds,
            source="gemini_generate_content",
            stream_requested=stream,
            request_prefix="gemini",
            allow_model_alias=True,
            api_key_id=api_key_id,
        )

    @application.post(
        "/v1beta/models/{model_name}:generateContent",
        dependencies=[Depends(require_google_api_key)],
    )
    @application.post(
        "/v1/models/{model_name}:generateContent",
        dependencies=[Depends(require_google_api_key)],
    )
    async def gemini_generate_content(
        model_name: str, payload: GeminiGenerateRequest, request: Request
    ) -> JSONResponse:
        row = create_gemini_human_request(
            model_name,
            payload,
            stream=False,
            api_key_id=getattr(request.state, "api_key_id", None),
        )
        response_headers = {
            "x-goog-request-id": row["id"],
            "X-Human-Request-ID": row["id"],
        }
        answered = await wait_for_human_answer(database, row, settings)
        if answered:
            return JSONResponse(
                content=gemini_response_payload(answered),
                headers=response_headers,
            )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The human did not answer before the request timed out",
            headers=response_headers,
        )

    @application.post(
        "/v1beta/models/{model_name}:streamGenerateContent",
        dependencies=[Depends(require_google_api_key)],
    )
    @application.post(
        "/v1/models/{model_name}:streamGenerateContent",
        dependencies=[Depends(require_google_api_key)],
    )
    async def gemini_stream_generate_content(
        model_name: str, payload: GeminiGenerateRequest, request: Request
    ) -> StreamingResponse:
        row = create_gemini_human_request(
            model_name,
            payload,
            stream=True,
            api_key_id=getattr(request.state, "api_key_id", None),
        )
        return StreamingResponse(
            gemini_stream(database, row, settings),
            media_type="text/event-stream",
            headers={
                "x-goog-request-id": row["id"],
                "X-Human-Request-ID": row["id"],
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @application.post(
        "/v1beta/models/{model_name}:countTokens",
        dependencies=[Depends(require_google_api_key)],
    )
    @application.post(
        "/v1/models/{model_name}:countTokens",
        dependencies=[Depends(require_google_api_key)],
    )
    async def gemini_count_tokens(
        model_name: str, payload: GeminiCountTokensRequest
    ) -> dict[str, int]:
        del model_name
        request_body = payload.generate_content_request or {
            "contents": payload.contents or []
        }
        try:
            generation = GeminiGenerateRequest.model_validate(request_body)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {"msg": "Invalid request"}
            raise HTTPException(status_code=400, detail=first.get("msg")) from exc
        return {"totalTokens": rough_token_count(normalize_gemini_messages(generation))}

    @application.post(
        "/v1/human/jobs",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_api_key)],
    )
    async def create_job(
        payload: ChatCompletionRequest, request: Request
    ) -> dict[str, Any]:
        row = create_human_request(
            payload,
            mode="async",
            ttl_seconds=settings.job_ttl_seconds,
            api_key_id=getattr(request.state, "api_key_id", None),
        )
        return {
            "id": row["id"],
            "object": "human.job",
            "status": row["status"],
            "conversation_id": row.get("conversation_id"),
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "status_url": f"/v1/human/jobs/{row['id']}",
        }

    @application.get(
        "/v1/human/jobs/{request_id}", dependencies=[Depends(require_api_key)]
    )
    async def get_job(request_id: str) -> dict[str, Any]:
        database.settle_due_requests(pick_timeout_fallback(settings))
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Human job not found")
        result: dict[str, Any] = {
            "id": row["id"],
            "object": "human.job",
            "status": row["status"],
            "conversation_id": row.get("conversation_id"),
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }
        if row["status"] == "answered":
            result["response"] = chat_completion(row)
        return result

    @application.post(
        "/v1/human/conversations",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_api_key)],
    )
    async def create_api_conversation() -> dict[str, Any]:
        conversation = database.create_conversation(
            conversation_id=f"conv_{secrets.token_urlsafe(12)}",
            owner_token="api",
        )
        return {
            "id": conversation["id"],
            "object": "human.conversation",
            "title": conversation["title"],
            "created_at": conversation["created_at"],
        }

    @application.get(
        "/v1/human/conversations/{conversation_id}",
        dependencies=[Depends(require_api_key)],
    )
    async def get_api_conversation(conversation_id: str) -> dict[str, Any]:
        conversation = database.get_conversation(
            conversation_id, owner_token="api"
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {
            "id": conversation["id"],
            "object": "human.conversation",
            "title": conversation["title"],
            "messages": conversation["messages"],
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
        }

    return application
