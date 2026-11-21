# ai-system

The code for the article on building the system around a message classifier. So far it has the intake and buffer layers (a gateway, Postgres and a Redis stream) and the classifier service with its fallback order. More services are added as the article goes on.

## Layout

```
docker-compose.yml           postgres, redis, gateway, classifier, and a one-off tools container
.env.example                 copy to .env and add your keys
data/messages.csv            the 360 synthetic messages from part 1
data/replay/                 saved Jev and Haiku answers for the 100 test messages
db/init.sql                  the messages table
services/gateway/            the webhook (FastAPI)
services/classifier/         the fallback order: policy.py is the decision, providers.py the three models, tests/
scripts/gateway_check.py     end-to-end check of the gateway (standard library only)
scripts/streams_demo.py      a worker crashes and another takes over its message
scripts/threshold_sweep.py   replays saved answers through the fallback order, no keys needed
scripts/classifier_eval.py   runs the 100 test messages through the live classifier service
```

## What you need

- Docker Desktop, running. Compose v2 (`docker compose`, with a space).
- Python 3.8 or newer on your machine, for `gateway_check.py`. It uses only the standard library, so there is nothing to install.
- Free ports 5432, 6379, 8000 and 8001. If one is taken, change the left-hand number under `ports:` in `docker-compose.yml`. The scripts hard-code ports 8000 (gateway) and 8001 (classifier).

## Run it

From this folder:

```bash
docker compose up -d --build
docker compose ps
```

Wait until postgres and redis show `healthy` and the gateway shows `running`. The first run pulls images, so it can take a few minutes.

### 1. Check the gateway

```bash
python3 scripts/gateway_check.py
```

It sends messages to the gateway, sends one twice, stops the redis container to simulate the queue going down, starts it again, and lets the "provider" retry. You should see this (your run number will differ):

```
Gateway check, run 1795048678

PASS  send message 1                                 expected 200 queued                   got 200 queued
PASS  send message 1 again                           expected 200 duplicate                got 200 duplicate
PASS  stream grew by one so far                      expected 1                            got 1

Stopping redis to simulate the queue going down...
PASS  send message 2 while the queue is down         expected 503                          got 503
Starting redis again...
PASS  message 2 is saved but not queued              expected received                     got received
PASS  provider retries message 2 (1 attempt(s))      expected 200 queued                   got 200 queued
PASS  provider retries message 2 again               expected 200 duplicate                got 200 duplicate
PASS  stream grew by two in total                    expected 2                            got 2
PASS  message 2 row ends as                          expected queued                       got queued

PASS  empty message is rejected                      expected 422                          got 422
PASS  unknown channel is rejected                    expected 404                          got 404

11 of 11 checks passed
```

The attempt count on the retry line can be higher than 1 if the gateway needs a moment to reconnect to redis. That is fine.

### 2. Watch a worker crash and another take over

```bash
docker compose run --rm tools sh -c "pip install -q redis && python scripts/streams_demo.py"
```

Expected:

```
worker-1 read m1 and crashed
worker-2 read and acknowledged m2
pending: 1, held by ['worker-1']
worker-3 claimed m1
worker-3 acknowledged m1
pending: 0
```

### 3. Try the fallback order without any keys

This needs nothing but Python 3.8 or newer. It replays the saved Jev and Haiku answers for the 100 test messages through the policy at different Jev confidence thresholds:

```bash
python3 scripts/threshold_sweep.py
```

Expected:

```
threshold  accepted  wrong  to a person  asked haiku  mean time  $ per 1,000
      0.7        97      0            3            5      0.51s       0.0264
      0.8        97      0            3            5      0.51s       0.0264
      0.9        97      0            3            8      0.55s       0.0294
     0.95        97      0            3           13      0.60s       0.0344
     0.99        97      0            3           15      0.62s       0.0363
```

Run the unit tests for the policy, also without keys:

```bash
docker compose run --rm --no-deps classifier python -m unittest discover -s tests -v
```

You should see `Ran 11 tests` and `OK`.

### 4. Run the live classifier (needs your keys)

```bash
cp .env.example .env        # then put your TYPESAFE_API_KEY and ANTHROPIC_API_KEY in .env
docker compose up -d --build classifier
curl localhost:8001/health  # should show "jev": true and "haiku": true
python3 scripts/classifier_eval.py
```

This makes about 100 Jev calls and a handful of Haiku calls, which cost a fraction of a cent. It prints how many messages were accepted automatically, how many went to a person, and the time per message.

To see the offline fallback, empty both keys in `.env`, run `docker compose up -d classifier`, and run `classifier_eval.py` again. Every message should go to a person with a TF-IDF suggestion (11 of the 100 suggestions will be wrong, matching the 89% from part 1).

### Look inside

```bash
docker compose exec postgres psql -U app -d appdb -c "select provider_message_id, status from messages order by received_at desc limit 5;"
docker compose exec redis redis-cli XLEN messages
docker compose logs gateway
```

### Stop

```bash
docker compose down        # stops everything and keeps the data
docker compose down -v     # also deletes the database and the stream
```

## Status

The gateway, the classifier code, the unit tests, the scripts and the SQL were run on Linux against Redis 7.0 and Postgres 16, with the services running as normal processes. The classifier was run without keys, so its Jev and Haiku calls have not been tried against the live APIs. The Compose file and the Dockerfiles haven't been run. If something fails on first start, send the output of `docker compose logs`.
