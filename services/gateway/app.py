import os

import psycopg
import redis
from fastapi import FastAPI, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
STREAM = "messages"
CHANNELS = {"whatsapp", "instagram"}

app = FastAPI()
cache = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


class Incoming(BaseModel):
    """Our one message shape. Each real channel gets an adapter that produces this."""

    message_id: str = Field(min_length=1)
    sender_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/{channel}")
def webhook(channel: str, msg: Incoming):
    if channel not in CHANNELS:
        raise HTTPException(status_code=404, detail="unknown channel")

    # autocommit: the row must be visible before anyone can read the stream entry
    with psycopg.connect(DATABASE_URL, autocommit=True) as db:
        status = db.execute(
            """
            INSERT INTO messages (provider_message_id, channel, sender_id, text, raw)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (provider_message_id)
            DO UPDATE SET provider_message_id = EXCLUDED.provider_message_id
            RETURNING status
            """,
            (msg.message_id, channel, msg.sender_id, msg.text, Jsonb(msg.model_dump())),
        ).fetchone()[0]

        if status == "queued":
            return {"status": "duplicate"}

        try:
            cache.xadd(
                STREAM,
                {"message_id": msg.message_id, "channel": channel, "sender_id": msg.sender_id, "text": msg.text},
                maxlen=100_000,
                approximate=True,
            )
        except redis.RedisError:
            # Saved but not queued. A 503 makes the provider retry, and the retry finds status 'received'.
            raise HTTPException(status_code=503, detail="queue unavailable")

        db.execute("UPDATE messages SET status = 'queued' WHERE provider_message_id = %s", (msg.message_id,))
    return {"status": "queued"}
