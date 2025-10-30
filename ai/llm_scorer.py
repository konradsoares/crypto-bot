import os, json
from typing import Dict

# If you want Perplexity instead, swap the call accordingly. Kept generic here.
# This grader converts engineered features into a 0..100 momentum score with a rationale.

def _call_openai(prompt: str) -> str:
    # Minimal HTTP call using requests to avoid SDK lock-in
    import requests
    api_key = os.getenv("OPENAI_API_KEY","")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    # Adjust model if you prefer a smaller/cheaper one
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role":"system","content":"You grade crypto momentum quality from features. No price prediction."},
            {"role":"user","content": prompt}
        ],
        "temperature": 0.0
    }
    r = requests.post(url, headers=headers, json=data, timeout=20)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def grade(features: Dict) -> Dict:
    schema = (
        "Return strict JSON: {"
        "\"score\": number (0-100), "
        "\"confidence\": number (0-100), "
        "\"rationale\": string (<=200 chars)"
        "}"
    )
    prompt = (
        "Given these features of the current market state, rate momentum QUALITY (trend strength/cleanliness) "
        "without predicting price:\n"
        f"{json.dumps(features, sort_keys=True)}\n\n"
        "Scoring rules:\n"
        "- Higher when EMAs are positively separated, slopes aligned, ADX >= 20, RSI 50-70, MACD hist > 0.\n"
        "- Penalize when ATR% is high (noisy), RSI extreme (>80 or <30), or volume is weak (<30th pct).\n"
        "- Score 0..100; provide a confidence 0..100 based on internal consistency; return JSON only.\n\n"
        + schema
    )
    raw = _call_openai(prompt).strip()
    try:
        obj = json.loads(raw)
        return {"score": float(obj["score"]), "confidence": float(obj["confidence"]), "rationale": obj.get("rationale","")}
    except Exception:
        # Fail safe: if parsing fails, fall back to deterministic scorer at the call site.
        raise
