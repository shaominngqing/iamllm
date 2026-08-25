from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.database import Database
from app.errors import install_error_handlers
from app.notifications import notification_worker
from app.routers.admin import create_admin_router
from app.routers.compatible_api import create_compatible_api_router
from app.routers.public import create_public_router
from app.services.api_keys import ApiKeyService
from app.services.human_requests import HumanRequestService
from app.services.streaming import pick_timeout_fallback


APP_DIR = Path(__file__).parent


def _format_timestamp(value: int | None) -> str:
    if value is None:
        return "—"
    if value > 10_000_000_000:
        value = value // 1000
    return datetime.fromtimestamp(value).astimezone().strftime("%m-%d %H:%M:%S")


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    response_timeout_label = (
        f"{settings.response_timeout_seconds} 秒"
        if settings.response_timeout_seconds < 60
        else f"{max(1, (settings.response_timeout_seconds + 59) // 60)} 分钟"
    )
    database = Database(settings.database_path, timezone_name=settings.timezone_name)
    notification_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1_000)
    human_requests = HumanRequestService(settings, database, notification_queue)
    api_keys = ApiKeyService(settings, database)
    upload_directory = settings.database_path.parent / "uploads"
    upload_directory.mkdir(parents=True, exist_ok=True)
    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.filters["datetime"] = _format_timestamp
    templates.env.filters["prettyjson"] = _pretty_json

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        database.ensure_profile(display_name=settings.model_name)
        human_requests.process_internal_requests()
        async def automation_worker() -> None:
            while True:
                database.process_due_auto_replies()
                database.settle_due_requests(pick_timeout_fallback(settings))
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
        description=(
            "A human-powered multimodal API compatible with OpenAI Chat "
            "Completions, OpenAI Responses, Anthropic Messages, and Gemini"
        ),
        version="0.4.0",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.database = database
    application.state.notification_queue = notification_queue
    application.state.human_requests = human_requests
    application.state.api_keys = api_keys
    application.add_middleware(GZipMiddleware, minimum_size=1_000)
    application.mount(
        "/static", StaticFiles(directory=APP_DIR / "static"), name="static"
    )
    application.mount("/uploads", StaticFiles(directory=upload_directory), name="uploads")
    install_error_handlers(application)
    application.include_router(
        create_compatible_api_router(settings, database, human_requests)
    )

    application.include_router(
        create_public_router(
            settings,
            database,
            templates,
            response_timeout_label,
            upload_directory,
            human_requests,
        )
    )

    application.include_router(
        create_admin_router(
            settings,
            database,
            templates,
            response_timeout_label,
            human_requests,
            api_keys,
        )
    )

    return application


app = create_app()
