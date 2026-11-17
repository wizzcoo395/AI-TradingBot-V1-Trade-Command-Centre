"""Ollama local LLM — auto-start and trade analysis (Windows-friendly)."""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Callable, Optional

import ai_trading_bot as bot
from market_types import MarketData, TradeSetup

_process: Optional[subprocess.Popen] = None
_last_error: Optional[str] = None
_status_cache: dict[str, Any] = {"at": 0.0, "data": None}
_STATUS_TTL_SEC = 12.0
_AI_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ollama-trade-ai")

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


def last_error_message() -> Optional[str]:
    return _last_error


def _set_error(msg: str) -> bool:
    global _last_error
    _last_error = msg
    return False


def _ollama_install_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"


def find_ollama_cli() -> Optional[str]:
    """ollama.exe CLI (serve, pull, etc.)."""
    which = shutil.which("ollama")
    if which and Path(which).is_file():
        return str(Path(which).resolve())

    for base in (_ollama_install_dir(), Path(os.environ.get("ProgramFiles", "")) / "Ollama"):
        for name in ("ollama.exe", "Ollama.exe"):
            path = base / name
            if path.is_file():
                return str(path.resolve())
    return None


def find_ollama_app() -> Optional[str]:
    """Windows desktop app — starts tray icon and API server."""
    for base in (_ollama_install_dir(),):
        for name in ("ollama app.exe", "Ollama app.exe", "Ollama.exe"):
            path = base / name
            if path.is_file():
                return str(path.resolve())
    return None


def find_ollama_exe() -> Optional[str]:
    """Backward-compatible: prefer CLI, then app."""
    return find_ollama_cli() or find_ollama_app()


def _api_url(path: str) -> str:
    base = bot.config.OLLAMA_HOST.rstrip("/")
    return f"{base}{path}"


