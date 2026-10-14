"""On-disk document store: one record per page/post across all sites, plus per-site sync state."""

import json
import threading
from pathlib import Path

from . import config


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)  # atomic swap: readers never see a half-written file


def doc_key(site: str, kind: str, item_id) -> str:
    return f"{site}:{kind}:{item_id}"


class Store:
    """docs: key -> {key, site, id, type, url, title, date, modified, text}; type is page, post,
    pdf or handbook (the last two come from app/documents.py)."""

    def __init__(self, docs_path: Path = config.DOCS_PATH, state_path: Path = config.STATE_PATH):
        self.docs_path, self.state_path = docs_path, state_path
        self.docs: dict[str, dict] = _read(docs_path, {})
        self.state: dict[str, dict] = _read(state_path, {})
        self.lock = threading.Lock()

    def site_state(self, site: str) -> dict:
        return self.state.setdefault(site, {})

    def upsert(self, doc: dict):
        # A slug change gives the same item a new URL; keying by site:type:id replaces the old one.
        self.docs[doc["key"]] = doc

    def remove(self, key: str) -> bool:
        return self.docs.pop(key, None) is not None

    def remove_url(self, url: str) -> bool:
        keys = [k for k, d in self.docs.items() if d["url"].rstrip("/") == url.rstrip("/")]
        for k in keys:
            del self.docs[k]
        return bool(keys)

    def keys_for(self, site: str, kind: str) -> set[str]:
        return {k for k, d in self.docs.items() if d["site"] == site and d["type"] == kind}

    def save(self):
        with self.lock:
            write_atomic(self.docs_path, self.docs)
            write_atomic(self.state_path, self.state)

    def stats(self) -> dict:
        per_site: dict[str, dict] = {}
        for d in self.docs.values():
            s = per_site.setdefault(d["site"], {"page": 0, "post": 0})
            s[d["type"]] = s.get(d["type"], 0) + 1
        return per_site
