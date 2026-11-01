"""Planning documents: department PDFs (handbooks, degree plans, flowcharts, checklists), the
CS handbook website, and a short list of campus office pages. See docs/ARCHITECTURE.md, "Planning
documents" and "Campus pages"."""

import asyncio
import hashlib
import html as html_lib
import json
import re
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from . import config
from .extract import EXTRACTOR_VERSION, join_pages, pdf_pages, rendered_page
from .live import allowed_url
from .store import doc_key, write_atomic
from .wp import Blocked, PoliteClient

STATE_PATH = config.RAW_DIR / "documents.json"
PDF_DIR = config.RAW_DIR / "documents"  # original PDF files, so a better extractor can re-read them offline

INCLUDE = re.compile(r"handbook|plan|flow ?chart|checklist|requirement|course list|elective|degree|emphas|"
                     r"ready|curricul|worksheet|articulation|general education|guideline", re.I)
EXCLUDE = re.compile(r"lesson|\bmaps?\b|seminar|exam|midterm|solution|sample|\bforms?\b|bios|travel|defense|"
                     r"late re|format|tracker|study plan|postdoc|thesis|parking|floorplan|audit|agenda|minutes|"
                     r"\brpt\b|fundrais|request|quals?\b|study guide|presentation", re.I)
SKIP_URLS = {  # superseded files still linked from old pages
    "https://www.cs.utah.edu/wp-content/uploads/2022/08/DS-1400_Ready.pdf",
    "https://www.cs.utah.edu/wp-content/uploads/2022/08/DS-1420_Ready.pdf",
    "https://www.cs.utah.edu/wp-content/uploads/2022/08/DS-4yearplan.pdf",
}
MIN_YEAR = date.today().year - 5

HANDBOOK_ROOT = "https://handbook.cs.utah.edu/"
HANDBOOK_PROGRAMS = {"CS": "Computer Science", "DS": "Data Science", "BSSD": "Software Development"}

# Pages from campus offices that the college sites only link to. A title of None uses the page's own.
CAMPUS = "campus"
_BURSAR_PDFS = "https://fbs.admin.utah.edu/download/income/"
CAMPUS_PAGES = {
    "https://financialaid.utah.edu/wue/index.php": None,
    "https://bursar.utah.edu/undergraduate-tuition/": None,
    _BURSAR_PDFS + "FreshSophRes/FreshSophTuitionFeeRes.pdf": "Undergraduate Tuition and Fees: Freshman and Sophomore, Resident (Bursar)",
    _BURSAR_PDFS + "FreshSophNRes/FreshSophTuitionFeeNRes.pdf": "Undergraduate Tuition and Fees: Freshman and Sophomore, Non-Resident (Bursar)",
    _BURSAR_PDFS + "JrSrRes/JrSrTuitionFeeRes.pdf": "Undergraduate Tuition and Fees: Junior and Senior, Resident (Bursar)",
    _BURSAR_PDFS + "JrSrNRes/JrSrTuitionFeeNRes.pdf": "Undergraduate Tuition and Fees: Junior and Senior, Non-Resident (Bursar)",
    "https://firstgen.utah.edu/": None,
    "https://robotics.coe.utah.edu/academics/undergraduate/minor/": None,
}

HREF_RE = re.compile(r'href=["\']([^"\']+?\.pdf)(?:[?#][^"\']*)?["\']', re.I)
SHORTCODE_URL_RE = re.compile(r'url:([^"|\]\s]+?\.pdf)', re.I)


def _name(url: str) -> str:
    return re.sub(r"[-_.\s]+", " ", unquote(PurePosixPath(urlparse(url).path).stem)).strip()


def _year(url: str) -> int:
    name = _name(url)
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", name)]
    years += [2000 + int(b) for a, b in re.findall(r"\b(\d{2}) (\d{2})\b", name) if int(b) == int(a) + 1]
    years += [2000 + int(y) for y in re.findall(r"\bCY ?(\d{2})\b", name, re.I)]  # catalog year: "CY 26"
    upload = re.search(r"/uploads/(?:sites/\d+/)?(20\d{2})/", url)
    return max(years) if years else int(upload.group(1)) if upload else 0


