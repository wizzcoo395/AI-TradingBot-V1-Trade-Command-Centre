"""Settings control: pick an installed Ollama model."""
from __future__ import annotations

import threading
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget


class OllamaModelSelector(QWidget):
    def __init__(self, current_model: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._combo = QComboBox()
        self._combo.setMinimumWidth(240)
        self._combo.setToolTip("Models installed in Ollama on this PC")
        if current_model:
            self._combo.addItem(current_model)
            self._combo.setCurrentText(current_model)

        self._refresh = QPushButton("Refresh")
        self._refresh.setObjectName("AccentButton")
        self._refresh.setCursor(Qt.PointingHandCursor)
        self._refresh.setToolTip("Reload the list from Ollama")
        self._refresh.clicked.connect(self.refresh)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._combo, stretch=1)
        row.addWidget(self._refresh)

        self._on_done: Optional[Callable[[bool, str], None]] = None

    def selected_model(self) -> str:
        return self._combo.currentText().strip()

    def refresh(self, on_done: Optional[Callable[[bool, str], None]] = None) -> None:
        self._on_done = on_done
        self._refresh.setEnabled(False)

        def work() -> tuple[list[str], str]:
            from ollama_service import is_ollama_running, list_installed_models

            if not is_ollama_running():
                return [], "Ollama is not running. Open Ollama or click Start AI on the dashboard."
            models = list_installed_models()
            if not models:
                return [], "No models installed. Run: ollama pull <model>"
            return models, ""

        def finish(result: tuple[list[str], str]) -> None:
            models, err = result
            self._apply_models(models)
            self._refresh.setEnabled(True)
            if self._on_done:
                self._on_done(not err, err)
                self._on_done = None

        def run() -> None:
            result = work()
            QTimer.singleShot(0, lambda: finish(result))

        threading.Thread(target=run, daemon=True).start()

    def _apply_models(self, models: list[str]) -> None:
        saved = self.selected_model() or self._combo.itemText(0)
        self._combo.blockSignals(True)
        self._combo.clear()
        if models:
            self._combo.addItems(models)
        elif saved:
            self._combo.addItem(saved)

        if saved:
            idx = self._combo.findText(saved)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
            else:
                self._combo.insertItem(0, saved)
                self._combo.setCurrentIndex(0)
        self._combo.blockSignals(False)
