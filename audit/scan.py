"""Read-only scan of our saved copy of the college sites for content that looks outdated (docs/SITE_AUDIT.md).

    python -m audit.scan              # stale pages, passed dates, image-only PDFs, leftover pages
    python -m audit.scan --links      # also check links to pages we don't have (10 s apart per site)

It reads data/ and never writes to it, so the assistant's answers don't change. Results go to
audit/results/<date>/scan.json, which the site-audit workflow's agents and the report start from.
Everything it finds is a candidate: the workflow checks each one against the live page.
"""

import argparse
import asyncio
import html as html_lib
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

from app import config
from app.extract import split_pages

OUT_DIR = Path(__file__).parent / "results"
STALE_YEARS = 3
LINK_DELAY = 10  # seconds between requests to one site, as the sites' robots.txt asks
LINKS_PER_SITE = 50  # the most-linked targets per site; the rest are counted as unchecked, not skipped silently

MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}
MONTHS.update({m[:3]: n for m, n in list(MONTHS.items())} | {"sept": 9})
DATE_RE = re.compile(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) +
                     r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I)
UPCOMING_RE = re.compile(r"deadline|due\b|apply|application|register|registration|closes|opens|last day|"
                         r"submit|upcoming|join us|will be held|save the date|rsvp|priority date", re.I)
PAST_RE = re.compile(r"\b(was|were|took place|held on|recap|congratulat|winners?|archive|previous)\b", re.I)
LEFTOVER_RE = re.compile(r"(-dnu|-old|-copy|copy-of|-test|test-page|-draft|-backup|-2)(/|$)", re.I)
HREF_RE = re.compile(r'href=["\']([^"\'#]+)', re.I)
SHORTCODE_RE = re.compile(r'url:([^"|\]\s]+)', re.I)


def norm_url(url: str) -> str:
    p = urlparse(url.strip())
    host = (p.netloc or "").lower()
    path = p.path.rstrip("/") or "/"
    return f"https://{host}{path}"


def load_docs() -> dict[str, dict]:
    return json.loads(config.DOCS_PATH.read_text())


