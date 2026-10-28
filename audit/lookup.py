"""Read-only lookups in our saved copy of the college sites, for the site audit (docs/SITE_AUDIT.md).

    python -m audit.lookup search "scholarship deadline"      # top matches: title, URL, last updated, excerpt
    python -m audit.lookup page https://www.price.utah.edu/scholarships   # the full saved text of one page or PDF
    python -m audit.lookup events --days 120                  # the college events calendar, live

Nothing here writes to data/ or calls the Claude API.
"""

import argparse
import asyncio

from app.events import search_events, today
from app.index import SearchIndex
from app.store import Store
from audit.scan import norm_url


def search(query: str, k: int):
    docs = Store().docs
    seen = []
    for h in SearchIndex(docs).search(query, k=k * 3):
        if h["url"] in seen:
            continue
        seen.append(h["url"])
        updated = (h.get("date") if h.get("type") == "post" else h.get("updated")) or ""
        print(f"- {h['title']} | {h['url']} | {h.get('type')} | updated {updated[:10]}\n  {h.get('text', '')[:300]}\n")
        if len(seen) >= k:
            break


def page(url: str):
    want = norm_url(url)
    for d in Store().docs.values():
        if norm_url(d["url"]) == want:
            print(f"{d['title']} | {d['url']} | {d['type']} | updated {(d.get('modified') or '')[:10]}\n")
            print(d["text"])
            return
    print("Not in the saved copy. Read it live instead.")


def events(days: int):
    for e in asyncio.run(search_events("", today(), days, limit=200)):
        print(f"- {e.get('start', '')[:16]} | {e.get('title')} | {e.get('location') or ''} | {e.get('url') or ''}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("-k", type=int, default=8)
    p = sub.add_parser("page"); p.add_argument("url")
    e = sub.add_parser("events"); e.add_argument("--days", type=int, default=90)
    a = ap.parse_args()
    {"search": lambda: search(a.query, a.k), "page": lambda: page(a.url), "events": lambda: events(a.days)}[a.cmd]()


if __name__ == "__main__":
    main()
