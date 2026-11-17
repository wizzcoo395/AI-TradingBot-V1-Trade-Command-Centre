"""Trade Command Centre — TradingBot V1 desktop console."""
from __future__ import annotations

import json
import sys
import threading
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_branding import APP_DISPLAY_NAME, APP_PRODUCT_NAME
from bot_controller import controller
from config_manager import CONFIG_FIELDS, config_to_dict, load_settings, save_settings
from desktop.ollama_model_selector import OllamaModelSelector
from desktop.paths import resource_path
from desktop.status_bridge import StatusBridge
from desktop.theme import ThemeManager

SETTING_LABELS: dict[str, str] = {
    "AGGRESSIVE_MODE": "Aggressive mode",
    "MIN_SCORE": "Min score (conservative)",
    "MIN_SCORE_AGGRESSIVE": "Min score (aggressive)",
    "RISK_PER_TRADE": "Risk per trade (0.01 = 1%)",
    "ATR_SL_MULTIPLIER": "ATR stop-loss multiplier",
    "ATR_TP_MULTIPLIER": "ATR take-profit multiplier",
    "MIN_RRR": "Min risk-reward",
    "MIN_RRR_AGGRESSIVE": "Min RRR (aggressive)",
    "SLIPPAGE_POINTS": "Slippage (points)",
    "MAGIC_NUMBER": "Magic number",
    "COOLDOWN_HOURS": "Cooldown hours",
    "MAX_SPREAD_POINTS": "Max spread (points)",
    "EMA_FAST": "EMA fast period",
    "EMA_MID": "EMA mid period",
    "EMA_SLOW": "EMA slow period",
    "RSI_PERIOD": "RSI period",
    "ATR_PERIOD": "ATR period",
    "MACD_FAST": "MACD fast",
    "MACD_SLOW": "MACD slow",
    "MACD_SIGNAL": "MACD signal",
    "EMA_WEIGHT": "EMA weight",
    "RSI_WEIGHT": "RSI weight",
    "MACD_WEIGHT": "MACD weight",
    "PRICE_WEIGHT": "Price action weight",
    "VOLUME_WEIGHT": "Volume weight",
    "WEEKEND_CLOSURE": "Pause on weekends",
    "MARKET_OPEN_HOUR_UTC": "Sunday open (UTC hour)",
    "MARKET_CLOSE_HOUR_UTC": "Friday close (UTC hour)",
    "MIN_SECONDS_BETWEEN_TRADES": "Seconds between trades",
    "DRY_RUN": "Dry run (no real orders)",
    "AUTO_START_TRADING": "Auto-start bot when app opens (after MT5 connects)",
    "TIMEFRAME": "Chart timeframe (M15, H1, H4, D1)",
    "MIN_CANDLES": "Candles to fetch per symbol",
    "USE_OLLAMA_AI": "Use Ollama AI for trade decisions",
    "OLLAMA_AUTO_START": "Auto-start Ollama when bot starts",
    "OLLAMA_HOST": "Ollama API URL",
    "OLLAMA_MODEL": "Trading AI model (installed in Ollama)",
    "OLLAMA_TIMEOUT_SEC": "Ollama startup / model pull timeout (seconds)",
    "OLLAMA_TRADE_TIMEOUT_SEC": "Max seconds to wait for AI per trade (then rules-only)",
    "OLLAMA_MIN_CONFIDENCE": "Minimum AI confidence (%)",
    "OLLAMA_FALLBACK_ON_ERROR": "Continue without AI if Ollama errors",
}


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(24, 20, 24, 24)
    layout.setSpacing(14)
    heading = QLabel(title.upper())
    heading.setObjectName("CardTitle")
    layout.addWidget(heading)
    return frame, layout


