"""
Tests for the fallback order. No network calls and no API keys needed.

Run from services/classifier:
    python -m unittest discover -s tests -v
In Compose (the data folder is mounted at /data):
    docker compose run --rm --no-deps classifier python -m unittest discover -s tests -v
"""
import csv
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import providers  # noqa: E402
from policy import decide  # noqa: E402

DATA_DIR = os.environ.get("DATA_DIR", "/data")
os.environ.setdefault("DATA_PATH", os.path.join(DATA_DIR, "messages.csv"))


def jev_says(label, conf):
    return lambda text: (label, conf)


def haiku_says(label):
    return lambda text: label


def down(text):
    raise providers.ProviderError("down")


def tfidf(text):
    return "order_status", 0.4


class PolicyTests(unittest.TestCase):
    def test_confident_jev_is_accepted_without_calling_haiku(self):
        calls = []
        r = decide("x", jev_says("place_order", 0.97), lambda t: calls.append(t) or "place_order", tfidf)
        self.assertFalse(r.needs_review)
        self.assertEqual((r.intent, r.model, r.path), ("place_order", "jev", ["jev"]))
        self.assertEqual(calls, [])

    def test_unsure_jev_and_agreeing_haiku_is_accepted(self):
        r = decide("x", jev_says("order_status", 0.6), haiku_says("order_status"), tfidf)
        self.assertFalse(r.needs_review)
        self.assertEqual((r.model, r.path), ("jev+haiku", ["jev", "haiku"]))

    def test_disagreement_goes_to_a_person(self):
        r = decide("x", jev_says("complaint_refund", 0.64), haiku_says("order_status"), tfidf)
        self.assertTrue(r.needs_review)
        self.assertEqual((r.intent, r.alternative, r.reason), ("complaint_refund", "order_status", "jev and haiku disagree"))

    def test_other_is_never_accepted_automatically(self):
        r = decide("x", jev_says("other", 0.94), haiku_says("other"), tfidf)
        self.assertTrue(r.needs_review)
        self.assertEqual(r.reason, "no matching intent")

    def test_confident_other_still_gets_a_second_opinion(self):
        r = decide("x", jev_says("other", 0.99), haiku_says("payment_confirmation"), tfidf)
        self.assertTrue(r.needs_review)
        self.assertEqual(r.alternative, "payment_confirmation")

    def test_jev_down_uses_haiku_alone(self):
        r = decide("x", down, haiku_says("price_availability"), tfidf)
        self.assertFalse(r.needs_review)
        self.assertEqual((r.model, r.confidence), ("haiku", None))

    def test_jev_down_and_haiku_says_other_goes_to_a_person(self):
        r = decide("x", down, haiku_says("other"), tfidf)
        self.assertTrue(r.needs_review)

    def test_unsure_jev_with_haiku_down_goes_to_a_person(self):
        r = decide("x", jev_says("place_order", 0.5), down, tfidf)
        self.assertTrue(r.needs_review)
        self.assertEqual(r.reason, "jev unsure and no second opinion")

    def test_both_down_falls_back_to_tfidf_and_always_reviews(self):
        r = decide("x", down, down, tfidf)
        self.assertTrue(r.needs_review)
        self.assertEqual((r.model, r.path), ("tfidf", ["tfidf"]))


class TfidfTests(unittest.TestCase):
    def test_offline_model_labels_an_obvious_message(self):
        label, prob = providers.ask_tfidf("I've paid 12k, please confirm")
        self.assertEqual(label, "payment_confirmation")
        self.assertGreater(prob, 0.2)


class ReplayTests(unittest.TestCase):
    """Replays the saved Jev and Haiku answers for the 100 test messages through the policy."""

    def load(self, name):
        with open(os.path.join(DATA_DIR, "replay", name), newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_replay_of_the_100_test_messages(self):
        fix = lambda s: "other" if s == "out_of_scope" else s
        jev = {r["message"]: (fix(r["predicted"]), float(r["confidence"])) for r in self.load("jev_test.csv")}
        haiku = {r["message"]: fix(r["predicted"]) for r in self.load("haiku_test.csv")}
        truth = {r["message"]: r["intent"] for r in self.load("jev_test.csv")}

        accepted = wrong_accepted = review = escalated = 0
        for text in truth:
            r = decide(text, lambda t: jev[t], lambda t: haiku[t], tfidf, threshold=0.9)
            escalated += "haiku" in r.path
            if r.needs_review:
                review += 1
            else:
                accepted += 1
                wrong_accepted += r.intent != truth[text]

        self.assertEqual((accepted, wrong_accepted, review, escalated), (97, 0, 3, 8))


if __name__ == "__main__":
    unittest.main()
