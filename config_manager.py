"""Load and persist trading configuration for the UI."""
from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from market_types import TradingConfig

import ai_trading_bot as bot_module

try:
    from desktop.paths import settings_path as _settings_path
except ImportError:
    _settings_path = lambda: Path(__file__).parent / "user_settings.json"  # noqa: E731

SETTINGS_PATH = _settings_path()

# Fields exposed in the UI (all TradingConfig dataclass fields)
CONFIG_FIELDS = [f.name for f in fields(TradingConfig)]


def config_to_dict(cfg: TradingConfig | None = None) -> dict[str, Any]:
    cfg = cfg or bot_module.config
    return asdict(cfg)


def apply_config(data: dict[str, Any]) -> TradingConfig:
    """Merge incoming settings into the live config object."""
    cfg = bot_module.config
    for key in CONFIG_FIELDS:
        if key not in data:
            continue
        expected = type(getattr(cfg, key))
        value = data[key]
        if expected is bool:
            value = bool(value)
        elif expected is int:
            value = int(value)
        elif expected is float:
            value = float(value)
        elif expected is str:
            value = str(value)
        setattr(cfg, key, value)
    return cfg


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return config_to_dict()
    with SETTINGS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    apply_config(data)
    return config_to_dict()


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    clean = {k: data[k] for k in CONFIG_FIELDS if k in data}
    apply_config(clean)
    with SETTINGS_PATH.open("w", encoding="utf-8") as f:
        json.dump(config_to_dict(), f, indent=2)
    return config_to_dict()
