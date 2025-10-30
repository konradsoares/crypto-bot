import ccxt
import pandas as pd

def _get_exchange(name: str, testnet=True):
    name = (name or "binance").lower()
    if name == "binance":
        ex = ccxt.binance({"enableRateLimit": True})
        if testnet:
            ex.set_sandbox_mode(True)
        return ex
    elif name in ("coinbase", "coinbaseadvanced"):
        # ccxt 'coinbase' implements Advanced Trade
        ex = ccxt.coinbase({"enableRateLimit": True})
        # Coinbase sandbox via ccxt is limited; no simple toggle like Binance.
        return ex
    else:
        raise ValueError(f"Unsupported exchange: {name}")

def load_ohlcv(symbol, timeframe="5m", limit=300, exchange="binance", testnet=True):
    ex = _get_exchange(exchange, testnet=testnet)
    ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df
