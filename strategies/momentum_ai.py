# strategies/momentum_ai.py
import os, math, requests
from ai.feature_engineering import build_features  # must return a dict of numeric features

OPENAI_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def _ml_score(feats):
    # Tiny deterministic scorer so you always get a number even without OpenAI
    # Tweak weights if you like.
    w = {
        "ema_gap_pct":  35.0,   # momentum bias
        "slope_20_pct": 25.0,   # short slope
        "adx14":        15.0,   # trend strength
        "rsi14":         5.0,   # midrange rsi is fine
        "vol_rank_20":  10.0,   # volume participation
        "atr14_pct":    10.0,   # volatility (tempered)
    }
    # normalize inputs
    s  = 0.0
    s += w["ema_gap_pct"]  * max(-1.0, min(1.0, feats.get("ema_gap_pct", 0.0)/1.5))
    s += w["slope_20_pct"] * max(-1.0, min(1.0, feats.get("slope_20_pct", 0.0)/1.0))
    s += w["adx14"]        * (max(0.0, min(50.0, feats.get("adx14", 0.0)))/50.0)
    rsi = feats.get("rsi14", 50.0)
    s += w["rsi14"] * (1.0 - abs(50.0 - rsi)/50.0)     # reward mid RSI
    s += w["vol_rank_20"] * (max(0.0, min(100.0, feats.get("vol_rank_20", 50.0)))/100.0)
    s += w["atr14_pct"] * (1.0 - max(0.0, min(2.0, feats.get("atr14_pct", 0.5)))/2.0)
    # clamp 0..100
    return max(0.0, min(100.0, s))

def _openai_call(prompt):
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role":"system","content":"You score crypto long entries 0..100 and explain briefly."},
                    {"role":"user","content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 200
            },
            timeout=20
        )
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"].strip()
        # Extract leading score like: "Score: 72\nReason: ..."
        import re
        m = re.search(r'(\d{1,3})', txt)
        score = float(m.group(1)) if m else None
        score = max(0.0, min(100.0, score)) if score is not None else None
        return {"score": score, "rationale": txt}
    except Exception:
        return None

def ai_momentum_gate(df):
    """
    Returns:
      {
        "ai_score": float(0..100),
        "ai_conf": float(0..100),
        "passed": bool,
        "use_llm": bool,
        "rationale": str
      }
    Env:
      USE_OPENAI=1 to enable LLM
      AI_FORCE_LLM=1 to force LLM even if ML is confident
      AI_SCORE_PASS=number (default 65)
      AI_CONF_PASS=number (default 60)
    """
    feats = build_features(df)  # last-row features
    ml = _ml_score(feats)
    conf = 60.0 + 0.4*abs(ml-50.0)  # crude confidence: farther from 50 -> higher

    use_llm = str(os.getenv("USE_OPENAI","0")).lower() in ("1","true","yes","on")
    force_llm = str(os.getenv("AI_FORCE_LLM","0")).lower() in ("1","true","yes","on")

    rationale = ""
    if use_llm and (force_llm or 45.0 < ml < 75.0):
        # Build compact prompt with the core features
        core = {k: round(float(feats.get(k,0.0)),4) for k in ("ema_gap_pct","slope_20_pct","adx14","rsi14","atr14_pct","vol_rank_20")}
        llm = _openai_call(
            f"Features={core}. Score a long entry 0..100 and explain in one sentence. Reply like '72 Reason: ...'."
        )
        if llm and llm.get("score") is not None:
            ml = float(llm["score"])
            rationale = llm.get("rationale","")
            use_llm = True
            conf = 70.0 + 0.3*abs(ml-50.0)

    pass_cut = float(os.getenv("AI_SCORE_PASS", "65"))
    conf_cut = float(os.getenv("AI_CONF_PASS", "60"))
    passed = (ml >= pass_cut) and (conf >= conf_cut)

    return {
        "ai_score": round(ml,1),
        "ai_conf": round(conf,0),
        "passed": passed,
        "use_llm": use_llm,
        "rationale": rationale
    }
