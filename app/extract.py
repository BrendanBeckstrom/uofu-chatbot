"""Turn WordPress content (REST shortcodes or rendered pages) into clean text."""

import base64
import binascii
import html
import io
import logging
import re
from urllib.parse import unquote, urljoin

import pypdf
from bs4 import BeautifulSoup

logging.getLogger("pypdf").setLevel(logging.ERROR)

# WPBakery / Uncode store layout as shortcodes like [vc_row ...] inside the
# REST "content" field. Strip the tags but keep the text between them.
SHORTCODE_RE = re.compile(r"\[/?[a-zA-Z][\w-]*(?:\s[^\[\]]*)?/?\]")
BLANK_LINES_RE = re.compile(r"\n{3,}")
SPACES_RE = re.compile(r"[ \t ]+")

DROP_TAGS = ["script", "style", "noscript", "svg", "form", "iframe", "button", "select", "template"]
BLOCK_TAGS = {"p", "div", "section", "article", "br", "tr", "table", "ul", "ol", "dl", "blockquote", "figure"}

# Chrome around the main content on rendered price.utah.edu pages (Uncode theme).
SITE_CHROME = ["header", "nav", "footer", "#colophon", ".menu-container", ".overlay",
               ".navbar", ".site-footer", "#cookie-law-info-bar", ".screen-reader-text"]


RAW_HTML_RE = re.compile(r"\[vc_raw_html[^\]]*\]\s*([A-Za-z0-9+/=\s]+?)\s*\[/vc_raw_html\]")
LEFTOVER_B64_RE = re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}")


def _decode_raw_html(match: re.Match) -> str:
    # [vc_raw_html] blocks hold base64-encoded, URL-encoded HTML (often tables).
    try:
        return unquote(base64.b64decode("".join(match.group(1).split())).decode("utf-8", "ignore"))
    except (ValueError, binascii.Error):
        return " "


def strip_shortcodes(raw: str) -> str:
    # Shortcode attributes arrive with curly quotes (&#8221;), so unescape first.
    text = RAW_HTML_RE.sub(_decode_raw_html, html.unescape(raw))
    return LEFTOVER_B64_RE.sub(" ", SHORTCODE_RE.sub(" ", text))


