"""Resolve broker-specific MT5 symbol names."""
from __future__ import annotations

from typing import Optional

import MetaTrader5 as mt5


def resolve_symbol(name: str) -> Optional[str]:
    """Map a user symbol (e.g. XAUUSD) to the broker's Market Watch name."""
    base = name.strip().upper()
    if not base:
        return None

    candidates: list[str] = [base]
    for suffix in (".", "m", ".m", "pro", ".pro", "i", ".i", "#", ".raw", "_", ".a"):
        candidates.append(f"{base}{suffix}")

    seen: set[str] = set()
    for sym in candidates:
        key = sym.upper()
        if key in seen:
            continue
        seen.add(key)
        info = mt5.symbol_info(sym)
        if info is None:
            continue
        if mt5.symbol_select(sym, True):
            return sym

    try:
        all_symbols = mt5.symbols_get()
    except Exception:
        all_symbols = None

    if all_symbols:
        for info in all_symbols:
            sym_name = info.name
            upper = sym_name.upper()
            if upper == base or upper.startswith(base):
                if mt5.symbol_select(sym_name, True):
                    return sym_name

    return None


def resolve_symbol_list(names: list[str]) -> tuple[list[str], list[str]]:
    """Return (resolved, missing) symbol lists."""
    resolved: list[str] = []
    missing: list[str] = []
    for name in names:
        sym = resolve_symbol(name)
        if sym:
            if sym not in resolved:
                resolved.append(sym)
        else:
            missing.append(name)
    return resolved, missing
