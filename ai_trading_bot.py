import json
import MetaTrader5 as mt5
import time
import datetime
import numpy as np
import sys
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Callable
from threading import Event
from market_types import MarketData, TradeSetup, TradingConfig

config = TradingConfig()
TRADE_LOG_PATH = Path(__file__).parent / "trade_log.jsonl"
SCORE_WEIGHT_SUM = (
    config.EMA_WEIGHT + config.RSI_WEIGHT + config.MACD_WEIGHT
    + config.PRICE_WEIGHT + config.VOLUME_WEIGHT
)

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


def chart_timeframe() -> int:
    return TIMEFRAME_MAP.get(config.TIMEFRAME.upper(), mt5.TIMEFRAME_H1)


def min_score_threshold() -> float:
    if config.AGGRESSIVE_MODE:
        return config.MIN_SCORE_AGGRESSIVE
    return config.MIN_SCORE


def min_rrr_threshold() -> float:
    if config.AGGRESSIVE_MODE:
        return config.MIN_RRR_AGGRESSIVE
    return config.MIN_RRR


def ensure_mt5_connected() -> bool:
    from mt5_connection import ensure_mt5_connected as _connect

    return _connect()


# --- Technical Analysis ---

def calculate_ema_series(prices: np.ndarray, period: int) -> np.ndarray:
    """Standard exponential moving average over the full price series."""
    if len(prices) < period:
        raise ValueError(f"Need at least {period} prices for EMA({period})")

    multiplier = 2.0 / (period + 1)
    ema = np.empty(len(prices), dtype=float)
    ema[period - 1] = np.mean(prices[:period])
    for i in range(period, len(prices)):
        ema[i] = prices[i] * multiplier + ema[i - 1] * (1.0 - multiplier)
    return ema


def calculate_ema(prices: np.ndarray, period: int) -> float:
    return float(calculate_ema_series(prices, period)[-1])


def calculate_rsi(prices: np.ndarray, period: int = 14) -> float:
    """RSI with Wilder smoothing."""
    if len(prices) < period + 1:
        return 50.0

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_macd(
    prices: np.ndarray,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[float, float, float]:
    """MACD line, signal line, and histogram from EMA series."""
    ema_fast = calculate_ema_series(prices, fast_period)
    ema_slow = calculate_ema_series(prices, slow_period)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema_series(macd_line, signal_period)
    macd_val = float(macd_line[-1])
    signal_val = float(signal_line[-1])
    return macd_val, signal_val, macd_val - signal_val


def calculate_atr(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
) -> float:
    """Average True Range (Wilder-style smoothed)."""
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) else 0.0

    atr = float(np.mean(tr[:period]))
    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
    return atr


def fetch_market_data(
    symbol: str,
    timeframe: Optional[int] = None,
    n_candles: Optional[int] = None,
) -> Optional[MarketData]:
    """Fetch live market data from MT5."""
    from mt5_symbols import resolve_symbol

    try:
        resolved = resolve_symbol(symbol) or symbol
        timeframe = chart_timeframe() if timeframe is None else timeframe
        n_candles = n_candles or max(config.MIN_CANDLES, config.EMA_SLOW + 15)

        if not mt5.symbol_select(resolved, True):
            print(f"❌ Symbol {symbol} not available in Market Watch")
            return None

        rates = mt5.copy_rates_from_pos(resolved, timeframe, 0, n_candles)
        min_bars = max(config.EMA_SLOW + 5, 50)
        if rates is None or len(rates) < min_bars:
            print(f"❌ Failed to fetch enough candles for {resolved} (got {0 if rates is None else len(rates)})")
            return None

        rates = np.array(rates)
        opens = rates["open"]
        highs = rates["high"]
        lows = rates["low"]
        closes = rates["close"]
        volumes = rates["tick_volume"]

        ema9 = calculate_ema(closes, config.EMA_FAST)
        ema21 = calculate_ema(closes, config.EMA_MID)
        ema50 = calculate_ema(closes, config.EMA_SLOW)
        rsi = calculate_rsi(closes, config.RSI_PERIOD)
        macd, signal, hist = calculate_macd(
            closes, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
        )
        atr = calculate_atr(highs, lows, closes, config.ATR_PERIOD)
        avg_volume = float(np.mean(volumes[-20:]))

        return MarketData(
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            ema9=ema9,
            ema21=ema21,
            ema50=ema50,
            rsi=rsi,
            macd=macd,
            macd_signal=signal,
            macd_hist=hist,
            atr=atr,
            avg_volume=avg_volume,
        )
    except Exception as e:
        print(f"❌ Error fetching market data: {e}")
        return None


