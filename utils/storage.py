import json, csv, time
from pathlib import Path

BASE_DIR = Path(".")
STATE = BASE_DIR / "state.json"
LOGS_DIR = BASE_DIR / "logs"
TRADES_CSV = LOGS_DIR / "trades.csv"
EQUITY_CSV = LOGS_DIR / "equity.csv"

LOGS_DIR.mkdir(exist_ok=True, parents=True)

INITIAL_STATE = {
    "base_ccy": "USDT",
    "deposits": [],           # [{"ts","amount","note"}]
    "withdrawals": [],        # [{"ts","amount","note"}]
    "positions": {},          # symbol -> {"qty","avg","sl","tp","trail_pct","opened_ts"}
    "realized_pnl_frac": 0.0, # legacy %
    "realized_pnl_usdt": 0.0, # absolute USDT
    "day_pnl_frac": {},       # YYYY-MM-DD -> %
    "day_pnl_usdt": {},       # YYYY-MM-DD -> USDT
    "loss_streak": 0,
    "last_trade_day": None
}

def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def day_key():
    return time.strftime("%Y-%m-%d", time.gmtime())

def _initial_state():
    # fresh copy so callers don’t mutate the template
    return json.loads(json.dumps(INITIAL_STATE))

def read_state():
    if STATE.exists():
        with open(STATE, "r") as f:
            return json.load(f)
    return _initial_state()

def write_state(s):
    with open(STATE, "w") as f:
        json.dump(s, f, indent=2)

def append_trade(ts, side, symbol, qty, price, pnl_frac=None, pnl_usdt=None, note=""):
    header = ["ts","side","symbol","qty","price","pnl_frac","pnl_usdt","note"]
    exists = TRADES_CSV.exists()
    with open(TRADES_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if not exists: w.writerow(header)
        w.writerow([
            ts, side, symbol,
            f"{qty:.10f}", f"{price:.8f}",
            "" if pnl_frac is None else f"{pnl_frac:.8f}",
            "" if pnl_usdt is None else f"{pnl_usdt:.2f}",
            note
        ])

def append_equity(ts, equity_usdt, deposits_usdt, realized_pnl_frac, note=""):
    header = ["ts","equity_usdt","deposits_usdt","realized_pnl_frac","note"]
    exists = EQUITY_CSV.exists()
    with open(EQUITY_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if not exists: w.writerow(header)
        w.writerow([ts, f"{equity_usdt:.2f}", f"{deposits_usdt:.2f}", f"{realized_pnl_frac:.6f}", note])

def total_deposits(state):
    return sum(d["amount"] for d in state.get("deposits", [])) - sum(w["amount"] for w in state.get("withdrawals", []))

def record_deposit(amount, note=""):
    s = read_state()
    s["deposits"].append({"ts": now_iso(), "amount": float(amount), "note": note})
    write_state(s)

def record_withdraw(amount, note=""):
    s = read_state()
    s["withdrawals"].append({"ts": now_iso(), "amount": float(amount), "note": note})
    write_state(s)
