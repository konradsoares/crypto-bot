import argparse, numpy as np
from adapters.data_ccxt import load_ohlcv
from strategies.momentum import signal, compute_indicators

def run_bt(symbol="BTC/USDT", timeframe="5m", exchange="binance", limit=2000):
    df = load_ohlcv(symbol, timeframe, limit=limit, exchange=exchange, testnet=True)
    # simple walk-forward: generate signals per bar, naive flat/long only
    short,long,atr,bo_up,bo_dn = compute_indicators(df)
    pos = 0
    entry = 0
    rets = []
    for i in range(60, len(df)):  # warmup
        sub = df.iloc[:i].copy()
        sig = signal(sub)
        price = sub["close"].iloc[-1]
        if sig["buy"] and pos == 0:
            pos = 1
            entry = price
        elif sig["sell"] and pos == 1:
            r = (price - entry) / entry
            rets.append(r)
            pos, entry = 0, 0
    if pos == 1:  # close last
        r = (df["close"].iloc[-1] - entry) / entry
        rets.append(r)
    if not rets:
        return {"trades": 0, "avg": 0.0, "sum": 0.0, "winrate": 0.0}
    arr = np.array(rets)
    return {
        "trades": len(arr),
        "avg": float(arr.mean()),
        "sum": float(arr.sum()),
        "winrate": float((arr > 0).mean()),
    }

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--limit", type=int, default=2000)
    args = ap.parse_args()
    res = run_bt(args.symbol, args.tf, limit=args.limit)
    print(res)
