"""Background bot runner with status for the desktop UI."""
from __future__ import annotations

import datetime
import queue
import threading
from collections import deque
from typing import Any, Optional

import MetaTrader5 as mt5

import ai_trading_bot as bot
from config_manager import config_to_dict, load_settings
from mt5_connection import (
    check_algo_trading_enabled,
    connection_details,
    ensure_mt5_connected,
    last_error_message,
)
from mt5_symbols import resolve_symbol_list
from ollama_service import (
    ensure_ollama_ready,
    is_ollama_ready_for_trading,
    last_error_message as ollama_error,
    ollama_status,
)

load_settings()

_THREAD_JOIN_SEC = 20.0


class BotController:
  def __init__(self) -> None:
    self._thread: Optional[threading.Thread] = None
    self._stop_event = threading.Event()
    self._bot_active = False
    self._logs: deque[dict[str, Any]] = deque(maxlen=500)
    self._log_subscribers: list[queue.Queue] = []
    self._lock = threading.Lock()
    self.symbols: list[str] = ["XAUUSD", "EURUSD", "USDJPY", "GBPUSD"]
    self.last_error: Optional[str] = None

  def _emit_log(self, message: str) -> None:
    entry = {
      "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
      "message": message,
    }
    with self._lock:
      self._logs.append(entry)
      subscribers = list(self._log_subscribers)
    for log_queue in subscribers:
      try:
        log_queue.put_nowait(entry)
      except Exception:
        pass

  @property
  def is_running(self) -> bool:
    return self._bot_active

  def _thread_alive(self) -> bool:
    return self._thread is not None and self._thread.is_alive()

  def _wait_for_thread_exit(self, timeout: float = _THREAD_JOIN_SEC) -> bool:
    thread = self._thread
    if thread is None or not thread.is_alive():
      return True
    thread.join(timeout=timeout)
    return not thread.is_alive()

  def _request_stop(self) -> None:
    self._stop_event.set()

  def get_logs(self, limit: int = 100) -> list[dict[str, Any]]:
    with self._lock:
      return list(self._logs)[-limit:]

  def subscribe_logs(self) -> queue.Queue:
    log_queue: queue.Queue = queue.Queue()
    with self._lock:
      self._log_subscribers.append(log_queue)
    return log_queue

  def unsubscribe_logs(self, log_queue: queue.Queue) -> None:
    with self._lock:
      if log_queue in self._log_subscribers:
        self._log_subscribers.remove(log_queue)

  def mt5_status(self) -> dict[str, Any]:
    details = connection_details(try_connect=False)
    details["market_open"] = bot.is_in_trading_hours(quiet=True)
    return details

  def connect_mt5(self) -> dict[str, Any]:
    ok = ensure_mt5_connected()
    if not ok:
      self.last_error = last_error_message() or "Failed to connect to MetaTrader 5"
      return {"ok": False, "error": self.last_error}
    self.last_error = None
    details = connection_details(try_connect=False)
    self._emit_log(
      f"MT5 connected — account {details.get('account')} @ {details.get('server')}"
    )
    return {"ok": True, "mt5": details}

  def analyze_symbol(self, symbol: str) -> dict[str, Any]:
    if not bot.ensure_mt5_connected():
      return {"ok": False, "error": "MT5 not connected"}

    data = bot.fetch_market_data(symbol)
    if data is None:
      return {"ok": False, "error": f"No data for {symbol}"}

    setup = bot.analyze_market(data, symbol)
    direction = bot.determine_trade_direction(data)
    score = bot.weighted_score(data)
    aligned = bot.aligned_score(score, direction) if direction != "NONE" else 0.0
    rejection = None if setup else bot.explain_no_setup(data, symbol)

    return {
      "ok": True,
      "symbol": symbol,
      "direction": direction,
      "raw_score": round(score, 4),
      "aligned_score": round(aligned, 4),
      "rejection_reason": rejection,
      "rsi": round(data.rsi, 2),
      "atr": round(data.atr, 5),
      "ema9": round(data.ema9, 5),
      "ema21": round(data.ema21, 5),
      "ema50": round(data.ema50, 5),
      "setup": None
      if setup is None
      else {
        "direction": setup.direction,
        "entry": setup.entry,
        "sl": setup.sl,
        "tp": setup.tp,
        "score": setup.score,
        "rrr": setup.rrr,
        "lot": setup.lot,
        "reasons": setup.reasons,
      },
    }

  def start_ollama(self, *, quick: bool = False) -> dict[str, Any]:
    """Start Ollama and ensure the configured model is available."""
    if not bot.config.USE_OLLAMA_AI:
      return {"ok": False, "error": "Enable 'Use Ollama AI' in Settings first."}

    if quick and is_ollama_ready_for_trading():
      from ollama_service import invalidate_status_cache

      invalidate_status_cache()
      self._emit_log(f"Ollama ready — model: {bot.config.OLLAMA_MODEL}")
      return {"ok": True, "model": bot.config.OLLAMA_MODEL}

    self._emit_log("Starting Ollama AI (may take up to 90 seconds)…")
    if not ensure_ollama_ready():
      err = ollama_error() or "Failed to start Ollama"
      self.last_error = err
      self._emit_log(f"Ollama failed: {err}")
      return {"ok": False, "error": err}

    from ollama_service import invalidate_status_cache

    invalidate_status_cache()
    self._emit_log(f"Ollama ready — model: {bot.config.OLLAMA_MODEL}")
    return {"ok": True, "model": bot.config.OLLAMA_MODEL}

  def start(self, symbols: Optional[list[str]] = None, dry_run: Optional[bool] = None) -> dict[str, Any]:
    if self.is_running or self._thread_alive():
      self._emit_log("Stopping previous run before restart…")
      self._request_stop()
      if not self._wait_for_thread_exit():
        return {
          "ok": False,
          "error": (
            "Previous bot run is still stopping. Wait a few seconds, then click Start again."
          ),
        }

    if symbols:
      self.symbols = symbols

    if not ensure_mt5_connected():
      self.last_error = last_error_message() or "Failed to connect to MetaTrader 5"
      return {"ok": False, "error": self.last_error}

    resolved, missing = resolve_symbol_list(self.symbols)
    if missing:
      self._emit_log(f"Symbols not found: {', '.join(missing)}")
    if resolved:
      self.symbols = resolved
      self._emit_log(f"Resolved symbols: {', '.join(resolved)}")
    elif not self.symbols:
      return {"ok": False, "error": "No tradable symbols found in MT5 Market Watch."}

    use_dry = bot.config.DRY_RUN if dry_run is None else dry_run
    algo = check_algo_trading_enabled()
    if not algo.get("ok") and not use_dry:
      err = " ".join(algo.get("issues", ["Algorithmic trading is disabled in MT5."]))
      self.last_error = err
      return {"ok": False, "error": err}

    if bot.config.USE_OLLAMA_AI:
      ollama_res = self.start_ollama(quick=True)
      if not ollama_res.get("ok"):
        if bot.config.OLLAMA_FALLBACK_ON_ERROR:
          self._emit_log("Ollama unavailable — continuing with rule-based signals only")
        else:
          return {"ok": False, "error": ollama_res.get("error")}

    self._stop_event.clear()

    def run() -> None:
      self._bot_active = True
      try:
        bot.start_trading(
          self.symbols,
          stop_event=self._stop_event,
          log=self._emit_log,
          dry_run=use_dry,
        )
      except Exception as exc:
        self.last_error = str(exc)
        self._emit_log(f"Bot error: {exc}")
      finally:
        self._bot_active = False
        self._thread = None
        self._emit_log("Bot stopped")

    self._thread = threading.Thread(target=run, name="TradingBot", daemon=True)
    self._thread.start()
    self._emit_log("Bot started")
    return {"ok": True, "symbols": self.symbols, "dry_run": use_dry}

  def stop(self) -> dict[str, Any]:
    if not self.is_running and not self._thread_alive():
      return {"ok": False, "error": "Bot is not running"}

    self._request_stop()
    self._emit_log("Stop requested…")

    if self._wait_for_thread_exit():
      self._bot_active = False
      self._thread = None
      return {"ok": True}

    self._bot_active = False
    self._emit_log("Bot is stopping (should finish within ~20 seconds)…")
    return {"ok": True, "stopping": True}

  def get_status_snapshot(self) -> dict[str, Any]:
    """Full status for background UI refresh (may include HTTP for Ollama)."""
    from mt5_connection import is_session_active

    mt5 = self.mt5_status()
    return {
      "running": self.is_running,
      "symbols": list(self.symbols),
      "config": {
        "USE_OLLAMA_AI": bot.config.USE_OLLAMA_AI,
        "DRY_RUN": bot.config.DRY_RUN,
        "OLLAMA_MODEL": bot.config.OLLAMA_MODEL,
      },
      "mt5": mt5,
      "ollama": ollama_status(use_cache=False),
      "last_error": self.last_error,
      "mt5_connected": is_session_active(),
    }

  def status(self) -> dict[str, Any]:
    """Lightweight status (cached Ollama check)."""
    return {
      "running": self.is_running,
      "symbols": self.symbols,
      "config": config_to_dict(),
      "mt5": self.mt5_status(),
      "ollama": ollama_status(use_cache=True),
      "last_error": self.last_error,
    }


controller = BotController()
