"""Keep the local copy of the engineering websites current.

    python -m app.sync build                 # full index of every site (polite: 10s between requests per site)
    python -m app.sync build --site ece mse  # just these sites
    python -m app.sync build --offline       # rebuild from data/raw without touching the sites
    python -m app.sync update                # fetch only what changed since the last sync
    python -m app.sync reconcile             # also drop pages that were deleted or unpublished
    python -m app.sync documents             # handbooks, degree plans and flowcharts (PDFs + CS handbook)
    python -m app.sync status

While the server runs, the same update happens automatically in the background when a question
arrives and the last check is older than SYNC_TTL_MINUTES (see Syncer.maybe_sync).
"""

import argparse
import asyncio
import html
import json
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx

from . import config
from .documents import DocumentSync
from .extract import rendered_page, rest_content_to_text
from .store import Store, doc_key, write_atomic
from .wp import Blocked, PoliteClient, fetch_all, newest_modified, robots_ok

KINDS = ("pages", "posts")
DOC_TYPES = ("pdf", "handbook")


class RawStore:
    """Raw REST items per site (data/raw/<site>/), so the index can be rebuilt offline."""

    def __init__(self, site: str):
        self.dir = config.RAW_DIR / site
        self.items = {k: self._load(k) for k in KINDS}
        self.rendered: dict = self._read(self.dir / "rendered.json", {})
        self.dirty = False

    @staticmethod
    def _read(path, default):
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def _load(self, kind: str) -> dict:
        return {str(i["id"]): i for i in self._read(self.dir / f"{kind}.json", [])}

    def replace(self, kind: str, items: list[dict]):
        self.items[kind] = {str(i["id"]): i for i in items}
        self.dirty = True

    def upsert(self, kind: str, items: list[dict]):
        self.items[kind].update({str(i["id"]): i for i in items})
        self.dirty = True

    def remove(self, kind: str, item_id):
        self.dirty |= self.items[kind].pop(str(item_id), None) is not None

    def save(self):
        if not self.dirty:
            return
        for kind in KINDS:
            write_atomic(self.dir / f"{kind}.json", list(self.items[kind].values()))
        write_atomic(self.dir / "rendered.json", self.rendered)
        self.dirty = False


def to_doc(site: str, kind: str, item: dict) -> dict:
    doc_type = "post" if kind == "posts" else "page"
    return {
        "key": doc_key(site, doc_type, item["id"]),
        "site": site,
        "id": item["id"],
        "type": doc_type,
        "url": item["link"],
        "title": html.unescape(item["title"]["rendered"]).strip() or item["link"],
        "date": item.get("date"),
        "modified": item.get("modified"),
        "text": rest_content_to_text((item.get("content") or {}).get("rendered", "")),
    }


def _minus_one_second(stamp: str) -> str:
    # modified_after is strictly "after"; step back a second and let upserts dedupe.
    return (datetime.fromisoformat(stamp) - timedelta(seconds=1)).isoformat(timespec="seconds")


