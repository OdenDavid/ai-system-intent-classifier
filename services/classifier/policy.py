"""
The fallback order. This file is the decision, in one place.

1. Ask Jev. If it is sure enough and the intent has an action, accept.
2. Otherwise ask Haiku for a second opinion. If they agree on an intent with an action, accept.
   If they disagree, or both say "other", a person reviews it.
3. If Jev is down, use Haiku alone. "other" goes to a person.
4. If both are down, TF-IDF suggests a label and a person reviews every message.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from errors import ProviderError


@dataclass
class Result:
    intent: str
    model: str
    needs_review: bool
    reason: str
    confidence: float | None = None
    alternative: str | None = None
    path: list = field(default_factory=list)


def _try(fn, text):
    try:
        return fn(text)
    except ProviderError:
        return None


def decide(text, jev, haiku, tfidf, threshold=0.9):
    path = []

    answer = _try(jev, text)
    if answer is not None:
        path.append("jev")
        label, conf = answer
        if conf >= threshold and label != "other":
            return Result(label, "jev", False, "jev is confident", conf, None, path)

        second = _try(haiku, text)
        if second is None:
            return Result(label, "jev", True, "jev unsure and no second opinion", conf, None, path)
        path.append("haiku")
        if second == label and label != "other":
            return Result(label, "jev+haiku", False, "haiku agrees", conf, None, path)
        reason = "no matching intent" if second == label else "jev and haiku disagree"
        return Result(label, "jev+haiku", True, reason, conf, second if second != label else None, path)

    second = _try(haiku, text)
    if second is not None:
        path.append("haiku")
        if second != "other":
            return Result(second, "haiku", False, "jev unavailable", None, None, path)
        return Result(second, "haiku", True, "no matching intent", None, None, path)

    label, conf = tfidf(text)
    path.append("tfidf")
    return Result(label, "tfidf", True, "providers unavailable, suggestion only", conf, None, path)
