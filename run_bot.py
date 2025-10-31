"""
run_bot.py
- Hybrid entry logic:
    TA (strategies.momentum.signal) decides direction/levels,
    AI gate (strategies.momentum_ai.ai_momentum_gate) validates momentum quality,
    optional bullish candlestick confirmation (strategies.patterns).
- Daily risk gates block NEW entries after loss/target; exits always allowed.
- Verbose logs + CSV ledgers (trades, equity, ai_decisions) for audit.
- Env toggles:
    DRY_RUN=true|false
    VERBOSE=1 (logs per-symbol lines)
    HEARTBEAT=1 (Telegram heartbeat)
    AI_DEBUG=1 (feature peek + rationale snippet in ai_decisions.csv)
    ALLOW_AI_ONLY=1 (let AI gate open entries even if TA buy=False; for testing)
"""

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
from ai.feature_engineering import build_features


# ------------------------------
# CLI parsing (CLI is fallback; config wins where both exist)
# ------------------------------
def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=os.getenv("SYMBOLS", "BTC/USDT").split(","))
    ap.add_argument("--tf", default=os.getenv("TIMEFRAME", "5m"))  # fallback; config wins
    ap.add_argument("--budget", type=float, default=float(os.getenv("BUDGET_USDT", "1000")))
    ap.add_argument("--config", default="config.example.yaml")
    ap.add_argument("--trail", type=float, default=float(os.getenv("TRAIL_PCT", "0.0")))  # 0.01 = 1%
    return ap.parse_args()


