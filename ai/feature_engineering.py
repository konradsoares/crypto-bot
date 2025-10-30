import numpy as np
import pandas as pd

def pct_rank(x: pd.Series):
    return x.rank(pct=True).iloc[-1] * 100.0

def roll_slope(y: pd.Series, win=20):
    # slope of close over window (scaled to % of price)
    x = np.arange(win)
    ywin = y.iloc[-win:].values
    b, a = np.polyfit(x, ywin, 1)  # y = a + b*x
    return (b / ywin[-1]) * 100.0

def rsi(close: pd.Series, period=14):
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = up / (down + 1e-12)
    return 100 - (100 / (1 + rs))

def macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def adx(high, low, close, period=14):
    # lightweight ADX approximation (good enough for grading)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = np.maximum.reduce([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ])
    atr = pd.Series(tr).rolling(period).mean()
    plus_di = 100 * pd.Series(plus_dm).rolling(period).sum() / (atr * period + 1e-12)
    minus_di = 100 * pd.Series(minus_dm).rolling(period).sum() / (atr * period + 1e-12)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-12)) * 100
    return pd.Series(dx).rolling(period).mean()

def build_features(df: pd.DataFrame) -> dict:
    # Assumes columns: ts, open, high, low, close, volume
    feats = {}
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]

    # Trend / momentum
    feats["ema_fast"] = close.ewm(span=20).mean().iloc[-1]
    feats["ema_slow"] = close.ewm(span=50).mean().iloc[-1]
    feats["ema_gap_pct"] = ((feats["ema_fast"] - feats["ema_slow"]) / close.iloc[-1]) * 100.0
    feats["slope_20_pct"] = roll_slope(close, 20)
    feats["slope_50_pct"] = roll_slope(close, 50)

    # Volatility / structure
    atr14 = (high - low).rolling(14).mean()
    feats["atr14_pct"] = (atr14.iloc[-1] / close.iloc[-1]) * 100.0
    feats["vol_rank_20"] = pct_rank(vol.rolling(20).mean())

    # RSI / MACD / ADX
    rsi14 = rsi(close, 14)
    feats["rsi14"] = float(rsi14.iloc[-1])
    macd_line, signal_line, hist = macd(close)
    feats["macd_hist_norm"] = float((hist.iloc[-1]) / (close.iloc[-1] + 1e-12) * 100.0)
    adx14 = adx(high, low, close, 14)
    feats["adx14"] = float(adx14.iloc[-1])

    # Breakout distances
    feats["dist_to_20d_high_pct"] = ((close.iloc[-1] - high.rolling(20).max().iloc[-2]) / close.iloc[-1]) * 100.0
    feats["dist_to_20d_low_pct"]  = ((close.iloc[-1] - low.rolling(20).min().iloc[-2]) / close.iloc[-1]) * 100.0

    # Sanity
    feats["price"] = float(close.iloc[-1])

    return {k: float(v) for k, v in feats.items()}
