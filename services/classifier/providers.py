"""The three ways to label a message. Each raises ProviderError when it can't answer."""
import csv
import os

import anthropic
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from typesafe_sdk import Choice, TypeSafeClient

from errors import ProviderError  # noqa: F401  (re-exported)

JEV_MODEL = "jev-1.13.0"
HAIKU_MODEL = "claude-haiku-5-5"

# One set of definitions, shared by Jev and Haiku.
DEFINITIONS = {
    "price_availability": "asks about prices, the menu, what is available, opening hours, delivery fees or portion sizes, before ordering.",
    "place_order": "wants to order, add to an order or change an order.",
    "payment_confirmation": "says they have paid and wants the payment confirmed.",
    "order_status": "asks where their order is, when it will arrive or whether it is ready.",
    "complaint_refund": "reports a problem with an order (wrong, missing, cold or late food, rude service) or asks for a refund.",
    "other": "fits none of the above, such as greetings, job enquiries or supplier pitches.",
}
TIE_BREAK = "If a message contains more than one request, choose the first one the customer asks for."
INTENTS = list(DEFINITIONS)


# ---- Jev -------------------------------------------------------------------
JEV_QUESTIONS = {
    "intent": Choice(
        instructions=f"Choose the one intent that best describes what the customer wants in `message`. {TIE_BREAK}",
        criteria=DEFINITIONS,
    )
}
_jev = None


def ask_jev(text):
    """Returns (intent, confidence)."""
    global _jev
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise ProviderError("no TYPESAFE_API_KEY")
    try:
        if _jev is None:
            _jev = TypeSafeClient(model=JEV_MODEL, timeout=8)
        answer = _jev.system_one(state={"message": text}, questions=JEV_QUESTIONS).choices["intent"]
        return answer.choice, float(answer.confidence)
    except Exception as err:
        raise ProviderError(f"jev: {err}") from err


# ---- Claude Haiku ----------------------------------------------------------
HAIKU_SYSTEM = (
    "You classify customer messages sent to a food business on WhatsApp and Instagram.\n"
    "Choose the one intent that best describes what the customer wants.\n\nIntents:\n"
    + "\n".join(f"- {name}: {desc}" for name, desc in DEFINITIONS.items())
    + f"\n\n{TIE_BREAK}"
)
HAIKU_TOOLS = [
    {
        "name": "record_intent",
        "description": "Record the intent of the customer message.",
        "input_schema": {
            "type": "object",
            "properties": {"intent": {"type": "string", "enum": INTENTS}},
            "required": ["intent"],
        },
    }
]
_haiku = None


def ask_haiku(text):
    """Returns an intent. Haiku gives no confidence score."""
    global _haiku
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ProviderError("no ANTHROPIC_API_KEY")
    try:
        if _haiku is None:
            _haiku = anthropic.Anthropic(timeout=10, max_retries=1)
        response = _haiku.messages.create(
            model=HAIKU_MODEL,
            max_tokens=100,
            system=HAIKU_SYSTEM,
            tools=HAIKU_TOOLS,
            tool_choice={"type": "tool", "name": "record_intent"},
            messages=[{"role": "user", "content": text}],
        )
    except Exception as err:
        raise ProviderError(f"haiku: {err}") from err
    for block in response.content:
        if block.type == "tool_use" and block.input.get("intent") in INTENTS:
            return block.input["intent"]
    raise ProviderError("haiku: no valid answer")


# ---- TF-IDF, the offline fallback -------------------------------------------
_tfidf = None


def ask_tfidf(text):
    """Returns (intent, probability). Trained on the train split, in memory, on first use."""
    global _tfidf
    if _tfidf is None:
        path = os.environ.get("DATA_PATH", "/data/messages.csv")
        with open(path, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["split"] == "train"]
        _tfidf = make_pipeline(
            TfidfVectorizer(lowercase=True, ngram_range=(1, 2), sublinear_tf=True),
            LogisticRegression(max_iter=1000),
        )
        _tfidf.fit([r["message"] for r in rows], [r["intent"] for r in rows])
    proba = _tfidf.predict_proba([text])[0]
    best = int(proba.argmax())
    return str(_tfidf.classes_[best]), float(proba[best])
