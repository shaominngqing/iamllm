from __future__ import annotations

import asyncio
import io
import json
import secrets
import time
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.database import Database
from app.schemas import PublicChatMessage
from app.security import (
    VISITOR_COOKIE,
    new_visitor_cookie as _new_visitor_cookie,
    require_visitor,
    visitor_token as _visitor_token,
)
from app.services.human_requests import HumanRequestService
from app.services.streaming import pick_timeout_fallback


def create_public_router(
    settings: Settings,
    database: Database,
    templates: Jinja2Templates,
    response_timeout_label: str,
    upload_directory: Path,
    human_requests: HumanRequestService,
) -> APIRouter:
    application = APIRouter()
    enqueue_new_request_notification = (
        human_requests.enqueue_new_request_notification
    )

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
        database.settle_due_requests(pick_timeout_fallback(settings))
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
                detail="Please wait for the current response to finish",
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

    return application
