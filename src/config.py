"""Config loading: YAML file + environment overlay.

Looks for ``config.yaml`` (local, git-ignored) and falls back to the committed
``config.example.yaml``. Secrets/personal values are never read from the YAML —
they come from environment variables named by the ``*_env_var`` keys.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Optional[str | Path] = None) -> dict:
    """Load the YAML config. Explicit ``path`` wins; otherwise prefer config.yaml."""
    if path is None:
        for candidate in (ROOT / "config.yaml", ROOT / "config.example.yaml"):
            if candidate.exists():
                path = candidate
                break
    if path is None:
        raise FileNotFoundError(
            "No config found. Create config.yaml (copy config.example.yaml)."
        )
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    return _apply_env_overrides(cfg)


# Env var per toggle, so infra (SAM) can flip behaviour without baking a
# config.yaml into the deployment package. Only the committed
# config.example.yaml ships to Lambda, so anything not listed here is stuck at
# whatever that file says.
_FEATURE_ENV_VARS = {
    "earnings_guard": "EARNINGS_GUARD_ENABLED",
    "macro_overlay": "MACRO_OVERLAY_ENABLED",
    "news_sentiment": "NEWS_SENTIMENT_ENABLED",
}

_REPORT_ENV_VARS = {
    "save_to_s3": "SAVE_TO_S3",
}


def _as_bool(raw: str) -> bool:
    return raw.strip().lower() == "true"


def _apply_env_overrides(cfg: dict) -> dict:
    """Overlay toggles from env vars; an unset var leaves the config value."""
    features = cfg.setdefault("features", {})
    for flag, var in _FEATURE_ENV_VARS.items():
        raw = os.environ.get(var)
        if raw is not None:
            features[flag] = _as_bool(raw)

    report = cfg.setdefault("report", {})
    for key, var in _REPORT_ENV_VARS.items():
        raw = os.environ.get(var)
        if raw is not None:
            report[key] = _as_bool(raw)
    return cfg


def env(name: Optional[str], default: Optional[str] = None) -> Optional[str]:
    """Read an environment variable by name, tolerating a None name."""
    if not name:
        return default
    return os.environ.get(name, default)


def resolve_recipients(report_cfg: dict) -> list[str]:
    """Resolve recipient list from the env var named in config."""
    raw = env(report_cfg.get("recipient_env_var"), "") or ""
    return [addr.strip() for addr in raw.split(",") if addr.strip()]
