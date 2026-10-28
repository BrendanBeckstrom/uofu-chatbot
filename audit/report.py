"""Builds the site content audit report (docs/SITE_AUDIT.md) from the scan and the workflow's verified findings.

    python -m audit.report audit/results/<date>      # reads scan.json and findings.json there
    python -m audit.report audit/results/<date> --pdf

Writes site-content-audit-<date>.html into the same folder, and the PDF next to it with --pdf (needs Google
Chrome). Each run's folder is committed (docs/SITE_AUDIT.md).
Only findings the verifier confirmed or marked uncertain are reported; refuted ones are counted, not shown.
A finding with "duplicate_of" (added by hand to findings.json when two topics reported the same problem) is
counted as merged and not shown twice.
"""

import argparse
import html
import json
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
UNITS = {"price": "College (price.utah.edu)", "bme": "Biomedical Engineering", "che": "Chemical Engineering",
         "civil": "Civil & Environmental Engineering", "cs": "Kahlert School of Computing",
         "ece": "Electrical & Computer Engineering", "mech": "Mechanical Engineering",
         "mse": "Materials Science & Engineering"}
KIND = {"conflict": "Conflict", "outdated": "Outdated", "passed_date": "Passed date", "dead_link": "Broken link",
        "missing": "Missing", "unreadable": "Unreadable", "leftover_page": "Leftover page"}

STYLE = """
  :root {
    --bg: #FFFFFF; --surface: #F3F5F5; --ink: #151515; --muted: #5C5F61; --line: #DCE1E1; --red: #BE0000;
    --high: #890000; --medium: #8A5D00; --low: #5C5F61; --ok: #2C7A43;
    --display: "Work Sans", "Helvetica Neue", Arial, sans-serif;
    --body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
    --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { --bg: #111314; --surface: #1A1D1F; --ink: #ECEEEE; --muted: #A4A8AA;
      --line: #2D3133; --red: #FF5C5C; --high: #FF7A7A; --medium: #FFB81D; --low: #A4A8AA; --ok: #6CC24A; color-scheme: dark; }
  }
  :root[data-theme="dark"] { --bg: #111314; --surface: #1A1D1F; --ink: #ECEEEE; --muted: #A4A8AA;
    --line: #2D3133; --red: #FF5C5C; --high: #FF7A7A; --medium: #FFB81D; --low: #A4A8AA; --ok: #6CC24A; color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; }
  body { background: var(--bg); color: var(--ink); font: 17px/1.6 var(--body); }
  main { max-width: 980px; margin: 0 auto; padding-inline: 20px; padding-block: 40px 72px; }
  header { border-top: 6px solid var(--red); padding-top: 20px; margin-bottom: 28px; }
  .eyebrow { font: 600 12px/1.3 var(--display); letter-spacing: .1em; text-transform: uppercase; color: var(--red); margin: 0 0 10px; }
  h1 { font: 700 clamp(30px, 4.4vw, 42px)/1.12 var(--display); margin: 0 0 12px; text-wrap: balance; }
  h2 { font: 700 25px/1.2 var(--display); margin: 52px 0 12px; text-wrap: balance; }
  h3 { font: 600 18px/1.3 var(--display); margin: 0; text-wrap: balance; }
  p, li { max-width: 70ch; }
  .meta, .small { color: var(--muted); font-size: 15px; }
  a { color: var(--ink); text-decoration-color: var(--red); text-underline-offset: 3px; overflow-wrap: anywhere; }
  a:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }
  .card { border: 1px solid var(--line); border-radius: 6px; padding: 14px 16px; display: grid; gap: 2px; align-content: start; }
  .card .label { font-size: 14px; color: var(--muted); }
  .card .value { font: 600 28px/1.15 var(--display); font-variant-numeric: tabular-nums; }
  .card .note { font-size: 13px; color: var(--muted); }
  .callout { background: var(--surface); border-left: 4px solid var(--red); padding: 16px 20px; border-radius: 0 6px 6px 0; }
  .callout ol { margin: 8px 0 0; padding-left: 22px; display: grid; gap: 4px; }
  h3.topic { margin: 28px 0 4px; font-size: 19px; }
  .finding { border: 1px solid var(--line); border-radius: 6px; padding: 16px 18px; margin: 14px 0; display: grid; gap: 10px; min-width: 0; }
  .tags { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; font: 600 12px/1 var(--display); letter-spacing: .05em; text-transform: uppercase; }
  .sev-high { color: var(--high); } .sev-medium { color: var(--medium); } .sev-low { color: var(--low); }
  .kind, .owner { color: var(--muted); }
  .quotes { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
  .quotes li { border-left: 2px solid var(--line); padding-left: 12px; font-size: 15px; max-width: none; }
  .quotes .src { display: block; font-size: 13px; color: var(--muted); }
  .quotes .official { border-left-color: var(--ok); }
  .row2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px 24px; font-size: 15px; }
  .row2 p { margin: 0; } .row2 b { font-family: var(--display); font-size: 13px; letter-spacing: .03em; color: var(--muted); display: block; }
  .note { font-size: 14px; color: var(--muted); margin: 0; }
  .scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; margin: 12px 0; }
  table { border-collapse: collapse; width: 100%; min-width: 640px; font-size: 14px; }
  th, td { text-align: left; vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--line); }
  th { font: 600 12px/1.3 var(--display); letter-spacing: .04em; color: var(--muted); background: var(--surface); text-transform: uppercase; }
  tr:last-child td { border-bottom: 0; }
  td.num { font-family: var(--mono); font-variant-numeric: tabular-nums; white-space: nowrap; }
  details.more summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  @media print { details.more { display: none; } }
  footer { margin-top: 56px; padding-top: 14px; border-top: 1px solid var(--line); font-size: 14px; color: var(--muted); }
  @media print {
    @page { size: Letter; margin: 0.55in 0.6in; }
    body { font-size: 10.5pt; } main { max-width: none; padding: 0; }
    h1 { font-size: 24pt; } h2 { font-size: 16pt; margin: 20pt 0 8pt; break-after: avoid; } h3 { font-size: 11.5pt; }
    p, li { max-width: none; } .card, tr, .tags, .finding h3 { break-inside: avoid; } .finding h3, .tags { break-after: avoid; }
    .quotes li, .row2, .note, td { font-size: 9pt; }
    .finding { border: 0; border-top: 1px solid var(--line); border-radius: 0; padding: 8pt 0 2pt; gap: 5pt; margin: 6pt 0; }
    h2, h3.topic { break-after: avoid; }
    .scroll { overflow: visible; border: 0; } table { min-width: 0; font-size: 8.5pt; } a { text-decoration: none; }
    * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
"""


