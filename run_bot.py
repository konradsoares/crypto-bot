import os
import argparse
import yaml
import logging

from adapters.data_ccxt import load_ohlcv
from adapters.broker_binance import BinanceBroker
from strategies.momentum import signal
from strategies.momentum_ai import ai_momentum_gate
from strategies.patterns import bullish_pattern_hit
from strategies.risk import position_size

from utils import storage
from utils.pnl import next_trailing_sl
from utils.telegram import notify


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=os.getenv("SYMBOLS", "BTC/USDT").split(","))
    ap.add_argument("--tf", default=os.getenv("TIMEFRAME", "5m"))  # fallback; config wins
    ap.add_argument("--budget", type=float, default=float(os.getenv("BUDGET_USDT", "1000")))
    ap.add_argument("--config", default="config.example.yaml")
    ap.add_argument("--trail", type=float, default=float(os.getenv("TRAIL_PCT", "0.0")))  # 0.01 = 1%
    return ap.parse_args()


def load_cfg(path):
    # Robust UTF-8 loader for Windows (handles UTF-8 and UTF-8 with BOM)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except UnicodeDecodeError:
        # Retry with BOM-tolerant codec
        with open(path, "r", encoding="utf-8-sig") as f:
            return yaml.safe_load(f)


def daily_risk_gate(state, cfg, day):
    """Blocks NEW ENTRIES when daily max loss reached or daily profit target hit. Exits always allowed."""
    max_loss = float(cfg["risk"].get("max_daily_loss_usdt", 0) or 0.0)
    target = float(cfg["risk"].get("target_daily_profit_usdt", 0) or 0.0)
    pnl_today = float(state["day_pnl_usdt"].get(day, 0.0))

    if max_loss > 0 and pnl_today <= -abs(max_loss):
        return False, f"Max daily loss hit ({pnl_today:.2f} USDT ≤ -{max_loss})"
    if target > 0 and pnl_today >= target:
        return False, f"Target daily profit hit ({pnl_today:.2f} USDT ≥ {target})"
    return True, ""


