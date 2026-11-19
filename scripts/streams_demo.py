import os
import time

import redis

r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
STREAM, GROUP = "demo", "workers"

r.delete(STREAM)
r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
r.xadd(STREAM, {"message_id": "m1", "text": "I've paid 12k, please confirm"})
r.xadd(STREAM, {"message_id": "m2", "text": "Where is my order?"})

# worker-1 reads a message, then crashes before acknowledging it
(_, entries), = r.xreadgroup(GROUP, "worker-1", {STREAM: ">"}, count=1)
print(f"worker-1 read {entries[0][1]['message_id']} and crashed")

# worker-2 reads the next message and acknowledges it
(_, entries), = r.xreadgroup(GROUP, "worker-2", {STREAM: ">"}, count=1)
entry_id, fields = entries[0]
r.xack(STREAM, GROUP, entry_id)
print(f"worker-2 read and acknowledged {fields['message_id']}")

pending = r.xpending(STREAM, GROUP)
print(f"pending: {pending['pending']}, held by {[c['name'] for c in pending['consumers']]}")

# after a message has sat unacknowledged for a second, another worker takes it over
time.sleep(1.1)
result = r.xautoclaim(STREAM, GROUP, "worker-3", min_idle_time=1000, start_id="0-0", count=10)
for entry_id, fields in result[1]:
    print(f"worker-3 claimed {fields['message_id']}")
    r.xack(STREAM, GROUP, entry_id)
    print(f"worker-3 acknowledged {fields['message_id']}")

print(f"pending: {r.xpending(STREAM, GROUP)['pending']}")