def page_links() -> dict[str, list[tuple[str, str]]]:
    """target url -> [(page title, page url)] for every link on the saved pages (data/raw/<site>/pages.json)."""
    links: dict[str, list] = defaultdict(list)
    for site, meta in config.SITES.items():
        try:
            pages = json.loads((config.RAW_DIR / site / "pages.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        for page in pages:
            body = html_lib.unescape((page.get("content") or {}).get("rendered") or "")
            title = html_lib.unescape((page.get("title") or {}).get("rendered") or "").strip()
            hrefs = HREF_RE.findall(body) + [unquote(u) for u in SHORTCODE_RE.findall(body)]
            for href in hrefs:
                if href.startswith(("mailto:", "tel:", "javascript:")):
                    continue
                target = norm_url(urljoin(meta["base"] + "/", href))
                if (title, page.get("link")) not in links[target]:
                    links[target].append((title, page.get("link")))
    return links


def stale_pages(docs: dict, inbound: dict) -> list[dict]:
    cutoff = (date.today() - timedelta(days=365 * STALE_YEARS)).isoformat()
    recent = (date.today() - timedelta(days=365)).isoformat()
    recent_pages = {norm_url(d["url"]) for d in docs.values() if (d.get("modified") or "") >= recent}
    out = []
    for d in docs.values():
        if d["type"] != "page" or not d.get("modified") or d["modified"] >= cutoff:
            continue
        from_recent = [u for _, u in inbound.get(norm_url(d["url"]), []) if u and norm_url(u) in recent_pages]
        out.append({"url": d["url"], "title": d["title"], "site": d["site"], "modified": d["modified"][:10],
                    "linked_from_recent_pages": len(from_recent), "example_linking_page": from_recent[:1]})
    return sorted(out, key=lambda r: (-r["linked_from_recent_pages"], r["modified"]))


def passed_dates(docs: dict) -> list[dict]:
    """Evergreen pages that put a date that has passed next to words like "deadline" or "register"."""
    today, out = date.today(), []
    for d in docs.values():
        if d["type"] != "page":
            continue
        hits = []
        for m in DATE_RE.finditer(d["text"]):
            try:
                when = date(int(m.group(3)), MONTHS[m.group(1).lower().rstrip(".")], int(m.group(2)))
            except ValueError:
                continue
            if when >= today - timedelta(days=14):
                continue
            context = d["text"][max(0, m.start() - 120):m.end() + 80]
            if UPCOMING_RE.search(context) and not PAST_RE.search(context):
                hits.append({"date": when.isoformat(), "context": re.sub(r"\s+", " ", context).strip()})
        if hits:
            out.append({"url": d["url"], "title": d["title"], "site": d["site"], "modified": (d.get("modified") or "")[:10],
                        "passed_dates": len(hits), "newest_passed": max(h["date"] for h in hits), "examples": hits[:3]})
    return sorted(out, key=lambda r: (r["modified"], r["passed_dates"]), reverse=True)


def image_only_pdfs() -> list[dict]:
    """PDF pages with no readable text: screen readers and search can't read them either."""
    try:
        state = json.loads((config.RAW_DIR / "documents.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    out = []
    for url, s in state.items():
        if s.get("kind") != "pdf" or not s.get("text"):
            continue
        pages = split_pages(s["text"])
        total = s.get("pages") if isinstance(s.get("pages"), int) else (max(pages) if pages else 0)
        empty = [n for n in range(1, total + 1) if len((pages.get(n) or "").strip()) < 40]
        if empty:
            out.append({"url": url, "title": s.get("title"), "pages": total, "pages_without_text": empty,
                        "linked_from": (s.get("linked_from") or [])[:2]})
    return sorted(out, key=lambda r: -len(r["pages_without_text"]) / max(r["pages"], 1))


def leftover_pages(docs: dict) -> list[dict]:
    return [{"url": d["url"], "title": d["title"], "modified": (d.get("modified") or "")[:10]}
            for d in docs.values() if d["type"] == "page" and LEFTOVER_RE.search(urlparse(d["url"]).path)]


async def dead_links(docs: dict, links: dict, per_site: int) -> tuple[list[dict], int, int]:
    """Links on recently updated pages to utah.edu pages we don't have a copy of, checked live. Checks the
    `per_site` most-linked targets per site and returns how many it left unchecked."""
    recent = (date.today() - timedelta(days=730)).isoformat()
    recent_pages = {norm_url(d["url"]) for d in docs.values() if (d.get("modified") or "") >= recent}
    known = {norm_url(d["url"]) for d in docs.values()}
    by_host: dict[str, list[str]] = defaultdict(list)
    for target, sources in links.items():
        host = urlparse(target).netloc
        if (target in known or not host.endswith("utah.edu")
                or not any(u and norm_url(u) in recent_pages for _, u in sources)):
            continue
        by_host[host].append(target)
    unchecked = 0
    for host, targets in by_host.items():
        targets.sort(key=lambda t: -len(links[t]))
        unchecked += max(0, len(targets) - per_site)
        del targets[per_site:]
    total = sum(len(v) for v in by_host.values())
    print(f"Checking {total} links on {len(by_host)} sites, {LINK_DELAY}s apart per site "
          f"(about {max(len(v) for v in by_host.values()) * LINK_DELAY / 60:.0f} minutes); {unchecked} less-linked "
          f"targets left unchecked" if total else "No links to check.")
    out: list[dict] = []

    async def check_host(client, host, targets):
        for i, url in enumerate(targets):
            if i:
                await asyncio.sleep(LINK_DELAY)
            try:
                r = await client.get(url)
                status = r.status_code
            except httpx.HTTPError as e:
                status = type(e).__name__
            if status != 200:
                out.append({"url": url, "status": status, "linked_from": links[url][:3]})

    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": config.USER_AGENT}) as client:
        await asyncio.gather(*(check_host(client, h, t) for h, t in by_host.items()))
    return sorted(out, key=lambda r: r["url"]), unchecked, total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--links", action="store_true", help="also check links live")
    ap.add_argument("--per-site", type=int, default=LINKS_PER_SITE, help="most-linked targets to check per site")
    args = ap.parse_args()
    docs = load_docs()
    links = page_links()
    result = {
        "date": date.today().isoformat(),
        "content_as_of": datetime.fromtimestamp(config.DOCS_PATH.stat().st_mtime).strftime("%Y-%m-%d"),
        "stale_pages": stale_pages(docs, links),
        "passed_dates": passed_dates(docs),
        "image_only_pdfs": image_only_pdfs(),
        "leftover_pages": leftover_pages(docs),
    }
    if args.links:
        result["dead_links"], result["links_unchecked"], result["links_checked"] = asyncio.run(
            dead_links(docs, links, args.per_site))
    out = OUT_DIR / result["date"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "scan.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    for key, rows in result.items():
        if isinstance(rows, list):
            print(f"  {key:18} {len(rows)}")
    print(f"Saved to {(out / 'scan.json').relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