class Syncer:
    def __init__(self, store: Store, on_change=None, log=None):
        self.store = store
        self.on_change = on_change  # async callable, run after docs change (e.g. rebuild the index)
        self.log = log or (lambda msg: None)
        self._client: PoliteClient | None = None
        self._task: asyncio.Task | None = None
        self.dirty = False  # documents changed since the last save

    @property
    def client(self) -> PoliteClient:
        if self._client is None:
            self._client = PoliteClient(config.CRAWL_DELAY)
        return self._client

    # ---- thin pages: the API text is a stub, the real content is in theme blocks ------------

    async def _fill_thin(self, site: str, docs: list[dict], raw: RawStore, fetch: bool):
        host = urlparse(config.SITES[site]["base"]).hostname
        thin = [d for d in docs if d["type"] == "page" and len(d["text"]) < config.THIN_PAGE_CHARS
                and urlparse(d["url"]).hostname == host]  # only the site's own pages
        todo = [d for d in thin if raw.rendered.get(d["url"], {}).get("modified") != d["modified"]]
        if fetch and todo:
            self.log(f"[{site}] reading {len(todo)} pages with little API text "
                     f"(~{len(todo) * config.CRAWL_DELAY / 60:.0f} min)")
            for n, d in enumerate(todo, 1):
                try:
                    resp = await self.client.get(d["url"])
                    raw.rendered[d["url"]] = {"modified": d["modified"],
                                              "text": rendered_page(resp.text, d["url"])["text"]}
                    raw.dirty = True
                except (httpx.HTTPError, Blocked) as e:
                    self.log(f"[{site}]   skip {d['url']}: {type(e).__name__}")
                if n % 20 == 0:
                    self.log(f"[{site}]   {n}/{len(todo)}")
        for d in thin:
            text = raw.rendered.get(d["url"], {}).get("text", "")
            if len(text) > len(d["text"]):
                d["text"] = text

    def _apply(self, docs: list[dict]) -> int:
        """Merge docs into the store; returns how many were actually new or different."""
        changed = 0
        for d in docs:
            old = self.store.docs.get(d["key"])
            if d["text"].strip():
                if old != d:
                    self.store.upsert(d)
                    changed += 1
            elif old:
                self.store.remove(d["key"])
                changed += 1
        self.dirty = self.dirty or bool(changed)
        return changed

    # ---- full build -------------------------------------------------------------------------

    async def build_site(self, site: str, render: bool = True, offline: bool = False):
        base, raw = config.SITES[site]["base"], RawStore(site)
        if offline:
            fetched = {k: list(raw.items[k].values()) for k in KINDS}
            if not any(fetched.values()):
                self.log(f"[{site}] no raw data saved yet; run without --offline first")
                return
        else:
            await robots_ok(self.client, base)
            fetched = {}
            for kind in KINDS:
                fetched[kind] = await fetch_all(
                    self.client, base, kind,
                    on_page=lambda k, p, tp, n: self.log(f"[{site}] {k}: page {p}/{tp} ({n} items)"))
                raw.replace(kind, fetched[kind])

        docs = [to_doc(site, kind, item) for kind in KINDS for item in fetched[kind]]
        await self._fill_thin(site, docs, raw, fetch=render and not offline)
        stale = {k for k, d in self.store.docs.items()
                 if d["site"] == site and d["type"] not in DOC_TYPES} - {d["key"] for d in docs}
        for key in stale:
            self.store.remove(key)
        self.dirty = True
        self._apply(docs)

        st, now = self.store.site_state(site), time.time()
        for kind in KINDS:
            st[f"{kind}_newest"] = max((i.get("modified") or "" for i in fetched[kind]), default="")
        st.update(built_at=now, last_probe=now, last_reconcile=now, last_change=now, last_error=None)
        raw.save()
        self.log(f"[{site}] indexed {sum(1 for d in docs if d['text'].strip())} documents")

    # ---- incremental update -----------------------------------------------------------------

    async def update_site(self, site: str, render: bool = True) -> int:
        """Probe for edits (2 tiny requests); fetch only what changed."""
        base, st = config.SITES[site]["base"], self.store.site_state(site)
        raw, changed = None, 0
        for kind in KINDS:
            newest = await newest_modified(self.client, base, kind)
            known = st.get(f"{kind}_newest") or ""
            if not newest or newest <= known:
                continue
            raw = raw or RawStore(site)
            items = await fetch_all(self.client, base, kind,
                                    modified_after=_minus_one_second(known) if known else None)
            raw.upsert(kind, items)
            docs = [to_doc(site, kind, i) for i in items]
            await self._fill_thin(site, docs, raw, fetch=render)
            n = self._apply(docs)
            changed += n
            st[f"{kind}_newest"] = max([newest] + [i.get("modified") or "" for i in items])
            self.log(f"[{site}] {n} {kind} changed since {known or 'never'}")
        st["last_probe"] = time.time()
        if changed:
            st["last_change"] = time.time()
        if raw:
            raw.save()
        return changed

    async def reconcile_site(self, site: str) -> int:
        """Find pages/posts that were deleted or unpublished (they never show up as 'modified')."""
        base, raw, removed = config.SITES[site]["base"], RawStore(site), 0
        for kind in KINDS:
            live_ids = {str(i["id"]) for i in await fetch_all(self.client, base, kind, fields="id")}
            doc_type = "post" if kind == "posts" else "page"
            for key in self.store.keys_for(site, doc_type):
                item_id = key.rsplit(":", 1)[1]
                if item_id not in live_ids:
                    self.store.remove(key)
                    self.dirty = True
                    raw.remove(kind, item_id)
                    removed += 1
        self.store.site_state(site)["last_reconcile"] = time.time()
        raw.save()
        if removed:
            self.log(f"[{site}] removed {removed} deleted or unpublished items")
        return removed

    # ---- planning documents -----------------------------------------------------------------

    async def sync_documents(self, include_handbook: bool = True) -> int:
        changed, removed = await DocumentSync(self.client, self.log).sync(include_handbook)
        fresh = {d["key"]: d for d in DocumentSync(self.client).docs()}
        for key in [k for k, d in self.store.docs.items() if d["type"] in DOC_TYPES and k not in fresh]:
            self.store.remove(key)
        n = self._apply(list(fresh.values())) + removed
        self.store.state.setdefault("documents", {})["checked"] = time.time()
        self.log(f"[documents] {changed} new or changed, {removed} removed, {len(fresh)} indexed")
        return n

    def documents_due(self) -> bool:
        checked = self.store.state.get("documents", {}).get("checked", 0)
        return time.time() - checked > config.RECONCILE_DAYS * 86400

    # ---- orchestration ----------------------------------------------------------------------

    def built_sites(self) -> list[str]:
        return [s for s in config.SITES if self.store.site_state(s).get("built_at")]

    def due(self) -> bool:
        ttl = config.SYNC_TTL_MINUTES * 60
        return any(time.time() - self.store.site_state(s).get("last_probe", 0) > ttl for s in self.built_sites())

    async def sync_all(self, reconcile: bool | None = None, sites: list[str] | None = None) -> dict:
        """Update every built site in parallel (each host still gets its own polite spacing)."""
        async def one(site):
            st = self.store.site_state(site)
            try:
                changes = await self.update_site(site)
                rec_due = time.time() - st.get("last_reconcile", 0) > config.RECONCILE_DAYS * 86400
                if reconcile or (reconcile is None and rec_due):
                    changes += await self.reconcile_site(site)
                st["last_error"] = None
                return changes
            except (httpx.HTTPError, Blocked, ValueError) as e:
                st["last_error"] = f"{type(e).__name__}: {e}"[:300]
                st["last_probe"] = time.time()  # don't hammer a failing site on every question
                self.log(f"[{site}] sync failed: {st['last_error']}")
                return 0

        sites = [s for s in self.built_sites() if not sites or s in sites]
        results = dict(zip(sites, await asyncio.gather(*(one(s) for s in sites))))
        if reconcile or (reconcile is None and self.documents_due()):
            try:
                results["documents"] = await self.sync_documents()
            except (httpx.HTTPError, Blocked, OSError) as e:
                self.log(f"[documents] sync failed: {type(e).__name__}: {e}")
        await self.save()
        if any(results.values()) and self.on_change:
            await self.on_change()
        return results

    async def save(self):
        """Write state always; write the (large) docs file only if documents changed."""
        docs = dict(self.store.docs) if self.dirty else None
        state = json.loads(json.dumps(self.store.state))
        self.dirty = False

        def write():
            if docs is not None:
                write_atomic(self.store.docs_path, docs)
            write_atomic(self.store.state_path, state)
        await asyncio.to_thread(write)

    def maybe_sync(self) -> bool:
        """Called on each question: start a background sync if one is due and none is running.
        The current question is answered from the existing index (stale-while-revalidate)."""
        if (self._task and not self._task.done()) or not self.due():
            return False
        self._task = asyncio.create_task(self.sync_all())
        return True

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def remove_url(self, url: str) -> bool:
        """A live read found this page gone (404); drop it until the next reconcile confirms."""
        removed = self.store.remove_url(url)
        self.dirty = self.dirty or removed
        return removed

    def status(self) -> dict:
        per_site = self.store.stats()
        out = {}
        for site, meta in config.SITES.items():
            st = self.store.site_state(site)
            fmt = lambda t: datetime.fromtimestamp(t).isoformat(timespec="seconds") if t else None
            out[site] = {
                "name": meta["name"], **per_site.get(site, {"page": 0, "post": 0}),
                "built": fmt(st.get("built_at")), "last_check": fmt(st.get("last_probe")),
                "last_change": fmt(st.get("last_change")), "last_reconcile": fmt(st.get("last_reconcile")),
                "newest_page_edit": st.get("pages_newest"), "newest_post_edit": st.get("posts_newest"),
                "error": st.get("last_error"),
            }
        return out


