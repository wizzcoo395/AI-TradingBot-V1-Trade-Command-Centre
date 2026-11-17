"""Robust MetaTrader 5 connection for Windows."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5

_last_error: Optional[str] = None
_connected_path: Optional[str] = None


def last_error_message() -> Optional[str]:
    return _last_error


def connected_terminal_path() -> Optional[str]:
    return _connected_path


def _set_error(msg: str) -> bool:
    global _last_error
    _last_error = msg
    return False


def _format_mt5_error(context: str) -> str:
    code, desc = mt5.last_error()
    if code:
        return f"{context} [{code}: {desc}]"
    return context


def find_running_terminal_exe() -> Optional[str]:
    """Path of terminal64.exe that is currently running (Windows)."""
    try:
        ps = (
            "Get-Process -Name terminal64 -ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty Path"
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            timeout=12,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()
        if out and Path(out).is_file():
            return str(Path(out).resolve())
    except Exception:
        pass
    return None


def find_all_terminal_exes() -> list[str]:
    """Candidate terminal64.exe paths; running instance first."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(path: Optional[str]) -> None:
        if not path:
            return
        p = Path(path)
        if not p.is_file():
            return
        key = str(p.resolve()).lower()
        if key in seen:
            return
        seen.add(key)
        ordered.append(str(p.resolve()))

    add(find_running_terminal_exe())

    env_path = os.environ.get("MT5_PATH") or os.environ.get("METATRADER5_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            add(str(p))
        elif p.is_dir():
            for name in ("terminal64.exe", "terminal.exe"):
                add(str(p / name))

    add(r"C:\Program Files\MetaTrader 5\terminal64.exe")
    add(r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe")

    appdata = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    if appdata.is_dir():
        for terminal_dir in sorted(appdata.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            add(str(terminal_dir / "terminal64.exe"))

    for root in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        broker_root = Path(root)
        if broker_root.is_dir():
            for child in broker_root.glob("**/terminal64.exe"):
                add(str(child))

    return ordered


def find_terminal_exe() -> Optional[str]:
    paths = find_all_terminal_exes()
    return paths[0] if paths else None


def _init_kwargs(path: Optional[str] = None) -> dict:
    kwargs: dict = {"timeout": 90_000}
    if path:
        kwargs["path"] = path

    login = os.environ.get("MT5_LOGIN")
    password = os.environ.get("MT5_PASSWORD")
    server = os.environ.get("MT5_SERVER")
    if login and password:
        kwargs["login"] = int(login)
        kwargs["password"] = password
        if server:
            kwargs["server"] = server
    return kwargs


def _verify_session() -> bool:
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None:
        return _set_error(_format_mt5_error("MT5 terminal not responding"))
    if account is None:
        return _set_error(
            _format_mt5_error(
                "MT5 has no logged-in account. Log in to your broker in the terminal window."
            )
        )
    return True


def _try_initialize(path: Optional[str]) -> bool:
    global _connected_path
    label = path or "active terminal"
    if not mt5.initialize(**_init_kwargs(path)):
        _set_error(_format_mt5_error(f"initialize() failed for {label}"))
        return False
    if not _verify_session():
        mt5.shutdown()
        return False
    _connected_path = path
    _last_error = None
    return True


def initialize_mt5() -> bool:
    """Connect Python to MetaTrader 5."""
    global _last_error, _connected_path

    try:
        mt5.shutdown()
    except Exception:
        pass

    # 1) Running terminal (best when user already opened MT5)
    if _try_initialize(None):
        return True
    try:
        mt5.shutdown()
    except Exception:
        pass

    # 2) Each installed terminal path (newest / running first)
    paths = find_all_terminal_exes()
    for path in paths:
        if _try_initialize(path):
            return True
        try:
            mt5.shutdown()
        except Exception:
            pass

    hint = (
        "Ensure MetaTrader 5 is open, you are logged in, and "
        "'Allow algorithmic trading' is enabled under Tools → Options → Expert Advisors. "
        "If you use a portable install, set MT5_PATH to your terminal64.exe folder."
    )
    if not paths:
        return _set_error(f"No MetaTrader 5 installation found. {hint}")
    return _set_error(
        f"Could not connect to MetaTrader 5 (tried {len(paths)} location(s)). {hint}"
    )


def ensure_mt5_connected() -> bool:
    if is_session_active():
        _last_error = None
        return True
    return initialize_mt5()


def is_session_active() -> bool:
    try:
        if mt5.terminal_info() is None:
            return False
        return mt5.account_info() is not None
    except Exception:
        return False


def check_algo_trading_enabled() -> dict:
    """Verify MT5 allows automated / API trading."""
    if not is_session_active() and not ensure_mt5_connected():
        return {
            "ok": False,
            "issues": [last_error_message() or "MT5 not connected"],
            "trade_allowed": False,
            "expert_allowed": False,
        }

    terminal = mt5.terminal_info()
    account = mt5.account_info()
    issues: list[str] = []

    if terminal is None:
        issues.append("MT5 terminal not responding")
    else:
        if not getattr(terminal, "connected", False):
            issues.append("MT5 is not connected to the broker server")
        if not getattr(terminal, "trade_allowed", False):
            issues.append(
                "Algorithmic trading is OFF — in MetaTrader 5 enable the green "
                "'Algo Trading' button on the toolbar (or Tools → Options → "
                "Expert Advisors → Allow algorithmic trading)."
            )

    if account is None:
        issues.append("No trading account logged in")
    else:
        if not getattr(account, "trade_allowed", True):
            issues.append("Trading is disabled for this account (contact broker or check MT5)")
        if hasattr(account, "trade_expert") and not account.trade_expert:
            issues.append(
                "Expert Advisors are disabled for this account — enable in "
                "Tools → Options → Expert Advisors"
            )

    trade_ok = bool(getattr(terminal, "trade_allowed", False)) if terminal else False
    expert_ok = not account or getattr(account, "trade_expert", True)

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "trade_allowed": trade_ok,
        "expert_allowed": expert_ok,
        "terminal_name": getattr(terminal, "name", None) if terminal else None,
        "account": getattr(account, "login", None) if account else None,
    }


def connection_details(*, try_connect: bool = False) -> dict:
    connected = ensure_mt5_connected() if try_connect else is_session_active()
    if try_connect and not connected:
        connected = False

    terminal = mt5.terminal_info() if connected else None
    account = mt5.account_info() if connected else None
    algo = check_algo_trading_enabled() if connected else {"ok": False, "issues": []}

    return {
        "connected": connected,
        "error": last_error_message(),
        "terminal_path": connected_terminal_path() or find_terminal_exe(),
        "trade_allowed": bool(getattr(terminal, "trade_allowed", False)) if terminal else False,
        "algo_trading_ok": algo.get("ok", False),
        "algo_issues": algo.get("issues", []),
        "terminal_name": getattr(terminal, "name", None) if terminal else None,
        "account": getattr(account, "login", None) if account else None,
        "balance": getattr(account, "balance", None) if account else None,
        "server": getattr(account, "server", None) if account else None,
    }
