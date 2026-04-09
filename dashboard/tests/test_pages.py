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
