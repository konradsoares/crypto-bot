import os
from ai.feature_engineering import build_features
from ai.ml_scorer import score as ml_score
try:
    from ai.llm_scorer import grade as llm_grade
except Exception:
    llm_grade = None

def ai_momentum_gate(df):
    """
    Returns dict:
      {
        "ai_score": float(0..100),
        "ai_conf": float(0..100),
        "use_llm": bool,
        "rationale": str
      }
    """
    feats = build_features(df)
    provider = os.getenv("AI_SCORER_PROVIDER", "none").lower()
    threshold = float(os.getenv("AI_SCORE_THRESHOLD", "70"))
    conf_thr  = float(os.getenv("AI_CONF_THRESHOLD", "60"))

    use_llm = False
    rationale = ""
    try:
        if provider == "openai" and llm_grade is not None:
            use_llm = True
            g = llm_grade(feats)
            ai_score = float(g["score"])
            ai_conf  = float(g["confidence"])
            rationale = g.get("rationale","")
        else:
            s = ml_score(feats)
            ai_score = float(s["score"])
            ai_conf  = float(s["confidence"])
    except Exception:
        # Fallback to deterministic scorer on any AI/API error
        s = ml_score(feats)
        ai_score = float(s["score"])
        ai_conf  = float(s["confidence"])
        use_llm = False

    return {
        "ai_score": ai_score,
        "ai_conf": ai_conf,
        "passed": (ai_score >= threshold) and (ai_conf >= conf_thr),
        "use_llm": use_llm,
        "rationale": rationale
    }
