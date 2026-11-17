"""Background status polling — keeps the UI thread responsive."""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from bot_controller import controller


class StatusBridge(QObject):
    """Fetches bot status on a worker thread and emits updates to the UI."""

    updated = Signal(dict)

    def __init__(self, interval_sec: float = 5.0) -> None:
        super().__init__()
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._busy = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="StatusBridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def refresh_now(self) -> None:
        """Trigger one immediate background refresh."""
        threading.Thread(target=self._fetch_and_emit, daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._fetch_and_emit()
            self._stop.wait(self._interval)

    def _fetch_and_emit(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            snapshot = controller.get_status_snapshot()
            self.updated.emit(snapshot)
        finally:
            self._busy = False
