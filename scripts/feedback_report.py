"""Print the per-rule noise report from the feedback store (P3.5).

  python scripts/feedback_report.py [--since 2026-09-01] [--json]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.feedback import db_path, noise_report  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="ISO date/time lower bound")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows = noise_report(since=a.since)
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        print(f"feedback store: {db_path()} — {len(rows)} keys")
        print(f"{'kind':5} {'key':40} {'up':>4} {'down':>5} {'total':>6} {'down_rate':>9}")
        for r in rows:
            print(f"{r['kind']:5} {r['key']:40} {r['up']:>4} {r['down']:>5} {r['total']:>6} {r['down_rate']:>9.0%}")