def esc(s) -> str:
    return html.escape(str(s or ""))


def clip(s: str, n: int) -> str:
    s = re.sub(r"^\s*(Confirmed live today[.:]?|Live today[.:]?)\s*", "", str(s or "")).strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def units(f: dict) -> list[str]:
    """Which sites a finding is on, from its pages' addresses."""
    found = []
    for p in f["pages"]:
        host = urlparse(p["url"]).netloc.lower().removeprefix("www.")
        key = "cs" if host.endswith("cs.utah.edu") else host.split(".")[0]
        if key in UNITS and UNITS[key] not in found:
            found.append(UNITS[key])
    return found or ["Other"]


def quote(s: str, n: int) -> str:
    """The page's words in quotation marks, unless the agent's text already quotes them."""
    s = clip(s, n)
    return esc(s) if s[:1] in "\"“'" else f"“{esc(s)}”"


def link(url: str, text: str | None = None) -> str:
    return f'<a href="{esc(url)}">{esc(text or url.replace("https://", ""))}</a>'


def finding_html(f: dict) -> str:
    v = f["verdict"]
    sev = v.get("severity") or f["severity"]
    quotes = "".join(
        f'<li>{quote(p["says"], 380)}<span class="src">{link(p["url"])}'
        + (f' · updated {esc(p["page_updated"])}' if p.get("page_updated") else "") + "</span></li>"
        for p in f["pages"])
    if f.get("official_url"):
        quotes += (f'<li class="official">{quote(f.get("official_says"), 340)}<span class="src">Official source: '
                   f'{link(f["official_url"])}</span></li>')
    notes = []
    if v.get("correction"):
        notes.append(f"Verifier's note: {esc(clip(v['correction'], 320))}")
    if v["verdict"] == "uncertain":
        notes.append(f"Verifier marked this uncertain: {esc(v['reason'])}")
    return f"""<article class="finding">
  <div class="tags"><span class="sev-{sev}">{sev}</span><span class="kind">{KIND.get(f["kind"], f["kind"])}</span><span class="owner">Owner: {esc(f["owner"])}</span></div>
  <h3>{esc(f["title"])}</h3>
  <ul class="quotes">{quotes}</ul>
  <div class="row2"><p><b>Why it matters</b>{esc(clip(f["why_it_matters"], 480))}</p><p><b>Suggested fix</b>{esc(clip(f["suggested_fix"], 480))}</p></div>
  {"".join(f'<p class="note">{n}</p>' for n in notes)}
</article>"""


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def build(folder: Path) -> Path:
    scan = json.loads((folder / "scan.json").read_text())
    topics = json.loads((folder / "findings.json").read_text())
    day = scan["date"]
    kept, refuted, merged = [], 0, 0
    for t in topics:
        for f in t["findings"]:
            if f.get("duplicate_of"):  # set by hand when two topics reported the same problem
                merged += 1
            elif f["verdict"]["verdict"] in ("confirmed", "uncertain"):
                kept.append({**f, "topic": t["title"]})
            else:
                refuted += 1
    sev = lambda f: f["verdict"].get("severity") or f["severity"]
    kept.sort(key=lambda f: (SEVERITY_ORDER[sev(f)], f["topic"]))
    counts = Counter(sev(f) for f in kept)
    dead = scan.get("dead_links", [])
    dead_404 = [d for d in dead if d["status"] in (404, 410)]
    linked_stale = [s for s in scan["stale_pages"] if s["linked_from_recent_pages"]]

    fix_first = "".join(f"<li>{esc(f['title'])} <span class='small'>({esc(f['owner'])})</span></li>"
                        for f in kept if sev(f) == "high")
    sections = "<h2>High severity, in detail</h2><p class='small'>Someone could act on these and be wrong.</p>"
    for t in topics:
        fs = [f for f in kept if f["topic"] == t["title"] and sev(f) == "high"]
        if fs:
            sections += f"<h3 class='topic'>{esc(t['title'])}</h3>" + "".join(finding_html(f) for f in fs)
    rest = [f for f in kept if sev(f) != "high"]
    sections += ("<h2>Medium and low severity</h2><p class='small'>Outdated or confusing, but unlikely to cause a wrong "
                 "decision. The web version of this report expands each row to show the quoted evidence.</p>")
    for t in topics:
        fs = [f for f in rest if f["topic"] == t["title"]]
        if fs:
            rows = [[f'<span class="sev-{sev(f)}">{sev(f)}</span>',
                     f'<b>{esc(f["title"])}</b><br>{link(f["pages"][0]["url"])}'
                     f'<details class="more"><summary>Evidence</summary>{finding_html(f)}</details>',
                     esc(clip(f["owner"], 90)), esc(clip(f["suggested_fix"], 240))] for f in fs]
            sections += f"<h3 class='topic'>{esc(t['title'])}</h3>" + table(["", "Problem", "Owner", "Suggested fix"], rows)

    by_unit = {}
    for f in kept:
        for u in units(f):
            by_unit.setdefault(u, Counter())[sev(f)] += 1
    owner_rows = [[esc(u), *[f'<span class="num">{c.get(k, 0)}</span>' for k in ("high", "medium", "low")]]
                  for u, c in sorted(by_unit.items(), key=lambda kv: (-kv[1].get("high", 0), -sum(kv[1].values())))]
    dead_rows = [[link(d["url"]), esc(d["status"]), link(d["linked_from"][0][1], d["linked_from"][0][0] or None)
                  if d["linked_from"] else ""] for d in sorted(dead_404, key=lambda d: -len(d["linked_from"]))[:20]]
    stale_rows = [[link(s["url"], s["title"]), s["modified"], f'<span class="num">{s["linked_from_recent_pages"]}</span>']
                  for s in linked_stale[:15]]
    left_rows = [[link(p["url"]), p["modified"]] for p in scan["leftover_pages"][:15]]
    img_rows = [[link(p["url"], p.get("title")), f'{len(p["pages_without_text"])} of {p["pages"]}']
                for p in scan["image_only_pdfs"]]
    not_checked = "".join(f"<li><b>{esc(t['title'])}:</b> {esc('; '.join(t['not_checked']))}</li>"
                          for t in topics if t.get("not_checked"))

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>Site Content Audit</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Work+Sans:wght@600;700&family=Source+Sans+3:wght@400;600;700&family=IBM+Plex+Mono&display=swap">
<style>{STYLE}</style>
</head>
<body>
<main>
<header>
  <p class="eyebrow">Price Engineering Assistant · Internal · Site content audit</p>
  <h1>Outdated and conflicting information on the college websites</h1>
  <p class="meta">Checked {esc(day)} · price.utah.edu and the seven department sites · saved copy from {esc(scan.get("content_as_of"))}, every finding re-checked live by a second agent</p>
