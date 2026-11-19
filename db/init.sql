CREATE TABLE IF NOT EXISTS messages (
    provider_message_id TEXT PRIMARY KEY,
    channel             TEXT NOT NULL,
    sender_id           TEXT NOT NULL,
    text                TEXT NOT NULL,
    raw                 JSONB NOT NULL,
    status              TEXT NOT NULL DEFAULT 'received',  -- received, then queued
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