# ------------------------------
# YAML loader (robust on Windows encodings)
# ------------------------------
def load_cfg(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-8-sig") as f:
            return yaml.safe_load(f)


# ------------------------------
# Daily gate: block NEW entries if max loss hit or profit target reached
# ------------------------------
def daily_risk_gate(state, cfg, day):
    max_loss = float(cfg["risk"].get("max_daily_loss_usdt", 0) or 0.0)
    target = float(cfg["risk"].get("target_daily_profit_usdt", 0) or 0.0)
    pnl_today = float(state["day_pnl_usdt"].get(day, 0.0))
    if max_loss > 0 and pnl_today <= -abs(max_loss):
        return False, f"Max daily loss hit ({pnl_today:.2f} USDT ≤ -{max_loss})"
    if target > 0 and pnl_today >= target:
        return False, f"Target daily profit hit ({pnl_today:.2f} USDT ≥ {target})"
    return True, ""


# ------------------------------
# Main bot loop (single-shot run; schedule via cron/CI)
# ------------------------------
def main():
    args = parse_args()
    cfg = load_cfg(args.config)

    # Verbosity / heartbeat toggles
    verbose = str(os.getenv("VERBOSE", "0")).lower() in ("1", "true", "yes", "on")
    heartbeat = str(os.getenv("HEARTBEAT", "0")).lower() in ("1", "true", "yes", "on")
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")

    # Paper/live mode and broker init (Binance Spot testnet when testnet=True)
    dry = str(os.getenv("DRY_RUN", "true")).lower() == "true"
    broker = BinanceBroker(
        os.getenv("BINANCE_API_KEY", ""),
        os.getenv("BINANCE_API_SECRET", ""),
        testnet=True,
        dry_run=dry,
    )

    # Load state; reset loss streak per day
    state = storage.read_state()
    day = storage.day_key()
    if state.get("last_trade_day") != day:
        state["loss_streak"] = 0
        state["last_trade_day"] = day

    # Daily new-entry gate (exits are still allowed)
    allow_new_entries, reason = daily_risk_gate(state, cfg, day)
    if not allow_new_entries:
        notify(f"⏸️ New entries blocked: {reason}")
        logging.info(f"Daily gate active: {reason}")

    # Resolve timeframe/exchange once. Config runtime wins; CLI is fallback.
    timeframe = cfg.get("runtime", {}).get("timeframe", args.tf)
    exchange = cfg.get("runtime", {}).get("exchange", "binance")

    # Sanitize kwargs for TA signal() (don’t leak unknown keys)
    sig_params = {}
    for k in ("lookback_short", "lookback_long", "atr_len", "breakout_len"):
        if "signals" in cfg and k in cfg["signals"]:
            sig_params[k] = cfg["signals"][k]

    # Option to allow AI-only entries (useful for testing end-to-end)
    allow_ai_only = str(os.getenv("ALLOW_AI_ONLY", "0")).lower() in ("1", "true", "yes", "on")

    # Iterate symbols
    symbols = args.symbols if isinstance(args.symbols, list) else [s.strip() for s in str(args.symbols).split(",")]
    buys = 0
    sells = 0

    for sym in [s.strip() for s in symbols]:
        # -------- DATA FETCH --------
        df = load_ohlcv(sym, timeframe, limit=300, exchange=exchange, testnet=True)
        if df is None or len(df) == 0:
            logging.info(f"{sym}: no data")
            continue

        # -------- SIGNALS: TA + AI --------
        # TA gives directional bias + levels (sl/tp/price) but not size
        sig = signal(df, **sig_params)
        price = float(sig["price"])

        # AI gate: ML baseline; optionally calls OpenAI when enabled (see strategies/momentum_ai.py)
        ai = ai_momentum_gate(df)

        # Current position snapshot (if any)
        pos = state["positions"].get(sym, {"qty": 0.0, "avg": 0.0, "sl": 0.0, "tp": 0.0, "trail_pct": 0.0})

        # -------- VISIBILITY: features + candlestick pattern --------
        ai_debug = str(os.getenv("AI_DEBUG", "0")).lower() in ("1", "true", "yes", "on")
        feat_note = ""
        if ai_debug:
            feats = build_features(df)
            core = {k: round(float(feats.get(k, 0.0)), 4)
                    for k in ("ema_gap_pct", "slope_20_pct", "adx14", "rsi14", "atr14_pct", "vol_rank_20")
                    if k in feats}
            feat_note = f"feats={core}"

        # Evaluate candlestick pattern every cycle (name or 'none')
        ok_pat, pattern_name = bullish_pattern_hit(
            df, tuple(cfg.get("signals", {}).get("allowed_patterns",
                                                 ["bullish_engulfing", "hammer", "morning_star"]))
        )
        pattern_str = pattern_name if pattern_name else "none"

        # Log a compact, definitive line per symbol so you KNOW AI + patterns ran
        logging.info(
            f"{sym} @ {price:.2f} | TA buy={sig['buy']} sell={sig['sell']} | "
            f"AI={ai['ai_score']:.1f}/{ai['ai_conf']:.0f}% pass={ai['passed']} "
            f"use_llm={ai['use_llm']} status={ai.get('llm_status','')} | "
            f"pattern={pattern_str} | pos_qty={pos['qty']:.6f} sl={pos['sl']:.2f} tp={pos['tp']:.2f} | {feat_note}"
        )

        # Persist AI decision row (put status/rationale in note when AI_DEBUG=1)
        note_txt = ""
        if ai_debug:
            # status first, then rationale snippet
            rat = ai.get("rationale","")
            note_txt = f"status={ai.get('llm_status','')}" + (f" | {rat[:120]}" if rat else "")

        storage.append_ai_decision(
            storage.now_iso(), sym, price,
            ai["ai_score"], ai["ai_conf"], ai["passed"], ai["use_llm"],
            pattern_str, sig["buy"], sig["sell"],
            note_txt
        )

        # =========================================
        # EXIT MANAGEMENT (always allowed if in pos)
        # =========================================
        if pos["qty"] > 0:
            # Trailing stop ratchet (only raises SL)
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

                    # Ledgers
                    state["realized_pnl_frac"] += pnl_frac
                    state["day_pnl_frac"][day] = state["day_pnl_frac"].get(day, 0.0) + pnl_frac
                    state["realized_pnl_usdt"] += pnl_usdt
                    state["day_pnl_usdt"][day] = state["day_pnl_usdt"].get(day, 0.0) + pnl_usdt

                    storage.append_trade(storage.now_iso(), "SELL", sym, qty, price, pnl_frac, pnl_usdt, "TP")
                    notify(f"🎯 TP SELL {sym} qty={qty:.6f} @ {price:.2f} | +{pnl_usdt:.2f} USDT | paper={str(dry).lower()}")
                    logging.info(f"{sym}: TP SELL qty={qty:.6f} @ {price:.2f}")
                    sells += 1

                # Flat the position
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

                    # Track loss streak for future adaptive risk if wanted
                    if pnl_usdt < 0:
                        state["loss_streak"] = state.get("loss_streak", 0) + 1
                    else:
                        state["loss_streak"] = 0

                state["positions"][sym] = {"qty": 0.0, "avg": 0.0, "sl": 0.0, "tp": 0.0, "trail_pct": 0.0}

            # else: HOLD (waiting for TP/SL)

        # =========================================
        # ENTRY (gated): TA buy + AI pass + (optional) pattern
        # =========================================
        # For testing complete flow, set ALLOW_AI_ONLY=1 to ignore TA buy
        ta_allows = bool(sig["buy"]) or allow_ai_only
        if allow_new_entries and pos["qty"] <= 0 and ta_allows and ai["passed"]:
            # Enforce pattern only if configured
            require_pat = cfg.get("signals", {}).get("require_bullish_pattern", True)
            if require_pat and not ok_pat:
                logging.info(f"{sym}: skipped — no bullish candlestick")
                continue

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

    # ------------------------------
    # Equity snapshot (realized-only proxy). Mark-to-market can be added later.
    # ------------------------------
    deposits = storage.total_deposits(state)
    equity_proxy = deposits + state.get("realized_pnl_usdt", 0.0)
    storage.append_equity(storage.now_iso(), equity_proxy, deposits, state.get("realized_pnl_frac", 0.0), "auto")
    storage.write_state(state)

    # Human-friendly heartbeat/summary (also to Telegram if enabled)
    pnl_today = float(state["day_pnl_usdt"].get(day, 0.0))
    summary = (
        f"Processed {len(symbols)} symbols | buys={buys} sells={sells} | "
        f"day_pnl_usdt={pnl_today:.2f} | equity={equity_proxy:.2f}"
    )
    logging.info(summary)
    if heartbeat:
        notify(f"🤖 heartbeat: {summary}")


if __name__ == "__main__":
    main()
