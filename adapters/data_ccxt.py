import os
import time
import requests
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
        return ccxt.coinbase({"enableRateLimit": True})
    else:
        raise ValueError(f"Unsupported exchange: {name}")


def _tf_to_cc_minutes(tf: str):
    tf = (tf or "5m").lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 60 * 24
    return 5


def _load_ohlcv_cryptocompare(symbol: str, timeframe: str = "5m", limit: int = 300):
    """
    Use CryptoCompare histo* endpoints.
    Requires CRYPTOCOMPARE_API_KEY in env.
    Minute/Hour/Day are chosen based on timeframe; we use 'aggregate' for 5m, 15m, etc.
    """
    api_key = os.getenv("CRYPTOCOMPARE_API_KEY", "")
    if not api_key:
        raise RuntimeError("CRYPTOCOMPARE_API_KEY not set; cannot fetch market data in cryptocompare mode.")

    base, quote = symbol.split("/")
    mins = _tf_to_cc_minutes(timeframe)

    if mins < 60:
        url = "https://min-api.cryptocompare.com/data/v2/histominute"
        aggregate = max(1, mins)
    elif mins % 60 == 0 and mins < 24 * 60:
        url = "https://min-api.cryptocompare.com/data/v2/histohour"
        aggregate = max(1, mins // 60)
    else:
        url = "https://min-api.cryptocompare.com/data/v2/histoday"
        aggregate = max(1, mins // (24 * 60))

    # CryptoCompare throws if toTs is invalid. Either omit it or pass an int.
    params = {
        "fsym": base,
        "tsym": quote,
        "limit": int(limit),
        "aggregate": int(aggregate),
        # "toTs": int(time.time())  # optional; omit for latest
    }

    headers = {"authorization": f"Apikey {api_key}"}
    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("Response") != "Success":
        raise RuntimeError(f"CryptoCompare error: {data.get('Message')}")

    rows = data["Data"]["Data"]  # fields: time, open, high, low, close, volumefrom, volumeto
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.rename(columns={"volumeto": "volume"})
    df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df[["ts", "open", "high", "low", "close", "volume"]]
    return df


def load_ohlcv(symbol, timeframe="5m", limit=300, exchange="binance", testnet=True):
    """
    Market data loader with two modes:
    - MARKET_DATA_PROVIDER=cryptocompare -> always use CryptoCompare
    - otherwise try CCXT (exchange); on failure, fall back to CryptoCompare
    """
    provider = os.getenv("MARKET_DATA_PROVIDER", "").lower()

    if provider == "cryptocompare":
        return _load_ohlcv_cryptocompare(symbol, timeframe, limit)

    # Try CCXT first
    try:
        ex = _get_exchange(exchange, testnet=testnet)
        ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df
    except Exception as e:
        # Fallback to CryptoCompare (e.g., Binance testnet geo-blocked on CI)
        try:
            return _load_ohlcv_cryptocompare(symbol, timeframe, limit)
        except Exception as ee:
            raise RuntimeError(f"Failed CCXT fetch ({e}); and CryptoCompare fallback failed ({ee})")
