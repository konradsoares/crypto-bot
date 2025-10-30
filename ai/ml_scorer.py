import math

# A transparent, rule-driven score 0..100 built from features.
# This does NOT peek ahead; it grades *current* structure (trend strength/coherence).

WEIGHTS = {
    "ema_gap_pct": 0.25,      # positive separation favors trend
    "slope_20_pct": 0.20,     # short-term slope
    "slope_50_pct": 0.10,     # consistency across horizons
    "adx14": 0.15,            # trend strength
    "macd_hist_norm": 0.10,   # momentum thrust
    "rsi14": 0.10,            # mid 50-70 is good; extremes penalized
    "atr14_pct": -0.10,       # too much noise hurts trend quality
    "vol_rank_20": 0.10,      # participation (volume percentile)
}

def _clamp(x, a, b): return max(a, min(b, x))

def score(features: dict) -> dict:
    # Normalize inputs to sensible ranges
    ema_gap = _clamp(features.get("ema_gap_pct", 0.0), -2.0, 2.0) / 2.0    # -1..1
    slope20 = _clamp(features.get("slope_20_pct", 0.0), -3.0, 3.0) / 3.0   # -1..1
    slope50 = _clamp(features.get("slope_50_pct", 0.0), -2.0, 2.0) / 2.0   # -1..1
    adx     = _clamp((features.get("adx14", 0.0) - 15) / 35, 0.0, 1.0)     # 0..1 (15..50)
    macd_n  = _clamp((features.get("macd_hist_norm", 0.0) + 0.5) / 1.0, 0.0, 1.0)  # -50bp..+50bp
    rsi     = features.get("rsi14", 50.0)
    rsi_q   = 1.0 - abs((rsi - 60.0) / 40.0)       # peak at ~60, fades to 0 at 20/100
    rsi_q   = _clamp(rsi_q, 0.0, 1.0)
    atrp    = features.get("atr14_pct", 1.0)
    noise   = _clamp((atrp - 0.5) / 3.0, 0.0, 1.0) # 0.5%..3.5%+
    volp    = _clamp(features.get("vol_rank_20", 50.0) / 100.0, 0.0, 1.0)

    components = {
        "ema_gap": ema_gap,
        "slope20": (slope20 + 1) / 2,    # 0..1
        "slope50": (slope50 + 1) / 2,
        "adx": adx,
        "macd": macd_n,
        "rsi": rsi_q,
        "noise_penalty": 1.0 - noise,
        "volume": volp,
    }

    # Weighted sum
    raw = (
        WEIGHTS["ema_gap_pct"] * components["ema_gap"] +
        WEIGHTS["slope_20_pct"] * components["slope20"] +
        WEIGHTS["slope_50_pct"] * components["slope50"] +
        WEIGHTS["adx14"]       * components["adx"] +
        WEIGHTS["macd_hist_norm"] * components["macd"] +
        WEIGHTS["rsi14"]       * components["rsi"] +
        WEIGHTS["atr14_pct"]   * components["noise_penalty"] +
        WEIGHTS["vol_rank_20"] * components["volume"]
    )

    # Map to 0..100
    momentum_score = _clamp(raw, 0.0, 1.0) * 100.0

    # Confidence: how “coherent” the components are (low dispersion => higher confidence)
    vals = list(components.values())
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    coherence = 1.0 / (1.0 + 5.0 * var)  # heuristic
    confidence = _clamp(coherence * 100.0, 0.0, 100.0)

    return {"score": round(momentum_score, 1), "confidence": round(confidence, 1), "components": components}
