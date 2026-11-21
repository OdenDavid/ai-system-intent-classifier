import os
import time
from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel, Field

import providers
from policy import decide

THRESHOLD = float(os.environ.get("JEV_THRESHOLD", "0.9"))
app = FastAPI()


class Request(BaseModel):
    text: str = Field(min_length=1)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "jev": bool(os.environ.get("TYPESAFE_API_KEY")),
        "haiku": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "threshold": THRESHOLD,
    }


@app.post("/classify")
def classify(req: Request):
    start = time.perf_counter()
    result = decide(req.text, providers.ask_jev, providers.ask_haiku, providers.ask_tfidf, THRESHOLD)
    return {**asdict(result), "latency_ms": round((time.perf_counter() - start) * 1000)}
