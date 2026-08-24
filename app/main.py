from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Literal

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import Settings
from app.database import Database
from app.notifications import build_new_request_notification, notification_worker


APP_DIR = Path(__file__).parent
VISITOR_COOKIE = "iamllm_visitor"
ADMIN_COOKIE = "iamllm_admin_session"
logger = logging.getLogger("iamllm")


class TextContentPart(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=50_000)


class ImageURLValue(BaseModel):
    url: str = Field(min_length=1, max_length=8_500_000)
    detail: Literal["auto", "low", "high"] | None = None

    @field_validator("url")
    @classmethod
    def validate_image_url(cls, value: str) -> str:
        allowed = ("https://", "http://", "data:image/", "/uploads/")
        if not value.startswith(allowed):
            raise ValueError("image_url must be http(s), an image data URL, or /uploads")
        return value


class ImageContentPart(BaseModel):
    type: Literal["image_url"]
    image_url: ImageURLValue


ContentPart = TextContentPart | ImageContentPart


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["developer", "system", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def validate_message(self) -> "ChatMessage":
        if self.content is None and not self.tool_calls:
            raise ValueError("message content is required unless tool_calls are present")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool messages require tool_call_id")
        return self


class FunctionDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str | None = Field(default=None, max_length=2_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    strict: bool | None = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["function"]
    function: FunctionDefinition


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    user: str | None = None
    tools: list[ToolDefinition] = Field(default_factory=list, max_length=32)
    tool_choice: Any = None
    conversation_id: str | None = None


class PublicChatMessage(BaseModel):
    text: str = Field(default="", max_length=20_000)
    image_urls: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("image_urls")
    @classmethod
    def validate_uploaded_urls(cls, values: list[str]) -> list[str]:
        if any(not value.startswith("/uploads/") for value in values):
            raise ValueError("Only images uploaded to this service are accepted")
        return values

    @model_validator(mode="after")
    def require_content(self) -> "PublicChatMessage":
        if not self.text.strip() and not self.image_urls:
            raise ValueError("A message or image is required")
        return self


class AdminAnswerPayload(BaseModel):
    response_type: Literal["text", "tool_call"] = "text"
    text: str = Field(default="", max_length=50_000)
    tool_name: str = Field(default="", max_length=64)
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    operator_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{12,100}$"
    )


class StreamChunkPayload(BaseModel):
    content: str = Field(max_length=50_000)
    operator_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{12,100}$"
    )

    @field_validator("content")
    @classmethod
    def require_visible_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("流式片段不能为空")
        return value


class AdminOperatorPayload(BaseModel):
    operator_id: str = Field(pattern=r"^[A-Za-z0-9_-]{12,100}$")


class QuickReplyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=5_000)
    category: str = Field(default="常用", min_length=1, max_length=40)
    active: bool = True


class QuickReplyPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    content: str | None = Field(default=None, min_length=1, max_length=5_000)
    category: str | None = Field(default=None, min_length=1, max_length=40)
    active: bool | None = None


class AutoRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    rule_type: Literal["keyword", "schedule"]
    match_type: Literal["contains", "exact"] | None = None
    pattern: str | None = Field(default=None, max_length=200)
    response_text: str = Field(min_length=1, max_length=5_000)
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    delay_seconds: int = Field(default=3, ge=0, le=86_400)
    priority: int = Field(default=0, ge=-1000, le=1000)
    active: bool = False

    @field_validator("days")
    @classmethod
    def validate_days(cls, values: list[int]) -> list[int]:
        if any(value < 0 or value > 6 for value in values):
            raise ValueError("days must contain weekday numbers from 0 to 6")
        return sorted(set(values))

    @model_validator(mode="after")
    def validate_rule_fields(self) -> "AutoRuleCreate":
        if self.rule_type == "keyword" and not (self.pattern or "").strip():
            raise ValueError("keyword rules require a pattern")
        if self.rule_type == "schedule" and not (self.start_time and self.end_time):
            raise ValueError("schedule rules require a start and end time")
        return self


class AutoRulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    rule_type: Literal["keyword", "schedule"] | None = None
    match_type: Literal["contains", "exact"] | None = None
    pattern: str | None = Field(default=None, max_length=200)
    response_text: str | None = Field(default=None, min_length=1, max_length=5_000)
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days: list[int] | None = Field(default=None, min_length=1, max_length=7)
    delay_seconds: int | None = Field(default=None, ge=0, le=86_400)
    priority: int | None = Field(default=None, ge=-1000, le=1000)
    active: bool | None = None

    @field_validator("days")
    @classmethod
    def validate_days(cls, values: list[int] | None) -> list[int] | None:
        if values is not None and any(value < 0 or value > 6 for value in values):
            raise ValueError("days must contain weekday numbers from 0 to 6")
        return sorted(set(values)) if values is not None else None


