from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from app.config import Settings
from app.services.api_keys import ApiKeyLimitError


VISITOR_COOKIE = "iamllm_visitor"
ADMIN_COOKIE = "iamllm_admin_session"


def admin_cookie(settings: Settings) -> str:
    return hmac.new(
        settings.session_secret.encode(), b"iamllm-admin", hashlib.sha256
    ).hexdigest()


def new_visitor_cookie(settings: Settings) -> tuple[str, str]:
    token = secrets.token_urlsafe(24)
    signature = hmac.new(
        settings.session_secret.encode(), token.encode(), hashlib.sha256
    ).hexdigest()
    return token, f"{token}.{signature}"


def visitor_token(cookie: str | None, settings: Settings) -> str | None:
    if not cookie or "." not in cookie:
        return None
    token, signature = cookie.rsplit(".", 1)
    expected = hmac.new(
        settings.session_secret.encode(), token.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return token


def _authenticate_api_candidates(
    request: Request, candidates: list[str]
) -> dict[str, object]:
    limit_error: ApiKeyLimitError | None = None
    for candidate in candidates:
        try:
            principal = request.app.state.api_keys.authenticate(
                candidate,
                count_usage=request.app.state.api_keys.is_metered_request(
                    request.method, request.url.path
                ),
            )
        except ApiKeyLimitError as error:
            limit_error = error
            continue
        if principal:
            request.state.api_key_id = principal["id"]
            request.state.api_key_principal = principal
            return principal
    if limit_error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(limit_error),
            headers={"Retry-After": str(limit_error.retry_after)},
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
    )


async def require_api_key(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer API key",
        )
    return _authenticate_api_candidates(
        request, [authorization.removeprefix("Bearer ").strip()]
    )


async def require_compatible_api_key(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
) -> dict[str, object]:
    candidates = []
    if authorization and authorization.startswith("Bearer "):
        candidates.append(authorization.removeprefix("Bearer ").strip())
    if x_api_key:
        candidates.append(x_api_key.strip())
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key; use Authorization: Bearer or x-api-key",
        )
    return _authenticate_api_candidates(request, candidates)


async def require_google_api_key(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_goog_api_key: Annotated[
        str | None, Header(alias="x-goog-api-key")
    ] = None,
) -> dict[str, object]:
    candidates = []
    if authorization and authorization.startswith("Bearer "):
        candidates.append(authorization.removeprefix("Bearer ").strip())
    if x_goog_api_key:
        candidates.append(x_goog_api_key.strip())
    query_key = request.query_params.get("key")
    if query_key:
        candidates.append(query_key.strip())
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key; use x-goog-api-key, key, or Bearer auth",
        )
    return _authenticate_api_candidates(request, candidates)


def require_admin(request: Request) -> None:
    supplied_cookie = request.cookies.get(ADMIN_COOKIE, "")
    expected = admin_cookie(request.app.state.settings)
    if not secrets.compare_digest(supplied_cookie, expected):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin/login"},
        )


def require_visitor(request: Request) -> str:
    token = visitor_token(
        request.cookies.get(VISITOR_COOKIE), request.app.state.settings
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Open /chat first to start a visitor session",
        )
    return token
