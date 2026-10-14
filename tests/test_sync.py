"""Sync logic against a fake WordPress site (no network): build, change-only update, deletion check.

Run:  .venv/bin/python -m tests.test_sync
"""

import asyncio
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from app import config
from app.store import Store
from app.sync import Syncer
from app.wp import PoliteClient

BASE = "https://www.ece.utah.edu"


def item(id_, kind, title, modified, body):
    slug = title.lower().replace(" ", "-")
    return {"id": id_, "type": "post" if kind == "posts" else "page", "link": f"{BASE}/{slug}/",
            "title": {"rendered": title}, "content": {"rendered": body},
            "date": modified, "modified": modified}


class FakeWordPress:
    """Serves /wp-json/wp/v2/{pages,posts} with paging, orderby=modified and modified_after."""

    def __init__(self):
        long = "<p>" + "Advising appointments are available every weekday. " * 12 + "</p>"
        self.content = {
            "pages": [item(1, "pages", "Undergraduate Advising", "2026-09-01T10:00:00", long),
                      item(2, "pages", "Research Labs", "2026-09-02T10:00:00", "[vc_row][/vc_row]")],  # thin
            "posts": [item(10, "posts", "Grid Resilience Award", "2026-09-03T10:00:00", long),
                      item(11, "posts", "New Robotics Lab Opens", "2026-09-04T10:00:00", long)],
        }
        self.log = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.log.append(str(request.url))
        path, q = request.url.path, {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 10\n")
        if path == "/research-labs/":  # rendered HTML of the thin page
            return httpx.Response(200, html="<html><body><div class='post-content'><h2>Research Labs</h2>"
                                            "<p>" + "We run twelve research labs across power, devices and signals. " * 6
                                            + "</p></div></body></html>")
        kind = path.rsplit("/", 1)[-1]
        if kind not in self.content:
            return httpx.Response(404)
        items = sorted(self.content[kind], key=lambda i: i["modified"], reverse=True)
        if "modified_after" in q:
            items = [i for i in items if i["modified"] > q["modified_after"]]
        per, page = int(q.get("per_page", 10)), int(q.get("page", 1))
        chunk = items[(page - 1) * per: page * per]
        fields = q.get("_fields", "").split(",")
        chunk = [{k: v for k, v in i.items() if k in fields} for i in chunk]
        pages = max(1, -(-len(items) // per))
        # mimic the stray plugin HTML that price.utah.edu prints before its JSON
        return httpx.Response(200, text="<!-- START DIRECTORY LISTING -->" + httpx.Response(200, json=chunk).text,
                              headers={"X-WP-TotalPages": str(pages), "X-WP-Total": str(len(items))})


async def main():
    tmp = Path(tempfile.mkdtemp())
    config.RAW_DIR = tmp / "raw"
    wp = FakeWordPress()
    store = Store(tmp / "docs.json", tmp / "state.json")
    changes_seen = []

    async def on_change():
        changes_seen.append(len(store.docs))

    syncer = Syncer(store, on_change=on_change)
    syncer._client = PoliteClient(0, transport=httpx.MockTransport(wp.handler))
    config.SITES = {"ece": {"name": "ECE", "base": BASE}}

    # 1. Full build: 4 items, the thin page gets its rendered HTML text.
    await syncer.build_site("ece")
    await syncer.save()
    assert len(store.docs) == 4, store.docs.keys()
    labs = store.docs["ece:page:2"]
    assert "twelve research labs" in labs["text"], labs["text"]
    assert store.site_state("ece")["posts_newest"] == "2026-09-04T10:00:00"
    print("✓ build: 4 documents; thin page filled from its rendered HTML")

    # 2. Nothing changed: the update costs exactly 2 tiny probe requests.
    wp.log.clear()
    assert await syncer.update_site("ece") == 0
    assert len(wp.log) == 2 and all("per_page=1" in u for u in wp.log), wp.log
    print("✓ update with no edits: 2 probe requests, nothing fetched")

    # 3. One post edited and one page added: only those are fetched, via modified_after.
    wp.content["posts"][0] = item(10, "posts", "Grid Resilience Award Renewed", "2026-10-01T09:00:00",
                                  wp.content["posts"][0]["content"]["rendered"])
    wp.content["pages"].append(item(3, "pages", "Graduate Advising", "2026-10-02T09:00:00",
                                    wp.content["pages"][0]["content"]["rendered"]))
    wp.log.clear()
    assert await syncer.update_site("ece") == 2
    fetched = [u for u in wp.log if "modified_after" in u]
    assert len(fetched) == 2 and all("2026-09-0" in u for u in fetched), wp.log
    assert store.docs["ece:post:10"]["title"] == "Grid Resilience Award Renewed"
    assert "ece:page:3" in store.docs and len(store.docs) == 5
    print(f"✓ edits: {len(wp.log)} requests, only the 2 changed items fetched and merged")

    # 4. A page is deleted on the site: the weekly reconcile removes it.
    wp.content["pages"] = [p for p in wp.content["pages"] if p["id"] != 1]
    assert await syncer.update_site("ece") == 0, "deletions are invisible to modified_after"
    assert "ece:page:1" in store.docs
    assert await syncer.reconcile_site("ece") == 1
    assert "ece:page:1" not in store.docs
    print("✓ deletion: missed by the change check, caught by reconcile")

    # 5. sync_all saves, reports, and triggers a rebuild only when something changed.
    store.site_state("ece")["last_probe"] = 0
    assert syncer.due()
    results = await syncer.sync_all(reconcile=False)
    assert results == {"ece": 0} and not changes_seen
    wp.content["posts"].append(item(12, "posts", "Senior Design Day", "2026-10-05T09:00:00", "<p>Demo day</p>"))
    results = await syncer.sync_all(reconcile=False)
    assert results == {"ece": 1} and changes_seen == [5]
    reloaded = Store(tmp / "docs.json", tmp / "state.json")
    assert "ece:post:12" in reloaded.docs and not syncer.due()
    print("✓ sync_all: persists to disk and rebuilds the index only on changes")

    # 6. A live read that 404s drops the page immediately.
    assert syncer.remove_url(f"{BASE}/research-labs") and "ece:page:2" not in store.docs
    print("✓ 404 on a live read removes the page")
    await syncer._client.aclose()
    print("All sync checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
