from __future__ import annotations

import base64
import binascii
import copy
import json
import re
import secrets
from typing import Any, AsyncIterator
from urllib.parse import unquote_to_bytes

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.database import Database
from app.schemas import (
    AdminAnswerPayload,
    AdminOperatorPayload,
    ApiKeyCreate,
    ApiKeyPatch,
    AutoRuleCreate,
    AutoRulePatch,
    AutoRulePreviewPayload,
    ProfilePayload,
    QuickReplyCreate,
    QuickReplyPatch,
    StreamChunkPayload,
)
from app.security import (
    ADMIN_COOKIE,
    admin_cookie as _admin_cookie,
    require_admin,
)
from app.services.human_requests import HumanRequestService
from app.services.api_keys import ApiKeyService


def _admin_attachment_url(
    request_id: str, message_index: int, part_index: int
) -> str:
    return f"/admin/api/requests/{request_id}/attachments/{message_index}/{part_index}"


def _strip_client_internal_text(value: str) -> tuple[str, int]:
    """Remove agent-runtime blocks while preserving user text beside them."""
    text, count = re.subn(
        r"<system-reminder(?:\s[^>]*)?>.*?</system-reminder>",
        "",
        str(value or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = text.strip()
    if re.match(
        r"^SessionStart hook additional context\s*:",
        text,
        flags=re.IGNORECASE,
    ):
        return "", count + 1
    if re.match(
        r"^The user stepped away and is coming back\.\s*"
        r"Recap in under \d+ words\b",
        text,
        flags=re.IGNORECASE,
    ):
        return "", count + 1
    return text, count


def _sanitize_client_message(
    original: dict[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    """Return the user-visible portion of a message plus hidden block count."""
    message = copy.deepcopy(original)
    if message.get("role") != "user":
        return message, 0
    content = message.get("content")
    if isinstance(content, str):
        visible, hidden = _strip_client_internal_text(content)
        message["content"] = visible
        return (message if visible or message.get("tool_calls") else None), hidden
    if not isinstance(content, list):
        return message, 0

    visible_parts: list[Any] = []
    hidden = 0
    for original_part in content:
        if not isinstance(original_part, dict) or original_part.get("type") != "text":
            visible_parts.append(original_part)
            continue
        visible, removed = _strip_client_internal_text(
            str(original_part.get("text") or "")
        )
        hidden += removed
        if visible:
            part = copy.deepcopy(original_part)
            part["text"] = visible
            visible_parts.append(part)
    message["content"] = visible_parts
    return (message if visible_parts or message.get("tool_calls") else None), hidden


def _operator_request_view(row: dict[str, Any]) -> dict[str, Any]:
    """Return the fast, human-facing subset used by the default conversation view."""
    result = dict(row)
    messages: list[dict[str, Any]] = []
    client_internal_count = 0
    if row.get("request_kind", "conversation") in {
        "conversation", "recap", "bootstrap"
    }:
        for message_index, original in enumerate(row.get("messages") or []):
            if original.get("role") not in {"user", "assistant"}:
                continue
            if original.get("role") == "assistant" and original.get("tool_calls"):
                continue
            prepared = copy.deepcopy(original)
            content = prepared.get("content")
            if isinstance(content, list):
                for part_index, part in enumerate(content):
                    if not isinstance(part, dict):
                        continue
                    image = part.get("image_url")
                    if isinstance(image, dict) and str(
                        image.get("url", "")
                    ).startswith("data:"):
                        image["url"] = _admin_attachment_url(
                            str(row["id"]), message_index, part_index
                        )
                    elif isinstance(image, str) and image.startswith("data:"):
                        part["image_url"] = _admin_attachment_url(
                            str(row["id"]), message_index, part_index
                        )
                    file_value = part.get("file")
                    if isinstance(file_value, dict) and str(
                        file_value.get("url", "")
                    ).startswith("data:"):
                        file_value["url"] = _admin_attachment_url(
                            str(row["id"]), message_index, part_index
                        )
            message, hidden = _sanitize_client_message(prepared)
            client_internal_count += hidden
            if message is None:
                continue
            messages.append(message)
    result["messages"] = messages
    result["client_internal_count"] = client_internal_count
    result["raw_loaded"] = False
    return result


def _inline_part_data(
    row: dict[str, Any], message_index: int, part_index: int
) -> tuple[str, bytes]:
    try:
        part = row["messages"][message_index]["content"][part_index]
    except (IndexError, KeyError, TypeError):
        raise HTTPException(status_code=404, detail="Attachment not found") from None
    value: Any = None
    if isinstance(part, dict):
        image = part.get("image_url")
        if isinstance(image, dict):
            value = image.get("url")
        elif isinstance(image, str):
            value = image
        if not value and isinstance(part.get("file"), dict):
            value = part["file"].get("url")
    if (
        not isinstance(value, str)
        or not value.startswith("data:")
        or "," not in value
    ):
        raise HTTPException(status_code=404, detail="Attachment not found")
    metadata, encoded = value[5:].split(",", 1)
    media_type = metadata.split(";", 1)[0] or "application/octet-stream"
    try:
        content = (
            base64.b64decode(encoded, validate=True)
            if ";base64" in metadata.lower()
            else unquote_to_bytes(encoded)
        )
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Attachment data is invalid") from None
    return media_type, content


def create_admin_router(
    settings: Settings,
    database: Database,
    templates: Jinja2Templates,
    response_timeout_label: str,
    human_requests: HumanRequestService,
    api_keys: ApiKeyService,
) -> APIRouter:
    application = APIRouter()
    enqueue_notification = human_requests.enqueue_notification

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
                "stream_idle_timeout_seconds": settings.stream_idle_timeout_seconds,
                "job_ttl_hours": round(settings.job_ttl_seconds / 3600, 1),
                "max_upload_megabytes": round(settings.max_upload_bytes / 1024 / 1024, 1),
                "environment": settings.environment,
                "public_base_url": settings.public_base_url,
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
        rows = database.list_request_summaries(
            status=None if selected == "all" else selected
        )
        return {"items": rows, "filter": selected, "total": len(rows)}

    @application.get("/admin/api/requests/{request_id}")
    async def admin_api_request(
        request_id: str, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        row["stream_chunks"] = database.list_stream_chunks(request_id)
        return _operator_request_view(row)

    @application.get("/admin/api/requests/{request_id}/raw")
    async def admin_api_request_raw(
        request_id: str, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        row["stream_chunks"] = database.list_stream_chunks(request_id)
        row["raw_loaded"] = True
        return row

    @application.get(
        "/admin/api/requests/{request_id}/attachments/{message_index}/{part_index}"
    )
    async def admin_api_request_attachment(
        request_id: str,
        message_index: int,
        part_index: int,
        _: None = Depends(require_admin),
    ) -> Response:
        row = database.get_request(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        media_type, content = _inline_part_data(row, message_index, part_index)
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=3600",
                "Content-Security-Policy": "sandbox; default-src 'none'",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @application.post("/admin/api/requests/{request_id}/claim")
    async def admin_api_claim_request(
        request_id: str,
        payload: AdminOperatorPayload,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        claimed = database.claim_request(
            request_id, payload.operator_id, lease_seconds=30
        )
        if not claimed:
            raise HTTPException(
                status_code=409,
                detail="请求已经结束，或另一张后台页面正在回答",
            )
        return claimed

    @application.post("/admin/api/requests/{request_id}/claim/release")
    async def admin_api_release_request_claim(
        request_id: str,
        payload: AdminOperatorPayload,
        _: None = Depends(require_admin),
    ) -> dict[str, bool]:
        return {
            "released": database.release_request_claim(
                request_id, payload.operator_id
            )
        }

    @application.get("/admin/api/requests/{request_id}/presence")
    async def admin_api_request_presence(
        request_id: str, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        row = database.get_request_state(request_id)
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
        row = database.get_request_state(request_id)
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
        row = database.get_request_state(request_id)
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
        result = database.get_request_state(request_id)
        assert result is not None
        return {
            "id": request_id,
            "status": result["status"],
            "answer_source": result.get("answer_source"),
            "answered_at": result.get("answered_at"),
            "stream_chunk_count": result["stream_chunk_count"],
        }

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
        result = database.get_request_state(request_id)
        assert result is not None
        return {
            "id": request_id,
            "status": result["status"],
            "answer_source": result.get("answer_source"),
            "answered_at": result.get("answered_at"),
        }

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

    @application.get("/admin/api/api-keys")
    async def admin_api_keys(_: None = Depends(require_admin)) -> dict[str, Any]:
        items = api_keys.list()
        return {
            "items": items,
            "active_managed": sum(
                1 for item in items if item["managed"] and item["active"]
            ),
        }

    @application.post("/admin/api/api-keys", status_code=201)
    async def admin_api_create_key(
        payload: ApiKeyCreate, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        return api_keys.create(**payload.model_dump())

    @application.patch("/admin/api/api-keys/{key_id}")
    async def admin_api_update_key(
        key_id: str,
        payload: ApiKeyPatch,
        _: None = Depends(require_admin),
    ) -> dict[str, Any]:
        result = api_keys.update(
            key_id, payload.model_dump(exclude_unset=True, exclude_none=True)
        )
        if not result:
            raise HTTPException(status_code=404, detail="API key not found")
        return result

    @application.post("/admin/api/api-keys/{key_id}/revoke")
    async def admin_api_revoke_key(
        key_id: str, _: None = Depends(require_admin)
    ) -> dict[str, Any]:
        result = api_keys.revoke(key_id)
        if not result:
            raise HTTPException(status_code=404, detail="API key not found")
        return result

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
            "/admin#settings", status_code=status.HTTP_303_SEE_OTHER
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
