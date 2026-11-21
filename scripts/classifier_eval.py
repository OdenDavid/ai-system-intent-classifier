"""
Sends the 100 test messages to the running classifier service and summarises what the
fallback order did. Standard library only.

Run from the repo root, with the stack up (docker compose up -d --build):
    python3 scripts/classifier_eval.py
"""
import csv
import json
import statistics
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "http://localhost:8001"

# Average tokens per call from the earlier runs, and USD per million tokens. An estimate only.
JEV_TOKENS, HAIKU_IN_TOKENS, HAIKU_OUT_TOKENS = 509, 818, 37
JEV_PRICE, HAIKU_IN_PRICE, HAIKU_OUT_PRICE = 0.042, 0.10, 0.50


def call(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{URL}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


health = call("/health")
print(f"Service: jev key {'set' if health['jev'] else 'missing'}, haiku key {'set' if health['haiku'] else 'missing'}, threshold {health['threshold']}")
if not (health["jev"] and health["haiku"]):
    print("A key is missing, so some or all messages will use the fallbacks. That is expected if you removed a key on purpose.")

with open(ROOT / "data" / "messages.csv", newline="", encoding="utf-8") as f:
    rows = [r for r in csv.DictReader(f) if r["split"] == "test"]

results = [(r, call("/classify", {"text": r["message"]})) for r in rows]
accepted = [(r, x) for r, x in results if not x["needs_review"]]
reviewed = [(r, x) for r, x in results if x["needs_review"]]
wrong_accepted = [(r, x) for r, x in accepted if x["intent"] != r["intent"]]
caught = [(r, x) for r, x in reviewed if x["intent"] != r["intent"]]
asked_haiku = sum("haiku" in x["path"] for _, x in results)
asked_jev = sum("jev" in x["path"] for _, x in results)
ms = [x["latency_ms"] for _, x in results]
cost = asked_jev * JEV_TOKENS * JEV_PRICE / 1e6 + asked_haiku * (HAIKU_IN_TOKENS * HAIKU_IN_PRICE + HAIKU_OUT_TOKENS * HAIKU_OUT_PRICE) / 1e6

print(f"\nMessages:                         {len(results)}")
print(f"Accepted automatically:           {len(accepted)}  (wrong: {len(wrong_accepted)})")
print(f"Sent to a person:                 {len(reviewed)}  (label was wrong on {len(caught)} of them)")
print(f"Models used:                      {dict(Counter(x['model'] for _, x in results))}")
print(f"Asked Haiku for a second opinion: {asked_haiku}")
print(f"Time per message (ms):            mean {statistics.mean(ms):.0f}, median {statistics.median(ms):.0f}, p95 {sorted(ms)[int(len(ms) * 0.95) - 1]}")
print(f"Estimated cost per 1,000 messages: ${cost / len(results) * 1000:.4f}")
print("\nSent to a person:")
for r, x in reviewed:
    alt = f", alternative {x['alternative']}" if x["alternative"] else ""
    print(f"  {r['message'][:56]:<56} truth {r['intent']:<20} got {x['intent']}{alt} ({x['reason']})")
