"""Measure how accurate the assistant is, using evals/questions.json.

    python -m evals.run retrieval            # no API key: does search surface the right page? (hit@6)
    python -m evals.run selftest             # no API key: graders pass reference answers, fail empty ones
    python -m evals.run answers              # full bot, needs ANTHROPIC_API_KEY with credit
    python -m evals.run answers --reps 3 --only events,admissions
    python -m evals.run baseline             # no API key: the college site's own search box, for comparison
    python -m evals.run regrade --dir evals/results/<timestamp>   # re-score saved answers after fixing a case

Answers are graded with simple, separate checks (no AI judge):
  cited       links one of the expected pages
  facts       contains every required fact (each fact accepts a few phrasings)
  forbidden   avoids known-wrong statements
  events      mentions an event that is really on the live calendar for that window
  redirect    off-topic / out-of-scope requests get a polite redirect, not an attempt
A case passes when all of its checks pass. API or network failures go to errors.jsonl and are
never counted as wrong answers. Every run saves full transcripts and summary.json (pass rates with
95% ranges, per category and per check, cost and speed) under evals/results/<timestamp>/.
Cases have a tier (docs/MAKING_CHANGES.md): "gate" cases must pass every rep (a failure exits 1),
"gap" cases are known failures reported apart, and the rest are tracked as a pass rate.
Exploratory, multi-turn testing uses evals/converse.py instead.
"""

import argparse
import asyncio
import json
import math
import re
import statistics
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path

from app import config
from app.chat import ChatEngine, MD_LINK_RE
from app.events import search_events, today
from app.index import SearchIndex
from app.pricing import PRICES, cost_usd
from app.store import Store

HERE = Path(__file__).parent
CASES_PATH = HERE / "questions.json"
RESULTS_DIR = HERE / "results"
CASE_TIMEOUT = 240  # seconds, hard ceiling per answer

# The canned scope decline (app/scope.py), whether it came from the gate or the main model.
DECLINE_MARKERS = ["I'm scoped to University of Utah questions"]
REDIRECT_PHRASES = ["help with", "questions about", "can't", "cannot", "can not", "not able", "unable",
                    "i'm here", "i am here", "happy to help", "instead", "best place", "reach out"]
TIERS = ("gate", "gap")  # a case without a tier is expected to pass and tracked as a rate


def norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace("**", "").replace(" ", " ")
    return re.sub(r"\s+", " ", text)


def load_cases(only: str | None = None) -> list[dict]:
    cases = json.loads(CASES_PATH.read_text())
    if only:
        wanted = {w.strip() for w in only.split(",")}
        cases = [c for c in cases if c["id"] in wanted or c["category"] in wanted or c.get("tier") in wanted]
    return cases


def stale_warnings(cases: list[dict]) -> list[str]:
    out = []
    for c in cases:
        if c.get("as_of") and date.fromisoformat(c["as_of"]) < today() - timedelta(days=45):
            out.append(f"  {c['id']}: expected facts verified {c['as_of']}; re-check them on the site")
    return out


async def event_titles(spec: dict) -> list[str]:
    events = await search_events(spec.get("query", ""), today(), spec.get("days", 7), limit=50)
    return [e["title"] for e in events if not e["canceled"]]


def title_mentioned(title: str, answer: str) -> bool:
    # "Biomedical Engineering Seminar - Dr. Heath Henninger": either half is enough
    parts = [p.strip() for p in re.split(r" - |: ", title) if len(p.strip()) > 6] or [title]
    return any(norm(p) in answer for p in parts)


def contains(phrase: str, text: str) -> bool:
    """Case-insensitive; short phrases ("TA", "AI", "the U") must match whole words."""
    phrase = norm(phrase)
    if len(phrase) <= 5:
        return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None
    return phrase in text


def url_matches(part: str, url: str) -> bool:
    """An expected URL fragment; one ending in "$" must be the end of the URL (not a sub-page)."""
    if part.endswith("$"):
        return url.rstrip("/").endswith(part[:-1].rstrip("/"))
    return part in url


