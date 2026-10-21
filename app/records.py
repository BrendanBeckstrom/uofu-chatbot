"""Where question, feedback and daily-spend records go.

LOG_BACKEND=files (the default) appends to data/usage.jsonl and data/feedback.jsonl, and keeps the day's
spend in data/spend.json. LOG_BACKEND=firestore (the hosted beta) writes the same fields to the Firestore
collections `questions`, `feedback` and `spend`. docs/DATA_PLAN.md lists the fields.

Firestore writes go through one background thread, so a slow write never delays an answer. The server
calls flush() before closing each response, because Cloud Run pauses the CPU once a response ends.
"""

import json
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import config

COLLECTIONS = {"question": "questions", "feedback": "feedback"}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now_local() -> str:
    """Local time, which is Salt Lake City on the server (TZ in the Dockerfile)."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Files:
    def _path(self, kind: str):
        return config.USAGE_PATH if kind == "question" else config.FEEDBACK_PATH

    def save(self, kind: str, record: dict):
        try:
            path = self._path(kind)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def read(self, kind: str, since: str) -> list[dict]:
        try:
            rows = [json.loads(line) for line in self._path(kind).read_text().splitlines() if line.strip()]
        except FileNotFoundError:
            return []
        return [r for r in rows if r.get("ts", "")[:10] >= since]

    def flush(self, timeout: float = 10):
        pass


class Firestore:
    def __init__(self, client=None):
        if client is None:
            from google.cloud import firestore
            client = firestore.Client()
        self.db = client
        self.queue: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None

    def save(self, kind: str, record: dict):
        doc = {**record, "expire_at": datetime.now(timezone.utc) + timedelta(days=config.LOG_RETENTION_DAYS)}
        self._enqueue(lambda: self.db.collection(COLLECTIONS[kind]).document(record["id"]).set(doc))

    def read(self, kind: str, since: str) -> list[dict]:
        from google.cloud.firestore_v1.base_query import FieldFilter
        docs = self.db.collection(COLLECTIONS[kind]).where(filter=FieldFilter("ts", ">=", since)).stream()
        return [{k: v for k, v in d.to_dict().items() if k != "expire_at"} for d in docs]

    def get_spend(self, day: str) -> float:
        snap = self.db.collection("spend").document(day).get(timeout=10)
        return float((snap.to_dict() or {}).get("spent", 0)) if snap.exists else 0.0

    def put_spend(self, day: str, spent: float):
        self._enqueue(lambda: self.db.collection("spend").document(day).set(
            {"day": day, "spent": spent, "updated": now_local()}))

    def flush(self, timeout: float = 10):
        deadline = time.monotonic() + timeout
        while self.queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)

    def _enqueue(self, write):
        if not self.thread:
            self.thread = threading.Thread(target=self._run, name="records", daemon=True)
            self.thread.start()
        self.queue.put(write)

    def _run(self):
        while True:
            write = self.queue.get()
            try:
                write()
            except Exception as e:  # a lost log line must never break the chat
                print(f"[records] write failed: {type(e).__name__}: {e}", flush=True)
            finally:
                self.queue.task_done()


_backend: Files | Firestore | None = None


def backend() -> Files | Firestore:
    global _backend
    if _backend is None:
        _backend = Firestore() if config.LOG_BACKEND == "firestore" else Files()
    return _backend


def save(kind: str, record: dict):
    backend().save(kind, record)


def read(kind: str, since: str) -> list[dict]:
    return backend().read(kind, since)


def flush():
    backend().flush()
