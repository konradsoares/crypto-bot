from typing import Dict

def unrealized_pnl_frac(position: Dict, last_price: float) -> float:
    """
    Fractional PnL of an open long: (P - avg) / avg
    """
    qty = float(position.get("qty", 0.0))
    if qty <= 0 or last_price <= 0:
        return 0.0
    avg = float(position.get("avg", 0.0))
    return (last_price - avg) / (avg if avg > 0 else last_price)

def next_trailing_sl(position: Dict, last_price: float) -> float:
    """
    If trailing is enabled, ratchet SL up when price makes a new high by trail_pct.
    We store SL directly in the position dict upstream; this returns the *suggested* SL.
    """
    trail = position.get("trail_pct")
    if not trail or trail <= 0:
        return float(position.get("sl", 0.0))
    # Move SL up to (1 - trail_pct) * last_price if that’s higher than current SL
    candidate = last_price * (1.0 - trail)
    return max(candidate, float(position.get("sl", 0.0)))