class AutoRulePreviewPayload(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class ProfilePayload(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    bio: str = Field(min_length=1, max_length=2_000)
    availability: str = Field(default="", max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, values: list[str]) -> list[str]:
        return [value.strip()[:100] for value in values if value.strip()]


def _format_timestamp(value: int | None) -> str:
    if value is None:
        return "—"
    if value > 10_000_000_000:
        value = value // 1000
    return datetime.fromtimestamp(value).astimezone().strftime("%m-%d %H:%M:%S")


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _admin_cookie(settings: Settings) -> str:
    return hmac.new(
        settings.session_secret.encode(), b"iamllm-admin", hashlib.sha256
    ).hexdigest()


def _new_visitor_cookie(settings: Settings) -> tuple[str, str]:
    token = secrets.token_urlsafe(24)
    signature = hmac.new(
        settings.session_secret.encode(), token.encode(), hashlib.sha256
    ).hexdigest()
    return token, f"{token}.{signature}"


def _visitor_token(cookie: str | None, settings: Settings) -> str | None:
    if not cookie or "." not in cookie:
        return None
    token, signature = cookie.rsplit(".", 1)
    expected = hmac.new(
        settings.session_secret.encode(), token.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return token


def _chat_completion(row: dict[str, Any]) -> dict[str, Any]:
    message = row["response"] or {"role": "assistant", "content": row["answer"]}
    finish_reason = "tool_calls" if message.get("tool_calls") else "stop"
    result = {
        "id": row["id"],
        "object": "chat.completion",
        "created": row["created_at"],
        "model": row["model"],
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
    }
    if row.get("conversation_id"):
        result["conversation_id"] = row["conversation_id"]
    if row.get("answer_source"):
        result["human_metadata"] = {"answer_source": row["answer_source"]}
    return result


def _stream_event(data: dict[str, Any] | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _stream_base(current: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": current["id"],
        "object": "chat.completion.chunk",
        "created": current["created_at"],
        "model": current["model"],
    }


def _stream_role_event(current: dict[str, Any]) -> str:
    return _stream_event(
        {
            **_stream_base(current),
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }
            ],
            "human_metadata": {"answer_source": "human_stream"},
        }
    )


def _stream_content_event(current: dict[str, Any], content: str) -> str:
    return _stream_event(
        {
            **_stream_base(current),
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": None,
                }
            ],
        }
    )


def _stream_finish_events(
    current: dict[str, Any], *, finish_reason: str = "stop"
) -> list[str]:
    return [
        _stream_event(
            {
                **_stream_base(current),
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": finish_reason}
                ],
                "human_metadata": {
                    "answer_source": current.get("answer_source") or "human"
                },
            }
        ),
        _stream_event("[DONE]"),
    ]


