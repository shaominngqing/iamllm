from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from typing import Any

from app.config import Settings
from app.database import Database


class ApiKeyLimitError(Exception):
    def __init__(self, message: str, *, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ApiKeyService:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database

    def _digest(self, secret: str) -> str:
        return hmac.new(
            self.settings.session_secret.encode(),
            secret.encode(),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _hint(secret: str) -> str:
        if len(secret) <= 12:
            return f"{secret[:4]}…"
        return f"{secret[:9]}…{secret[-4:]}"

    @staticmethod
    def is_metered_request(method: str, path: str) -> bool:
        if method.upper() != "POST":
            return False
        if path in {
            "/v1/chat/completions",
            "/v1/responses",
            "/v1/messages",
            "/v1/human/jobs",
        }:
            return True
        return path.endswith(":generateContent") or path.endswith(
            ":streamGenerateContent"
        )

    def authenticate(self, secret: str, *, count_usage: bool) -> dict[str, Any] | None:
        if secrets.compare_digest(secret, self.settings.api_key):
            return {
                "id": None,
                "name": "环境变量总钥匙",
                "managed": False,
            }
        result = self.database.authorize_api_key_hash(
            self._digest(secret), count_usage=count_usage
        )
        if result["status"] == "invalid":
            return None
        if result["status"] == "limited":
            reason = result["reason"]
            limit = result["limit"]
            messages = {
                "minute": f"这把钥匙跑得比人脑快：每分钟最多 {limit} 次，请稍后再试。",
                "daily": f"今天的真人额度已经用完了：每天最多 {limit} 次，明天再来敲门。",
                "concurrent": f"已经有 {limit} 个问题在等真人，这把钥匙先排会儿队。",
            }
            raise ApiKeyLimitError(
                messages[reason], retry_after=int(result["retry_after"])
            )
        return {
            "id": result["api_key_id"],
            "name": "managed",
            "managed": True,
        }

    def create(
        self,
        *,
        name: str,
        rate_limit_per_minute: int,
        daily_limit: int,
        max_concurrent: int,
    ) -> dict[str, Any]:
        secret = f"sk-{secrets.token_urlsafe(32)}"
        item = self.database.create_api_key(
            key_id=f"key_{uuid.uuid4().hex}",
            name=name.strip(),
            key_hint=self._hint(secret),
            key_hash=self._digest(secret),
            rate_limit_per_minute=rate_limit_per_minute,
            daily_limit=daily_limit,
            max_concurrent=max_concurrent,
        )
        return {"key": secret, "item": item}

    def list(self) -> list[dict[str, Any]]:
        master = {
            "id": "environment",
            "name": "环境变量总钥匙",
            "key_hint": self._hint(self.settings.api_key),
            "active": True,
            "revoked": False,
            "status": "active",
            "managed": False,
            "unlimited": True,
            "rate_limit_per_minute": None,
            "daily_limit": None,
            "max_concurrent": None,
            "request_count": None,
            "usage_minute": None,
            "usage_today": None,
            "pending_requests": None,
            "created_at": None,
            "updated_at": None,
            "last_used_at": None,
            "revoked_at": None,
        }
        return [master, *self.database.list_api_keys()]

    def update(self, key_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        return self.database.update_api_key(key_id, values)

    def revoke(self, key_id: str) -> dict[str, Any] | None:
        return self.database.revoke_api_key(key_id)
