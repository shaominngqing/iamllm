from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _error_message(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or detail)
    return str(detail)


def _openai_error(status_code: int, message: str) -> dict[str, Any]:
    error_type = (
        "authentication_error"
        if status_code == 401
        else "not_found_error"
        if status_code == 404
        else "rate_limit_error"
        if status_code == 429
        else "server_error"
        if status_code >= 500
        else "invalid_request_error"
    )
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": None,
            "code": None,
        }
    }


def _anthropic_error(status_code: int, message: str) -> dict[str, Any]:
    error_type = (
        "authentication_error"
        if status_code == 401
        else "not_found_error"
        if status_code == 404
        else "rate_limit_error"
        if status_code == 429
        else "api_error"
        if status_code >= 500
        else "invalid_request_error"
    )
    return {"type": "error", "error": {"type": error_type, "message": message}}


def _gemini_error(status_code: int, message: str) -> dict[str, Any]:
    error_status = (
        "UNAUTHENTICATED"
        if status_code == 401
        else "NOT_FOUND"
        if status_code == 404
        else "RESOURCE_EXHAUSTED"
        if status_code == 429
        else "DEADLINE_EXCEEDED"
        if status_code == 504
        else "INTERNAL"
        if status_code >= 500
        else "INVALID_ARGUMENT"
    )
    return {
        "error": {
            "code": status_code,
            "message": message,
            "status": error_status,
        }
    }


def _is_openai_path(path: str) -> bool:
    return path.startswith(("/v1/chat/completions", "/v1/responses", "/v1/models"))


def _is_anthropic_path(path: str) -> bool:
    return path == "/v1/messages" or path == "/v1/messages/count_tokens"


def _is_gemini_path(path: str) -> bool:
    return path.startswith("/v1beta/models/") or (
        path.startswith("/v1/models/") and ":" in path
    )


def install_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {"msg": "Invalid request"}
        location = ".".join(str(item) for item in first.get("loc", [])[1:])
        message = (
            f"{location}: {first.get('msg', 'Invalid request')}"
            if location
            else str(first.get("msg", "Invalid request"))
        )
        if _is_anthropic_path(request.url.path):
            return JSONResponse(status_code=400, content=_anthropic_error(400, message))
        if _is_gemini_path(request.url.path):
            return JSONResponse(status_code=400, content=_gemini_error(400, message))
        if _is_openai_path(request.url.path):
            return JSONResponse(status_code=400, content=_openai_error(400, message))
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @application.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = _error_message(exc.detail)
        if _is_anthropic_path(request.url.path):
            content = _anthropic_error(exc.status_code, message)
        elif _is_gemini_path(request.url.path):
            content = _gemini_error(exc.status_code, message)
        elif _is_openai_path(request.url.path):
            content = _openai_error(exc.status_code, message)
        else:
            content = {"detail": exc.detail}
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response
