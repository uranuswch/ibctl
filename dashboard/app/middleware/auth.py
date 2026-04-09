"""Dashboard authentication middleware.

When `IBCTL_DASHBOARD_TOKEN` is set, requests are authorized by any of:
- `Authorization: Bearer <token>`
- HTTP Basic auth with the configured token as the password
- `ibctl_dashboard_auth` cookie set by the login form

When the token is empty, all requests pass through (open access).
"""

from __future__ import annotations

import base64
import binascii
import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.responses import JSONResponse

AUTH_COOKIE_NAME = "ibctl_dashboard_auth"


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Enforce dashboard auth while preserving Bearer token compatibility."""

    @staticmethod
    def _is_static_or_public(path: str) -> bool:
        return (
            path.startswith("/static")
            or path == "/login"
            or path == "/logout"
        )

    @staticmethod
    def _is_api_request(request: Request) -> bool:
        path = request.url.path
        if path.startswith("/api/"):
            return True
        accept = request.headers.get("Accept", "")
        return "application/json" in accept

    @staticmethod
    def _valid_bearer(auth_header: str, token: str) -> bool:
        return hmac.compare_digest(auth_header, f"Bearer {token}")

    @staticmethod
    def _valid_basic(auth_header: str, token: str) -> bool:
        if not auth_header.startswith("Basic "):
            return False
        try:
            encoded = auth_header[6:].strip()
            decoded = base64.b64decode(encoded).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        _, _, password = decoded.partition(":")
        return hmac.compare_digest(password, token)

    @staticmethod
    def _valid_cookie(request: Request, token: str) -> bool:
        cookie = request.cookies.get(AUTH_COOKIE_NAME, "")
        return bool(cookie) and hmac.compare_digest(cookie, token)

    def _is_authorized(self, request: Request, token: str) -> bool:
        auth_header = request.headers.get("Authorization", "")
        return (
            self._valid_bearer(auth_header, token)
            or self._valid_basic(auth_header, token)
            or self._valid_cookie(request, token)
        )

    async def dispatch(self, request: Request, call_next):
        token = request.app.state.settings.token

        # No token configured — open access
        if not token:
            return await call_next(request)

        if self._is_static_or_public(request.url.path):
            return await call_next(request)

        if self._is_authorized(request, token):
            return await call_next(request)

        if not self._is_api_request(request) and request.method == "GET":
            next_path = request.url.path
            if request.url.query:
                next_path = f"{next_path}?{request.url.query}"
            login_url = request.url_for("login_page")
            response = RedirectResponse(url=f"{login_url}?next={next_path}", status_code=303)
            return response

        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer, Basic"},
        )
