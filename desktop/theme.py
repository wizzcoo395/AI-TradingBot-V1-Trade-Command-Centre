"""Light / dark Fluent-style themes with persistence."""
from __future__ import annotations

import json

from PySide6.QtWidgets import QApplication

from desktop.paths import resource_path, user_data_dir

PREFS_FILE = user_data_dir() / "ui_preferences.json"
THEME_LIGHT = "light"
THEME_DARK = "dark"


def load_saved_theme() -> str:
    if not PREFS_FILE.exists():
        return THEME_DARK
    try:
        data = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        theme = data.get("theme", THEME_DARK)
        return theme if theme in (THEME_LIGHT, THEME_DARK) else THEME_DARK
    except (json.JSONDecodeError, OSError):
        return THEME_DARK


def save_theme(theme: str) -> None:
    PREFS_FILE.write_text(
        json.dumps({"theme": theme}, indent=2),
        encoding="utf-8",
    )


def stylesheet_for(theme: str) -> str:
    path = resource_path(f"desktop/styles_{theme}.qss")
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


class ThemeManager:
    def __init__(self) -> None:
        self._current = load_saved_theme()

    @property
    def current(self) -> str:
        return self._current

    def is_dark(self) -> bool:
        return self._current == THEME_DARK

    def apply(self, app: QApplication, theme: str | None = None) -> str:
        if theme is not None:
            self._current = theme if theme in (THEME_LIGHT, THEME_DARK) else THEME_DARK
        app.setStyle("Fusion")
        app.setStyleSheet(stylesheet_for(self._current))
        save_theme(self._current)
        return self._current

    def toggle(self, app: QApplication) -> str:
        next_theme = THEME_LIGHT if self.is_dark() else THEME_DARK
        return self.apply(app, next_theme)

    def toggle_button_label(self) -> str:
        return "Dark" if not self.is_dark() else "Light"
