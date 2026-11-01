"""A small BM25 keyword index over document chunks. No embeddings API needed."""

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from .extract import chunk_text, split_pages

STOPWORDS = set("""
a an and are as at be been but by can could do does for from had has have how i if in into is it its
me my of on or our so than that the their them then there these they this to us was we were what when
where which who why will with would you your about any all also am get just more most not only other
some such tell want know please help need find
""".split())

# Common shorthand people type -> words that actually appear on the sites.
ALIASES = {
    "ece": "electrical computer", "bme": "biomedical", "chpe": "chemical", "che": "chemical",
    "cvee": "civil environmental", "mse": "materials", "mech": "mechanical", "cs": "computing computer science",
    "soc": "computing", "kahlert": "computing", "grad": "graduate", "undergrad": "undergraduate",
    "phd": "doctoral graduate", "ms": "master graduate", "ta": "teaching assistant",
    "advisor": "advising", "advisors": "advising", "advising": "advisor", "majors": "degree program",
    "major": "degree program", "apply": "admission", "applying": "admission",
    "scholarship": "scholarships financial", "tuition": "cost financial", "cost": "tuition", "costs": "tuition", "ambassador": "ambassadors",
    "housing": "living learning floor", "dorm": "housing living learning floor", "dorms": "housing living learning floor",
}

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _stem(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokenize(text: str, expand: bool = False) -> list[str]:
    toks = TOKEN_RE.findall(text.lower())
    if expand:
        toks = toks + [w for t in toks if t in ALIASES for w in ALIASES[t].split()]
    return [_stem(t) for t in toks if t not in STOPWORDS and len(t) > 1]


class SearchIndex:
    K1, B = 1.4, 0.75
    TITLE_BONUS = 1.5       # extra idf-weighted credit when a query term is in the title or URL
    NEWS_WEIGHT = 0.8       # prefer evergreen pages over news posts
    DOC_WEIGHT = 0.8        # PDFs and handbook pages: strong for planning questions, below pages for general ones
    PER_FOLDER = 2          # max pages from one parent folder, so a set of sibling stubs (".../aerospace",
                            # ".../energy-systems", each just "Affiliated Faculty: TBA") can't crowd out the overview

    def __init__(self, docs: dict[str, dict]):
        self.docs = docs
        self.built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.excluded: set[str] = set()  # URLs found to be gone since the last rebuild
        self.chunks: list[tuple[str, str]] = []  # (doc key, text)
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths: list[int] = []
        self.doc_terms: dict[str, set[str]] = {}
        for key, d in docs.items():
            self.doc_terms[key] = set(tokenize(" ".join([
                d["title"], urlparse(d["url"]).path.replace("-", " "), d.get("context", "")])))
            title_toks = tokenize(d["title"])
            for piece in self._pieces(d):
                idx = len(self.chunks)
                self.chunks.append((key, piece))
                toks = tokenize(piece) + title_toks
                self.lengths.append(len(toks))
                for term, tf in Counter(toks).items():
                    self.postings[term].append((idx, tf))
        self.avg_len = sum(self.lengths) / max(len(self.lengths), 1)

    @staticmethod
    def _pieces(d: dict) -> list[str]:
        if d["type"] != "pdf":
            return chunk_text(d["text"])
        return [f"[Page {n}] {piece}" for n, text in split_pages(d["text"]).items() for piece in chunk_text(text)]

    def stats(self) -> dict:
        types = Counter(d["type"] for d in self.docs.values())
        return {"built_at": self.built_at, "docs": len(self.docs), "chunks": len(self.chunks), **types}

    def exclude(self, url: str):
        self.excluded.add(url.rstrip("/"))

    def search(self, query: str, k: int = 6, per_doc: int = 2) -> list[dict]:
        terms = set(tokenize(query, expand=True))
        if not terms:
            return []
        n = len(self.chunks)
        scores: dict[int, float] = defaultdict(float)
        idfs = {}
        for term in terms:
            posting = self.postings.get(term)
            if not posting:
                continue
            idf = idfs[term] = math.log(1 + (n - len(posting) + 0.5) / (len(posting) + 0.5))
            for idx, tf in posting:
                norm = tf + self.K1 * (1 - self.B + self.B * self.lengths[idx] / self.avg_len)
                scores[idx] += idf * tf * (self.K1 + 1) / norm

        ranked = []
        for idx, score in scores.items():
            key = self.chunks[idx][0]
            kind = self.docs[key]["type"]
            if kind == "post":
                score *= self.NEWS_WEIGHT
            elif kind in ("pdf", "handbook"):
                score *= self.DOC_WEIGHT
            score += self.TITLE_BONUS * sum(idf for t, idf in idfs.items() if t in self.doc_terms[key])
            ranked.append((score, idx))
        ranked.sort(reverse=True)

        results, per, folders = [], Counter(), Counter()
        for score, idx in ranked:
            key, text = self.chunks[idx]
            doc = self.docs[key]
            if per[key] >= per_doc or doc["url"].rstrip("/") in self.excluded:
                continue
            if not per[key] and doc["type"] == "page":
                u = urlparse(doc["url"].rstrip("/"))
                folder = u.netloc + u.path.rsplit("/", 1)[0]
                if folders[folder] >= self.PER_FOLDER:
                    continue
                folders[folder] += 1
            per[key] += 1
            results.append({
                "title": doc["title"], "url": doc["url"], "type": doc["type"], "site": doc["site"],
                "date": (doc.get("date") or "")[:10], "updated": (doc.get("modified") or "")[:10],
                "score": round(score, 2), "text": text,
            })
            if len(results) >= k:
                break
        return results

    def lookup(self, url: str) -> dict | None:
        url = url.rstrip("/")
        return next((d for d in self.docs.values() if d["url"].rstrip("/") == url), None)

    def latest_posts(self, n: int = 4, site: str = "price") -> list[dict]:
        posts = [d for d in self.docs.values() if d["type"] == "post" and d["site"] == site]
        posts.sort(key=lambda d: d.get("date") or "", reverse=True)
        return [{"title": p["title"], "url": p["url"], "date": (p.get("date") or "")[:10]} for p in posts[:n]]