def analyze_ema_trend(ema9: float, ema21: float, ema50: float) -> float:
    """Score EMA trend alignment from -1 to 1."""
    if ema9 > ema21 > ema50:
        return 1.0
    if ema9 < ema21 < ema50:
        return -1.0
    if ema9 > ema21 and ema21 < ema50:
        return 0.5
    if ema9 < ema21 and ema21 > ema50:
        return -0.5
    return 0.0


def analyze_rsi(rsi: float) -> float:
    """Score RSI from -1 to 1 (mean-reversion bias)."""
    if rsi <= 30:
        return 1.0
    if rsi >= 70:
        return -1.0
    if rsi < 45:
        return 0.5
    if rsi > 55:
        return -0.5
    return 0.0


def analyze_macd(macd: float, signal: float, hist: float) -> float:
    """Score MACD from -1 to 1."""
    if hist > 0 and macd > signal:
        return 1.0
    if hist < 0 and macd < signal:
        return -1.0
    if hist > 0:
        return 0.5
    if hist < 0:
        return -0.5
    return 0.0


def analyze_price_action(data: MarketData) -> float:
    """Score recent price action from -1 to 1."""
    last_candle = data.closes[-1] - data.opens[-1]
    prev_candle = data.closes[-2] - data.opens[-2]

    if last_candle > 0 and prev_candle > 0:
        return 1.0
    if last_candle < 0 and prev_candle < 0:
        return -1.0
    if last_candle > 0:
        return 0.5
    if last_candle < 0:
        return -0.5
    return 0.0


def analyze_volume(current_volume: float, avg_volume: float) -> float:
    """Score volume from -1 to 1 based on deviation from average."""
    if avg_volume <= 0:
        return 0.0
    if current_volume > avg_volume * 1.5:
        return 1.0
    if current_volume < avg_volume * 0.5:
        return -1.0
    if current_volume > avg_volume:
        return 0.5
    if current_volume < avg_volume:
        return -0.5
    return 0.0


def determine_trade_direction(data: MarketData) -> str:
    """Trend-following direction from EMA, MACD, and price vs EMA21."""
    bullish_signals = 0
    bearish_signals = 0

    if data.ema9 > data.ema21 > data.ema50:
        bullish_signals += 1
    elif data.ema9 < data.ema21 < data.ema50:
        bearish_signals += 1

    if data.macd_hist > 0 and data.macd > data.macd_signal:
        bullish_signals += 1
    elif data.macd_hist < 0 and data.macd < data.macd_signal:
        bearish_signals += 1

    if data.closes[-1] > data.ema21:
        bullish_signals += 1
    elif data.closes[-1] < data.ema21:
        bearish_signals += 1

    if bullish_signals > bearish_signals and bullish_signals >= 2:
        return "BUY"
    if bearish_signals > bullish_signals and bearish_signals >= 2:
        return "SELL"

    score = weighted_score(data)
    if score >= 0.25:
        return "BUY"
    if score <= -0.25:
        return "SELL"
    return "NONE"


def weighted_score(data: MarketData) -> float:
    """Weighted composite score on -1..+1 scale."""
    return (
        analyze_ema_trend(data.ema9, data.ema21, data.ema50) * config.EMA_WEIGHT
        + analyze_rsi(data.rsi) * config.RSI_WEIGHT
        + analyze_macd(data.macd, data.macd_signal, data.macd_hist) * config.MACD_WEIGHT
        + analyze_price_action(data) * config.PRICE_WEIGHT
        + analyze_volume(data.volumes[-1], data.avg_volume) * config.VOLUME_WEIGHT
    ) / SCORE_WEIGHT_SUM