def grade(case: dict, answer: str, cited_urls: list[str], titles: list[str] | None) -> dict:
    a = norm(answer)
    checks = {"answered": bool(a.strip())}
    links = cited_urls + [u for _, u in MD_LINK_RE.findall(answer)]
    if case.get("expect_urls"):
        checks["cited"] = any(url_matches(part, u) for part in case["expect_urls"] for u in links)
    if case.get("must_include"):
        checks["facts"] = all(any(contains(alt, a) for alt in group) for group in case["must_include"])
    if case.get("must_not_include"):
        checks["forbidden"] = not any(contains(bad, a) for bad in case["must_not_include"])
    if case.get("expect_events") is not None:
        if titles:
            checks["events"] = any(title_mentioned(t, a) for t in titles)
        else:  # nothing on the calendar: the right answer says so
            checks["events"] = bool(re.search(r"\b(no|not any|nothing)\b.*\bevents?\b|\bcalendar\b", a))
    if case.get("expect_redirect"):
        checks["redirect"] = bool(a.strip()) and any(p in a for p in REDIRECT_PHRASES)
    if case.get("decline") is True:
        checks["declined"] = any(contains(m, a) for m in DECLINE_MARKERS)
    elif case.get("decline") is False:
        checks["not_declined"] = bool(a.strip()) and not any(contains(m, a) for m in DECLINE_MARKERS)
    return checks


def cost(usage: dict, model: str) -> float | None:
    if "cost_usd" in usage:  # the engine's own figure, gate call included
        return usage["cost_usd"]
    return cost_usd(usage, model) if model in PRICES else None


