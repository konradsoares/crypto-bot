import argparse, os
from utils import storage

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")

    d = sub.add_parser("deposit");   d.add_argument("--amount", type=float, required=True); d.add_argument("--note", default="seed")
    w = sub.add_parser("withdraw");  w.add_argument("--amount", type=float, required=True); w.add_argument("--note", default="")
    s = sub.add_parser("snapshot");  s.add_argument("--equity", type=float, required=True); s.add_argument("--note", default="manual snapshot")

    args = ap.parse_args()
    if args.cmd == "deposit":
        storage.record_deposit(args.amount, args.note)
        print(f"Recorded deposit: {args.amount} USDT")
    elif args.cmd == "withdraw":
        storage.record_withdraw(args.amount, args.note)
        print(f"Recorded withdraw: {args.amount} USDT")
    elif args.cmd == "snapshot":
        st = storage.read_state()
        storage.append_equity(storage.now_iso(), args.equity, storage.total_deposits(st), st.get("realized_pnl", 0.0), args.note)
        print("Snapshot written.")
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
