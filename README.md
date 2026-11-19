# ai-system

The code for the article on building the system around a message classifier. This first stage has the intake and buffer layers: a gateway that takes in messages, Postgres to record them, and a Redis stream to hold them. More services are added as the article goes on.

## Layout

```
docker-compose.yml           postgres, redis, gateway, and a one-off tools container
db/init.sql                  the messages table
services/gateway/            the webhook (FastAPI): app.py, Dockerfile, requirements.txt
scripts/gateway_check.py     end-to-end check of the gateway (standard library only)
scripts/streams_demo.py      a worker crashes and another takes over its message
```

## What you need

- Docker Desktop, running. Compose v2 (`docker compose`, with a space).
- Python 3.8 or newer on your machine, for `gateway_check.py`. It uses only the standard library, so there is nothing to install.
- Free ports 5432, 6379 and 8000. If one is taken, change the left-hand number under `ports:` in `docker-compose.yml`. Port 8000 is also hard-coded as `BASE` in `scripts/gateway_check.py`.

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

The gateway code, both scripts and the SQL were run on Linux against Redis 7.0 and Postgres 16, with the gateway running as a normal process. The Compose file and the Dockerfile are new and haven't been run. If something fails on first start, send the output of `docker compose logs`.
