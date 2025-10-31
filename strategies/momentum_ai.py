# strategies/momentum_ai.py
import os, requests, re

from ai.feature_engineering import build_features  # returns dict of numeric features

def _ml_score(feats):
    # Simple deterministic scorer so we always have a number even without LLM
    w = {
        "ema_gap_pct":  35.0,
        "slope_20_pct": 25.0,
        "adx14":        15.0,
        "rsi14":         5.0,
        "vol_rank_20":  10.0,
        "atr14_pct":    10.0,
    }
    s  = 0.0
    s += w["ema_gap_pct"]  * max(-1.0, min(1.0, feats.get("ema_gap_pct", 0.0)/1.5))
    s += w["slope_20_pct"] * max(-1.0, min(1.0, feats.get("slope_20_pct", 0.0)/1.0))
    s += w["adx14"]        * (max(0.0, min(50.0, feats.get("adx14", 0.0)))/50.0)
    rsi = feats.get("rsi14", 50.0)
    s += w["rsi14"] * (1.0 - abs(50.0 - rsi)/50.0)
    s += w["vol_rank_20"] * (max(0.0, min(100.0, feats.get("vol_rank_20", 50.0)))/100.0)
    s += w["atr14_pct"] * (1.0 - max(0.0, min(2.0, feats.get("atr14_pct", 0.5)))/2.0)
    return max(0.0, min(100.0, s))

def _normalize_openai_url():
    """
    Accepts:
      - OPENAI_BASE_URL unset  -> use official endpoint
      - https://api.openai.com -> append /v1/chat/completions
      - https://api.openai.com/v1 -> append /chat/completions
      - full /v1/chat/completions -> use as-is
      - Azure/OpenRouter-compatible base URLs -> append /chat/completions if they end with /v1
    """
    base = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
    if not base:
        return "https://api.openai.com/v1/chat/completions"
    # if they supplied the full path already
    if base.endswith("/v1/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if base.endswith("/chat/completions"):
        return base  # some gateways don’t include /v1
    # bare domain → assume OpenAI style
    if base == "https://api.openai.com":
        return base + "/v1/chat/completions"
    # best effort: assume base wants /v1/chat/completions
    return base + "/v1/chat/completions"

def _openai_call(prompt):
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return None, "no_key"

    url = _normalize_openai_url()
    if not url.startswith("http"):
        return None, "bad_url"

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [
                    {"role":"system","content":"You score crypto long entries 0..100 and explain briefly."},
                    {"role":"user","content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 200
            },
            timeout=25
        )
        if r.status_code >= 400:
            return None, f"http_{r.status_code}"
        data = r.json()
        txt = data.get("choices",[{}])[0].get("message",{}).get("content","").strip()
        m = re.search(r'(\d{1,3})', txt)
        score = float(m.group(1)) if m else None
        if score is not None:
            score = max(0.0, min(100.0, score))
        return ({"score": score, "rationale": txt}, "ok") if score is not None else (None, "parse_err")
    except requests.exceptions.Timeout:
        return None, "timeout"
    except Exception:
        return None, "error"

def ai_momentum_gate(df):
    """
    Returns:
      {
        "ai_score": float(0..100),
        "ai_conf": float(0..100),
        "passed": bool,
        "use_llm": bool,         # TRUE only if an LLM call actually succeeded
        "rationale": str,        # short reason from LLM (when available)
        "llm_status": str        # 'ok','skipped','no_key','bad_url','http_XXX','timeout','error','parse_err'
      }
    Env:
      USE_OPENAI=1          -> allow LLM usage
      AI_FORCE_LLM=1        -> force LLM call every cycle (for testing)
      AI_SCORE_PASS=65
      AI_CONF_PASS=60
    """
    feats = build_features(df)
    ml = _ml_score(feats)
    conf = 60.0 + 0.4*abs(ml-50.0)

    allow_llm = str(os.getenv("USE_OPENAI","0")).lower() in ("1","true","yes","on")
    force_llm = str(os.getenv("AI_FORCE_LLM","0")).lower() in ("1","true","yes","on")

    used_llm = False
    rationale = ""
    llm_status = "skipped"

    # Only attempt LLM if allowed and either forced, or ML is in a gray zone
    if allow_llm and (force_llm or 45.0 < ml < 75.0):
        core = {k: round(float(feats.get(k,0.0)), 4) for k in ("ema_gap_pct","slope_20_pct","adx14","rsi14","atr14_pct","vol_rank_20")}
        llm, llm_status = _openai_call(
            f"Features={core}. Score a long entry 0..100 and explain in one sentence. Reply like '72 Reason: ...'."
        )
        if llm and llm.get("score") is not None:
            ml = float(llm["score"])
            rationale = llm.get("rationale","")
            used_llm = True
            conf = 70.0 + 0.3*abs(ml-50.0)

    pass_cut = float(os.getenv("AI_SCORE_PASS", "65"))
    conf_cut = float(os.getenv("AI_CONF_PASS", "60"))
    passed = (ml >= pass_cut) and (conf >= conf_cut)

    return {
        "ai_score": round(ml,1),
        "ai_conf": round(conf,0),
        "passed": passed,
        "use_llm": used_llm,       # TRUE only on successful call
        "rationale": rationale,
        "llm_status": llm_status,
    }
