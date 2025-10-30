import pandas as pd

def _candle(df, idx=-1):
    o = df["open"].iloc[idx]; h = df["high"].iloc[idx]; l = df["low"].iloc[idx]; c = df["close"].iloc[idx]
    body = abs(c - o); upper = h - max(c, o); lower = min(c, o) - l
    return o, h, l, c, body, upper, lower

def bullish_engulfing(df: pd.DataFrame) -> bool:
    if len(df) < 2: return False
    o1,h1,l1,c1,_,_,_ = _candle(df, -2)
    o2,h2,l2,c2,_,_,_ = _candle(df, -1)
    return (c1 < o1) and (c2 > o2) and (c2 >= o1) and (o2 <= c1)  # red then green fully engulfs

def hammer(df: pd.DataFrame) -> bool:
    if len(df) < 1: return False
    o,h,l,c,body,upper,lower = _candle(df, -1)
    total = (h - l) if (h - l) > 0 else 1e-9
    return (c > o*0.995) and (lower >= 2*body) and (upper <= body) and (body/total <= 0.35)

def morning_star(df: pd.DataFrame) -> bool:
    if len(df) < 3: return False
    # red big body, small indecision, then strong green close into red's body
    o1,h1,l1,c1,body1,_,_ = _candle(df, -3)
    o2,h2,l2,c2,body2,_,_ = _candle(df, -2)
    o3,h3,l3,c3,body3,_,_ = _candle(df, -1)
    cond1 = (c1 < o1) and (body1 > (h1 - l1) * 0.4)
    cond2 = body2 < (h2 - l2) * 0.2
    cond3 = (c3 > o3) and (c3 > (o1 - (o1 - c1)*0.5))  # closes into prior red body
    return cond1 and cond2 and cond3

def bullish_pattern_hit(df: pd.DataFrame, allowed=("bullish_engulfing","hammer","morning_star")):
    checks = {
        "bullish_engulfing": bullish_engulfing(df),
        "hammer": hammer(df),
        "morning_star": morning_star(df)
    }
    for name in allowed:
        if checks.get(name, False):
            return True, name
    return False, None