def _uploaded(url: str) -> str:
    m = re.search(r"/uploads/(?:sites/\d+/)?(20\d{2})/(\d{2})/", url)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def _family(site: str, url: str) -> str:
    """Versions of one document share a family key: "2025-2026-Civil-Flowchart_ADA" and
    "2026-2027-Civil-Flowchart" both become "civil flowchart"."""
    n = _name(url).lower()
    n = re.sub(r"\bcy ?\d{2}\b", "cy", n)
    n = re.sub(r"\b20\d{2}\b|\b\d{2} \d{2}\b(?! ?year)", " ", n)
    n = re.sub(r"\b\d{1,2}\b(?! ?year)", " ", n)
    n = re.sub(r"\b(updated?|final|ada|bg|wp|copy|docx|v\d+|jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)\b", " ", n)
    n = re.sub(r"\b(tech(nical)?|te)( ele(ctives?)?)?\b|\bele\b", " ", n)
    n = re.sub(r"\btrad(tional|itional)?\b", "traditional", re.sub(r"\bengr\b", "engineering", n))
    return f"{site}:{' '.join(n.split())}"


ABBREVIATIONS = {"ug": "Undergraduate", "grad": "Graduate", "reqs": "Requirements", "trad": "Traditional",
                 "engr": "Engineering", "yr": "year"}


def pretty_title(url: str) -> str:
    name = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", _name(url))
    name = re.sub(r"\b(ADA|bg|wp|docx)\b", "", name, flags=re.I)
    return " ".join(ABBREVIATIONS.get(w.lower(), w) for w in name.split())


def doc_title(url: str, embedded: str, info: dict) -> str:
    """A readable title naming the department: "Undergraduate Handbook 2026 (Biomedical Engineering)".
    The PDF's embedded title is used only when it says what the document is."""
    useful = 8 <= len(embedded) <= 120 and INCLUDE.search(embedded) and not embedded.lower().startswith(
        ("microsoft", "untitled"))
    title = " ".join((embedded if useful else pretty_title(url)).split())
    if title.isupper():
        title = title.title()
    if info.get("program"):
        return f"{HANDBOOK_PROGRAMS[info['program']]} Handbook {info['year']}: {title}"
    dept = config.SITES.get(info.get("site"), {}).get("name", "")
    words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", dept)} - {"engineering", "school", "college"}
    if dept and info.get("site") != "price" and not any(w in title.lower() for w in words):
        title = f"{title} ({dept})"
    return title


