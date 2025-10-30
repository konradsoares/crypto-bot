def position_size(equity_usdt: float, price: float, risk_pct=0.005, sl_price=None):
    if not price or price <= 0:
        return 0.0
    if not sl_price or sl_price >= price:
        # fallback: 1% move proxy
        per_unit_risk = price * 0.01
    else:
        per_unit_risk = price - sl_price
    qty = (equity_usdt * risk_pct) / max(per_unit_risk, 1e-8)
    return max(qty, 0.0)
