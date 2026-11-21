"""
Replays the saved Jev and Haiku answers for the 100 test messages through the fallback order
at different Jev confidence thresholds. Standard library only, no API calls.

Run from the repo root:  python3 scripts/threshold_sweep.py
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "classifier"))
from policy import decide  # noqa: E402

# USD per million tokens
JEV_IN, HAIKU_IN, HAIKU_OUT = 0.042, 0.10, 0.50


def load(name):
    with open(ROOT / "data" / "replay" / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


fix = lambda s: "other" if s == "out_of_scope" else s
jev_rows, haiku_rows = load("jev_test.csv"), load("haiku_test.csv")
haiku_by_id = {r["id"]: r for r in haiku_rows}

print(f"{'threshold':>9} {'accepted':>9} {'wrong':>6} {'to a person':>12} {'asked haiku':>12} {'mean time':>10} {'$ per 1,000':>12}")
for threshold in (0.7, 0.8, 0.9, 0.95, 0.99):
    accepted = wrong = review = asked = 0
    seconds = cost = 0.0
    for j in jev_rows:
        h = haiku_by_id[j["id"]]
        result = decide(
            j["message"],
            lambda t, j=j: (fix(j["predicted"]), float(j["confidence"])),
            lambda t, h=h: fix(h["predicted"]),
            lambda t: ("order_status", 0.4),
            threshold,
        )
        seconds += float(j["latency_s"])
        cost += float(j["input_tokens"]) * JEV_IN / 1e6
        if "haiku" in result.path:
            asked += 1
            seconds += float(h["latency_s"])
            cost += (float(h["input_tokens"]) * HAIKU_IN + float(h["output_tokens"]) * HAIKU_OUT) / 1e6
        if result.needs_review:
            review += 1
        else:
            accepted += 1
            wrong += result.intent != j["intent"]
    n = len(jev_rows)
    print(f"{threshold:>9} {accepted:>9} {wrong:>6} {review:>12} {asked:>12} {seconds / n:>9.2f}s {cost / n * 1000:>12.4f}")
