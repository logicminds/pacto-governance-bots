"""Handler-local configuration for the bosun governance snapshot bot.

Configuration starts from environment variables. The daemon does not own the
RPC endpoint; it lives here in the handler.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from eth_utils import is_address, to_checksum_address
from pydantic import Field, ValidationError, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sepolia infrastructure addresses, matching the Rust governance crate.
SEPOLIA_REGISTRY = "0x45127C1c92741C0dA38e1A73fbb97a8a2C46770f"
SEPOLIA_HATS = "0x3bc1A0Ad72417f2d411118085256fC53CBdDd137"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _is_nsec_like(value: str) -> bool:
    """Return True if a value looks like an nsec secret."""
    return value.startswith("nsec1")


_REQUIRED_SETTINGS_EXAMPLE = """\
Set the required variables, for example:

  export PACTO_GOVERNANCE_RPC_URL="https://sepolia.infura.io/v3/YOUR_PROJECT_ID"
  export PACTO_GOVERNANCE_BOT_ID="bosun"
  export PACTO_GOVERNANCE_GROUP_ID="your-squad-group-id"
  export PACTO_GOVERNANCE_DAEMON_SOCKET="/run/pacto/pacto-bot-api.sock"

Or copy bots/bosun/.env.example to .env and fill in the values."""


def format_settings_error(exc: BaseException) -> str:
    """Return a human-readable message for a settings validation error.

    The message names the environment variable responsible for each failure and
    includes a copy-pasteable example so operators know what to set.
    """
    lines = [
        "bosun: configuration error — required settings are missing or invalid.",
        "",
    ]

    if isinstance(exc, ValidationError):
        for err in exc.errors():
            loc = err.get("loc", ())
            msg = err.get("msg", "invalid value")
            if loc and loc != ("__root__",):
                field = loc[0]
                env_name = f"PACTO_GOVERNANCE_{field.upper()}"
                lines.append(f"  - {env_name}: {msg}")
            else:
                lines.append(f"  - {msg}")
    else:
        lines.append(f"  - {exc}")

    lines.append("")
    lines.append(_REQUIRED_SETTINGS_EXAMPLE)
    return "\n".join(lines)


class Settings(BaseSettings):
    """Runtime configuration for the snapshot bot."""

    model_config = SettingsConfigDict(
        env_prefix="PACTO_GOVERNANCE_",
        env_file=[".env", "bots/bosun/.env"],
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Required
    rpc_url: str = Field(description="JSON-RPC endpoint for the target EVM chain")
    bot_id: str = Field(description="Bot identity registered with the daemon")
    group_id: str = Field(description="MLS Squad group id to post snapshots into")

    # Optional with defaults
    squad_index: int = Field(default=0, description="Registry deployment index")
    daemon_socket: str | None = Field(
        default=None, description="Unix socket path for the daemon"
    )
    daemon_http: str | None = Field(
        default=None, description="HTTP URL for the daemon"
    )
    http_secret: str | None = Field(
        default=None, description="Shared secret for HTTP transport"
    )
    captain: str = Field(default=ZERO_ADDRESS, description="Captain address for Hats checks")
    crew_candidates_raw: str = Field(
        default="",
        validation_alias="PACTO_GOVERNANCE_CREW_CANDIDATES",
        description="Comma-separated crew candidate addresses",
    )
    proposer_candidates_raw: str = Field(
        default="",
        validation_alias="PACTO_GOVERNANCE_PROPOSER_CANDIDATES",
        description="Comma-separated proposer candidate addresses",
    )
    registry: str = Field(default=SEPOLIA_REGISTRY, description="NavePirataRegistry address")
    hats: str = Field(default=SEPOLIA_HATS, description="Hats Protocol contract address")
    config_file: str | None = Field(
        default=None, description="Optional JSON config overlay file"
    )

    @field_validator("rpc_url")
    @classmethod
    def _non_empty_rpc_url(cls, value: str) -> str:
        stripped = value.strip() if isinstance(value, str) else value
        if not stripped:
            raise ValueError("URL must not be empty")
        return stripped

    @field_validator("daemon_http", "daemon_socket")
    @classmethod
    def _optional_transport(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    @field_validator("captain", "registry", "hats", mode="before")
    @classmethod
    def _check_address(cls, value: Any) -> Any:
        return cls._validate_address(value, "address")

    @field_validator("crew_candidates_raw", "proposer_candidates_raw", mode="before")
    @classmethod
    def _check_address_list(cls, value: Any, info: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a string")
        stripped = value.strip()
        if not stripped:
            return ""
        parts = [part.strip() for part in stripped.split(",") if part.strip()]
        for part in parts:
            cls._validate_address(part, info.field_name)
        return ",".join(to_checksum_address(part) for part in parts)

    @staticmethod
    def _validate_address(value: Any, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        stripped = value.strip()
        if not stripped.startswith("0x"):
            raise ValueError(f"{field} must start with 0x: {value!r}")
        if not is_address(stripped):
            raise ValueError(f"{field} is not a valid EVM address: {value!r}")
        if _is_nsec_like(stripped):
            raise ValueError(f"{field} looks like a secret, not an address: {value!r}")
        return to_checksum_address(stripped)

    @field_validator("http_secret")
    @classmethod
    def _no_secret_in_plain_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _is_nsec_like(value):
            raise ValueError("HTTP secret looks like an nsec; use a generated shared secret")
        return value

    @computed_field
    @property
    def crew_candidates(self) -> list[str]:
        """Crew candidate addresses parsed from the comma-separated env var."""
        return self._parse_address_list(self.crew_candidates_raw)

    @computed_field
    @property
    def proposer_candidates(self) -> list[str]:
        """Proposer candidate addresses parsed from the comma-separated env var."""
        return self._parse_address_list(self.proposer_candidates_raw)

    @staticmethod
    def _parse_address_list(value: str) -> list[str]:
        if not value or not value.strip():
            return []
        return [to_checksum_address(part.strip()) for part in value.split(",") if part.strip()]

    @model_validator(mode="after")
    def _validate_transport(self) -> "Settings":
        # At least one daemon transport must be configured.
        if self.daemon_socket is None and self.daemon_http is None:
            raise ValueError(
                "One of PACTO_GOVERNANCE_DAEMON_SOCKET or PACTO_GOVERNANCE_DAEMON_HTTP must be set"
            )
        # HTTP transport requires a secret.
        if self.daemon_http is not None and not self.http_secret:
            raise ValueError(
                "PACTO_GOVERNANCE_HTTP_SECRET is required when using HTTP transport"
            )
        return self

    def apply_overlay(self) -> "Settings":
        """Apply optional JSON file overlay if configured."""
        if not self.config_file:
            return self
        path = Path(self.config_file)
        if not path.exists():
            raise ValueError(f"Config file not found: {self.config_file}")
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return self
        import json

        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError(f"Config file must be a JSON object: {self.config_file}")
        # Merge file values over env values.
        merged = self.model_dump(exclude={"crew_candidates", "proposer_candidates"})
        merged.update({k: v for k, v in data.items() if v is not None})
        return Settings(**merged)

    def to_bot_transport_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for the pacto_bot_sdk.Bot transport constructor.

        The Rust bot uses PACTO_GOVERNANCE_DAEMON_SOCKET / _DAEMON_HTTP; the Python
        SDK Bot accepts explicit transport settings. This maps one surface to the
        other.
        """
        if self.daemon_http:
            return {
                "transport": "http",
                "http_bind": self.daemon_http,
                "secret": self.http_secret,
            }
        return {
            "transport": "unix",
            "socket_path": self.daemon_socket,
        }


def load_settings() -> Settings:
    """Load settings from environment, then apply optional JSON file overlay."""
    settings = Settings()
    return settings.apply_overlay()


# Optional legacy alias used by tests.
Settings.from_env = load_settings  # type: ignore[attr-defined]