def _http_get(path: str, timeout: float = 3.0) -> Optional[dict]:
    try:
        req = urllib.request.Request(_api_url(path), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _http_post(path: str, payload: dict, timeout: float = 120.0) -> Optional[dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _api_url(path),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise TimeoutError(str(exc)) from exc


def is_ollama_running() -> bool:
    return _http_get("/api/tags", timeout=2.0) is not None


def _wait_until_ready(max_wait_sec: Optional[float] = None) -> bool:
    wait = max_wait_sec or float(getattr(bot.config, "OLLAMA_STARTUP_WAIT_SEC", 90))
    deadline = time.time() + wait
    while time.time() < deadline:
        if is_ollama_running():
            return True
        time.sleep(0.75)
    return False


def _launch_detached(command: list[str], cwd: Optional[str] = None) -> subprocess.Popen:
    flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def _start_ollama_windows_app() -> bool:
    """Start Ollama via the official Windows desktop launcher."""
    app_exe = find_ollama_app()
    if not app_exe:
        return False

    app_dir = str(Path(app_exe).parent)
    errors: list[str] = []

    for cmd in (
        [app_exe],
        [app_exe, "--background"],
        ["cmd", "/c", "start", "", app_exe],
    ):
        try:
            global _process
            _process = _launch_detached(cmd, cwd=app_dir)
            if _wait_until_ready(90):
                return True
            errors.append(f"{' '.join(cmd)}: API not ready after 90s")
        except Exception as exc:
            errors.append(f"{' '.join(cmd)}: {exc}")

    if errors:
        _last_error = "Ollama app launch attempts failed: " + "; ".join(errors[:2])
    return False


def _start_ollama_serve() -> bool:
    """Start `ollama serve` subprocess."""
    global _process, _last_error

    exe = find_ollama_cli()
    if not exe:
        return False

    exe_dir = str(Path(exe).parent)
    try:
        if _process is None or _process.poll() is not None:
            _process = _launch_detached([exe, "serve"], cwd=exe_dir)
    except Exception as exc:
        _last_error = f"ollama serve failed: {exc}"
        return False

    if _wait_until_ready(60):
        return True

    if _process and _process.poll() is not None:
        _last_error = (
            f"ollama serve exited immediately (code {_process.returncode}). "
            "Try opening the Ollama app from the Start menu first."
        )
    else:
        _last_error = "ollama serve started but API did not respond in time."
    return False


def start_ollama_server() -> bool:
    """Start Ollama API server using the best method for this OS."""
    global _last_error

    if is_ollama_running():
        _last_error = None
        return True

    if os.name == "nt":
        if _start_ollama_windows_app():
            _last_error = None
            return True
        if _start_ollama_serve():
            _last_error = None
            return True
    else:
        if _start_ollama_serve():
            _last_error = None
            return True

    if not find_ollama_exe():
        return _set_error(
            "Ollama not found. Install from https://ollama.com — "
            f"expected folder: {_ollama_install_dir()}"
        )

    return _set_error(
        _last_error
        or "Could not start Ollama. Open the Ollama app from the Start menu, wait until "
        "it says running, then click Start Bot again."
    )


def list_installed_models() -> list[str]:
    """Return sorted unique model names from the local Ollama API."""
    tags = _http_get("/api/tags", timeout=5.0)
    if not tags:
        return []
    names = [m.get("name", "").strip() for m in tags.get("models", []) if m.get("name")]
    return sorted(set(names), key=str.lower)


def _model_available(model: str) -> bool:
    tags = _http_get("/api/tags", timeout=5.0)
    if not tags:
        return False

    available = list_installed_models() if tags else []
    if not available:
        return False

    base = model.split(":")[0].lower()
    model_l = model.lower()
    for name in available:
        n = name.lower()
        if n == model_l or n.startswith(f"{base}:") or n.split(":")[0] == base:
            return True
    return False


def ensure_model(model: Optional[str] = None) -> bool:
    """Ensure Ollama is up and the configured model is present."""
    model = model or bot.config.OLLAMA_MODEL
    if not start_ollama_server():
        return False

    if _model_available(model):
        global _last_error
        _last_error = None
        return True

    exe = find_ollama_cli()
    if not exe:
        return _set_error("Ollama CLI not found — cannot download model.")

    try:
        result = subprocess.run(
            [exe, "pull", model],
            capture_output=True,
            text=True,
            timeout=900,
            creationflags=CREATE_NO_WINDOW,
            cwd=str(Path(exe).parent),
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()[:300]
            return _set_error(f"Model pull failed for '{model}': {err}")
    except subprocess.TimeoutExpired:
        return _set_error(f"Timed out downloading model '{model}' (15 min).")
    except Exception as exc:
        return _set_error(f"Could not download model '{model}': {exc}")

    if not _model_available(model):
        return _set_error(
            f"Model '{model}' still not listed. Run in a terminal: ollama pull {model}"
        )

    _last_error = None
    invalidate_status_cache()
    return True


def is_ollama_ready_for_trading(model: Optional[str] = None) -> bool:
    """Fast check: API up and configured model is installed (no pull)."""
    if not bot.config.USE_OLLAMA_AI:
        return True
    model = model or bot.config.OLLAMA_MODEL
    return is_ollama_running() and _model_available(model)


def ensure_ollama_ready() -> bool:
    if not bot.config.USE_OLLAMA_AI:
        return True
    if is_ollama_ready_for_trading():
        _last_error = None
        return True
    if not bot.config.OLLAMA_AUTO_START:
        if is_ollama_running():
            return True
        return _set_error(
            "Ollama is not running. Open the Ollama app from Start menu, or enable "
            "'Auto-start Ollama' in Settings."
        )
    return ensure_model()


def _parse_json_response(text: str) -> Optional[dict]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return None


def evaluate_trade_setup(data: MarketData, setup: TradeSetup) -> dict[str, Any]:
    if not bot.config.USE_OLLAMA_AI:
        return {"action": "approve", "confidence": 100, "reason": "AI disabled", "skipped": True}

    if not is_ollama_running():
        return {
            "action": "reject",
            "confidence": 0,
            "reason": last_error_message() or "Ollama not running",
            "error": True,
        }

    snapshot = {
        "symbol": setup.symbol,
        "direction": setup.direction,
        "entry": setup.entry,
        "sl": setup.sl,
        "tp": setup.tp,
        "rrr": round(setup.rrr, 2),
        "rule_score": round(setup.score, 3),
        "rsi": round(data.rsi, 2),
        "ema9": round(data.ema9, 5),
        "ema21": round(data.ema21, 5),
        "ema50": round(data.ema50, 5),
        "macd_hist": round(data.macd_hist, 5),
        "atr": round(data.atr, 5),
        "price": round(float(data.closes[-1]), 5),
    }

    prompt = (
        f"Forex trade review. Reply ONLY JSON: "
        '{{"action":"approve"|"reject"|"hold","confidence":0-100,"reason":"short"}} '
        f"Data: {json.dumps(snapshot, separators=(',', ':'))}"
    )

    trade_timeout = float(
        getattr(bot.config, "OLLAMA_TRADE_TIMEOUT_SEC", 12) or 12
    )

    try:
        result = _http_post(
            "/api/generate",
            {
                "model": bot.config.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.15, "num_predict": 64},
            },
            timeout=trade_timeout,
        )
    except TimeoutError as exc:
        return {
            "action": "reject",
            "confidence": 0,
            "reason": f"Ollama timed out ({trade_timeout:.0f}s)",
            "error": True,
            "timeout": True,
        }
    except Exception as exc:
        return {
            "action": "reject",
            "confidence": 0,
            "reason": f"Ollama error: {exc}",
            "error": True,
        }

    if not result:
        return {"action": "reject", "confidence": 0, "reason": "Empty Ollama response", "error": True}

    parsed = _parse_json_response(result.get("response", ""))
    if not parsed:
        return {
            "action": "reject",
            "confidence": 0,
            "reason": "Could not parse AI response",
            "error": True,
        }

    action = str(parsed.get("action", "hold")).lower()
    if action not in ("approve", "reject", "hold"):
        action = "hold"

    return {
        "action": action,
        "confidence": int(parsed.get("confidence", 0)),
        "reason": str(parsed.get("reason", "AI analysis")),
        "error": False,
    }


def _trade_ai_timeout_sec() -> float:
    return float(getattr(bot.config, "OLLAMA_TRADE_TIMEOUT_SEC", 12) or 12)


def ai_approves_trade(data: MarketData, setup: TradeSetup) -> tuple[bool, str]:
    """Ask Ollama to approve a setup; never block longer than OLLAMA_TRADE_TIMEOUT_SEC."""
    if not bot.config.USE_OLLAMA_AI:
        return True, "AI off — rule-based only"

    hard_limit = _trade_ai_timeout_sec() + 2.0
    future = _AI_EXECUTOR.submit(evaluate_trade_setup, data, setup)

    try:
        verdict = future.result(timeout=hard_limit)
    except FuturesTimeoutError:
        if bot.config.OLLAMA_FALLBACK_ON_ERROR:
            return (
                True,
                f"AI skipped (>{hard_limit:.0f}s) — executing on rule-based signal",
            )
        return False, f"AI timed out after {hard_limit:.0f}s"

    if verdict.get("skipped"):
        return True, "AI off — rule-based only"

    action = verdict.get("action", "hold")
    confidence = verdict.get("confidence", 0)
    reason = verdict.get("reason", "")

    if verdict.get("error"):
        if bot.config.OLLAMA_FALLBACK_ON_ERROR:
            return True, f"AI skipped ({reason}) — executing on rule-based signal"
        return False, f"AI error: {reason}"

    min_conf = bot.config.OLLAMA_MIN_CONFIDENCE
    if action == "approve" and confidence >= min_conf:
        return True, f"AI approve ({confidence}%): {reason}"
    if action == "hold":
        return False, f"AI hold ({confidence}%): {reason}"
    return False, f"AI reject ({confidence}%): {reason}"


def ai_approves_trade_nonblocking(
    data: MarketData,
    setup: TradeSetup,
    on_done: Callable[[bool, str], None],
) -> None:
    """Fire-and-forget AI check (optional; main loop uses ai_approves_trade)."""

    def run() -> None:
        approved, msg = ai_approves_trade(data, setup)
        on_done(approved, msg)

    _AI_EXECUTOR.submit(run)


def ollama_status(*, use_cache: bool = True) -> dict[str, Any]:
    now = time.time()
    if use_cache and _status_cache["data"] is not None:
        if now - _status_cache["at"] < _STATUS_TTL_SEC:
            return _status_cache["data"]

    running = is_ollama_running() if bot.config.USE_OLLAMA_AI else False
    data = {
        "enabled": bot.config.USE_OLLAMA_AI,
        "running": running,
        "model": bot.config.OLLAMA_MODEL,
        "error": last_error_message(),
        "exe": find_ollama_cli(),
        "app": find_ollama_app(),
    }
    _status_cache["at"] = now
    _status_cache["data"] = data
    return data


def invalidate_status_cache() -> None:
    _status_cache["at"] = 0.0
    _status_cache["data"] = None
