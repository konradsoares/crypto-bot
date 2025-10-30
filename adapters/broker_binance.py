import ccxt
from typing import Dict, Any

class BinanceBroker:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True, dry_run: bool = True):
        self.ex = ccxt.binance({
            "apiKey": api_key or "",
            "secret": api_secret or "",
            "enableRateLimit": True
        })
        if testnet:
            self.ex.set_sandbox_mode(True)
        self.dry = bool(dry_run)

    def market_buy(self, symbol: str, qty: float) -> Dict[str, Any]:
        if self.dry:
            return {"id":"paper", "side":"buy", "symbol":symbol, "qty":qty}
        return self.ex.create_order(symbol, "market", "buy", qty)

    def market_sell(self, symbol: str, qty: float) -> Dict[str, Any]:
        if self.dry:
            return {"id":"paper", "side":"sell", "symbol":symbol, "qty":qty}
        return self.ex.create_order(symbol, "market", "sell", qty)

    def fetch_balance(self):
        try:
            return self.ex.fetch_balance() if not self.dry else {"free": {}}
        except Exception:
            return {"free": {}}
