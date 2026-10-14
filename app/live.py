"""Live, on-demand scraping used by the chatbot while it answers a question."""

import asyncio
import html
import ipaddress
import time
from urllib.parse import urljoin, urlparse

import httpx

from . import config
from .extract import pdf_pages, rendered_page

MAX_BYTES = 3_000_000
MAX_PDF_BYTES = 12_000_000  # department handbooks run 1–5 MB
MAX_TEXT = 8_000  # ~2k tokens per page read keeps each tool round cheap

_http = httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT}, timeout=20, follow_redirects=False)
_cache: dict[str, tuple[float, dict]] = {}
_host_locks: dict[str, asyncio.Lock] = {}
_host_last: dict[str, float] = {}


class FetchError(Exception):
    pass


def allowed_url(url: str) -> bool:
    """Only public University of Utah web pages (price.utah.edu, department sites, etc.)."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not host or p.port not in (None, 80, 443):
        return False
    try:
        ipaddress.ip_address(host)
        return False  # no raw IPs
    except ValueError:
        pass
    return host == "utah.edu" or host.endswith(".utah.edu")


async def _resolves_public(host: str) -> bool:
    """Reject utah.edu names that point at private or internal addresses (SSRF via DNS)."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443)
    except OSError:
        return False
    for *_, sockaddr in infos:
        try:
            addr = ipaddress.ip_address(str(sockaddr[0]).split("%")[0])
        except ValueError:
            return False
        if not addr.is_global:
            return False
    return bool(infos)


async def _polite_get(url: str) -> httpx.Response:
    host = urlparse(url).hostname
    if not await _resolves_public(host):
        raise FetchError(f"{host} doesn't resolve to a public address")
    lock = _host_locks.setdefault(host, asyncio.Lock())
    async with lock:
        wait = _host_last.get(host, 0) + config.LIVE_FETCH_INTERVAL - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with _http.stream("GET", url) as resp:
                limit = MAX_PDF_BYTES if "pdf" in resp.headers.get("content-type", "") else MAX_BYTES
                body = b""
                async for part in resp.aiter_bytes():
                    body += part
                    if len(body) > limit:
                        raise FetchError("file is too large")
                resp._content = body
                return resp
        finally:
            _host_last[host] = time.monotonic()


async def fetch_page(url: str) -> dict:
    """Fetch and extract a page, following redirects only within allowed hosts."""
    url = url.strip().split("#")[0]
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if not allowed_url(url):
        raise FetchError("only utah.edu pages can be read")

    hit = _cache.get(url)
    if hit and time.time() - hit[0] < config.LIVE_CACHE_TTL:
        return hit[1]

    current = url
    for _ in range(5):
        resp = await _polite_get(current)
        if resp.is_redirect:
            nxt = urljoin(current, resp.headers.get("location", ""))
            if not allowed_url(nxt):
                raise FetchError(f"redirects off utah.edu to {urlparse(nxt).hostname}")
            current = nxt
            continue
        break
    else:
        raise FetchError("too many redirects")

    if resp.status_code >= 400:
        raise FetchError(f"HTTP {resp.status_code}")
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype:
        try:
            title, pages = await asyncio.to_thread(pdf_pages, resp.content)
        except Exception:
            raise FetchError("the PDF couldn't be read")
        page = {"title": title or current.rsplit("/", 1)[-1], "url": current, "text": "", "links": [],
                "pages": {i: t for i, t in enumerate(pages, 1) if t.strip()}}
        _cache[url] = (time.time(), page)
        return page
    if "html" not in ctype:
        raise FetchError(f"not an HTML page or PDF ({ctype.split(';')[0] or 'unknown type'})")
    text = resp.text
    if "Attention Required! | Cloudflare" in text[:3000]:
        raise FetchError("blocked by the site's firewall")

    page = rendered_page(text, current)
    page["url"] = current
    if len(page["text"]) > MAX_TEXT:
        page["text"] = page["text"][:MAX_TEXT] + "\n\n[...page truncated...]"
    _cache[url] = (time.time(), page)
    return page


async def wp_search(query: str, k: int = 8) -> list[dict]:
    """Live WordPress site search; used when the local index is missing or comes up empty."""
    resp = await _polite_get(
        httpx.URL(f"{config.SITE}/wp-json/wp/v2/search", params={"search": query, "per_page": k}).__str__())
    if resp.status_code != 200:
        return []
    return [{"title": html.unescape(r.get("title", "")), "url": r.get("url"), "type": r.get("subtype", "")}
            for r in resp.json()]