def main():
    args = parse_args()
    cfg = load_cfg(args.config)

    # Verbosity / heartbeat
    verbose = str(os.getenv("VERBOSE", "0")).lower() in ("1", "true", "yes", "on")
    heartbeat = str(os.getenv("HEARTBEAT", "0")).lower() in ("1", "true", "yes", "on")
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")

    dry = str(os.getenv("DRY_RUN", "true")).lower() == "true"
    broker = BinanceBroker(
        os.getenv("BINANCE_API_KEY", ""),
        os.getenv("BINANCE_API_SECRET", ""),
        testnet=True,
        dry_run=dry,
    )

    state = storage.read_state()
    day = storage.day_key()
    if state.get("last_trade_day") != day:
        state["loss_streak"] = 0
        state["last_trade_day"] = day

    # ----- DAILY GATE (blocks NEW ENTRIES only; exits always allowed) -----
    allow_new_entries, reason = daily_risk_gate(state, cfg, day)
    if not allow_new_entries:
        notify(f"⏸️ New entries blocked: {reason}")
        logging.info(f"Daily gate active: {reason}")

    # Resolve timeframe once (config runtime wins; CLI --tf is fallback)
    timeframe = cfg.get("runtime", {}).get("timeframe", args.tf)
    exchange = cfg.get("runtime", {}).get("exchange", "binance")

    # Prepare sanitized kwargs for momentum.signal()
    sig_params = {}
    for k in ("lookback_short", "lookback_long", "atr_len", "breakout_len"):
        if "signals" in cfg and k in cfg["signals"]:
            sig_params[k] = cfg["signals"][k]

    # Symbol iteration
    symbols = args.symbols if isinstance(args.symbols, list) else [s.strip() for s in str(args.symbols).split(",")]

    buys = 0
    sells = 0

    for sym in [s.strip() for s in symbols]:
        # -------- DATA --------
        df = load_ohlcv(sym, timeframe, limit=300, exchange=exchange, testnet=True)
        if df is None or len(df) == 0:
            logging.info(f"{sym}: no data")
            continue

        # -------- TA DIRECTION + AI QUALITY --------
        sig = signal(df, **sig_params)          # TA: gives buy/sell, sl/tp, price
        ai = ai_momentum_gate(df)               # AI: grades momentum quality
        price = float(sig["price"])

        pos = state["positions"].get(sym, {"qty": 0.0, "avg": 0.0, "sl": 0.0, "tp": 0.0, "trail_pct": 0.0})

        logging.info(
            f"{sym} @ {price:.2f} | TA buy={sig['buy']} sell={sig['sell']} | "
            f"AI={ai['ai_score']:.1f}/{ai['ai_conf']:.0f}% pass={ai['passed']} | "
            f"pos_qty={pos['qty']:.6f} sl={pos['sl']:.2f} tp={pos['tp']:.2f}"
        )

        # -------- EXIT MANAGEMENT (always evaluated; we only sell if we own) --------
        if pos["qty"] > 0:
            # Optional trailing stop ratchet
            new_sl = next_trailing_sl(pos, price)
            if new_sl > pos["sl"]:
                pos["sl"] = new_sl
                logging.info(f"{sym}: trail ratchet → SL {pos['sl']:.2f}")

            # Take Profit
            if price >= pos["tp"]:
                qty = max(0.0, float(pos["qty"]))
                if qty > 0:
                    pnl_frac = (price - pos["avg"]) / pos["avg"]
                    pnl_usdt = qty * (price - pos["avg"])
                    broker.market_sell(sym, qty)

                    # Update ledgers
                    state["realized_pnl_frac"] += pnl_frac
                    state["day_pnl_frac"][day] = state["day_pnl_frac"].get(day, 0.0) + pnl_frac
                    state["realized_pnl_usdt"] += pnl_usdt
                    state["day_pnl_usdt"][day] = state["day_pnl_usdt"].get(day, 0.0) + pnl_usdt

                    storage.append_trade(storage.now_iso(), "SELL", sym, qty, price, pnl_frac, pnl_usdt, "TP")
                    notify(f"🎯 TP SELL {sym} qty={qty:.6f} @ {price:.2f} | +{pnl_usdt:.2f} USDT | paper={str(dry).lower()}")
                    logging.info(f"{sym}: TP SELL qty={qty:.6f} @ {price:.2f}")
                    sells += 1

                # Flat position
                state["positions"][sym] = {"qty": 0.0, "avg": 0.0, "sl": 0.0, "tp": 0.0, "trail_pct": 0.0}
                state["loss_streak"] = 0

            # Stop Loss
            elif price <= pos["sl"]:
                qty = max(0.0, float(pos["qty"]))
                if qty > 0:
                    pnl_frac = (price - pos["avg"]) / pos["avg"]
                    pnl_usdt = qty * (price - pos["avg"])
                    broker.market_sell(sym, qty)

                    state["realized_pnl_frac"] += pnl_frac
                    state["day_pnl_frac"][day] = state["day_pnl_frac"].get(day, 0.0) + pnl_frac
                    state["realized_pnl_usdt"] += pnl_usdt
                    state["day_pnl_usdt"][day] = state["day_pnl_usdt"].get(day, 0.0) + pnl_usdt

                    storage.append_trade(storage.now_iso(), "SELL", sym, qty, price, pnl_frac, pnl_usdt, "SL")
                    notify(f"🛑 SL SELL {sym} qty={qty:.6f} @ {price:.2f} | {pnl_usdt:.2f} USDT | paper={str(dry).lower()}")
                    logging.info(f"{sym}: SL SELL qty={qty:.6f} @ {price:.2f}")
                    sells += 1

                    # Count a loss toward the streak if negative
                    if pnl_usdt < 0:
                        state["loss_streak"] = state.get("loss_streak", 0) + 1
                    else:
                        state["loss_streak"] = 0

                state["positions"][sym] = {"qty": 0.0, "avg": 0.0, "sl": 0.0, "tp": 0.0, "trail_pct": 0.0}

            # Else: HOLD (waiting for TP or SL)

        # -------- ENTRY (only if daily gate allows; buy only with TA+AI and optional pattern) --------
        if allow_new_entries and pos["qty"] <= 0 and sig["buy"] and ai["passed"]:
            # Optional bullish candlestick confirmation
            if cfg.get("signals", {}).get("require_bullish_pattern", True):
                ok, pat = bullish_pattern_hit(df, tuple(cfg["signals"].get("allowed_patterns", [])))
                if not ok:
                    logging.info(f"{sym}: skipped — no bullish candlestick")
                    continue  # no bullish confirmation → skip

            qty = position_size(args.budget, price, cfg["risk"]["risk_pct"], sig["sl"])
            if qty > 0:
                broker.market_buy(sym, qty)
                state["positions"][sym] = {
                    "qty": qty,
                    "avg": price,
                    "sl": float(sig["sl"]),
                    "tp": float(sig["tp"]),
                    "trail_pct": float(args.trail) if args.trail > 0 else 0.0,
                    "opened_ts": storage.now_iso(),
                }

                note = f"AI {ai['ai_score']:.1f}/{ai['ai_conf']:.0f}%"
                storage.append_trade(storage.now_iso(), "BUY", sym, qty, price, None, None, note)
                notify(
                    f"✅ BUY {sym} qty={qty:.6f} @ {price:.2f} | "
                    f"AI {ai['ai_score']:.1f}/{ai['ai_conf']:.0f}% "
                    f"{'(LLM)' if ai['use_llm'] else '(ML)'} | paper={str(dry).lower()}"
                )
                logging.info(f"{sym}: BUY qty={qty:.6f} @ {price:.2f}")
                buys += 1

    # ----- Equity snapshot (realized PnL only; simple, conservative) -----
    deposits = storage.total_deposits(state)
    equity_proxy = deposits + state.get("realized_pnl_usdt", 0.0)
    storage.append_equity(storage.now_iso(), equity_proxy, deposits, state.get("realized_pnl_frac", 0.0), "auto")
    storage.write_state(state)

    # Heartbeat / summary
    pnl_today = float(state["day_pnl_usdt"].get(day, 0.0))
    summary = f"Processed {len(symbols)} symbols | buys={buys} sells={sells} | day_pnl_usdt={pnl_today:.2f} | equity={equity_proxy:.2f}"
    logging.info(summary)
    if heartbeat:
        notify(f"🤖 heartbeat: {summary}")


if __name__ == "__main__":
    main()
