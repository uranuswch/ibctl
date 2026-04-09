"""Tests for dashboard authentication middleware."""

from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DashboardSettings
from app.main import create_app
from app.middleware.auth import build_oauth_session


def _make_app(token: str = "") -> create_app:
    """Create app with given token setting."""
    settings = DashboardSettings(
        port=8080,
        token=token,
        debug_mode=False,
        ibctl_host="127.0.0.1",
        ibctl_port=7462,
        auth_secret=token or "test-auth-secret",
    )
    return create_app(settings=settings)


@pytest.fixture
async def authed_client():
    """Client for an app with token='test-secret'."""
    app = _make_app(token="test-secret")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def open_client():
    """Client for an app with no token (empty string)."""
    app = _make_app(token="")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- Token configured: endpoints require auth ---

class TestTokenConfigured:
    """When IBCTL_DASHBOARD_TOKEN is set, auth supports bearer, basic, or login cookie."""

    @pytest.mark.asyncio
    async def test_command_rejects_no_auth(self, authed_client):
        resp = await authed_client.post("/api/v1/command", json={"command": "RESTART"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_command_rejects_wrong_token(self, authed_client):
        resp = await authed_client.post(
            "/api/v1/command",
            json={"command": "RESTART"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_command_accepts_correct_token(self, authed_client):
        resp = await authed_client.post(
            "/api/v1/command",
            json={"command": "RESTART"},
            headers={"Authorization": "Bearer test-secret"},
        )
        # May fail to connect to ibctl, but should NOT be 401
        assert resp.status_code != 401

    @pytest.mark.asyncio
    async def test_status_rejects_no_auth(self, authed_client):
        resp = await authed_client.get("/api/v1/status")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_status_accepts_correct_token(self, authed_client):
        resp = await authed_client.get(
            "/api/v1/status",
            headers={"Authorization": "Bearer test-secret"},
        )
        assert resp.status_code != 401

    @pytest.mark.asyncio
    async def test_pages_reject_no_auth(self, authed_client):
        resp = await authed_client.get("/")
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("http://test/login")

    @pytest.mark.asyncio
    async def test_pages_accept_correct_token(self, authed_client):
        resp = await authed_client.get(
            "/",
            headers={"Authorization": "Bearer test-secret"},
        )
        assert resp.status_code != 401

    @pytest.mark.asyncio
    async def test_static_files_bypass_auth(self, authed_client):
        """Static assets (CSS/JS) should not require auth."""
        resp = await authed_client.get("/static/nonexistent.css")
        # 404 is fine — should NOT be 401
        assert resp.status_code != 401

    @pytest.mark.asyncio
    async def test_login_page_is_public(self, authed_client):
        resp = await authed_client.get("/login")
        assert resp.status_code == 200
        assert "Password" in resp.text

    @pytest.mark.asyncio
    async def test_login_form_sets_cookie(self, authed_client):
        resp = await authed_client.post("/login", content="password=test-secret&next=%2Fstate")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/state"
        assert "ibctl_dashboard_auth=test-secret" in resp.headers.get("set-cookie", "")

    @pytest.mark.asyncio
    async def test_login_cookie_grants_access(self, authed_client):
        resp = await authed_client.get("/", headers={"Cookie": "ibctl_dashboard_auth=test-secret"})
        assert resp.status_code != 401
        assert resp.status_code != 303

    @pytest.mark.asyncio
    async def test_basic_auth_accepts_password(self, authed_client):
        creds = base64.b64encode(b"user:test-secret").decode("ascii")
        resp = await authed_client.get(
            "/api/v1/status",
            headers={"Authorization": f"Basic {creds}"},
        )
        assert resp.status_code != 401

    @pytest.mark.asyncio
    async def test_logout_clears_cookie(self, authed_client):
        authed_client.cookies.set("ibctl_dashboard_auth", "test-secret", domain="test", path="/")
        resp = await authed_client.post("/logout")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
        assert "ibctl_dashboard_auth=\"\"" in resp.headers.get("set-cookie", "")

    @pytest.mark.asyncio
    async def test_oauth_cookie_grants_access(self, authed_client):
        cookie = build_oauth_session("octocat", "test-secret")
        resp = await authed_client.get("/", headers={"Cookie": f"ibctl_dashboard_oauth={cookie}"})
        assert resp.status_code != 401
        assert resp.status_code != 303


# --- No token configured: endpoints are open ---

class TestNoToken:
    """When IBCTL_DASHBOARD_TOKEN is empty, all endpoints are open."""

    @pytest.mark.asyncio
    async def test_command_open_no_token(self, open_client):
        resp = await open_client.post("/api/v1/command", json={"command": "RESTART"})
        # May fail to connect, but not 401
        assert resp.status_code != 401

    @pytest.mark.asyncio
    async def test_status_open_no_token(self, open_client):
        resp = await open_client.get("/api/v1/status")
        assert resp.status_code != 401

    @pytest.mark.asyncio
    async def test_pages_open_no_token(self, open_client):
        resp = await open_client.get("/")
        assert resp.status_code != 401
