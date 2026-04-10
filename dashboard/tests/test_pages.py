"""Tests for web UI page routes."""

import pytest

from app.config import DashboardSettings
from app.main import create_app
from app.middleware.auth import OAUTH_COOKIE_NAME, OAUTH_STATE_COOKIE_NAME, build_oauth_state
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_overview_page_returns_200(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "ibctl" in response.text.lower()


@pytest.mark.asyncio
async def test_state_page_returns_200(client):
    response = await client.get("/state")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_config_page_returns_200(client):
    response = await client.get("/config")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logs_page_returns_200(client):
    response = await client.get("/logs")
    assert response.status_code == 200
    assert "Log file:" in response.text


@pytest.mark.asyncio
async def test_controls_page_returns_200(client):
    response = await client.get("/controls", follow_redirects=True)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_overview_partial_returns_html(client):
    response = await client.get("/partials/overview")
    assert response.status_code == 200
    assert "Gateway" in response.text or "Connected" in response.text or "status" in response.text.lower()


@pytest.mark.asyncio
async def test_logs_partial_supports_search(client, fake_client):
    from app.domain.models import LogEntry

    fake_client._logs = [
        LogEntry(timestamp="2026-04-10T00:00:00Z", level="INFO", message="gateway ready"),
        LogEntry(timestamp="2026-04-10T00:00:01Z", level="ERROR", message="2fa failed"),
    ]
    response = await client.get("/partials/logs?search=2fa")
    assert response.status_code == 200
    assert "2fa failed" in response.text
    assert "gateway ready" not in response.text


@pytest.mark.asyncio
async def test_logs_download_redirects_when_file_missing(client):
    response = await client.get("/logs/download", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/logs"


@pytest.mark.asyncio
async def test_login_page_shows_github_button_when_enabled():
    app = create_app(settings=DashboardSettings(
        port=8080,
        token="test-secret",
        debug_mode=False,
        ibctl_host="127.0.0.1",
        ibctl_port=7462,
        auth_secret="test-secret",
        github_client_id="github-client-id",
        github_client_secret="github-client-secret",
    ))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/login")
        assert response.status_code == 200
        assert "Sign In with GitHub" in response.text


@pytest.mark.asyncio
async def test_github_oauth_start_sets_state_cookie_and_redirects():
    app = create_app(settings=DashboardSettings(
        port=8080,
        token="test-secret",
        debug_mode=False,
        ibctl_host="127.0.0.1",
        ibctl_port=7462,
        auth_secret="test-secret",
        github_client_id="github-client-id",
        github_client_secret="github-client-secret",
    ))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/github?next=%2Fstate", follow_redirects=False)
        assert response.status_code == 303
        assert "github.com/login/oauth/authorize" in response.headers["location"]
        assert OAUTH_STATE_COOKIE_NAME in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_github_oauth_start_uses_explicit_redirect_uri():
    app = create_app(settings=DashboardSettings(
        port=8080,
        token="test-secret",
        debug_mode=False,
        ibctl_host="127.0.0.1",
        ibctl_port=7462,
        auth_secret="test-secret",
        github_client_id="github-client-id",
        github_client_secret="github-client-secret",
        github_redirect_uri="https://ibctl.example.com/auth/github/callback",
    ))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/auth/github?next=%2Fstate", follow_redirects=False)
        assert response.status_code == 303
        assert "redirect_uri=https%3A%2F%2Fibctl.example.com%2Fauth%2Fgithub%2Fcallback" in response.headers["location"]


@pytest.mark.asyncio
async def test_github_oauth_callback_sets_session_cookie(monkeypatch):
    app = create_app(settings=DashboardSettings(
        port=8080,
        token="test-secret",
        debug_mode=False,
        ibctl_host="127.0.0.1",
        ibctl_port=7462,
        auth_secret="test-secret",
        github_client_id="github-client-id",
        github_client_secret="github-client-secret",
    ))

    async def fake_exchange_code(code: str, redirect_uri: str, settings):
        return "access-token"

    async def fake_fetch_user(access_token: str):
        return {"login": "octocat"}

    monkeypatch.setattr("app.api.pages._github_exchange_code", fake_exchange_code)
    monkeypatch.setattr("app.api.pages._github_fetch_user", fake_fetch_user)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        state = build_oauth_state("/state", "test-secret")
        client.cookies.set(OAUTH_STATE_COOKIE_NAME, state, path="/")
        response = await client.get(
            "/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/state"
        assert OAUTH_COOKIE_NAME in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_github_oauth_callback_uses_explicit_redirect_uri(monkeypatch):
    app = create_app(settings=DashboardSettings(
        port=8080,
        token="test-secret",
        debug_mode=False,
        ibctl_host="127.0.0.1",
        ibctl_port=7462,
        auth_secret="test-secret",
        github_client_id="github-client-id",
        github_client_secret="github-client-secret",
        github_redirect_uri="https://ibctl.example.com/auth/github/callback",
    ))

    seen = {}

    async def fake_exchange_code(code: str, redirect_uri: str, settings):
        seen["redirect_uri"] = redirect_uri
        return "access-token"

    async def fake_fetch_user(access_token: str):
        return {"login": "octocat"}

    monkeypatch.setattr("app.api.pages._github_exchange_code", fake_exchange_code)
    monkeypatch.setattr("app.api.pages._github_fetch_user", fake_fetch_user)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        state = build_oauth_state("/state", "test-secret")
        client.cookies.set(OAUTH_STATE_COOKIE_NAME, state, path="/")
        response = await client.get(
            "/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert seen["redirect_uri"] == "https://ibctl.example.com/auth/github/callback"


@pytest.mark.asyncio
async def test_github_oauth_callback_rejects_unauthorized_user(monkeypatch):
    app = create_app(settings=DashboardSettings(
        port=8080,
        token="test-secret",
        debug_mode=False,
        ibctl_host="127.0.0.1",
        ibctl_port=7462,
        auth_secret="test-secret",
        github_client_id="github-client-id",
        github_client_secret="github-client-secret",
        github_allowed_users=("expected-user",),
    ))

    async def fake_exchange_code(code: str, redirect_uri: str, settings):
        return "access-token"

    async def fake_fetch_user(access_token: str):
        return {"login": "actual-user"}

    monkeypatch.setattr("app.api.pages._github_exchange_code", fake_exchange_code)
    monkeypatch.setattr("app.api.pages._github_fetch_user", fake_fetch_user)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        state = build_oauth_state("/state", "test-secret")
        client.cookies.set(OAUTH_STATE_COOKIE_NAME, state, path="/")
        response = await client.get(
            "/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            follow_redirects=False,
        )
        assert response.status_code == 401
        assert "not authorized" in response.text
