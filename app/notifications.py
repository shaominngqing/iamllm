from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.request import Request, urlopen


logger = logging.getLogger("iamllm.notifications")


def build_new_request_notification(
    row: dict[str, Any], *, public_base_url: str = ""
) -> dict[str, Any]:
    admin_url = (
        f"{public_base_url}/admin#inbox/{row['id']}" if public_base_url else ""
    )
    source_label = "访客聊天" if row.get("source") == "web_chat" else "API"
    text = f"🧠 新问题到达 · {source_label}\n{row.get('preview') or '（没有文字，可能是一张图）'}"
    if admin_url:
        text = f"{text}\n{admin_url}"
    return {
        "event": "human_request.created",
        "text": text,
        "request": {
            "id": row["id"],
            "model": row["model"],
            "source": row.get("source", "api"),
            "preview": row.get("preview", ""),
            "created_at": row["created_at"],
            "admin_url": admin_url,
        },
    }


def post_webhook(url: str, payload: dict[str, Any], *, timeout: float) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "iamllm-webhook/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status >= 400:
            raise RuntimeError(f"notification webhook returned {response.status}")


async def notification_worker(
    queue: asyncio.Queue[dict[str, Any]],
    *,
    webhook_url: str,
    timeout: float,
) -> None:
    while True:
        payload = await queue.get()
        try:
            for attempt in range(3):
                try:
                    await asyncio.to_thread(
                        post_webhook,
                        webhook_url,
                        payload,
                        timeout=timeout,
                    )
                    break
                except Exception as error:
                    if attempt == 2:
                        logger.warning(
                            "notification webhook failed after 3 attempts: %s",
                            error,
                        )
                        break
                    await asyncio.sleep(0.5 * (2**attempt))
        finally:
            queue.task_done()