</header>

<p>The assistant answers from these sites, so each problem below can turn into a wrong answer. This list is for the
assistant team to bring to the people who own the pages. Each finding quotes the pages involved and, where there is
one, the official source.</p>

<div class="cards">
  <div class="card"><span class="label">Confirmed problems</span><span class="value">{len(kept)}</span><span class="note">{counts.get("high", 0)} high, {counts.get("medium", 0)} medium, {counts.get("low", 0)} low severity</span></div>
  <div class="card"><span class="label">Broken links</span><span class="value">{len(dead_404)}</span><span class="note">"Not found" among {scan.get("links_checked", "the")} links checked; {len(dead) - len(dead_404)} more couldn't connect or were blocked; {scan.get("links_unchecked", 0)} less-linked links not checked</span></div>
  <div class="card"><span class="label">Pages not updated in 3+ years</span><span class="value">{len(scan["stale_pages"])}</span><span class="note">{len(linked_stale)} still linked from recently updated pages</span></div>
  <div class="card"><span class="label">Unreadable PDF pages</span><span class="value">{len(scan["image_only_pdfs"])}</span><span class="note">PDFs with pages that are only an image</span></div>
</div>

<div class="callout"><b>Fix first (high severity)</b><ol>{fix_first or "<li>None</li>"}</ol></div>

