from dataclasses import dataclass
from typing import List
import numpy as np


@dataclass
class TradingConfig:
    """Trading configuration settings"""
    # Mode settings (scores are on -1..+1 scale; aligned score must exceed MIN_SCORE)
    AGGRESSIVE_MODE: bool = False
    MIN_SCORE: float = 0.35
    MIN_SCORE_AGGRESSIVE: float = 0.28

    # Risk settings
    RISK_PER_TRADE: float = 0.01
    ATR_SL_MULTIPLIER: float = 1.5
    ATR_TP_MULTIPLIER: float = 3.0
    MIN_RRR: float = 1.2
    MIN_RRR_AGGRESSIVE: float = 1.0
    SLIPPAGE_POINTS: int = 20
    MAGIC_NUMBER: int = 123456
    COOLDOWN_HOURS: int = 4
    MAX_SPREAD_POINTS: int = 80

    # Indicator periods
    EMA_FAST: int = 9
    EMA_MID: int = 21
    EMA_SLOW: int = 50
    RSI_PERIOD: int = 14
    ATR_PERIOD: int = 14
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9

    # Scoring weights
    EMA_WEIGHT: float = 1.5
    RSI_WEIGHT: float = 1.0
    MACD_WEIGHT: float = 1.0
    PRICE_WEIGHT: float = 0.5
    VOLUME_WEIGHT: float = 0.5

    # Market closure checks
    WEEKEND_CLOSURE: bool = True
    MARKET_OPEN_HOUR_UTC: int = 22
    MARKET_CLOSE_HOUR_UTC: int = 21

    # Throttle
    MIN_SECONDS_BETWEEN_TRADES: int = 300
    MIN_CANDLES: int = 60
    TIMEFRAME: str = "H1"  # M15, H1, H4, D1

    # UI / safety
    DRY_RUN: bool = False
    AUTO_START_TRADING: bool = True

    # Ollama AI
    USE_OLLAMA_AI: bool = True
    OLLAMA_AUTO_START: bool = True
    OLLAMA_HOST: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "llama3:latest"
    OLLAMA_TIMEOUT_SEC: int = 90
    OLLAMA_TRADE_TIMEOUT_SEC: int = 12
    OLLAMA_STARTUP_WAIT_SEC: int = 90
    OLLAMA_MIN_CONFIDENCE: int = 55
    OLLAMA_FALLBACK_ON_ERROR: bool = True


@dataclass
class MarketData:
    """Container for market data and indicators"""
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray
    ema9: float
    ema21: float
    ema50: float
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    atr: float
    avg_volume: float


@dataclass
class TradeSetup:
    """Container for trade setup details"""
    symbol: str
    direction: str
    entry: float
    sl: float
    tp: float
    score: float
    rrr: float
    lot: float
    reasons: List[str]
