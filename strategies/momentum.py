import pandas as pd

def compute_indicators(df: pd.DataFrame, lookback_short=20, lookback_long=50, atr_len=14, breakout_len=20):
    high, low, close = df["high"], df["low"], df["close"]
    short = close.rolling(lookback_short).mean()
    long = close.rolling(lookback_long).mean()
    tr = (high - low)
    atr = tr.rolling(atr_len).mean()
    breakout_up = high.rolling(breakout_len).max()
    breakout_dn = low.rolling(breakout_len).min()
    return short, long, atr, breakout_up, breakout_dn

def signal(df: pd.DataFrame, **kw):
    short,long,atr,bo_up,bo_dn = compute_indicators(df, **kw)
    last = df.index[-1]
    mom = short.iloc[-1] - long.iloc[-1]
    price = df["close"].iloc[-1]
    buy  = bool(mom > 0 and price > bo_up.iloc[-2])
    sell = bool(mom < 0 and price < bo_dn.iloc[-2])
    sl   = float(price - 2*atr.iloc[-1])
    tp   = float(price + 3*atr.iloc[-1])
    return {"buy": buy, "sell": sell, "sl": sl, "tp": tp, "price": float(price)}
