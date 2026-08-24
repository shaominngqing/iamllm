from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


load_dotenv()


DEFAULT_TIMEOUT_FALLBACK_TEXT = "||".join(
    [
        "【超时兜底】我知道你很急，但你先别急。我的人类还在赶来的路上，稍后再戳我一次。",
        "【超时兜底】别慌，不是模型在思考，是人类暂时没看见。过会儿再来敲门。",
        "【超时兜底】请求已成功送达人类大脑，可惜大脑暂未签收。稍后重试一下。",
        "【超时兜底】这次不是网络延迟，是肉身延迟。等我的人类上线再问一次吧。",
        "【超时兜底】人类模型正在经历一些碳基生物特有的事情，稍后再来。",
        "【超时兜底】你的问题没有丢，只是我的人类把回复速度调成了省电模式。稍后再试。",
    ]
)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    model_name: str
    admin_username: str
    admin_password: str
    session_secret: str
    database_path: Path
    response_timeout_seconds: int
    job_ttl_seconds: int
    cookie_secure: bool
    timeout_fallback_text: str = DEFAULT_TIMEOUT_FALLBACK_TEXT
    max_upload_bytes: int = 8 * 1024 * 1024
    poll_interval_seconds: float = 0.4
    timezone_name: str = "Asia/Shanghai"
    stream_idle_timeout_seconds: int = 120
    stream_chunk_delay_seconds: float = 0.045
    stream_chunk_chars: int = 12
    stream_keepalive_seconds: float = 10.0
    environment: str = "development"
    public_base_url: str = ""
    notification_webhook_url: str = ""
    notification_webhook_timeout_seconds: float = 5.0

    def validate(self) -> None:
        if self.environment not in {"development", "production", "test"}:
            raise ValueError("IAMLLM_ENV must be development, production, or test")
        for label, value in {
            "IAMLLM_PUBLIC_BASE_URL": self.public_base_url,
            "IAMLLM_NOTIFICATION_WEBHOOK_URL": self.notification_webhook_url,
        }.items():
            if value and urlparse(value).scheme not in {"http", "https"}:
                raise ValueError(f"{label} must use http:// or https://")
        if self.environment != "production":
            return
        unsafe_values = {
            "IAMLLM_API_KEY": {
                "human-local-demo-key",
                "change-this-api-key",
            },
            "IAMLLM_ADMIN_PASSWORD": {
                "iamllm-local",
                "change-this-local-password",
                "change-this-admin-password",
            },
            "IAMLLM_SESSION_SECRET": {
                "iamllm-local-session-secret",
                "change-this-session-secret",
            },
        }
        actual = {
            "IAMLLM_API_KEY": self.api_key,
            "IAMLLM_ADMIN_PASSWORD": self.admin_password,
            "IAMLLM_SESSION_SECRET": self.session_secret,
        }
        for name, blocked in unsafe_values.items():
            if actual[name] in blocked:
                raise ValueError(f"{name} still uses an unsafe example value")
        if len(self.api_key) < 24:
            raise ValueError("IAMLLM_API_KEY must be at least 24 characters in production")
        if len(self.admin_password) < 16:
            raise ValueError(
                "IAMLLM_ADMIN_PASSWORD must be at least 16 characters in production"
            )
        if len(self.session_secret) < 32:
            raise ValueError(
                "IAMLLM_SESSION_SECRET must be at least 32 characters in production"
            )
        if self.public_base_url and not self.public_base_url.startswith("https://"):
            raise ValueError("IAMLLM_PUBLIC_BASE_URL must use HTTPS in production")
        if self.public_base_url and not self.cookie_secure:
            raise ValueError(
                "IAMLLM_COOKIE_SECURE must be true when a production public URL is set"
            )

    @classmethod
    def from_env(cls) -> "Settings":
        database_path = Path(
            os.getenv("IAMLLM_DATABASE_PATH", "data/iamllm.db")
        ).expanduser()
        settings = cls(
            api_key=os.getenv("IAMLLM_API_KEY", "human-local-demo-key"),
            model_name=os.getenv("IAMLLM_MODEL_NAME", "iam-shaomingqing"),
            admin_username=os.getenv("IAMLLM_ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("IAMLLM_ADMIN_PASSWORD", "iamllm-local"),
            session_secret=os.getenv(
                "IAMLLM_SESSION_SECRET", "iamllm-local-session-secret"
            ),
            database_path=database_path,
            response_timeout_seconds=int(
                os.getenv("IAMLLM_RESPONSE_TIMEOUT_SECONDS", "300")
            ),
            job_ttl_seconds=int(os.getenv("IAMLLM_JOB_TTL_SECONDS", "86400")),
            cookie_secure=_as_bool(os.getenv("IAMLLM_COOKIE_SECURE")),
            timeout_fallback_text=os.getenv(
                "IAMLLM_TIMEOUT_FALLBACK_TEXTS",
                os.getenv(
                    "IAMLLM_TIMEOUT_FALLBACK_TEXT",
                    DEFAULT_TIMEOUT_FALLBACK_TEXT,
                ),
            ).strip(),
            max_upload_bytes=int(
                os.getenv("IAMLLM_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024))
            ),
            timezone_name=os.getenv("IAMLLM_TIMEZONE", "Asia/Shanghai"),
            stream_idle_timeout_seconds=max(
                15,
                int(os.getenv("IAMLLM_STREAM_IDLE_TIMEOUT_SECONDS", "120")),
            ),
            stream_chunk_delay_seconds=max(
                0,
                float(os.getenv("IAMLLM_STREAM_CHUNK_DELAY_MS", "45")) / 1000,
            ),
            stream_chunk_chars=max(
                1, int(os.getenv("IAMLLM_STREAM_CHUNK_CHARS", "12"))
            ),
            stream_keepalive_seconds=max(
                1,
                float(os.getenv("IAMLLM_STREAM_KEEPALIVE_SECONDS", "10")),
            ),
            environment=os.getenv("IAMLLM_ENV", "development").strip().lower(),
            public_base_url=os.getenv("IAMLLM_PUBLIC_BASE_URL", "").strip().rstrip("/"),
            notification_webhook_url=os.getenv(
                "IAMLLM_NOTIFICATION_WEBHOOK_URL", ""
            ).strip(),
            notification_webhook_timeout_seconds=max(
                1,
                float(
                    os.getenv(
                        "IAMLLM_NOTIFICATION_WEBHOOK_TIMEOUT_SECONDS", "5"
                    )
                ),
            ),
        )
        settings.validate()
        return settings
