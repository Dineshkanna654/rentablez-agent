from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Raised on any config load failure."""


@dataclass(frozen=True)
class Config:
    device_token: str
    endpoint: str
    installed_at: str | None = None


def load_config(path: str) -> Config:
    p = Path(path)

    if not p.exists():
        raise ConfigError(f"config file not found: {path}")

    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid json in {path}: {exc}") from exc

    device_token = data.get("device_token")
    if not isinstance(device_token, str) or not device_token.strip():
        raise ConfigError(f"device_token is required and must be a non-empty string in {path}")

    endpoint = data.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ConfigError(f"endpoint is required and must be a non-empty string in {path}")

    installed_at = data.get("installed_at")

    return Config(
        device_token=device_token.strip(),
        endpoint=endpoint.strip(),
        installed_at=installed_at,
    )
