"""
End-to-end check of the gateway. Standard library only.

Run from the repo root, with the stack up (docker compose up -d --build):
    python3 scripts/gateway_check.py

It sends real HTTP requests to the gateway, reads the database and the stream
through `docker compose exec`, and stops and starts the redis container once
to simulate the queue going down.
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:8000"
RUN = str(int(time.time()))
results = []


def compose(*args):
    out = subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def redis_cli(*args):
    return compose("exec", "-T", "redis", "redis-cli", *args)


def row_status(message_id):
    sql = f"select status from messages where provider_message_id = '{message_id}'"
    return compose("exec", "-T", "postgres", "psql", "-U", "app", "-d", "appdb", "-tAc", sql) or "none"


def stream_length():
    return int(redis_cli("XLEN", "messages") or 0)


def post(channel, payload):
    req = urllib.request.Request(
        f"{BASE}/webhook/{channel}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def wait_until(fn, what, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if fn():
                return
        except Exception:
            pass
        time.sleep(1)
    sys.exit(f"Timed out waiting for {what}. Is the stack up? Try: docker compose up -d --build")


def record(step, expected, actual):
    ok = expected == actual
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {step:<46} expected {expected!s:<28} got {actual}")


def message(n, text):
    return {"message_id": f"chk-{RUN}-{n}", "sender_id": "2348012345678", "text": text}


wait_until(lambda: urllib.request.urlopen(f"{BASE}/health", timeout=3).status == 200, "the gateway")
print(f"Gateway check, run {RUN}\n")
start_len = stream_length()

m1, m2 = message(1, "I've paid 12k, please confirm"), message(2, "Where is my order?")

status, body = post("whatsapp", m1)
record("send message 1", "200 queued", f"{status} {body.get('status')}")
status, body = post("whatsapp", m1)
record("send message 1 again", "200 duplicate", f"{status} {body.get('status')}")
record("stream grew by one so far", 1, stream_length() - start_len)

print("\nStopping redis to simulate the queue going down...")
compose("stop", "redis")
status, body = post("whatsapp", m2)
record("send message 2 while the queue is down", "503", str(status))
print("Starting redis again...")
compose("start", "redis")
wait_until(lambda: redis_cli("ping") == "PONG", "redis")
record("message 2 is saved but not queued", "received", row_status(m2["message_id"]))

attempts, status, body = 0, None, {}
while attempts < 15:
    attempts += 1
    status, body = post("whatsapp", m2)
    if status == 200:
        break
    time.sleep(1)
record(f"provider retries message 2 ({attempts} attempt(s))", "200 queued", f"{status} {body.get('status')}")
status, body = post("whatsapp", m2)
record("provider retries message 2 again", "200 duplicate", f"{status} {body.get('status')}")
record("stream grew by two in total", 2, stream_length() - start_len)
record("message 2 row ends as", "queued", row_status(m2["message_id"]))

print()
status, _ = post("whatsapp", {**message(3, "x"), "text": ""})
record("empty message is rejected", "422", str(status))
status, _ = post("telegram", message(4, "hello"))
record("unknown channel is rejected", "404", str(status))

print(f"\n{sum(results)} of {len(results)} checks passed")
sys.exit(0 if all(results) else 1)