def aligned_score(total_score: float, direction: str) -> float:
    """Positive magnitude when score agrees with trade direction."""
    return total_score if direction == "BUY" else -total_score


def normalize_price(price: float, symbol_info) -> float:
    return round(price / symbol_info.point) * symbol_info.point


def enforce_stop_distance(entry: float, sl: float, tp: float, symbol_info) -> Tuple[float, float]:
    """Ensure SL/TP respect broker minimum stop distance."""
    min_dist = symbol_info.trade_stops_level * symbol_info.point
    if min_dist <= 0:
        return sl, tp

    if abs(entry - sl) < min_dist:
        sl = entry - min_dist if sl < entry else entry + min_dist
    if abs(entry - tp) < min_dist:
        tp = entry + min_dist if tp > entry else entry - min_dist
    return sl, tp


def calculate_trade_levels(
    symbol: str, direction: str, atr: float, symbol_info
) -> Optional[Tuple[float, float, float, float]]:
    """Entry, SL, TP, and RRR using live bid/ask."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None

    if direction == "BUY":
        entry = tick.ask
        sl = entry - atr * config.ATR_SL_MULTIPLIER
        tp = entry + atr * config.ATR_TP_MULTIPLIER
    else:
        entry = tick.bid
        sl = entry + atr * config.ATR_SL_MULTIPLIER
        tp = entry - atr * config.ATR_TP_MULTIPLIER

    sl = normalize_price(sl, symbol_info)
    tp = normalize_price(tp, symbol_info)
    sl, tp = enforce_stop_distance(entry, sl, tp, symbol_info)

    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rrr = reward / risk if risk > 0 else 0.0
    return entry, sl, tp, rrr


def calculate_lot_size(symbol: str, entry: float, sl: float) -> float:
    """Position size from account risk and symbol tick value."""
    account = mt5.account_info()
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return 0.01
    if account is None:
        return symbol_info.volume_min

    risk_amount = account.balance * config.RISK_PER_TRADE
    sl_distance = abs(entry - sl)
    if sl_distance <= 0 or symbol_info.trade_tick_size <= 0:
        return symbol_info.volume_min

    ticks = sl_distance / symbol_info.trade_tick_size
    money_per_lot = ticks * symbol_info.trade_tick_value
    if money_per_lot <= 0:
        return symbol_info.volume_min

    lots = risk_amount / money_per_lot
    lots = round(lots / symbol_info.volume_step) * symbol_info.volume_step
    lots = max(symbol_info.volume_min, min(lots, symbol_info.volume_max))
    return float(lots)


def spread_too_wide(symbol: str) -> bool:
    tick = mt5.symbol_info_tick(symbol)
    symbol_info = mt5.symbol_info(symbol)
    if tick is None or symbol_info is None or symbol_info.point <= 0:
        return True
    spread_points = (tick.ask - tick.bid) / symbol_info.point
    return spread_points > config.MAX_SPREAD_POINTS


def has_open_position(symbol: str) -> bool:
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return False
    return any(p.magic == config.MAGIC_NUMBER for p in positions)


# MQL5 SYMBOL_FILLING_* bitmask values (not exported by the MetaTrader5 Python wheel).
_SYMBOL_FILLING_FOK = 1
_SYMBOL_FILLING_IOC = 2


def order_filling_modes_for_symbol(symbol_info) -> list[int]:
    """Filling modes to try, best match for the symbol first."""
    filling = int(getattr(symbol_info, "filling_mode", 0) or 0)
    modes: list[int] = []
    if filling & _SYMBOL_FILLING_IOC:
        modes.append(mt5.ORDER_FILLING_IOC)
    if filling & _SYMBOL_FILLING_FOK:
        modes.append(mt5.ORDER_FILLING_FOK)
    # RETURN is widely supported as a fallback for many CFD/forex brokers.
    for fallback in (mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK):
        if fallback not in modes:
            modes.append(fallback)
    return modes


def get_order_filling_mode(symbol_info) -> int:
    return order_filling_modes_for_symbol(symbol_info)[0]


def explain_no_setup(data: MarketData, symbol: str) -> str:
    """Human-readable reason when analyze_market returns None."""
    direction = determine_trade_direction(data)
    total_score = weighted_score(data)

    if direction == "NONE":
        return (
            f"no clear trend (weighted score {total_score:+.2f}, need |score| ≥ 0.25 or "
            "2+ aligned EMA/MACD/price signals)"
        )

    score_aligned = aligned_score(total_score, direction)
    threshold = min_score_threshold()
    if score_aligned < threshold:
        return (
            f"{direction} signal too weak — aligned score {score_aligned:.2f} "
            f"< minimum {threshold:.2f}"
        )

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return f"symbol {symbol} not found on broker"

    levels = calculate_trade_levels(symbol, direction, data.atr, symbol_info)
    if levels is None:
        return "could not compute entry/SL/TP (no live tick)"
    _, _, _, rrr = levels
    min_rrr = min_rrr_threshold()
    if rrr < min_rrr:
        return f"RRR {rrr:.2f} below minimum {min_rrr:.2f}"

    if spread_too_wide(symbol):
        return f"spread too wide (max {config.MAX_SPREAD_POINTS} points)"

    setup = _build_trade_setup(data, symbol, direction, symbol_info, levels, total_score)
    if setup is None:
        return "AI rejected the setup (see Settings → Ollama confidence or disable AI filter)"
    return "unknown"


def _build_trade_setup(
    data: MarketData,
    symbol: str,
    direction: str,
    symbol_info,
    levels: Tuple[float, float, float, float],
    total_score: float,
) -> Optional[TradeSetup]:
    entry, sl, tp, rrr = levels
    score_aligned = aligned_score(total_score, direction)
    lot = calculate_lot_size(symbol, entry, sl)
    if lot < symbol_info.volume_min:
        return None

    reasons = []
    ema_score = analyze_ema_trend(data.ema9, data.ema21, data.ema50)
    if direction == "BUY":
        if ema_score > 0:
            reasons.append("EMAs aligned bullishly")
        if data.rsi < 45:
            reasons.append(f"RSI supportive ({data.rsi:.1f})")
        if data.macd_hist > 0:
            reasons.append("MACD histogram positive")
    else:
        if ema_score < 0:
            reasons.append("EMAs aligned bearishly")
        if data.rsi > 55:
            reasons.append(f"RSI supportive ({data.rsi:.1f})")
        if data.macd_hist < 0:
            reasons.append("MACD histogram negative")

    setup = TradeSetup(
        symbol=symbol,
        direction=direction,
        entry=entry,
        sl=sl,
        tp=tp,
        score=score_aligned,
        rrr=rrr,
        lot=lot,
        reasons=reasons,
    )

    if config.USE_OLLAMA_AI:
        from ollama_service import ai_approves_trade

        approved, ai_msg = ai_approves_trade(data, setup)
        if not approved:
            return None
        setup.reasons.append(ai_msg)

    return setup


def analyze_market(data: MarketData, symbol: str) -> Optional[TradeSetup]:
    """Analyze market data and generate trade setup if conditions are met."""
    direction = determine_trade_direction(data)
    if direction == "NONE":
        return None

    total_score = weighted_score(data)
    score_aligned = aligned_score(total_score, direction)
    if score_aligned < min_score_threshold():
        return None

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return None

    levels = calculate_trade_levels(symbol, direction, data.atr, symbol_info)
    if levels is None:
        return None

    if levels[3] < min_rrr_threshold():
        return None

    if spread_too_wide(symbol):
        return None

    return _build_trade_setup(data, symbol, direction, symbol_info, levels, total_score)


def log_trade_event(event: dict) -> None:
    event["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with TRADE_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def execute_trade(
    setup: TradeSetup,
    log: Optional[Callable[[str], None]] = None,
) -> tuple[Optional[int], str]:
    """Execute trade; returns (ticket, error_message). error_message empty on success."""
    from mt5_connection import check_algo_trading_enabled

    def emit(msg: str) -> None:
        print(msg)
        if log:
            log(msg)

    try:
        algo = check_algo_trading_enabled()
        if not algo.get("ok"):
            msg = "; ".join(algo.get("issues", ["Trading not allowed"]))
            emit(f"❌ {msg}")
            return None, msg

        symbol_info = mt5.symbol_info(setup.symbol)
        if symbol_info is None:
            msg = f"Failed to get symbol info for {setup.symbol}"
            emit(f"❌ {msg}")
            return None, msg

        if spread_too_wide(setup.symbol):
            msg = f"Spread too wide for {setup.symbol}"
            emit(f"❌ {msg}")
            return None, msg

        tick = mt5.symbol_info_tick(setup.symbol)
        if tick is None:
            msg = f"No live tick for {setup.symbol}"
            emit(f"❌ {msg}")
            return None, msg

        price = tick.ask if setup.direction == "BUY" else tick.bid
        volume = max(symbol_info.volume_min, min(setup.lot, symbol_info.volume_max))
        volume = round(volume / symbol_info.volume_step) * symbol_info.volume_step

        base_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": setup.symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if setup.direction == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": setup.sl,
            "tp": setup.tp,
            "deviation": config.SLIPPAGE_POINTS,
            "magic": config.MAGIC_NUMBER,
            "comment": f"Score: {setup.score:.2f}, RRR: {setup.rrr:.2f}",
            "type_time": mt5.ORDER_TIME_GTC,
        }

        emit(f"🚀 Sending {setup.direction} {setup.symbol} — {volume} lots…")
        result = None
        last_msg = ""
        invalid_fill = getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030)

        for fill_mode in order_filling_modes_for_symbol(symbol_info):
            request = {**base_request, "type_filling": fill_mode}
            result = mt5.order_send(request)
            if result is None:
                code, desc = mt5.last_error()
                last_msg = f"order_send failed [{code}: {desc}]"
                continue
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                break
            last_msg = f"{result.comment} (code {result.retcode})"
            if result.retcode != invalid_fill:
                break

        if result is None:
            emit(f"❌ {last_msg}")
            return None, last_msg
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = f"Order rejected: {last_msg}"
            emit(f"❌ {msg}")
            return None, msg

        emit("✅ Order executed successfully")
        emit(f"Order ID: {result.order} | Entry: {setup.entry:.5f} | SL: {setup.sl:.5f} | TP: {setup.tp:.5f}")

        position_ticket = result.order
        positions = mt5.positions_get(symbol=setup.symbol)
        if positions:
            for pos in positions:
                if pos.magic == config.MAGIC_NUMBER:
                    position_ticket = pos.ticket
                    break

        log_trade_event(
            {
                "event": "open",
                "symbol": setup.symbol,
                "direction": setup.direction,
                "entry": setup.entry,
                "sl": setup.sl,
                "tp": setup.tp,
                "lot": setup.lot,
                "score": setup.score,
                "rrr": setup.rrr,
                "reasons": setup.reasons,
                "ticket": position_ticket,
            }
        )
        return position_ticket, ""
    except Exception as e:
        msg = f"Error executing trade: {e}"
        emit(f"❌ {msg}")
        return None, msg


def monitor_open_trades(
    open_trades: Dict[int, dict],
    rolling_results: List[str],
    pause_until: List[Optional[datetime.datetime]],
) -> None:
    """Update rolling results when bot-managed positions close."""
    if not open_trades:
        return

    closed_tickets = []
    for ticket, meta in open_trades.items():
        position = None
        positions = mt5.positions_get(ticket=ticket)
        if positions:
            position = positions[0]

        if position is not None:
            continue

        profit = 0.0
        now = datetime.datetime.now(datetime.timezone.utc)
        deals = mt5.history_deals_get(meta["opened_at"], now)
        if deals:
            profit = sum(
                d.profit
                for d in deals
                if d.position_id == ticket and d.entry == mt5.DEAL_ENTRY_OUT
            )

        outcome = "win" if profit > 0 else "loss"
        rolling_results.append(outcome)
        if len(rolling_results) > 10:
            rolling_results.pop(0)

        log_trade_event(
            {
                "event": "close",
                "symbol": meta["symbol"],
                "ticket": ticket,
                "result": outcome,
                "profit": profit,
            }
        )
        print(f"📈 Trade {ticket} closed: {outcome} (profit: {profit:.2f})")
        closed_tickets.append(ticket)

        if len(rolling_results) >= 3 and rolling_results[-3:].count("loss") >= 2:
            pause_until[0] = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                hours=config.COOLDOWN_HOURS
            )
            print(
                f"🚫 Cooldown activated until "
                f"{pause_until[0].strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )

    for ticket in closed_tickets:
        del open_trades[ticket]


def is_in_trading_hours(*, quiet: bool = False) -> bool:
    """Check if forex market is open."""
    now = datetime.datetime.now(datetime.timezone.utc)

    if not config.WEEKEND_CLOSURE:
        return True

    if now.weekday() >= 5:
        if now.weekday() == 6 and now.hour >= config.MARKET_OPEN_HOUR_UTC:
            return True
        if not quiet:
            print("Market closed for weekend")
        return False

    if now.weekday() == 4 and now.hour >= config.MARKET_CLOSE_HOUR_UTC:
        if not quiet:
            print("Market closed for weekend")
        return False

    return True


def interruptible_sleep(seconds: float, stop_event: Optional[Event] = None) -> bool:
    """Sleep in 1s chunks; return True if stop was requested."""
    end = time.time() + seconds
    while time.time() < end:
        if stop_event and stop_event.is_set():
            return True
        time.sleep(min(1.0, end - time.time()))
    return False


def is_in_cooldown(
    pause_until: Optional[datetime.datetime],
    *,
    quiet: bool = False,
) -> bool:
    now = datetime.datetime.now(datetime.timezone.utc)
    if pause_until and now < pause_until:
        if not quiet:
            print(f"🚫 Trading paused until {pause_until.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        return True
    return False


def start_trading(
    symbols: List[str],
    stop_event: Optional[Event] = None,
    log: Optional[Callable[[str], None]] = None,
    dry_run: Optional[bool] = None,
) -> None:
    """Main trading loop analyzing multiple symbols."""

    def emit(message: str) -> None:
        print(message)
        if log:
            log(message)

    use_dry_run = config.DRY_RUN if dry_run is None else dry_run

    from mt5_connection import check_algo_trading_enabled
    from mt5_symbols import resolve_symbol_list

    emit("🤖 Starting AI Trading Bot")
    emit(f"Mode: {'Aggressive' if config.AGGRESSIVE_MODE else 'Conservative'}")
    emit(f"Dry run: {'ON' if use_dry_run else 'OFF — live orders enabled'}")
    emit(f"Chart: {config.TIMEFRAME} | Min score: {min_score_threshold():.2f} | Min RRR: {min_rrr_threshold():.2f}")
    emit(f"Risk per trade: {config.RISK_PER_TRADE * 100:.1f}%")

    resolved, missing = resolve_symbol_list(symbols)
    if missing:
        emit(f"⚠️ Symbols not found on broker: {', '.join(missing)}")
    if resolved:
        symbols = resolved
        emit(f"📈 Watching: {', '.join(symbols)}")
    else:
        emit("❌ No valid symbols — add symbols to Market Watch in MT5")
        return

    algo = check_algo_trading_enabled()
    if not algo.get("ok"):
        for issue in algo.get("issues", []):
            emit(f"❌ {issue}")
        if not use_dry_run:
            emit("Cannot place live orders until algo trading is enabled in MT5.")
            return

    last_trade_time: Dict[str, datetime.datetime] = {}
    rolling_results: List[str] = []
    pause_until: List[Optional[datetime.datetime]] = [None]
    open_trades: Dict[int, dict] = {}

    try:
        while not (stop_event and stop_event.is_set()):
            if not ensure_mt5_connected():
                emit("❌ MT5 disconnected — retrying in 60s")
                if interruptible_sleep(60, stop_event):
                    break
                continue

            now = datetime.datetime.now(datetime.timezone.utc)
            emit(f"\n⏰ Checking at {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")

            monitor_open_trades(open_trades, rolling_results, pause_until)

            if not is_in_trading_hours(quiet=True):
                emit("⏰ Outside trading hours. Waiting…")
                while not is_in_trading_hours(quiet=True):
                    if stop_event and stop_event.is_set():
                        break
                    if interruptible_sleep(15, stop_event):
                        break
                if stop_event and stop_event.is_set():
                    break
                continue

            if is_in_cooldown(pause_until[0], quiet=True):
                emit(
                    f"🚫 Cooldown active until "
                    f"{pause_until[0].strftime('%Y-%m-%d %H:%M:%S')} UTC"
                    if pause_until[0]
                    else "🚫 Cooldown active"
                )
                while is_in_cooldown(pause_until[0], quiet=True):
                    if stop_event and stop_event.is_set():
                        break
                    if interruptible_sleep(15, stop_event):
                        break
                if stop_event and stop_event.is_set():
                    break
                continue

            for symbol in symbols:
                if stop_event and stop_event.is_set():
                    break

                if symbol in last_trade_time:
                    elapsed = (now - last_trade_time[symbol]).total_seconds()
                    if elapsed < config.MIN_SECONDS_BETWEEN_TRADES:
                        continue

                if has_open_position(symbol):
                    emit(f"⏭️  Skipping {symbol} — open position exists")
                    continue

                emit(f"\n📊 Analyzing {symbol}...")

                market_data = fetch_market_data(symbol)
                if market_data is None:
                    emit(f"❌ Could not fetch {config.TIMEFRAME} data for {symbol}")
                    continue

                direction = determine_trade_direction(market_data)
                score = weighted_score(market_data)
                aligned = (
                    aligned_score(score, direction) if direction != "NONE" else 0.0
                )
                price = float(market_data.closes[-1])
                emit(
                    f"📉 {symbol} price={price:.5f} RSI={market_data.rsi:.1f} "
                    f"dir={direction} score={aligned:+.2f}"
                )

                trade_setup = analyze_market(market_data, symbol)
                if trade_setup is None:
                    emit(f"ℹ️ No setup for {symbol}: {explain_no_setup(market_data, symbol)}")
                    continue

                emit(f"\n🎯 Trade Setup Found for {symbol}:")
                emit(f"Direction: {trade_setup.direction}")
                emit(f"Aligned score: {trade_setup.score:.2f}")
                emit(f"RRR: {trade_setup.rrr:.2f}")
                emit(f"Lots: {trade_setup.lot}")
                emit("Reasons:")
                for reason in trade_setup.reasons:
                    emit(f"- {reason}")

                if use_dry_run:
                    emit(f"🔬 Dry run — order NOT sent for {symbol}")
                    last_trade_time[symbol] = now
                    continue

                ticket, order_err = execute_trade(trade_setup, log=emit)
                if ticket:
                    emit(f"✅ Live order placed — ticket {ticket}")
                    last_trade_time[symbol] = now
                    open_trades[ticket] = {
                        "symbol": symbol,
                        "opened_at": now,
                    }
                elif order_err:
                    emit(f"❌ Trade not opened: {order_err}")

            if interruptible_sleep(60, stop_event):
                break

    except KeyboardInterrupt:
        raise
    except Exception as e:
        emit(f"❌ Error in main loop: {e}")
        interruptible_sleep(60, stop_event)

    emit("🛑 Trading loop stopped")


def main_cli() -> None:
    """Console entry point (headless bot, no UI)."""
    if not mt5.initialize():
        print("❌ Failed to initialize MT5")
        sys.exit(1)

    symbols = ["XAUUSD", "EURUSD", "USDJPY", "GBPUSD"]

    try:
        start_trading(symbols)
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main_cli()
