"""Tests for notification config and login-failure monitoring."""

from __future__ import annotations

from app.domain.models import StateMachineState, Transition
from app.services.login_failure_monitor import LoginFailureMonitor
from app.services.notification_service import NotificationConfig, NotificationService


class SpyNotificationService:
    def __init__(self):
        self.alerts: list[dict] = []

    def is_event_enabled(self, event_type: str) -> bool:
        return event_type == "login_failed"

    async def send_alert(self, **kwargs) -> bool:
        self.alerts.append(kwargs)
        return True


class StatefulFakeClient:
    def __init__(self, state: StateMachineState):
        self._state = state

    async def state(self) -> StateMachineState:
        return self._state


class FakeRegistry:
    def __init__(self, states: dict[str, StateMachineState]):
        self._clients = {mode: StatefulFakeClient(state) for mode, state in states.items()}

    def modes(self) -> list[str]:
        return list(self._clients.keys())

    def get_client(self, mode: str):
        return self._clients[mode]


def test_notification_config_round_trip_with_slack_and_telegram():
    config = NotificationConfig(
        enabled=True,
        channel="telegram",
        slack_webhook_url="https://hooks.slack.com/services/a/b/c",
        telegram_bot_token="bot-token",
        telegram_chat_id="12345",
    )

    loaded = NotificationConfig.from_dict(config.to_dict())

    assert loaded.enabled is True
    assert loaded.channel == "telegram"
    assert loaded.slack_webhook_url == "https://hooks.slack.com/services/a/b/c"
    assert loaded.telegram_bot_token == "bot-token"
    assert loaded.telegram_chat_id == "12345"
    assert loaded.events["login_failed"]["enabled"] is True


def test_notification_service_uses_channel_specific_client():
    config = NotificationConfig(
        enabled=True,
        channel="slack",
        slack_webhook_url="https://hooks.slack.com/services/a/b/c",
    )

    service = NotificationService(config=config)

    assert service.config.channel == "slack"
    assert service._client.__class__.__name__ == "SlackWebhookClient"


async def test_login_failure_monitor_alerts_only_on_new_login_failure():
    initial_state = StateMachineState(
        current="Restarting",
        history=[
            Transition(
                timestamp="2026-04-09T10:00:00Z",
                from_state="WaitingForLogin",
                to_state="Error(Timed out waiting for login window)",
            )
        ],
    )
    registry = FakeRegistry({"live": initial_state})
    notifications = SpyNotificationService()
    monitor = LoginFailureMonitor(registry, notifications)

    await monitor._check()
    assert notifications.alerts == []

    registry._clients["live"]._state = StateMachineState(
        current="Restarting",
        history=[
            Transition(
                timestamp="2026-04-09T10:00:00Z",
                from_state="WaitingForLogin",
                to_state="Error(Timed out waiting for login window)",
            ),
            Transition(
                timestamp="2026-04-09T10:05:00Z",
                from_state="WaitingFor2fa",
                to_state="Error(Agent unreachable during 2FA wait)",
            ),
        ],
    )

    await monitor._check()

    assert len(notifications.alerts) == 1
    alert = notifications.alerts[0]
    assert alert["event_type"] == "login_failed"
    assert alert["title"] == "ibctl: LIVE login failed"
    assert "WaitingFor2fa" in alert["body"]
    assert "Agent unreachable during 2FA wait" in alert["body"]
