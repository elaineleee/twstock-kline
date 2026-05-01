"""8 Nison candlestick patterns + indicators (RSI, MA, ATR).

Each pattern returns a boolean pandas.Series aligned with the input frame; True
on bars where the pattern completes. The last-bar convenience helpers wrap the
vectorised detectors for the morning-brief workflow."""
from __future__ import annotations

import numpy as np
import pandas as pd

BUY_PATTERNS = ("早晨之星", "看漲孕線", "向上窗口", "倒錘子線")
SELL_PATTERNS = ("流星線", "大陰線", "看跌吞沒", "向下窗口")
ALL_PATTERNS = BUY_PATTERNS + SELL_PATTERNS

PATTERN_DIRECTION = {p: "買入" for p in BUY_PATTERNS} | {p: "賣出" for p in SELL_PATTERNS}


def _ohlc(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    return df["Open"], df["High"], df["Low"], df["Close"]


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _body(o: pd.Series, c: pd.Series) -> pd.Series:
    return (c - o).abs()


def _range(h: pd.Series, l: pd.Series) -> pd.Series:
    return (h - l).replace(0, np.nan)


def _upper_shadow(o: pd.Series, h: pd.Series, c: pd.Series) -> pd.Series:
    return h - pd.concat([o, c], axis=1).max(axis=1)


def _lower_shadow(o: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    return pd.concat([o, c], axis=1).min(axis=1) - l


# -- Buy patterns --------------------------------------------------------

def detect_morning_star(df: pd.DataFrame) -> pd.Series:
    """3-bar reversal at the bottom of a downtrend (Nison p.66–70)."""
    o, h, l, c = _ohlc(df)
    body = _body(o, c)
    rng = _range(h, l)

    o2, c2, h2, l2 = o.shift(2), c.shift(2), h.shift(2), l.shift(2)
    rng2 = _range(h2, l2)
    long_red_2 = (c2 < o2) & (_body(o2, c2) / rng2 > 0.6)

    o1, c1, h1, l1 = o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    rng1 = _range(h1, l1)
    small_star_1 = (_body(o1, c1) / rng1 < 0.3) & (
        pd.concat([o1, c1], axis=1).max(axis=1) < c2
    )

    long_green_now = (c > o) & (body / rng > 0.5)
    midpoint_2 = (o2 + c2) / 2
    pierces = c >= midpoint_2

    return (long_red_2 & small_star_1 & long_green_now & pierces).fillna(False)


def detect_bullish_harami(df: pd.DataFrame) -> pd.Series:
    """2-bar containment after a long red day (Nison p.88–89)."""
    o, h, l, c = _ohlc(df)
    o1, c1, h1, l1 = o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    rng1 = _range(h1, l1)
    rng = _range(h, l)

    long_red_prev = (c1 < o1) & (_body(o1, c1) / rng1 > 0.6)
    body_top_now = pd.concat([o, c], axis=1).max(axis=1)
    body_bot_now = pd.concat([o, c], axis=1).min(axis=1)

    contained = (body_top_now < o1) & (body_bot_now > c1)
    small_now = _body(o, c) / rng < 0.5
    bullish_now = c >= o
    return (long_red_prev & contained & small_now & bullish_now).fillna(False)


def detect_rising_window(df: pd.DataFrame) -> pd.Series:
    """Gap up: today's low strictly above yesterday's high (Nison p.138–147)."""
    _, h, l, _ = _ohlc(df)
    return (l > h.shift(1)).fillna(False)


def detect_inverted_hammer(df: pd.DataFrame) -> pd.Series:
    """Small body at low end, long upper shadow, in a downtrend (Nison p.83–85)."""
    o, h, l, c = _ohlc(df)
    rng = _range(h, l)
    body = _body(o, c)
    upper = _upper_shadow(o, h, c)
    lower = _lower_shadow(o, l, c)

    ma10 = c.rolling(10).mean()
    downtrend = c < ma10

    return (
        (body / rng < 0.3)
        & (upper / rng > 0.5)
        & (lower / rng < 0.15)
        & downtrend
    ).fillna(False)


# -- Sell patterns -------------------------------------------------------

def detect_shooting_star(df: pd.DataFrame) -> pd.Series:
    """Inverted hammer's mirror: long upper shadow at top of an uptrend."""
    o, h, l, c = _ohlc(df)
    rng = _range(h, l)
    body = _body(o, c)
    upper = _upper_shadow(o, h, c)
    lower = _lower_shadow(o, l, c)

    ma10 = c.rolling(10).mean()
    uptrend = c > ma10

    return (
        (body / rng < 0.3)
        & (upper / rng > 0.5)
        & (lower / rng < 0.15)
        & uptrend
    ).fillna(False)


def detect_large_bearish(df: pd.DataFrame) -> pd.Series:
    """Long black candle (a.k.a. bearish marubozu): >=1.5x ATR body, almost no shadow."""
    o, h, l, c = _ohlc(df)
    rng = _range(h, l)
    body = _body(o, c)
    a = atr(df, 14)
    return (
        (c < o)
        & (body / rng > 0.85)
        & ((c - l) / rng < 0.1)
        & ((h - o) / rng < 0.1)
        & (body >= 1.5 * a)
    ).fillna(False)


def detect_bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Today's red body fully wraps yesterday's green body."""
    o, _, _, c = _ohlc(df)
    o1, c1 = o.shift(1), c.shift(1)
    prev_green = c1 > o1
    today_red = c < o
    engulf = (o >= c1) & (c <= o1) & ((o > c1) | (c < o1))
    return (prev_green & today_red & engulf).fillna(False)


def detect_falling_window(df: pd.DataFrame) -> pd.Series:
    """Gap down: today's high strictly below yesterday's low."""
    _, h, l, _ = _ohlc(df)
    return (h < l.shift(1)).fillna(False)


DETECTORS: dict[str, callable] = {
    "早晨之星": detect_morning_star,
    "看漲孕線": detect_bullish_harami,
    "向上窗口": detect_rising_window,
    "倒錘子線": detect_inverted_hammer,
    "流星線": detect_shooting_star,
    "大陰線": detect_large_bearish,
    "看跌吞沒": detect_bearish_engulfing,
    "向下窗口": detect_falling_window,
}


def detect_all(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {name: fn(df) for name, fn in DETECTORS.items()}


def last_bar_signals(df: pd.DataFrame) -> list[str]:
    """Names of patterns that fire on the most recent bar."""
    if df.empty:
        return []
    return [name for name, ser in detect_all(df).items() if bool(ser.iloc[-1])]