def discover_pdfs() -> dict[str, dict]:
    """PDF links on the published pages saved by the site sync (data/raw/<site>/pages.json).
    Links appear as plain hrefs and as URL-encoded WPBakery button links ("url:%2F...pdf")."""
    found: dict[str, dict] = {}
    for site, meta in config.SITES.items():
        try:
            pages = json.loads((config.RAW_DIR / site / "pages.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        for page in pages:
            body = html_lib.unescape(((page.get("content") or {}).get("rendered") or ""))
            links = HREF_RE.findall(body) + [unquote(u) for u in SHORTCODE_URL_RE.findall(body)]
            for link in links:
                url = urljoin(meta["base"] + "/", link.strip())
                if url.startswith("http://"):
                    url = "https://" + url[7:]
                entry = found.setdefault(url, {"site": site, "linked_from": []})
                title = html_lib.unescape(((page.get("title") or {}).get("rendered") or "")).strip()
                if [title, page.get("link")] not in entry["linked_from"]:
                    entry["linked_from"].append([title, page.get("link")])
    return found


def select_pdfs(found: dict[str, dict]) -> dict[str, dict]:
    """Planning documents only, newest version of each, nothing older than MIN_YEAR."""
    newest: dict[str, tuple] = {}
    for url, info in found.items():
        name = _name(url)
        planning_page = any(INCLUDE.search(t or "") and not EXCLUDE.search(t or "") for t, _ in info["linked_from"])
        if url in SKIP_URLS or not allowed_url(url) or EXCLUDE.search(name) or not (
                INCLUDE.search(name) or planning_page):
            continue
        year = _year(url)
        if year < MIN_YEAR:
            continue
        fam = _family(info["site"], url)
        rank = (year, _uploaded(url))
        if fam not in newest or rank > newest[fam][0]:
            newest[fam] = (rank, url)
    return {url: {**found[url], "year": rank[0]} for rank, url in newest.values()}


async def discover_handbook(client: PoliteClient) -> dict[str, dict]:
    """The newest year of each program's handbook on handbook.cs.utah.edu, from its site maps."""
    root = await client.get(HANDBOOK_ROOT)
    years: dict[str, str] = {}
    for year, prog in re.findall(r'href="/?(\d{4}-\d{4})/([A-Z]+)/?"', root.text):
        if prog in HANDBOOK_PROGRAMS and year > years.get(prog, ""):
            years[prog] = year
    pages: dict[str, dict] = {}
    for prog, year in years.items():
        prefix = f"{HANDBOOK_ROOT}{year}/{prog}/"
        sitemap = await client.get(prefix + "site-map.php")
        for href in re.findall(r'href="([^"#]+)"', sitemap.text):
            url = urljoin(prefix, href)
            if url.startswith(prefix) and (url.endswith(".php") or url.lower().endswith(".pdf")):
                pages.setdefault(url, {"site": "cs", "program": prog, "year": year,
                                       "linked_from": [[f"{HANDBOOK_PROGRAMS[prog]} Handbook {year}", prefix]]})
    return pages


def campus_pages() -> dict[str, dict]:
    return {url: {"site": CAMPUS, "title": title, "linked_from": []} for url, title in CAMPUS_PAGES.items()}


def _campus_title(title: str) -> str:
    return re.sub(r"\s*[-|–]\s*The University of Utah\s*$", "", title.replace("\xad", ""))


def _http_date(value: str | None) -> str:
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return ""


def _key(url: str, kind: str, site: str) -> str:
    return doc_key(site, kind, hashlib.sha1(url.encode()).hexdigest()[:12])


def to_doc(url: str, entry: dict) -> dict:
    kind = entry["kind"]
    context = "; ".join(t for t, _ in entry.get("linked_from", []) if t)
    header = f"Linked from: {context}\n\n" if context else ""
    if entry["site"] == CAMPUS:  # campus servers send no Last-Modified for HTML, or the time of the request
        modified = entry.get("last_modified", "") if kind == "pdf" else ""
    else:
        modified = entry.get("last_modified") or entry.get("fetched", "")
    return {
        "key": _key(url, kind, entry["site"]),
        "site": entry["site"],
        "id": hashlib.sha1(url.encode()).hexdigest()[:12],
        "type": kind,
        "url": url,
        "title": entry["title"],
        "date": "",
        "modified": modified,
        "context": context,
        "text": header + entry["text"],
    }


class DocumentSync:
    """Downloads selected documents and keeps data/raw/documents.json current. A refresh asks the
    server "has it changed?" (ETag / Last-Modified), so unchanged files cost one tiny request."""

    def __init__(self, client: PoliteClient, log=None):
        self.client, self.log = client, log or (lambda m: None)
        try:
            self.state: dict = json.loads(STATE_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.state = {}

    def _reextract(self, url: str, old: dict) -> bool:
        path = PDF_DIR / f"{hashlib.sha1(url.encode()).hexdigest()[:12]}.pdf"
        if old.get("kind") != "pdf" or old.get("extractor") == EXTRACTOR_VERSION or not path.exists():
            return False
        meta_title, pages = pdf_pages(path.read_bytes())
        info = {**old, "program": old.get("program"), "year": old.get("year")}
        old.update(text=join_pages(pages), pages=len(pages), extractor=EXTRACTOR_VERSION,
                   title=old["title"] if old.get("site") == CAMPUS else doc_title(url, meta_title, info))
        return True

    async def _fetch(self, url: str, info: dict) -> bool:
        old = self.state.get(url, {})
        if self._reextract(url, old):
            return True
        headers = {}
        if old.get("kind") != "pdf" or old.get("extractor") == EXTRACTOR_VERSION:  # else: saved text is stale
            if old.get("etag"):
                headers["If-None-Match"] = old["etag"]
            if old.get("last_modified_raw"):
                headers["If-Modified-Since"] = old["last_modified_raw"]
        resp = await self.client.get(url, headers=headers or None)
        if resp.status_code == 304:
            renamed = bool(info.get("title")) and old.get("title") != info["title"]  # a title edited in CAMPUS_PAGES
            old.update(linked_from=info["linked_from"], checked=time.time(), **({"title": info["title"]} if renamed else {}))
            return renamed
        ctype = resp.headers.get("content-type", "")
        if url.lower().endswith(".pdf") or "pdf" in ctype:
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            (PDF_DIR / f"{hashlib.sha1(url.encode()).hexdigest()[:12]}.pdf").write_bytes(resp.content)
            meta_title, pages = pdf_pages(resp.content)
            text, kind = join_pages(pages), "pdf"
            title = info.get("title") or doc_title(url, meta_title, info)
        elif info["site"] == CAMPUS:
            page = rendered_page(resp.text, url)
            text, kind, pages = page["text"], "page", None
            title = info["title"] or _campus_title(page["title"])
        else:
            page = rendered_page(resp.text, url)
            text, kind, pages = page["text"], "handbook", None
            info["pdf_links"] = [l["url"] for l in page["links"] if l["url"].lower().endswith(".pdf")]
            title = f"{HANDBOOK_PROGRAMS.get(info.get('program'), '')} Handbook {info.get('year', '')}: {page['title']}"
        self.state[url] = {
            "site": info["site"], "kind": kind, "title": " ".join(title.split()), "text": text,
            "pages": len(pages) if pages else None, "linked_from": info["linked_from"],
            "etag": resp.headers.get("etag"), "last_modified_raw": resp.headers.get("last-modified"),
            "last_modified": _http_date(resp.headers.get("last-modified")),
            "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"), "checked": time.time(),
            "extractor": EXTRACTOR_VERSION, "pdf_links": info.get("pdf_links", []),
            "program": info.get("program"), "year": info.get("year"),
        }
        return True

    async def sync(self, include_handbook: bool = True) -> tuple[int, int]:
        """Returns (changed, removed)."""
        wanted = {**select_pdfs(discover_pdfs()), **campus_pages()}
        keep = set()
        if include_handbook:
            try:
                wanted.update(await discover_handbook(self.client))
            except (httpx.HTTPError, Blocked) as e:
                self.log(f"[documents] handbook site unreachable ({type(e).__name__}); keeping the saved copy")
                keep = {u for u in self.state if u.startswith(HANDBOOK_ROOT)}
        self.log(f"[documents] {len(wanted)} documents selected; checking for changes")
        by_host: dict[str, list] = {}
        for url, info in sorted(wanted.items()):
            by_host.setdefault(urlparse(url).hostname, []).append((url, info))

        async def host_worker(items):
            changed = 0
            for url, info in items:
                try:
                    changed += await self._fetch(url, info)
                except Exception as e:  # one bad file (HTTP error, unreadable PDF) shouldn't stop the rest
                    self.log(f"[documents]   skip {url}: {type(e).__name__}")
                    if url in self.state:
                        keep.add(url)
            self.log(f"[documents]   {urlparse(items[0][0]).hostname}: {len(items)} checked, {changed} updated")
            return changed

        changed = sum(await asyncio.gather(*(host_worker(items) for items in by_host.values())))
        linked = self._handbook_pdfs(wanted)
        if linked:
            changed += await host_worker(sorted(linked.items()))
            wanted.update(linked)
        removed = [u for u in self.state if u not in wanted and u not in keep]
        for url in removed:
            del self.state[url]
            (PDF_DIR / f"{hashlib.sha1(url.encode()).hexdigest()[:12]}.pdf").unlink(missing_ok=True)
        write_atomic(STATE_PATH, self.state)
        return changed, len(removed)

    def _handbook_pdfs(self, wanted: dict) -> dict:
        """PDFs (degree plans, course lists) linked from the handbook pages just read, same year and program."""
        out = {}
        for url, entry in self.state.items():
            info = wanted.get(url)
            if not info or not info.get("program") or entry.get("kind") != "handbook":
                continue
            prefix = f"{HANDBOOK_ROOT}{info['year']}/{info['program']}/"
            for link in entry.get("pdf_links", []):
                if link.startswith(prefix) and link not in wanted:
                    out[link] = {"site": "cs", "program": info["program"], "year": info["year"],
                                 "linked_from": [[entry["title"], url]]}
        return out

    def docs(self) -> list[dict]:
        return [to_doc(url, e) for url, e in self.state.items() if e.get("text", "").strip()]
