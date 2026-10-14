"""The usage report counts people, questions, errors and gaps from the logs.

Run:  .venv/bin/python -m tests.test_analytics
"""

import json
import tempfile
from datetime import date
from pathlib import Path

from app import analytics, config


def main():
    tmp = Path(tempfile.mkdtemp())
    config.USAGE_PATH, config.FEEDBACK_PATH = tmp / "usage.jsonl", tmp / "feedback.jsonl"
    today = date.today().isoformat()
    rows = [
        {"user": "a", "question": "How do I apply?", "gate": "in_scope", "topic": "admissions", "seconds": 4, "cost_usd": 0.002},
        {"user": "a", "question": "How do I apply?", "gate": "in_scope", "topic": "admissions", "seconds": 6, "cost_usd": 0.002},
        {"user": "b", "question": "When is the BME seminar?", "gate": "in_scope", "topic": "events", "gap": True,
         "seconds": 5, "cost_usd": 0.003, "audience": "current"},
        {"user": "b", "question": "cake recipe", "gate": "out_of_scope", "topic": "other", "seconds": 1, "cost_usd": 0.0001},
        {"user": "c", "question": "hi", "error": "The AI service returned an error (500).", "seconds": 1, "cost_usd": 0},
        {"question": "eval traffic has no user", "gate": "in_scope", "seconds": 3, "cost_usd": 0.002},
    ]
    config.USAGE_PATH.write_text("".join(json.dumps({"ts": f"{today}T10:00:00", **r}) + "\n" for r in rows))
    config.FEEDBACK_PATH.write_text(json.dumps({"ts": f"{today}T10:05:00", "rating": 1}) + "\n")

    r = analytics.report(7)
    assert r["people"] == 3 and r["questions"] == 4 and r["errors"] == 1, r
    assert r["declined"] == {"out_of_scope": 1} and r["content_gaps"] == 1
    assert r["topics"]["admissions"] == 2 and r["top_questions"][0] == ("how do i apply", 2)
    assert r["feedback"] == {"up": 1, "down": 0} and r["daily"][today] == {"people": 3, "questions": 4, "errors": 1}
    assert r["recent_gaps"] == ["When is the BME seminar?"]
    print("✓ report: people, questions, errors, declines, gaps, topics and feedback; script traffic left out")
    print("All analytics checks passed.")


if __name__ == "__main__":
    main()
