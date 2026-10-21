"""The usage report counts people, questions, errors and gaps from the logs, and the Firestore records
(app/records.py) hold the same data. Firestore is replaced by a small in-memory fake.

Run:  .venv/bin/python -m tests.test_analytics
"""

import json
import operator
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

from app import analytics, config, guard, records


class FakeFirestore:
    """Just enough of google.cloud.firestore.Client for app/records.py."""

    def __init__(self):
        self.data: dict[str, dict] = {}

    def collection(self, name):
        return FakeQuery(self.data.setdefault(name, {}))


class FakeQuery:
    OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq}

    def __init__(self, docs, filters=()):
        self.docs, self.filters = docs, list(filters)

    def document(self, doc_id):
        docs = self.docs
        return NS(set=lambda data: docs.__setitem__(doc_id, data),
                  get=lambda timeout=None: NS(exists=doc_id in docs, to_dict=lambda: docs.get(doc_id)))

    def where(self, filter):
        return FakeQuery(self.docs, self.filters + [filter])

    def stream(self):
        for d in list(self.docs.values()):
            if all(self.OPS[f.op_string](d.get(f.field_path), f.value) for f in self.filters):
                yield NS(to_dict=lambda d=d: dict(d))


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

    from_files = r
    fs = records.Firestore(client=FakeFirestore())
    records._backend = fs
    try:
        for row in rows:
            fs.save("question", {"id": records.new_id("q"), "ts": f"{today}T10:00:00", **row})
        fs.save("question", {"id": "q_old", "ts": "2020-01-01T10:00:00", "user": "z", "question": "old"})
        fs.save("feedback", {"id": "f_1", "ts": f"{today}T10:05:00", "rating": 1})
        fs.flush()
        stored = fs.db.data["questions"]
        assert len(stored) == len(rows) + 1 and all(d["expire_at"] > datetime.now(timezone.utc) for d in stored.values())
        from_firestore = analytics.report(7)
        assert from_firestore == from_files, (from_firestore, from_files)
        print("✓ Firestore: records get an expiry date, and the report reads them the same as the files")

        spend = guard.SpendGuard(1.0, tmp / "unused.json", remote=fs)
        spend.record({"input": 10_000, "output": 2_000}, "claude-haiku-5-5")
        fs.flush()
        assert guard.SpendGuard(1.0, tmp / "unused.json", remote=fs).spent == spend.spent > 0
        assert not (tmp / "unused.json").exists()
        print("✓ Firestore: the day's spend survives a restart, so the daily cap does too")
    finally:
        records._backend = None
    print("All analytics checks passed.")


if __name__ == "__main__":
    main()
