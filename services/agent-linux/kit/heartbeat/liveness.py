#!/usr/bin/env python3
"""
liveness.py — honest liveness check.

Separates the two kinds of writer in beats.jsonl:
  daemon       -> the background auto-beat (daemon.sh)
  you          -> "tick" (tick.py) and "manual" (heartbeat.py beat)

DRIFT fires only when YOU stop signing in. A daemon beating forever while you
are absent is exactly the failure this catches. Exit 0 = present, 1 = drift.

Usage: ./liveness.py [stale-minutes]   (default 15)
"""
import json, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "beats.jsonl")
STALE_MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 15


def main():
    rows = []
    if os.path.exists(LOG):
        with open(LOG) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    daemon = [r for r in rows if r.get("source") == "daemon"]
    you = [r for r in rows if r.get("source") in ("tick", "manual")]
    print(f"total beats : {len(rows)}")
    print(f"daemon      : {len(daemon)}" + (f"  (last {daemon[-1]['ts']})" if daemon else ""))
    print(f"you         : {len(you)}" + (f"  (last {you[-1]['ts']})" if you else ""))
    print("--- verdict ---")
    if not you:
        print("DRIFT: you have never signed in." + (" The daemon is beating alone." if daemon else ""))
        sys.exit(1)
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(you[-1]["ts"])).total_seconds() / 60
    if age > STALE_MIN:
        print(f"DRIFT: you have been silent {age:.1f} min. Sign in.")
        sys.exit(1)
    print(f"OK: you signed in {age:.1f} min ago.")


if __name__ == "__main__":
    main()