def jsonable(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj


def wilson(passed: int, n: int, z: float = 1.96) -> list[float]:
    """95% range for a pass rate measured on n questions (Wilson score interval); honest for small n."""
    if not n:
        return [0.0, 0.0]
    p, d = passed / n, 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def newly_failing(results: list[dict], folder: Path, tiers: dict) -> list[str]:
    """Cases that passed every rep the last time an earlier run included them, and failed a rep now."""
    now = {}
    for r in results:
        now.setdefault(r["id"], []).append(r["pass"])
    last = {}
    for run in sorted(p for p in RESULTS_DIR.iterdir() if re.fullmatch(r"\d{8}-\d{6}", p.name)
                      and p.name < folder.name and (p / "results.jsonl").exists()):
        passes = {}
        for line in (run / "results.jsonl").read_text().splitlines():
            r = json.loads(line)
            passes.setdefault(r["id"], []).append(r["pass"])
        last.update({cid: (run.name, p) for cid, p in passes.items()})
    return [f"{cid} (passed {len(last[cid][1])}/{len(last[cid][1])} in {last[cid][0]})"
            for cid, passes in sorted(now.items())
            if tiers.get(cid) != "gap" and not all(passes) and cid in last and all(last[cid][1])]


def summarize(results: list[dict], errors: list[dict], cases: list[dict], folder: Path) -> dict:
    """The numbers the evaluation report uses, saved as summary.json next to each run."""
    def block(rows):
        passed = sum(r["pass"] for r in rows)
        return {"n": len(rows), "passed": passed, "rate": round(passed / len(rows), 3) if rows else None,
                "range95": wilson(passed, len(rows))}
    tiers = {c["id"]: c.get("tier") for c in cases}
    gate = [r for r in results if tiers.get(r["id"]) == "gate"]
    gaps = [r for r in results if tiers.get(r["id"]) == "gap"]
    costs = [r["cost_usd"] for r in results if r["cost_usd"] is not None]
    secs = sorted(r["seconds"] for r in results)
    try:
        version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        version = ""
    return {
        "date": date.today().isoformat(), "model": config.MODEL, "version": version, "cases": len(cases),
        "overall": block(results), "errors_not_scored": len(errors),
        "gate": {**block(gate), "failed": sorted({r["id"] for r in gate if not r["pass"]})},
        "tracked": block([r for r in results if tiers.get(r["id"]) not in TIERS]),
        "gaps": {**block(gaps), "passing": sorted({r["id"] for r in gaps if r["pass"]})},
        "newly_failing": newly_failing(results, folder, tiers),
        "by_category": {c: block([r for r in results if r["category"] == c])
                        for c in sorted({r["category"] for r in results})},
        "by_check": {k: {"n": len(v), "passed": sum(v)} for k in
                     ("cited", "facts", "forbidden", "events", "redirect", "declined", "not_declined")
                     if (v := [r["checks"][k] for r in results if k in r["checks"]])},
        "time_sensitive": block([r for r in results if r["time_sensitive"]]),
        "cost_usd": {"total": round(sum(costs), 4), "per_answer": round(statistics.mean(costs), 5) if costs else None},
        "seconds": {"median": statistics.median(secs) if secs else None,
                    "p90": secs[int(0.9 * (len(secs) - 1))] if secs else None, "max": secs[-1] if secs else None},
        "failed": sorted({r["id"] for r in results if not r["pass"]}),
    }


# ---- modes --------------------------------------------------------------------------------------

def run_retrieval(cases: list[dict], k: int):
    engine = ChatEngine(SearchIndex(Store().docs))
    rows, by_cat = [], {}
    for c in cases:
        if not c.get("expect_urls"):
            continue
        urls = []
        for h in engine.index.search(c["question"], k=k * 2):
            if h["url"] not in urls:
                urls.append(h["url"])
        urls = urls[:k]
        rank = next((i + 1 for i, u in enumerate(urls) if any(url_matches(p, u) for p in c["expect_urls"])), None)
        rows.append((c, rank, urls))
        by_cat.setdefault(c["category"], []).append(rank is not None)
    hits = sum(r[1] is not None for r in rows)
    print(f"\nRetrieval hit@{k}: {hits}/{len(rows)} ({hits / max(len(rows), 1):.0%}) of questions get the "
          f"right page in the first search (before the AI searches again or reads pages itself)\n")
    for cat, vals in sorted(by_cat.items()):
        print(f"  {cat:16} {sum(vals)}/{len(vals)}")
    misses = [r for r in rows if r[1] is None]
    if misses:
        print("\nMisses (top results shown):")
        for c, _, urls in misses:
            print(f"  ✗ {c['id']}: {c['question']}\n      wanted {c['expect_urls']}\n      got    "
                  + "\n             ".join(u.replace("https://", "") for u in urls[:3]))


STOPWORDS = set("""a an and are as at be can could do does for from get how i i'm if in is it me my of on or so
    that the their there this to what when where which who why will with would you your should any about""".split())


def keywords(question: str) -> str:
    """What a student would type into a search box: the question minus filler words."""
    return " ".join(w for w in re.findall(r"[a-z0-9']+", question.lower()) if w not in STOPWORDS)


async def run_baseline(cases: list[dict], k: int):
    """The college's own site search (price.utah.edu/?s=...) against the assistant's first search, on the
    same questions. The site search gets the keywords, the charitable case. One request every CRAWL_DELAY
    seconds, as the site's robots.txt asks."""
    from bs4 import BeautifulSoup
    from app.wp import PoliteClient
    engine = ChatEngine(SearchIndex(Store().docs))
    todo = [c for c in cases if c.get("expect_urls")]
    print(f"Searching price.utah.edu for {len(todo)} questions, {config.CRAWL_DELAY:.0f}s apart "
          f"(about {len(todo) * config.CRAWL_DELAY / 60:.0f} minutes)…")
    rows = []
    client = PoliteClient(config.CRAWL_DELAY)
    try:
        for c in todo:
            query = keywords(c["question"])
            resp = await client.get(f"{config.SITE}/", s=query)
            site = [a.get("href") for a in BeautifulSoup(resp.text, "lxml").select(".entry-title a")][:k]
            ours = []
            for h in engine.index.search(c["question"], k=k * 2):
                if h["url"] not in ours:
                    ours.append(h["url"])
            hit = lambda urls: any(url_matches(part, u) for part in c["expect_urls"] for u in urls[:k])
            rows.append({"id": c["id"], "category": c["category"], "query": query, "site_hit": hit(site),
                         "ours_hit": hit(ours), "on_price_site": any("price.utah.edu" in part for part in c["expect_urls"]),
                         "site_top": site[:3]})
            print(f"  site {'✓' if rows[-1]['site_hit'] else '✗'}  assistant {'✓' if rows[-1]['ours_hit'] else '✗'}  {c['id']}")
    finally:
        await client.aclose()

    def line(label, subset):
        site, ours = sum(r["site_hit"] for r in subset), sum(r["ours_hit"] for r in subset)
        print(f"  {label:44} site search {site}/{len(subset)}   assistant {ours}/{len(subset)}")
    print(f"\nRight page in the top {k}:")
    line("all questions", rows)
    line("answer is on price.utah.edu", [r for r in rows if r["on_price_site"]])
    line("answer is on a department site", [r for r in rows if not r["on_price_site"]])
    out = RESULTS_DIR / f"baseline-{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"date": date.today().isoformat(), "k": k, "rows": rows,
                               "site_hits": sum(r["site_hit"] for r in rows), "assistant_hits": sum(r["ours_hit"] for r in rows),
                               "n": len(rows)}, indent=1))
    print(f"\nSaved to {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")