def _status_row(label: str) -> tuple[QWidget, QLabel, QLabel]:
    wrap = QWidget()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    dot = QLabel("●")
    dot.setObjectName("StatusDot")
    dot.setProperty("state", "idle")
    text = QLabel(label)
    text.setObjectName("StatusText")
    row.addWidget(dot)
    row.addWidget(text)
    row.addStretch()
    return wrap, dot, text


class MainWindow(QMainWindow):
    def __init__(self, theme_manager: ThemeManager) -> None:
        super().__init__()
        self._theme = theme_manager
        load_settings()
        self.setWindowTitle(APP_PRODUCT_NAME)
        self.setMinimumSize(1100, 700)
        self.resize(1280, 840)

        icon_path = resource_path("assets/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._setting_widgets: dict[str, QWidget] = {}
        self._ollama_model_selector: OllamaModelSelector | None = None
        self._auto_start_attempted = False
        self._log_queue = controller.subscribe_logs()
        self._nav_buttons: list[QPushButton] = []
        self._pending_log_lines: list[str] = []
        self._status_bridge = StatusBridge(interval_sec=5.0)
        self._last_status_key: tuple = ()

        shell = QFrame()
        shell.setObjectName("Shell")
        self.setCentralWidget(shell)
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        shell_layout.addWidget(self._build_sidebar())

        content_wrap = QFrame()
        content_wrap.setObjectName("Content")
        content_layout = QVBoxLayout(content_wrap)
        content_layout.setContentsMargins(28, 24, 28, 28)
        content_layout.setSpacing(20)

        content_layout.addWidget(self._build_top_bar())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_dashboard())
        self.stack.addWidget(self._build_settings())
        self.stack.addWidget(self._build_scanner())
        self.stack.addWidget(self._build_logs())
        content_layout.addWidget(self.stack, stretch=1)

        shell_layout.addWidget(content_wrap, stretch=1)

        self._status_bridge.updated.connect(self._apply_status)
        self._status_bridge.start()

        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._flush_logs)
        self._log_timer.start(400)

        self._select_nav(0)
        history = controller.get_logs(60)
        if history:
            lines = [
                f"[{e.get('time', '')[:19].replace('T', ' ')}] {e.get('message', '')}"
                for e in history
            ]
            text = "\n".join(lines)
            self.mini_log.setPlainText(text)
            self.log_view.setPlainText(text)

        QTimer.singleShot(800, lambda: self._connect_mt5(silent=True))
        QTimer.singleShot(1200, self._status_bridge.refresh_now)
        QTimer.singleShot(2000, self._refresh_ollama_models_on_load)
        QTimer.singleShot(5000, self._auto_start_trading_if_enabled)

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(16, 28, 16, 24)
        layout.setSpacing(4)

        mark = QLabel("Trade Command")
        mark.setObjectName("BrandMark")
        tag = QLabel("Centre")
        tag.setObjectName("BrandTag")
        layout.addWidget(mark)
        layout.addWidget(tag)
        layout.addSpacing(28)

        for i, name in enumerate(("Dashboard", "Settings", "Scanner", "Activity")):
            btn = QPushButton(name)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, idx=i: self._select_nav(idx))
            self._nav_buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch()
        return side

    def _select_nav(self, index: int) -> None:
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        self.stack.setCurrentIndex(index)
        if index == 1 and self._ollama_model_selector is not None:
            self._ollama_model_selector.refresh()

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        line = QFrame()
        line.setObjectName("AccentLine")
        outer.addWidget(line)

        inner = QHBoxLayout()
        inner.setContentsMargins(22, 16, 22, 16)
        inner.setSpacing(20)

        header_title = QLabel(APP_DISPLAY_NAME)
        header_title.setObjectName("HeaderTitle")
        inner.addWidget(header_title)

        self._status_mt5, self._dot_mt5, self._text_mt5 = _status_row("MT5")
        self._status_ollama, self._dot_ollama, self._text_ollama = _status_row("AI")
        self._status_market, self._dot_market, self._text_market = _status_row("Market")
        self._status_bot, self._dot_bot, self._text_bot = _status_row("Bot")

        for w in (self._status_mt5, self._status_ollama, self._status_market, self._status_bot):
            inner.addWidget(w)
        inner.addStretch()

        self.btn_theme = QPushButton(self._theme.toggle_button_label())
        self.btn_theme.setObjectName("ThemeToggle")
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.clicked.connect(self._on_toggle_theme)
        inner.addWidget(self.btn_theme)

        outer.addLayout(inner)
        return bar

    def _on_toggle_theme(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        self._theme.toggle(app)
        self.btn_theme.setText(self._theme.toggle_button_label())

    def _build_dashboard(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(18)

        control, cl = _card("Trading controls")
        sym = QLabel("Symbol list")
        sym.setObjectName("FieldLabel")
        cl.addWidget(sym)
        self.symbols_input = QLineEdit("XAUUSD,EURUSD,USDJPY,GBPUSD")
        self.symbols_input.setPlaceholderText("Comma-separated pairs")
        cl.addWidget(self.symbols_input)
        self.dry_run_cb = QCheckBox("Dry run only (no orders sent to MT5)")
        self.dry_run_cb.setChecked(config_to_dict().get("DRY_RUN", False))
        cl.addWidget(self.dry_run_cb)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_connect = QPushButton("Connect MT5")
        self.btn_connect.setObjectName("AccentButton")
        self.btn_connect.setCursor(Qt.PointingHandCursor)
        self.btn_connect.clicked.connect(lambda: self._connect_mt5(silent=False))
        self.btn_start_ai = QPushButton("Start AI")
        self.btn_start_ai.setObjectName("AccentButton")
        self.btn_start_ai.setCursor(Qt.PointingHandCursor)
        self.btn_start_ai.clicked.connect(self._on_start_ai)
        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("DangerButton")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        actions.addWidget(self.btn_connect)
        actions.addWidget(self.btn_start_ai)
        actions.addWidget(self.btn_start)
        actions.addWidget(self.btn_stop)
        actions.addStretch()
        cl.addLayout(actions)

        account, al = _card("Account")
        form = QFormLayout()
        form.setSpacing(14)
        form.setLabelAlignment(Qt.AlignLeft)
        self.stat_terminal = QLabel("—")
        self.stat_account = QLabel("—")
        self.stat_balance = QLabel("—")
        self.stat_trade = QLabel("—")
        for name, widget in (
            ("Terminal", self.stat_terminal),
            ("Account", self.stat_account),
            ("Balance", self.stat_balance),
            ("Trading", self.stat_trade),
        ):
            widget.setObjectName("ValueText")
            lbl = QLabel(name)
            lbl.setObjectName("FieldLabel")
            form.addRow(lbl, widget)
        al.addLayout(form)

        feed, fl = _card("Live feed")
        self.mini_log = QPlainTextEdit()
        self.mini_log.setReadOnly(True)
        self.mini_log.setObjectName("LogView")
        self.mini_log.setMaximumBlockCount(250)
        self.mini_log.setMinimumHeight(200)
        self.mini_log.setUndoRedoEnabled(False)
        fl.addWidget(self.mini_log)

        grid.addWidget(control, 0, 0)
        grid.addWidget(account, 0, 1)
        grid.addWidget(feed, 1, 0, 1, 2)
        return page

    def _build_settings(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        card, cl = _card("Parameters")
        top = QHBoxLayout()
        top.addStretch()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save_settings)
        top.addWidget(save_btn)
        cl.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(14)
        form.setContentsMargins(0, 0, 4, 0)

        for key in CONFIG_FIELDS:
            val = config_to_dict()[key]
            label = QLabel(SETTING_LABELS.get(key, key))
            label.setObjectName("FieldLabel")
            widget = self._make_setting_widget(key, val)
            self._setting_widgets[key] = widget
            form.addRow(label, widget)

        scroll.setWidget(inner)
        cl.addWidget(scroll)
        outer.addWidget(card)
        return page

    def _make_setting_widget(self, key: str, val: Any) -> QWidget:
        if key == "TIMEFRAME":
            w = QComboBox()
            for tf in ("M15", "H1", "H4", "D1"):
                w.addItem(tf)
            w.setCurrentText(str(val).upper() if str(val).upper() in ("M15", "H1", "H4", "D1") else "H1")
            return w
        if key == "OLLAMA_MODEL":
            selector = OllamaModelSelector(str(val))
            self._ollama_model_selector = selector
            return selector
        if isinstance(val, bool):
            w = QCheckBox()
            w.setChecked(val)
            return w
        if isinstance(val, str):
            w = QLineEdit()
            w.setText(val)
            return w
        if isinstance(val, int):
            w = QSpinBox()
            w.setRange(-999999, 999999)
            w.setValue(val)
            return w
        w = QDoubleSpinBox()
        w.setDecimals(4)
        w.setRange(-999999.0, 999999.0)
        w.setSingleStep(0.01)
        w.setValue(float(val))
        return w

    def _read_settings_from_form(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key, widget in self._setting_widgets.items():
            if key == "OLLAMA_MODEL" and self._ollama_model_selector is not None:
                data[key] = self._ollama_model_selector.selected_model()
            elif isinstance(widget, QCheckBox):
                data[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                data[key] = widget.currentText().strip()
            elif isinstance(widget, QLineEdit):
                data[key] = widget.text().strip()
            elif isinstance(widget, QSpinBox):
                data[key] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                data[key] = widget.value()
        return data

    def _build_scanner(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        card, cl = _card("Market scanner")
        row = QHBoxLayout()
        row.setSpacing(12)
        lbl = QLabel("Symbol")
        lbl.setObjectName("FieldLabel")
        self.scan_symbol = QLineEdit("XAUUSD")
        scan_btn = QPushButton("Run analysis")
        scan_btn.setObjectName("PrimaryButton")
        scan_btn.setCursor(Qt.PointingHandCursor)
        scan_btn.clicked.connect(self._on_scan)
        row.addWidget(lbl)
        row.addWidget(self.scan_symbol, stretch=1)
        row.addWidget(scan_btn)
        cl.addLayout(row)
        self.scan_result = QTextEdit()
        self.scan_result.setReadOnly(True)
        self.scan_result.setObjectName("LogView")
        self.scan_result.setMinimumHeight(400)
        cl.addWidget(self.scan_result)
        outer.addWidget(card)
        return page

    def _build_logs(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        card, cl = _card("System log")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("LogView")
        self.log_view.setMaximumBlockCount(400)
        self.log_view.setUndoRedoEnabled(False)
        cl.addWidget(self.log_view)
        outer.addWidget(card)
        return page

    def _set_status(self, dot: QLabel, text: QLabel, message: str, state: str) -> None:
        if text.text() == message and dot.property("state") == state:
            return
        text.setText(message)
        if dot.property("state") != state:
            dot.setProperty("state", state)
            dot.style().unpolish(dot)
            dot.style().polish(dot)

    def _apply_status(self, status: dict[str, Any]) -> None:
        mt5 = status.get("mt5", {})
        cfg = status.get("config", {})
        ollama = status.get("ollama", {})

        key = (
            mt5.get("connected"),
            mt5.get("market_open"),
            status.get("running"),
            cfg.get("USE_OLLAMA_AI"),
            ollama.get("running"),
            mt5.get("account"),
            mt5.get("balance"),
        )
        if key == self._last_status_key:
            return
        self._last_status_key = key

        if mt5.get("connected"):
            self._set_status(self._dot_mt5, self._text_mt5, "MT5 · connected", "ok")
        else:
            self._set_status(self._dot_mt5, self._text_mt5, "MT5 · offline", "bad")

        if not cfg.get("USE_OLLAMA_AI", False):
            self._set_status(self._dot_ollama, self._text_ollama, "AI · off", "idle")
        elif ollama.get("running"):
            model = ollama.get("model", "")
            self._set_status(self._dot_ollama, self._text_ollama, f"AI · {model}", "ok")
            self._text_ollama.setToolTip("")
        else:
            err = ollama.get("error") or status.get("last_error") or ""
            tip = err if err else "Click Start AI or open Ollama from the Start menu."
            self._text_ollama.setToolTip(tip)
            self._set_status(self._dot_ollama, self._text_ollama, "AI · offline", "bad")

        if mt5.get("market_open"):
            self._set_status(self._dot_market, self._text_market, "Market · open", "ok")
        else:
            self._set_status(self._dot_market, self._text_market, "Market · closed", "warn")

        if status.get("running"):
            self._set_status(self._dot_bot, self._text_bot, "Bot · running", "active")
        else:
            self._set_status(self._dot_bot, self._text_bot, "Bot · idle", "idle")

        if mt5.get("connected"):
            terminal = str(mt5.get("terminal_name") or "—")
            if self.stat_terminal.text() != terminal:
                self.stat_terminal.setText(terminal)
        else:
            err = mt5.get("error") or "Not connected"
            short = err if len(err) < 80 else err[:77] + "…"
            if self.stat_terminal.text() != short:
                self.stat_terminal.setText(short)

        acct = str(mt5.get("account") or "—")
        if self.stat_account.text() != acct:
            self.stat_account.setText(acct)

        bal = mt5.get("balance")
        bal_txt = f"{bal:,.2f}" if bal is not None else "—"
        if self.stat_balance.text() != bal_txt:
            self.stat_balance.setText(bal_txt)

        algo_ok = mt5.get("algo_trading_ok", mt5.get("trade_allowed"))
        trade_txt = "Allowed" if algo_ok else "Blocked"
        if self.stat_trade.text() != trade_txt:
            self.stat_trade.setText(trade_txt)
        issues = mt5.get("algo_issues") or []
        self.stat_trade.setToolTip("; ".join(issues) if issues else "")

    def refresh_status(self) -> None:
        self._status_bridge.refresh_now()

    def _connect_mt5(self, silent: bool = False) -> None:
        self.btn_connect.setEnabled(False)

        def work() -> None:
            res = controller.connect_mt5()

            def finish() -> None:
                self.btn_connect.setEnabled(True)
                self.refresh_status()
                if not res.get("ok") and not silent:
                    QMessageBox.warning(
                        self,
                        "Connection failed",
                        res.get("error", "Could not connect to MetaTrader 5."),
                    )
                elif res.get("ok"):
                    self._auto_start_trading_if_enabled()

            QTimer.singleShot(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _auto_start_trading_if_enabled(self) -> None:
        import ai_trading_bot as bot

        if self._auto_start_attempted:
            return
        if not bot.config.AUTO_START_TRADING or controller.is_running:
            return
        self._auto_start_attempted = True
        symbols = [
            s.strip().upper()
            for s in self.symbols_input.text().split(",")
            if s.strip()
        ]
        if not symbols:
            return
        dry = self.dry_run_cb.isChecked()

        def work() -> None:
            start_res = controller.start(symbols, dry)

            def finish() -> None:
                self.refresh_status()
                if not start_res.get("ok"):
                    self._emit_log_line(
                        f"Auto-start failed: {start_res.get('error', 'unknown')}"
                    )

            QTimer.singleShot(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _emit_log_line(self, message: str) -> None:
        self.mini_log.appendPlainText(message)

    def _on_start_ai(self) -> None:
        self.btn_start_ai.setEnabled(False)

        def work() -> None:
            res = controller.start_ollama()

            def finish() -> None:
                self.btn_start_ai.setEnabled(True)
                self.refresh_status()
                if res.get("ok"):
                    QMessageBox.information(
                        self,
                        "Ollama ready",
                        f"Model: {res.get('model', '')}",
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "Ollama failed",
                        res.get("error", "Could not start Ollama."),
                    )

            QTimer.singleShot(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _on_start(self) -> None:
        self.btn_start.setEnabled(False)
        symbols = [s.strip().upper() for s in self.symbols_input.text().split(",") if s.strip()]
        dry = self.dry_run_cb.isChecked()

        def work() -> None:
            mt5_conn = controller.connect_mt5()
            if not mt5_conn.get("ok"):
                start_res = {"ok": False, "error": mt5_conn.get("error")}
            elif dry:
                start_res = controller.start(symbols, dry)
            else:
                from mt5_connection import check_algo_trading_enabled

                algo = check_algo_trading_enabled()
                if not algo.get("ok"):
                    start_res = {
                        "ok": False,
                        "error": " ".join(
                            algo.get("issues", ["Enable Algo Trading in MT5."])
                        ),
                    }
                else:
                    start_res = controller.start(symbols, dry)

            def finish() -> None:
                self.btn_start.setEnabled(True)
                self.refresh_status()
                if start_res.get("ok"):
                    self._auto_start_attempted = True
                elif not start_res.get("ok"):
                    QMessageBox.warning(
                        self,
                        "Could not start",
                        start_res.get("error", "Unknown error"),
                    )

            QTimer.singleShot(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _on_stop(self) -> None:
        self.btn_stop.setEnabled(False)
        res = controller.stop()

        def finish() -> None:
            self.btn_stop.setEnabled(True)
            self.refresh_status()
            if not res.get("ok"):
                QMessageBox.information(self, "Stop", res.get("error", "Bot was not running"))

        if res.get("stopping"):
            QTimer.singleShot(500, finish)
        else:
            finish()

    def _on_scan(self) -> None:
        sym = self.scan_symbol.text().strip().upper()
        if not sym:
            return
        self.scan_result.setPlainText("Analyzing…")

        def work() -> None:
            res = controller.analyze_symbol(sym)

            def finish() -> None:
                self.scan_result.setPlainText(json.dumps(res, indent=2))

            QTimer.singleShot(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _refresh_ollama_models_on_load(self) -> None:
        if self._ollama_model_selector is not None:
            self._ollama_model_selector.refresh()

    def _save_settings(self) -> None:
        data = self._read_settings_from_form()
        if not data.get("OLLAMA_MODEL"):
            QMessageBox.warning(self, "Settings", "Select an Ollama model for trading AI.")
            return
        save_settings(data)
        QMessageBox.information(self, "Saved", "Settings saved.")
        self.refresh_status()

    def _queue_log(self, entry: dict[str, Any]) -> None:
        t = entry.get("time", "")[:19].replace("T", " ")
        self._pending_log_lines.append(f"[{t}] {entry.get('message', '')}")

    def _flush_logs(self) -> None:
        import queue as queue_module

        while True:
            try:
                entry = self._log_queue.get_nowait()
            except queue_module.Empty:
                break
            self._queue_log(entry)

        if not self._pending_log_lines:
            return

        chunk = self._pending_log_lines[:25]
        self._pending_log_lines = self._pending_log_lines[25:]
        block = "\n".join(chunk)

        page = self.stack.currentIndex()
        if page == 0:
            self.mini_log.appendPlainText(block)
        elif page == 3:
            self.log_view.appendPlainText(block)
        else:
            self.mini_log.appendPlainText(block)
            self.log_view.appendPlainText(block)

    def closeEvent(self, event) -> None:
        self._status_bridge.stop()
        super().closeEvent(event)


def run_app() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_PRODUCT_NAME)
    app.setOrganizationName("TradingBotV1")
    app.setFont(QFont("Segoe UI", 10))

    theme = ThemeManager()
    theme.apply(app)

    window = MainWindow(theme)
    window.show()
    return app.exec()


def main() -> None:
    raise SystemExit(run_app())
