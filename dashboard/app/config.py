"""Dashboard configuration from environment variables and ibctl.toml.

Env vars take precedence over TOML. The dashboard reads the [dashboard]
section from the same ibctl.toml that the Rust binary uses.
"""

from __future__ import annotations

import logging
import os

from app.domain.instance import InstanceEndpoint

logger = logging.getLogger("dashboard.config")


class DashboardSettings:
    """Immutable settings for the dashboard."""

    def __init__(
        self,
        port: int = 8080,
        token: str = "",
        debug_mode: bool = False,
        ibctl_host: str = "127.0.0.1",
        ibctl_port: int = 7462,
        log_level: str = "INFO",
        trading_mode: str = "live",
        ibctl_paper_host: str = "127.0.0.1",
        ibctl_paper_port: int = 7463,
        auth_secret: str = "",
        github_client_id: str = "",
        github_client_secret: str = "",
        github_allowed_users: tuple[str, ...] = (),
        github_allowed_orgs: tuple[str, ...] = (),
    ):
        self.port = port
        self.token = token
        self.debug_mode = debug_mode
        self.ibctl_host = ibctl_host
        self.ibctl_port = ibctl_port
        self.log_level = log_level
        self.trading_mode = trading_mode
        self.ibctl_paper_host = ibctl_paper_host
        self.ibctl_paper_port = ibctl_paper_port
        self.auth_secret = auth_secret
        self.github_client_id = github_client_id
        self.github_client_secret = github_client_secret
        self.github_allowed_users = github_allowed_users
        self.github_allowed_orgs = github_allowed_orgs

    @property
    def github_oauth_enabled(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def endpoints(self) -> list[InstanceEndpoint]:
        """Derive instance endpoints from trading_mode."""
        if self.trading_mode == "paper":
            return [InstanceEndpoint("paper", self.ibctl_host, self.ibctl_port)]
        elif self.trading_mode == "both":
            return [
                InstanceEndpoint("live", self.ibctl_host, self.ibctl_port),
                InstanceEndpoint("paper", self.ibctl_paper_host, self.ibctl_paper_port),
            ]
        else:
            # Default: live only
            return [InstanceEndpoint("live", self.ibctl_host, self.ibctl_port)]

    @classmethod
    def from_env(cls) -> DashboardSettings:
        """Load settings from environment variables."""
        token = os.environ.get("IBCTL_DASHBOARD_TOKEN", "")
        github_client_secret = os.environ.get("IBCTL_GITHUB_OAUTH_CLIENT_SECRET", "")
        auth_secret = (
            os.environ.get("IBCTL_DASHBOARD_AUTH_SECRET", "")
            or token
            or github_client_secret
        )
        return cls(
            port=int(os.environ.get("IBCTL_DASHBOARD_PORT", "8080")),
            token=token,
            debug_mode=os.environ.get("IBCTL_DEBUG_MODE", "").lower() in ("true", "yes", "1"),
            ibctl_host=os.environ.get("IBCTL_COMMAND_HOST", "127.0.0.1"),
            ibctl_port=int(os.environ.get("IBCTL_COMMAND_PORT", "7462")),
            log_level=os.environ.get("IBCTL_LOG_LEVEL", "INFO").upper(),
            trading_mode=os.environ.get("TRADING_MODE", "live").lower(),
            ibctl_paper_host=os.environ.get("IBCTL_COMMAND_HOST_PAPER", "127.0.0.1"),
            ibctl_paper_port=int(os.environ.get("IBCTL_COMMAND_PORT_PAPER", "7463")),
            auth_secret=auth_secret,
            github_client_id=os.environ.get("IBCTL_GITHUB_OAUTH_CLIENT_ID", ""),
            github_client_secret=github_client_secret,
            github_allowed_users=tuple(
                value.strip()
                for value in os.environ.get("IBCTL_GITHUB_OAUTH_ALLOWED_USERS", "").split(",")
                if value.strip()
            ),
            github_allowed_orgs=tuple(
                value.strip()
                for value in os.environ.get("IBCTL_GITHUB_OAUTH_ALLOWED_ORGS", "").split(",")
                if value.strip()
            ),
        )