def run_regrade(folder: Path):
    """Re-score a saved run with the current questions.json, e.g. after fixing a too-strict case. No API
    calls. The live-calendar check can't be redone offline, so it keeps its saved result."""
    cases = {c["id"]: c for c in load_cases()}
    rows = [json.loads(line) for line in (folder / "results.jsonl").read_text().splitlines()]
    errors = [json.loads(line) for line in (folder / "errors.jsonl").read_text().splitlines()] \
        if (folder / "errors.jsonl").exists() else []
    flipped = []
    for r in rows:
        c = cases.get(r["id"])
        if not c:
            continue
        checks = grade(c, r["answer"], r["cited"], None)
        if "events" in r["checks"]:
            checks["events"] = r["checks"]["events"]
        if all(checks.values()) != r["pass"]:
            flipped.append(f"{r['id']} (rep {r['rep']}): {'pass' if all(checks.values()) else 'fail'}")
        r["checks"], r["pass"] = checks, all(checks.values())
    (folder / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    summary = summarize(rows, errors, [c for c in cases.values() if any(r["id"] == c["id"] for r in rows)], folder)
    (folder / "summary.json").write_text(json.dumps(summary, indent=1))
    print(f"Re-scored {len(rows)} answers. Changed: {', '.join(flipped) or 'none'}")
    print_report(summary, rows, errors, max((r["rep"] for r in rows), default=0) + 1)
    if summary["gate"]["failed"]:
        raise SystemExit(1)


async def run_selftest(cases: list[dict]):
    """Known-good answers must pass every check; empty answers must fail. Catches grader bugs."""
    problems = 0
    for c in cases:
        if c.get("tier") not in (None, *TIERS) or (c.get("tier") == "gap") != bool(c.get("gap_reason")):
            problems += 1
            print(f"  ✗ {c['id']}: tier must be \"gate\" or \"gap\", and every gap (only a gap) needs a gap_reason")
        try:
            titles = await event_titles(c["expect_events"]) if c.get("expect_events") is not None else None
        except Exception:  # calendar unreachable (e.g. CI): grade as an empty window
            titles = []
        oracle = c.get("reference", "")
        if titles:
            oracle += f" Coming up: {titles[0]}."
        elif c.get("expect_events") is not None:
            oracle += " There are no events on the calendar for that window."
        cited = [] if c.get("expect_redirect") else [f"https://x/{c['expect_urls'][0].rstrip('$')}"] if c.get("expect_urls") else []
        good = grade(c, oracle, cited, titles)
        bad = grade(c, "", [], titles)
        if not all(good.values()):
            problems += 1
            print(f"  ✗ reference answer fails {c['id']}: {good}")
        if all(bad.values()):
            problems += 1
            print(f"  ✗ empty answer passes {c['id']}")
    print(f"Self-test: {len(cases)} cases, {problems} grader problems" + (" ✓" if not problems else ""))
    if problems:
        raise SystemExit(1)


async def run_answers(cases: list[dict], reps: int, concurrency: int):
    if not config.ai_enabled():
        raise SystemExit("Set ANTHROPIC_API_KEY in .env first (or run `retrieval` / `selftest`).")
    config.ANSWER_CACHE_HOURS = 0  # every rep must reach the model, or reps 2+ just replay rep 1
    engine = ChatEngine(SearchIndex(Store().docs))
    out_dir = RESULTS_DIR / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    config.USAGE_PATH = out_dir / "usage.jsonl"  # keep eval traffic out of the real usage statistics
    results, errors = [], []
    sem = asyncio.Semaphore(concurrency)

    async def one(c, rep):
        async with sem:
            sid = f"eval-{c['id']}-{rep}-{int(time.time() * 1000) % 10**8}"
            answer, statuses, sources, usage, refused, error = "", [], [], {}, False, None
            titles = await event_titles(c["expect_events"]) if c.get("expect_events") is not None else None

            async def collect():
                nonlocal answer, sources, usage, refused, error
                for earlier in c.get("setup_turns", []):  # e.g. a legit question before a drift attempt
                    async for ev in engine.answer(sid, earlier):
                        if ev["event"] == "error":
                            error = f"setup turn failed: {ev['text']}"
                            return
                async for ev in engine.answer(sid, c["question"]):
                    kind = ev["event"]
                    if kind == "delta":
                        answer += ev["text"]
                    elif kind == "replace":
                        answer, refused = ev["text"], True
                    elif kind == "status":
                        statuses.append(ev["text"])
                    elif kind == "sources" and ev["kind"] == "cited":
                        sources = ev["items"]
                    elif kind == "usage":
                        usage = {k: v for k, v in ev.items() if k != "event"}
                    elif kind == "error":
                        error = ev["text"]
            started = time.time()
            try:
                await asyncio.wait_for(collect(), CASE_TIMEOUT)
            except asyncio.TimeoutError:
                error = f"timeout after {CASE_TIMEOUT}s"
            transcript = jsonable(engine.sessions.get(sid).messages)
            engine.sessions.reset(sid)
            base = {"id": c["id"], "rep": rep, "category": c["category"], "question": c["question"],
                    "seconds": round(time.time() - started, 1), "transcript": transcript}
            if error:
                errors.append({**base, "error": error})
                print(f"  ! {c['id']} (rep {rep}): {error}")
                return
            cited = [s["url"] for s in sources]
            checks = grade(c, answer, cited, titles)
            models = usage.get("models") or []
            row = {**base, "time_sensitive": c.get("time_sensitive", False), "answer": answer,
                   "cited": cited, "steps": statuses, "checks": checks, "pass": all(checks.values()),
                   "refused": refused, "usage": usage, "models": models,
                   "model_mismatch": any(m != config.MODEL for m in models),
                   "cost_usd": cost(usage, config.MODEL)}
            results.append(row)
            mark = "✓" if row["pass"] else "✗"
            failed = [k for k, v in checks.items() if not v]
            print(f"  {mark} {c['id']} (rep {rep}) {row['seconds']}s" + (f"  failed: {failed}" if failed else ""))

    print(f"Running {len(cases)} questions × {reps} rep(s) against {config.MODEL}…")
    await asyncio.gather(*(one(c, r) for c in cases for r in range(reps)))

    with (out_dir / "results.jsonl").open("w") as f:
        for r in sorted(results, key=lambda r: (r["id"], r["rep"])):
            f.write(json.dumps({k: v for k, v in r.items() if k != "transcript"}) + "\n")
    with (out_dir / "transcripts.jsonl").open("w") as f:
        for r in results:
            f.write(json.dumps({"id": r["id"], "rep": r["rep"], "transcript": r["transcript"]}) + "\n")
    if errors:
        with (out_dir / "errors.jsonl").open("w") as f:
            for e in errors:
                f.write(json.dumps(e) + "\n")

    summary = summarize(results, errors, cases, out_dir)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print_report(summary, results, errors, reps)
    print(f"\nSaved to {out_dir.relative_to(Path.cwd()) if out_dir.is_relative_to(Path.cwd()) else out_dir}")
    if summary["gate"]["failed"]:
        raise SystemExit(1)


def print_report(summary: dict, results: list[dict], errors: list[dict], reps: int):
    def rate(rows):
        return f"{sum(r['pass'] for r in rows)}/{len(rows)} ({sum(r['pass'] for r in rows) / max(len(rows), 1):.0%})"

    def ranged(block):
        lo, hi = block["range95"]
        return f"{block['passed']}/{block['n']} ({block['rate']:.0%}) (95% range {lo:.0%}–{hi:.0%})"

    gate, tracked, gaps = summary["gate"], summary["tracked"], summary["gaps"]
    print()
    if gate["n"]:
        print(f"Must pass:        {gate['passed']}/{gate['n']}"
              + (f"   ✗ FAILED: {', '.join(gate['failed'])}" if gate["failed"] else " ✓"))
    if tracked["n"]:
        print(f"Expected to pass: {ranged(tracked)}")
    if gaps["n"]:
        print(f"Known gaps:       {gaps['passed']}/{gaps['n']} pass now"
              + (f" ({', '.join(gaps['passing'])})" if gaps["passing"] else ""))
    if summary["newly_failing"]:
        print("Newly failing (passed every time in its last run):\n    " + "\n    ".join(summary["newly_failing"]))
    print(f"All questions:    {ranged(summary['overall'])}   errors (not scored): {len(errors)}")
    if reps > 1:
        per_rep = [statistics.mean(r["pass"] for r in results if r["rep"] == k) for k in range(reps)
                   if any(r["rep"] == k for r in results)]
        print(f"  across reps: mean {statistics.mean(per_rep):.0%}, spread ±{statistics.pstdev(per_rep):.0%}")
    should_decline = [r for r in results if "declined" in r["checks"]]
    should_answer = [r for r in results if "not_declined" in r["checks"]]
    if should_decline:
        print(f"  under-refusal (answered when it should decline): "
              f"{sum(not r['checks']['declined'] for r in should_decline)}/{len(should_decline)}")
    if should_answer:
        print(f"  over-refusal (declined a legitimate question): "
              f"{sum(not r['checks']['not_declined'] for r in should_answer)}/{len(should_answer)}")
    ts = [r for r in results if r["time_sensitive"]]
    if ts:
        print(f"  time-sensitive questions: {rate(ts)}")
    for cat in sorted({r["category"] for r in results}):
        print(f"  {cat:16} {rate([r for r in results if r['category'] == cat])}")
    for check in ("cited", "facts", "forbidden", "events", "redirect", "declined", "not_declined"):
        vals = [r["checks"][check] for r in results if check in r["checks"]]
        if vals:
            print(f"  check {check:10} {sum(vals)}/{len(vals)}")
    refusals = sum(r["refused"] for r in results)
    mismatched = sum(r["model_mismatch"] for r in results)
    costs = [r["cost_usd"] for r in results if r["cost_usd"] is not None]
    secs = [r["seconds"] for r in results]
    print(f"  refusals {refusals}, served by a fallback model {mismatched}")
    if costs:
        print(f"  cost: ${sum(costs):.2f} total, ${statistics.mean(costs):.3f} per answer")
    if secs:
        print(f"  latency: median {statistics.median(secs):.1f}s, max {max(secs):.1f}s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["retrieval", "selftest", "answers", "baseline", "regrade"])
    ap.add_argument("--dir", help="regrade: the results folder to re-score")
    ap.add_argument("--only", help="comma-separated case ids or categories")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--concurrency", type=int, default=3)
    args = ap.parse_args()
    cases = load_cases(args.only)
    warnings = stale_warnings(cases)
    if warnings:
        print("Some expected answers may be out of date:\n" + "\n".join(warnings))
    if args.mode == "retrieval":
        run_retrieval(cases, args.k)
    elif args.mode == "selftest":
        asyncio.run(run_selftest(cases))
    elif args.mode == "regrade":
        run_regrade(Path(args.dir))
    elif args.mode == "baseline":
        asyncio.run(run_baseline(cases, min(args.k, 5)))
    else:
        asyncio.run(run_answers(cases, args.reps, args.concurrency))


if __name__ == "__main__":
    main()
