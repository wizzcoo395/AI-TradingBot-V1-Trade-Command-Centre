"""Resolve paths for dev and PyInstaller-installed builds."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from app_branding import APP_DATA_FOLDER


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    if is_frozen():
        path = Path(os.environ.get("APPDATA", "")) / APP_DATA_FOLDER
    else:
        path = app_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return user_data_dir() / "user_settings.json"


def resource_path(relative: str) -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return app_root() / relative