<h2>Problems by site</h2>
<p class="small">A problem that spans several sites counts once for each. Each finding below names a suggested owner.</p>
{table(["Site", "High", "Medium", "Low"], owner_rows)}

{sections}

<h2>From the automatic scan</h2>
<p class="small">Candidates from the scan of our saved copy. The findings above already include the ones that matter
most; these lists are for whoever cleans up the sites.</p>
<h3>Broken links on recently updated pages (top 20 of {len(dead_404)}, most-linked first)</h3>
{table(["Link", "Status", "Linked from"], dead_rows) if dead_rows else "<p>None found.</p>"}
<h3>Old pages still linked from recently updated pages</h3>
{table(["Page", "Last updated", "Linked from"], stale_rows) if stale_rows else "<p>None found.</p>"}
<h3>Leftover pages that are still public</h3>
{table(["Page", "Last updated"], left_rows) if left_rows else "<p>None found.</p>"}
<h3>PDFs with pages that are only an image</h3>
{table(["Document", "Pages without text"], img_rows) if img_rows else "<p>None found.</p>"}

<h2>How this was made</h2>
<p>An automatic scan of our saved copy of the sites listed candidates: old pages, passed dates shown as upcoming,
image-only PDFs, leftover pages, and live link checks (10 seconds apart per site; the 50 most-linked targets per
site). Five agents then cross-checked admissions and costs, the academic calendar and events, advising contacts,
policies and degree plans, and broken or stale pages against the live sites and official sources. A second agent
per topic re-checked every finding live and tried to refute it: {refuted} {"finding was" if refuted == 1 else "findings were"} refuted and left out, and {merged} reported
under two topics {"was" if merged == 1 else "were"} merged. The audit read the sites only and changed nothing in the assistant. See docs/SITE_AUDIT.md in the repository.</p>
<h3>Not checked this time</h3>
<ul>{not_checked or "<li>Nothing noted.</li>"}</ul>

<footer>Internal working document for the Price Engineering Assistant team, {esc(day)}. Page owners are suggestions.</footer>
</main>
</body>
</html>
"""
    out = folder / f"site-content-audit-{day}.html"
    out.write_text(page)
    return out


def pdf(html_path: Path) -> Path:
    out = html_path.with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                        "--no-pdf-header-footer", "--virtual-time-budget=15000", f"--print-to-pdf={out}",
                        html_path.resolve().as_uri()], check=True, capture_output=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--pdf", action="store_true")
    args = ap.parse_args()
    out = build(args.folder)
    print(f"Wrote {out}")
    if args.pdf:
        print(f"Wrote {pdf(out)}")


if __name__ == "__main__":
    main()