def _stream_answer_events(
    current: dict[str, Any], *, include_role: bool = True
) -> list[str]:
    message = current["response"] or {
        "role": "assistant",
        "content": current["answer"],
    }
    events: list[str] = []
    if include_role:
        events.append(_stream_role_event(current))
    if message.get("content") is not None:
        events.append(_stream_content_event(current, message["content"]))
    if message.get("tool_calls"):
        events.append(
            _stream_event(
                {
                    **_stream_base(current),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {"index": index, **tool_call}
                                    for index, tool_call in enumerate(
                                        message["tool_calls"]
                                    )
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )
        )
    events.extend(
        _stream_finish_events(
            current,
            finish_reason="tool_calls" if message.get("tool_calls") else "stop",
        )
    )
    return events


def _pick_timeout_fallback(settings: Settings) -> str:
    options = [
        option.strip()
        for option in settings.timeout_fallback_text.split("||")
        if option.strip()
    ]
    return secrets.choice(options) if options else ""


def _settle_sync_timeout(
    database: Database,
    row: dict[str, Any],
    settings: Settings,
) -> dict[str, Any] | None:
    current = database.get_request(row["id"])
    if current and current["status"] == "answered":
        return current
    if current and current["stream_chunk_count"]:
        database.finalize_stream_request(
            row["id"],
            f"msg_timeout_partial_{row['id']}",
            answer_source="human_timeout_partial",
        )
        partial = database.get_request(row["id"])
        if partial and partial["status"] == "answered":
            return partial
    timeout_fallback = _pick_timeout_fallback(settings)
    if timeout_fallback:
        database.answer_request(
            row["id"],
            {"role": "assistant", "content": timeout_fallback},
            f"msg_timeout_{row['id']}",
            answer_source="timeout_fallback",
        )
        current = database.get_request(row["id"])
        if current and current["status"] == "answered":
            return current
    database.expire_request(row["id"])
    return None


async def _completion_stream(
    database: Database,
    row: dict[str, Any],
    settings: Settings,
) -> AsyncIterator[str]:
    last_position = 0
    last_keepalive = time.monotonic()
    live_stream = bool(row.get("stream_requested"))
    if live_stream:
        yield _stream_role_event(row)
    while True:
        if live_stream:
            database.touch_client_connection(row["id"])
        current = database.get_request(row["id"])
        if live_stream:
            chunks = database.list_stream_chunks(
                row["id"], after_position=last_position
            )
            for chunk in chunks:
                yield _stream_content_event(current or row, chunk["content"])
                last_position = chunk["position"]
        if current and current["status"] == "answered":
            if live_stream and last_position:
                events = _stream_finish_events(current)
            else:
                events = _stream_answer_events(
                    current, include_role=not live_stream
                )
            for event in events:
                yield event
            return
        if (
            not current
            or current["status"] == "expired"
            or current["expires_at"] <= int(time.time())
        ):
            break
        if time.monotonic() - last_keepalive >= settings.stream_keepalive_seconds:
            yield ": 真人模型还在输入框附近\n\n"
            last_keepalive = time.monotonic()
        await asyncio.sleep(settings.poll_interval_seconds)

    if live_stream:
        final_chunks = database.list_stream_chunks(
            row["id"], after_position=last_position
        )
        for chunk in final_chunks:
            yield _stream_content_event(row, chunk["content"])
            last_position = chunk["position"]
        timed_current = database.get_request(row["id"])
        if timed_current and timed_current["status"] == "answered":
            events = (
                _stream_finish_events(timed_current)
                if last_position
                else _stream_answer_events(timed_current, include_role=False)
            )
            for event in events:
                yield event
            return
    if live_stream and last_position:
        database.finalize_stream_request(
            row["id"],
            f"msg_timeout_partial_{row['id']}",
            answer_source="human_timeout_partial",
        )
        partial = database.get_request(row["id"])
        if partial and partial["status"] == "answered":
            for event in _stream_finish_events(partial):
                yield event
            return
    fallback = _settle_sync_timeout(database, row, settings)
    if fallback:
        for event in _stream_answer_events(
            fallback, include_role=not live_stream
        ):
            yield event
        return
    yield _stream_event(
        {
            "error": {
                "message": "The human did not answer before the request timed out",
                "type": "human_timeout",
                "request_id": row["id"],
            }
        }
    )
    yield _stream_event("[DONE]")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    response_timeout_label = (
        f"{settings.response_timeout_seconds} 秒"
        if settings.response_timeout_seconds < 60
        else f"{max(1, (settings.response_timeout_seconds + 59) // 60)} 分钟"
    )
    database = Database(settings.database_path, timezone_name=settings.timezone_name)
    notification_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1_000)
    upload_directory = settings.database_path.parent / "uploads"
    upload_directory.mkdir(parents=True, exist_ok=True)
    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.filters["datetime"] = _format_timestamp
    templates.env.filters["prettyjson"] = _pretty_json

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        database.ensure_profile(display_name=settings.model_name)
        async def automation_worker() -> None:
            while True:
                database.process_due_auto_replies()
                database.settle_due_requests(_pick_timeout_fallback(settings))
                await asyncio.sleep(max(0.25, settings.poll_interval_seconds))

        workers = [asyncio.create_task(automation_worker())]
        if settings.notification_webhook_url:
            workers.append(
                asyncio.create_task(
                    notification_worker(
                        notification_queue,
                        webhook_url=settings.notification_webhook_url,
                        timeout=settings.notification_webhook_timeout_seconds,
                    )
                )
            )
        try:
            yield
        finally:
            for worker in workers:
                worker.cancel()
            for worker in workers:
                with suppress(asyncio.CancelledError):
                    await worker

    application = FastAPI(
        title="iamllm",
        description="A human-powered, OpenAI-compatible multimodal chat API",
        version="0.3.0",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.database = database
    application.state.notification_queue = notification_queue
    application.mount(
        "/static", StaticFiles(directory=APP_DIR / "static"), name="static"
    )
    application.mount("/uploads", StaticFiles(directory=upload_directory), name="uploads")

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    async def require_api_key(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Bearer API key",
            )
        supplied_key = authorization.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(supplied_key, settings.api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

    def require_admin(request: Request) -> None:
        supplied_cookie = request.cookies.get(ADMIN_COOKIE, "")
        if not secrets.compare_digest(supplied_cookie, _admin_cookie(settings)):
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/admin/login"},
            )

    def require_visitor(request: Request) -> str:
        token = _visitor_token(request.cookies.get(VISITOR_COOKIE), settings)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Open /chat first to start a visitor session",
            )
        return token

    def validate_model(payload: ChatCompletionRequest) -> None:
        if payload.model != settings.model_name:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown model: {payload.model}",
            )

    def enqueue_notification(payload: dict[str, Any]) -> bool:
        if not settings.notification_webhook_url:
            return False
        try:
            notification_queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            logger.warning("notification queue is full; dropping notification")
            return False

    def enqueue_new_request_notification(row: dict[str, Any]) -> None:
        enqueue_notification(
            build_new_request_notification(
                row, public_base_url=settings.public_base_url
            )
        )

    def add_messages_to_conversation(
        conversation_id: str, messages: list[ChatMessage]
    ) -> None:
        for message in messages:
            database.add_conversation_message(
                message_id=f"msg_{secrets.token_urlsafe(10)}",
                conversation_id=conversation_id,
                role=message.role,
                content=message.model_dump(mode="json")["content"],
                tool_call_id=message.tool_call_id,
                tool_calls=message.tool_calls,
            )

    def create_human_request(
        payload: ChatCompletionRequest,
        *,
        mode: str,
        ttl_seconds: int,
        source: str = "api",
        stream_requested: bool = False,
    ) -> dict[str, Any]:
        validate_model(payload)
        incoming = [message.model_dump(mode="json") for message in payload.messages]
        conversation_id = payload.conversation_id
        if conversation_id:
            conversation = database.get_conversation(
                conversation_id, owner_token="api"
            )
            if not conversation:
                raise HTTPException(status_code=404, detail="Conversation not found")
            if database.conversation_has_pending(conversation_id):
                raise HTTPException(
                    status_code=409,
                    detail="This conversation already has a pending human response",
                )
            add_messages_to_conversation(conversation_id, payload.messages)
            messages = database.conversation_messages_for_api(conversation_id)
        else:
            messages = incoming
        request_id = f"chatcmpl_{secrets.token_urlsafe(12)}"
        row = database.create_request(
            request_id=request_id,
            model=payload.model,
            messages=messages,
            mode=mode,
            expires_at=int(time.time()) + ttl_seconds,
            conversation_id=conversation_id,
            tools=[tool.model_dump(mode="json") for tool in payload.tools],
            source=source,
            stream_requested=stream_requested,
        )
        enqueue_new_request_notification(row)
        return row

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
            ],
        }

    def model_record() -> dict[str, Any]:
        profile = database.get_profile()
        return {
            "id": settings.model_name,
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
                ],
            },
        }

    @application.get("/v1/models", dependencies=[Depends(require_api_key)])
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": [model_record()]}

    @application.get(
        "/v1/models/{model_name}", dependencies=[Depends(require_api_key)]
    )
    async def retrieve_model(model_name: str) -> dict[str, Any]:
        if model_name != settings.model_name:
            raise HTTPException(status_code=404, detail="Model not found")
        return model_record()

    @application.post(
        "/v1/chat/completions", dependencies=[Depends(require_api_key)]
    )
    async def chat_completions(payload: ChatCompletionRequest):
        row = create_human_request(
            payload,
            mode="sync",
            ttl_seconds=settings.response_timeout_seconds,
            stream_requested=payload.stream,
        )
        if payload.stream:
            return StreamingResponse(
                _completion_stream(database, row, settings),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "X-Human-Request-ID": row["id"],
                },
            )
        while True:
            current = database.get_request(row["id"])
            if current and current["status"] == "answered":
                return _chat_completion(current)
            if (
                not current
                or current["status"] == "expired"
                or current["expires_at"] <= int(time.time())
            ):
                break
            database.touch_client_connection(row["id"])
            await asyncio.sleep(settings.poll_interval_seconds)

        fallback = _settle_sync_timeout(database, row, settings)
        if fallback:
            return _chat_completion(fallback)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "message": "The human did not answer before the request timed out",
                "request_id": row["id"],
            },
            headers={"X-Human-Request-ID": row["id"]},
        )

    @application.post(
        "/v1/human/jobs",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_api_key)],
    )
    async def create_job(payload: ChatCompletionRequest) -> dict[str, Any]:
        row = create_human_request(
            payload,
            mode="async",
            ttl_seconds=settings.job_ttl_seconds,
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
        database.settle_due_requests(_pick_timeout_fallback(settings))
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
            result["response"] = _chat_completion(row)
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

    @application.get("/chat", response_class=HTMLResponse)
    async def public_chat(request: Request) -> HTMLResponse:
        token = _visitor_token(request.cookies.get(VISITOR_COOKIE), settings)
        new_cookie: str | None = None
        if not token:
            token, new_cookie = _new_visitor_cookie(settings)
        profile = database.get_profile()
        response = templates.TemplateResponse(
            request=request,
            name="chat.html",
            context={
                "profile": profile,
                "model_name": settings.model_name,
                "response_timeout_seconds": settings.response_timeout_seconds,
                "response_timeout_label": response_timeout_label,
            },
        )
        if new_cookie:
            response.set_cookie(
                VISITOR_COOKIE,
                new_cookie,
                httponly=True,
                secure=settings.cookie_secure,
                samesite="lax",
                max_age=60 * 60 * 24 * 90,
            )
        return response

    @application.post("/chat/api/conversations", status_code=201)
    async def create_public_conversation(request: Request) -> dict[str, Any]:
        token = require_visitor(request)
        conversation = database.create_conversation(
            conversation_id=f"conv_{secrets.token_urlsafe(12)}",
            owner_token=token,
        )
        return {"id": conversation["id"], "title": conversation["title"]}

    @application.get("/chat/api/conversations/{conversation_id}")
    async def get_public_conversation(
        request: Request, conversation_id: str
    ) -> dict[str, Any]:
        token = require_visitor(request)
        database.settle_due_requests(_pick_timeout_fallback(settings))
        conversation = database.get_conversation(
            conversation_id, owner_token=token
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        latest = conversation["latest_request"]
        live_chunks = (
            database.list_stream_chunks(latest["id"])
            if latest and latest["status"] == "pending"
            else []
        )
        return {
            "id": conversation["id"],
            "title": conversation["title"],
            "messages": conversation["messages"],
            "pending": bool(latest and latest["status"] == "pending"),
            "latest_request_id": latest["id"] if latest else None,
            "expires_at": latest["expires_at"]
            if latest and latest["status"] == "pending"
            else None,
            "live_response": {
                "request_id": latest["id"],
                "chunks": live_chunks,
                "content": "".join(chunk["content"] for chunk in live_chunks),
                "expires_at": latest["expires_at"],
            }
            if live_chunks
            else None,
            "auto_reply": {
                "label": latest["auto_reply_label"],
                "due_at": latest["auto_reply_due_at"],
            }
            if latest
            and latest["status"] == "pending"
            and latest["auto_reply_due_at"]
            else None,
            "updated_at": conversation["updated_at"],
        }

    @application.get("/chat/api/conversations/{conversation_id}/events")
    async def public_conversation_events(
        request: Request, conversation_id: str
    ) -> StreamingResponse:
        token = require_visitor(request)
        if not database.get_conversation(conversation_id, owner_token=token):
            raise HTTPException(status_code=404, detail="Conversation not found")

        async def event_stream() -> AsyncIterator[str]:
            last_marker: str | None = None
            heartbeat = 0
            while True:
                if await request.is_disconnected():
                    return
                conversation = database.get_conversation(
                    conversation_id, owner_token=token
                )
                if not conversation:
                    return
                latest = conversation["latest_request"]
                if latest and latest["status"] == "pending":
                    database.touch_client_connection(latest["id"])
                marker = ":".join(
                    [
                        str(conversation["updated_at"]),
                        str(latest["id"] if latest else "none"),
                        str(latest["status"] if latest else "idle"),
                        str(latest["stream_chunk_count"] if latest else 0),
                    ]
                )
                if marker != last_marker:
                    last_marker = marker
                    yield f"data: {json.dumps({'marker': marker})}\n\n"
                heartbeat += 1
                if heartbeat % 15 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.post(
        "/chat/api/conversations/{conversation_id}/messages", status_code=202
    )
    async def create_public_message(
        request: Request,
        conversation_id: str,
        payload: PublicChatMessage,
    ) -> dict[str, Any]:
        token = require_visitor(request)
        conversation = database.get_conversation(
            conversation_id, owner_token=token
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if database.conversation_has_pending(conversation_id):
            raise HTTPException(
                status_code=409,
                detail="Please wait for the human to answer before sending again",
            )

        text = payload.text.strip()
        if payload.image_urls:
            content: str | list[dict[str, Any]] = []
            for image_url in payload.image_urls:
                content.append(
                    {"type": "image_url", "image_url": {"url": image_url}}
                )
            if text:
                content.append({"type": "text", "text": text})
        else:
            content = text

        database.add_conversation_message(
            message_id=f"msg_{secrets.token_urlsafe(10)}",
            conversation_id=conversation_id,
            role="user",
            content=content,
        )
        database.rename_conversation_if_new(
            conversation_id, text or "图片对话"
        )
        context = database.conversation_messages_for_api(conversation_id)
        row = database.create_request(
            request_id=f"chatcmpl_{secrets.token_urlsafe(12)}",
            model=settings.model_name,
            messages=context,
            mode="async",
            expires_at=int(time.time()) + settings.response_timeout_seconds,
            conversation_id=conversation_id,
            source="web_chat",
            stream_requested=True,
        )
        enqueue_new_request_notification(row)
        return {"request_id": row["id"], "status": row["status"]}

    @application.post("/chat/api/uploads", status_code=201)
    async def upload_chat_image(
        request: Request,
        image: UploadFile = File(...),
    ) -> dict[str, Any]:
        require_visitor(request)
        allowed_types = {"image/jpeg", "image/png", "image/webp"}
        if image.content_type not in allowed_types:
            raise HTTPException(
                status_code=415,
                detail="Only JPEG, PNG, and WebP images are supported",
            )
        raw = await image.read(settings.max_upload_bytes + 1)
        if len(raw) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Image is larger than 8 MB")
        try:
            with Image.open(io.BytesIO(raw)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(raw)) as source_image:
                if source_image.width * source_image.height > 20_000_000:
                    raise HTTPException(
                        status_code=413, detail="Image dimensions are too large"
                    )
                normalized = ImageOps.exif_transpose(source_image)
                normalized.thumbnail((4096, 4096))
                if normalized.mode not in {"RGB", "RGBA"}:
                    normalized = normalized.convert("RGBA" if "A" in normalized.mode else "RGB")
                filename = f"img_{secrets.token_urlsafe(14)}.webp"
                target = upload_directory / filename
                normalized.save(target, "WEBP", quality=88, method=4)
        except HTTPException:
            raise
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise HTTPException(status_code=422, detail="The uploaded file is not a valid image")
        return {"url": f"/uploads/{filename}", "content_type": "image/webp"}

    @application.get("/admin/login", response_class=HTMLResponse)
    async def admin_login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": None, "model_name": settings.model_name},
        )

    @application.post("/admin/login", response_class=HTMLResponse)
    async def admin_login(request: Request) -> HTMLResponse:
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))
        valid_username = secrets.compare_digest(username, settings.admin_username)
        valid_password = secrets.compare_digest(password, settings.admin_password)
        if not (valid_username and valid_password):
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "error": "用户名或密码不正确",
                    "model_name": settings.model_name,
                },
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        response = RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            ADMIN_COOKIE,
            _admin_cookie(settings),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
        )
        return response

    @application.post("/admin/logout")
    async def admin_logout() -> RedirectResponse:
        response = RedirectResponse(
            "/admin/login", status_code=status.HTTP_303_SEE_OTHER
        )
        response.delete_cookie(ADMIN_COOKIE)
        return response

    @application.get("/admin", response_class=HTMLResponse)
    async def admin_dashboard(
        request: Request,
        _: None = Depends(require_admin),
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "model_name": settings.model_name,
                "profile": database.get_profile(),
                "timezone_name": settings.timezone_name,
                "response_timeout_seconds": settings.response_timeout_seconds,
                "response_timeout_label": response_timeout_label,
                "timeout_fallback_enabled": bool(settings.timeout_fallback_text),
            },
        )

    @application.get("/admin/api/overview")
    async def admin_api_overview(_: None = Depends(require_admin)) -> dict[str, Any]:
        return {
            **database.overview(),
            "model_name": settings.model_name,
            "profile": database.get_profile(),
            "timezone": settings.timezone_name,
            "notifications_enabled": bool(settings.notification_webhook_url),
        }

    @application.post("/admin/api/notifications/test")
    async def admin_api_test_notification(
        _: None = Depends(require_admin),
    ) -> dict[str, bool]:
        if not settings.notification_webhook_url:
            raise HTTPException(
                status_code=409,
                detail="还没有配置 IAMLLM_NOTIFICATION_WEBHOOK_URL",
            )
        admin_url = (
            f"{settings.public_base_url}/admin" if settings.public_base_url else ""
        )
        queued = enqueue_notification(
            {
                "event": "human_request.notification_test",
                "text": "🧪 iamllm 通知测试成功。以后有人提问，我会来敲你。",
                "admin_url": admin_url,
            }
        )
        if not queued:
            raise HTTPException(status_code=503, detail="通知队列正忙，请稍后再试")
        return {"queued": True}

    @application.get("/admin/api/requests")
    async def admin_api_requests(
        filter: str = "pending", _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        selected = filter if filter in {"pending", "answered", "expired"} else "all"
        rows = database.list_requests(status=None if selected == "all" else selected)
        return {"items": rows, "filter": selected, "total": len(rows)}

    @application.get("/admin/api/requests/{request_id}")
    async def admin_api_request(
        request_id: str, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        row["stream_chunks"] = database.list_stream_chunks(request_id)
        return row

    @application.post("/admin/api/requests/{request_id}/claim")
    async def admin_api_claim_request(
        request_id: str,
        payload: AdminOperatorPayload,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="这个问题已经结束了")
        claimed = database.claim_request(
            request_id, payload.operator_id, lease_seconds=30
        )
        if not claimed:
            raise HTTPException(
                status_code=409,
                detail="另一张后台页面正在回答这条问题",
            )
        claimed["stream_chunks"] = database.list_stream_chunks(request_id)
        return claimed

    @application.post("/admin/api/requests/{request_id}/claim/release")
    async def admin_api_release_request_claim(
        request_id: str,
        payload: AdminOperatorPayload,
        _: None = Depends(require_admin),
    ) -> dict[str, bool]:
        if not database.get_request(request_id):
            raise HTTPException(status_code=404, detail="Request not found")
        return {
            "released": database.release_request_claim(
                request_id, payload.operator_id
            )
        }

    @application.get("/admin/api/requests/{request_id}/presence")
    async def admin_api_request_presence(
        request_id: str, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        return {
            "status": row["status"],
            "client_connected": row["client_connected"],
            "client_last_seen_at": row.get("client_last_seen_at"),
            "claim_active": row["claim_active"],
            "claim_owner": row.get("claim_owner"),
            "claim_expires_at": row.get("claim_expires_at"),
        }

    @application.post("/admin/api/requests/{request_id}/stream/chunks")
    async def admin_api_append_stream_chunk(
        request_id: str,
        payload: StreamChunkPayload,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="这个问题已经结束了")
        if not database.operator_can_write(row, payload.operator_id):
            raise HTTPException(
                status_code=409,
                detail="另一张后台页面已经接管，请先刷新状态",
            )
        chunk = database.append_stream_chunk(
            request_id,
            payload.content,
            idle_timeout_seconds=settings.stream_idle_timeout_seconds,
            owner_id=payload.operator_id,
        )
        if not chunk:
            raise HTTPException(status_code=409, detail="片段发送失败，请刷新后重试")
        return chunk

    @application.post("/admin/api/requests/{request_id}/stream/finish")
    async def admin_api_finish_stream(
        request_id: str,
        payload: AdminOperatorPayload | None = None,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail="这个问题已经结束了")
        if not database.operator_can_write(
            row, payload.operator_id if payload else None
        ):
            raise HTTPException(
                status_code=409,
                detail="另一张后台页面已经接管，请先刷新状态",
            )
        if row["stream_chunk_count"] < 1:
            raise HTTPException(
                status_code=422,
                detail="第一下空回车不算结束，先发一段，让对面听见你。",
            )
        if not database.finalize_stream_request(
            request_id,
            message_id=f"msg_{secrets.token_urlsafe(10)}",
            answer_source="human_stream",
            owner_id=payload.operator_id if payload else None,
        ):
            raise HTTPException(status_code=409, detail="流式回复未能结束，请刷新确认状态")
        result = database.get_request(request_id)
        assert result is not None
        result["stream_chunks"] = database.list_stream_chunks(request_id)
        return result

    @application.post("/admin/api/requests/{request_id}/answer")
    async def admin_api_answer_request(
        request_id: str,
        payload: AdminAnswerPayload,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        if not database.operator_can_write(row, payload.operator_id):
            raise HTTPException(
                status_code=409,
                detail="另一张后台页面已经接管，请先刷新状态",
            )
        if row["stream_chunk_count"]:
            raise HTTPException(
                status_code=409,
                detail="这条流式回复已经开口了，请用空回车结束，不要再整段发送。",
            )
        if payload.response_type == "tool_call":
            allowed_names = {tool["function"]["name"] for tool in row["tools"]}
            if payload.tool_name not in allowed_names:
                raise HTTPException(status_code=422, detail="请选择调用方提供的工具")
            response_message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{secrets.token_urlsafe(10)}",
                        "type": "function",
                        "function": {
                            "name": payload.tool_name,
                            "arguments": json.dumps(
                                payload.tool_arguments,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    }
                ],
            }
        else:
            answer = payload.text.strip()
            if not answer:
                raise HTTPException(status_code=422, detail="回答不能为空")
            response_message = {"role": "assistant", "content": answer}
        if not database.answer_request(
            request_id,
            response_message,
            message_id=f"msg_{secrets.token_urlsafe(10)}",
            owner_id=payload.operator_id,
        ):
            raise HTTPException(status_code=409, detail="这个问题已经回答或已经过期")
        result = database.get_request(request_id)
        assert result is not None
        return result

    @application.get("/admin/api/quick-replies")
    async def admin_api_quick_replies(
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        return {"items": database.list_quick_replies()}

    @application.post("/admin/api/quick-replies", status_code=201)
    async def admin_api_create_quick_reply(
        payload: QuickReplyCreate, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        return database.create_quick_reply(**payload.model_dump())

    @application.patch("/admin/api/quick-replies/{reply_id}")
    async def admin_api_update_quick_reply(
        reply_id: str,
        payload: QuickReplyPatch,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        result = database.update_quick_reply(
            reply_id, payload.model_dump(exclude_unset=True)
        )
        if not result:
            raise HTTPException(status_code=404, detail="Quick reply not found")
        return result

    @application.delete("/admin/api/quick-replies/{reply_id}")
    async def admin_api_delete_quick_reply(
        reply_id: str, _: None = Depends(require_admin)
    ) -> dict[str, bool]:
        if not database.delete_quick_reply(reply_id):
            raise HTTPException(status_code=404, detail="Quick reply not found")
        return {"deleted": True}

    @application.get("/admin/api/auto-rules")
    async def admin_api_auto_rules(
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        return {"items": database.list_auto_reply_rules()}

    @application.post("/admin/api/auto-rules", status_code=201)
    async def admin_api_create_auto_rule(
        payload: AutoRuleCreate, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        return database.create_auto_reply_rule(payload.model_dump())

    @application.post("/admin/api/auto-rules/preview")
    async def admin_api_preview_auto_rule(
        payload: AutoRulePreviewPayload, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        rule = database.resolve_auto_reply(
            [{"role": "user", "content": payload.text}]
        )
        if not rule:
            return {
                "matched": False,
                "message": "没有命中任何已启用规则，真人可以安心接管。",
            }
        if rule["rule_type"] == "keyword":
            reason = (
                f"{rule['match_type'] == 'exact' and '完全匹配' or '包含'}关键词"
                f"「{rule['pattern']}」"
            )
        else:
            reason = f"当前时间位于 {rule['start_time']}–{rule['end_time']}"
        return {
            "matched": True,
            "rule": rule,
            "reason": reason,
            "message": (
                f"将命中「{rule['name']}」，{rule['delay_seconds']} 秒后发送。"
            ),
        }

    @application.patch("/admin/api/auto-rules/{rule_id}")
    async def admin_api_update_auto_rule(
        rule_id: str,
        payload: AutoRulePatch,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        values = payload.model_dump(exclude_unset=True)
        result = database.update_auto_reply_rule(rule_id, values)
        if not result:
            raise HTTPException(status_code=404, detail="Auto reply rule not found")
        return result

    @application.delete("/admin/api/auto-rules/{rule_id}")
    async def admin_api_delete_auto_rule(
        rule_id: str, _: None = Depends(require_admin)
    ) -> dict[str, bool]:
        if not database.delete_auto_reply_rule(rule_id):
            raise HTTPException(status_code=404, detail="Auto reply rule not found")
        return {"deleted": True}

    @application.get("/admin/api/profile")
    async def admin_api_profile(_: None = Depends(require_admin)) -> dict[str, Any]:
        return database.get_profile()

    @application.put("/admin/api/profile")
    async def admin_api_update_profile(
        payload: ProfilePayload, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        database.update_profile(**payload.model_dump())
        return database.get_profile()

    @application.get("/admin/events")
    async def admin_events(
        request: Request, _: None = Depends(require_admin)
    ) -> StreamingResponse:
        async def event_stream() -> AsyncIterator[str]:
            # Compatibility for admin pages opened before v0.3.1. The old UI
            # kept one SSE connection per tab, which could exhaust the browser's
            # per-origin connection pool. New pages use visibility-aware polling;
            # old pages receive a one-shot update and reconnect only occasionally.
            yield f"retry: 10000\ndata: {database.queue_version()}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.get("/admin/settings", response_class=HTMLResponse)
    async def admin_settings(
        request: Request, _: None = Depends(require_admin)
    ) -> RedirectResponse:
        return RedirectResponse(
            "/admin#persona", status_code=status.HTTP_303_SEE_OTHER
        )

    @application.post("/admin/settings", response_class=HTMLResponse)
    async def update_admin_settings(
        request: Request, _: None = Depends(require_admin)
    ) -> HTMLResponse:
        form = await request.form()
        display_name = str(form.get("display_name", "")).strip()
        bio = str(form.get("bio", "")).strip()
        availability = str(form.get("availability", "")).strip()
        skills = [
            line.strip()
            for line in str(form.get("skills", "")).splitlines()
            if line.strip()
        ]
        if not display_name or not bio or len(skills) > 30:
            return templates.TemplateResponse(
                request=request,
                name="settings.html",
                context={
                    "profile": {
                        "display_name": display_name,
                        "bio": bio,
                        "availability": availability,
                        "skills": skills,
                    },
                    "model_name": settings.model_name,
                    "saved": False,
                    "error": "名称和简介不能为空，技能最多 30 项",
                },
                status_code=422,
            )
        database.update_profile(
            display_name=display_name[:80],
            bio=bio[:2_000],
            availability=availability[:200],
            skills=[skill[:100] for skill in skills],
        )
        return RedirectResponse(
            "/admin/settings?saved=1", status_code=status.HTTP_303_SEE_OTHER
        )

    @application.get("/admin/requests/{request_id}", response_class=HTMLResponse)
    async def admin_request_detail(
        request: Request,
        request_id: str,
        _: None = Depends(require_admin),
    ) -> RedirectResponse:
        if not database.get_request(request_id):
            raise HTTPException(status_code=404, detail="Request not found")
        return RedirectResponse(
            f"/admin#inbox/{request_id}", status_code=status.HTTP_303_SEE_OTHER
        )

    @application.post("/admin/requests/{request_id}/answer", response_class=HTMLResponse)
    async def admin_answer_request(
        request: Request,
        request_id: str,
        _: None = Depends(require_admin),
    ) -> HTMLResponse:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        form = await request.form()
        response_type = str(form.get("response_type", "text"))
        error: str | None = (
            "这条流式回复已经开口了，请回到控制台用空回车结束。"
            if row["stream_chunk_count"]
            else None
        )
        if row["claim_active"]:
            error = "这条问题正在新版控制台中回答，请回到那张页面继续。"
        if response_type == "tool_call":
            tool_name = str(form.get("tool_name", "")).strip()
            allowed_names = {
                tool["function"]["name"] for tool in row["tools"]
            }
            if tool_name not in allowed_names:
                error = "请选择调用方提供的工具"
            arguments_text = str(form.get("tool_arguments", "{}"))
            try:
                arguments = json.loads(arguments_text)
                if not isinstance(arguments, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                error = "工具参数必须是 JSON 对象"
                arguments = {}
            response_message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{secrets.token_urlsafe(10)}",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(
                                arguments, ensure_ascii=False, separators=(",", ":")
                            ),
                        },
                    }
                ],
            }
        else:
            answer = str(form.get("answer", "")).strip()
            if not answer or len(answer) > 50_000:
                error = "回答不能为空，且不能超过 50,000 个字符"
            response_message = {"role": "assistant", "content": answer}

        if error:
            return templates.TemplateResponse(
                request=request,
                name="detail.html",
                context={
                    "item": row,
                    "error": error,
                    "model_name": settings.model_name,
                    "pending_count": database.pending_count(),
                },
                status_code=422,
            )
        if not database.answer_request(
            request_id,
            response_message,
            message_id=f"msg_{secrets.token_urlsafe(10)}",
        ):
            return templates.TemplateResponse(
                request=request,
                name="detail.html",
                context={
                    "item": database.get_request(request_id),
                    "error": "这个问题已经回答或已经过期",
                    "model_name": settings.model_name,
                    "pending_count": database.pending_count(),
                },
                status_code=409,
            )
        return RedirectResponse(
            f"/admin/requests/{request_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return application


app = create_app()