async def _cli(args):
    store = Store()
    syncer = Syncer(store, log=lambda m: print(m, flush=True))
    sites = args.site or list(config.SITES)
    unknown = [s for s in sites if s not in config.SITES]
    if unknown:
        raise SystemExit(f"unknown site(s): {unknown}. Choose from {list(config.SITES)}")
    started = time.time()
    try:
        if args.cmd == "build":
            async def build(site):
                try:
                    await syncer.build_site(site, render=not args.no_render, offline=args.offline)
                except (httpx.HTTPError, Blocked, ValueError) as e:
                    print(f"[{site}] build failed: {type(e).__name__}: {e}", flush=True)
            await asyncio.gather(*(build(s) for s in sites))
            await syncer.save()
        elif args.cmd == "documents":
            await syncer.sync_documents(include_handbook=not args.no_render)
            await syncer.save()
        elif args.cmd in ("update", "reconcile"):
            for site in sites:
                if site not in syncer.built_sites():
                    print(f"[{site}] not built yet; run `python -m app.sync build --site {site}`")
            changes = await syncer.sync_all(reconcile=args.cmd == "reconcile", sites=sites)
            print("changes per site:", changes)
        if syncer._client:
            print(f"done in {time.time() - started:.0f}s, {syncer.client.requests} requests")
        print(json.dumps(syncer.status(), indent=1))
    finally:
        if syncer._client:
            await syncer._client.aclose()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "update", "reconcile", "documents", "status"])
    ap.add_argument("--site", nargs="*", help=f"subset of: {' '.join(config.SITES)}")
    ap.add_argument("--offline", action="store_true", help="build: use saved raw data, no network")
    ap.add_argument("--no-render", action="store_true", help="build: skip reading thin pages' HTML")
    asyncio.run(_cli(ap.parse_args()))


if __name__ == "__main__":
    main()
