"""Measure how accurate the assistant is, using evals/questions.json.

    python -m evals.run retrieval            # no API key: does search surface the right page? (hit@6)
    python -m evals.run selftest             # no API key: graders pass reference answers, fail empty ones
    python -m evals.run answers              # full bot, needs ANTHROPIC_API_KEY with credit
    python -m evals.run answers --reps 3 --only events,admissions

Answers are graded with simple, separate checks (no AI judge):
  cited       links one of the expected pages
  facts       contains every required fact (each fact accepts a few phrasings)
  forbidden   avoids known-wrong statements
  events      mentions an event that is really on the live calendar for that window
  redirect    off-topic / out-of-scope requests get a polite redirect, not an attempt
A case passes when all of its checks pass. API or network failures go to errors.jsonl and are
never counted as wrong answers. Every run saves full transcripts under evals/results/<timestamp>/.
"""

import argparse
import asyncio
import json
import re
import statistics
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


def norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace("**", "").replace(" ", " ")
    return re.sub(r"\s+", " ", text)


def load_cases(only: str | None = None) -> list[dict]:
    cases = json.loads(CASES_PATH.read_text())
    if only:
        wanted = {w.strip() for w in only.split(",")}
        cases = [c for c in cases if c["id"] in wanted or c["category"] in wanted]
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


async def run_selftest(cases: list[dict]):
    """Known-good answers must pass every check; empty answers must fail. Catches grader bugs."""
    problems = 0
    for c in cases:
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

    def rate(rows):
        return f"{sum(r['pass'] for r in rows)}/{len(rows)} ({sum(r['pass'] for r in rows) / max(len(rows), 1):.0%})"

    print(f"\nPassed {rate(results)}   errors (not scored): {len(errors)}")
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
    print(f"\nSaved to {out_dir.relative_to(Path.cwd()) if out_dir.is_relative_to(Path.cwd()) else out_dir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["retrieval", "selftest", "answers"])
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
    else:
        asyncio.run(run_answers(cases, args.reps, args.concurrency))


if __name__ == "__main__":
    main()