def _soup_to_text(root) -> str:
    for tag in root.find_all(DROP_TAGS):
        tag.decompose()
    for level in range(1, 5):
        for h in root.find_all(f"h{level}"):
            text = h.get_text(" ", strip=True)
            h.replace_with(f"\n\n{'#' * min(level + 1, 4)} {text}\n" if text else "")
    for li in root.find_all("li"):
        li.insert_before("\n- ")
    for tag in root.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = root.get_text(" ")
    lines = [SPACES_RE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n- \n", "\n", text)
    return BLANK_LINES_RE.sub("\n\n", text).strip()


def rest_content_to_text(rendered: str) -> str:
    soup = BeautifulSoup(strip_shortcodes(rendered), "lxml")
    return _soup_to_text(soup)


def rendered_page(page_html: str, base_url: str, max_links: int = 40) -> dict:
    """Extract title, main text and in-content links from a fully rendered page."""
    soup = BeautifulSoup(page_html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else base_url
    title = re.sub(r"\s*[|–-]\s*(The )?John and Marcia Price College of Engineering.*$", "", title) or title

    main = (soup.select_one(".post-content") or soup.select_one(".main-container")
            or soup.select_one("main") or soup.select_one("#content") or soup.body or soup)
    for sel in SITE_CHROME:
        for el in main.select(sel):
            el.decompose()

    links, seen = [], set()
    for a in main.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        label = a.get_text(" ", strip=True)
        if not label or not href.startswith("http") or href in seen:
            continue
        seen.add(href)
        links.append({"text": label[:80], "url": href})
        if len(links) >= max_links:
            break

    return {"title": title, "text": _soup_to_text(main), "links": links}


def chunk_text(text: str, size: int = 1400, overlap: int = 200) -> list[str]:
    """Split on paragraph boundaries into ~size-char chunks with a small overlap."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for para in paras:
        while len(para) > size:  # very long paragraph: hard split
            head, para = para[:size], para[size - overlap:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if current and len(current) + len(para) + 2 > size:
            chunks.append(current)
            tail = current[-overlap:]
            current = tail[tail.find(" ") + 1:] + "\n\n" + para if overlap else para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


EXTRACTOR_VERSION = 3  # bump when PDF text extraction changes, so saved documents are re-read
PAGE_MARK = "[Page {n}]"
PAGE_SPLIT_RE = re.compile(r"^\[Page (\d+)\]$", re.M)
DOUBLED_RE = re.compile(r"(\S.{3,60}?)\1")  # "CourseCourse": fake-bold PDFs draw each word twice


YEAR_LABEL_RE = re.compile(r"^(\s*)((?:Freshman|Sophomore|Junior|Senior|First|Second|Third|Fourth|Fifth) [Yy]ear)\b")
CREDITS_RE = re.compile(r"\((\d{1,2})\s+credits\)")
ROW_CREDITS_RE = re.compile(r"(?:^|\s)([1-6])(?=\s|$)")


def _row_credits(line: str, skip_optional: bool) -> int:
    line, total, last = CREDITS_RE.sub("", line), 0, 0
    for m in ROW_CREDITS_RE.finditer(line):
        if not (skip_optional and "if needed" in line[last:m.start()]):
            total += int(m.group(1))
        last = m.end()
    return total


def _label_plan_years(lines: list[str]) -> list[str]:
    """Degree plans print each year's label beside the middle of its rows, so in flat text a year's first
    row sits above its label. Use the printed credit totals to find each year's real rows, then put a
    "[Freshman year (28 credits)]" heading above them. Departments differ on whether "Free Elective, if
    needed" counts toward the total, so both ways are tried; years that can't be confirmed keep their
    original inline labels."""
    labels = []
    for i, line in enumerate(lines):
        m = YEAR_LABEL_RE.match(line)
        if m:
            credits = CREDITS_RE.search(line) or (CREDITS_RE.search(lines[i + 1]) if i + 1 < len(lines) else None)
            labels.append((i, m.group(2), int(credits.group(1)) if credits else None))
    if len(labels) < 2:
        return lines
    best = (0, [], [])
    for skip_optional in (False, True):
        row = [_row_credits(line, skip_optional) for line in lines]
        for first in range(max(0, labels[0][0] - 3), labels[0][0] + 1):
            starts, pos, matched = [], first, 0
            for n, (_, _, credits) in enumerate(labels):
                starts.append(pos)
                nxt = labels[n + 1][0] if n + 1 < len(labels) else len(lines)
                total, end = 0, pos
                while credits and end < len(lines) and total < credits:
                    total, end = total + row[end], end + 1
                if not credits or total != credits or end > nxt:
                    break
                matched, pos = matched + 1, end
            if matched > best[0]:
                best = (matched, starts, row)
    matched, starts, row = best
    if not matched:
        return lines
    for n, start in enumerate(starts):  # titles like "Track A: ..." have no credits; keep them above the heading
        while start < labels[n][0] and row[start] == 0:
            start += 1
        starts[n] = start
    cleaned = list(lines)
    for i, _, _ in labels[:len(starts)]:
        cleaned[i] = YEAR_LABEL_RE.sub(lambda m: m.group(1) + " " * len(m.group(2)), cleaned[i])
        for j in (i, i + 1):
            if j < len(cleaned):
                cleaned[j] = CREDITS_RE.sub(lambda m: " " * len(m.group(0)), cleaned[j])
    heads = {start: f"[{name} ({credits} credits)]" if credits else f"[{name}]"
             for start, (_, name, credits) in zip(starts, labels)}
    out = []
    for j, line in enumerate(cleaned):
        if j in heads:
            out.append(heads[j])
        out.append(line)
    return out


def pdf_pages(data: bytes) -> tuple[str, list[str]]:
    """(embedded title, text of each page). Layout mode keeps table rows together, so a semester
    grid reads "fall course | spring course" per line instead of two separate columns."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    title = ""
    try:
        title = (reader.metadata.title or "").strip() if reader.metadata else ""
    except Exception:
        pass
    pages = []
    for page in reader.pages:
        try:
            raw = page.extract_text(extraction_mode="layout")
        except Exception:
            raw = page.extract_text() or ""
        lines = _label_plan_years(raw.splitlines())
        lines = [DOUBLED_RE.sub(r"\1", re.sub(r"\s{3,}", " | ", line.strip())) for line in lines]
        pages.append("\n".join(l for l in lines if l.strip(" |")))
    return title, pages


def join_pages(pages: list[str]) -> str:
    return "\n\n".join(f"{PAGE_MARK.format(n=i)}\n{p}" for i, p in enumerate(pages, 1) if p.strip())


def split_pages(text: str) -> dict[int, str]:
    """Inverse of join_pages: {page number: text}."""
    parts = PAGE_SPLIT_RE.split(text)
    return {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
