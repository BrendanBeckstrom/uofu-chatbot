"""Usage report from the question and feedback records: people, questions, topics, errors and gaps.

    python -m app.analytics              # last 30 days, from data/usage.jsonl and data/feedback.jsonl
    python -m app.analytics --days 7
    python -m app.analytics --firestore  # the hosted beta's records (docs/DEPLOY.md: reading the logs)
    python -m app.analytics --json       # the same numbers, for a dashboard or spreadsheet

"People" are distinct browsers (an anonymous hash of each browser's token), so one person on two devices
counts twice and a cleared browser counts again. Lines without a user (tests, scripts) are left out.
"""

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import config, records


def report(days: int = 30) -> dict:
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = sorted((r for r in records.read("question", since) if r.get("user")), key=lambda r: r["ts"])
    feedback = records.read("feedback", since)
    questions = [r for r in rows if not r.get("error")]
    per_day: dict[str, dict] = defaultdict(lambda: {"people": set(), "questions": 0, "errors": 0})
    for r in rows:
        d = per_day[r["ts"][:10]]
        d["people"].add(r["user"])
        d["errors" if r.get("error") else "questions"] += 1
    daily = {day: {"people": len(v["people"]), "questions": v["questions"], "errors": v["errors"]}
             for day, v in sorted(per_day.items())}
    answered = [r for r in questions if r.get("gate") in (None, "in_scope")]
    repeat = Counter(re.sub(r"[^\w\s]", "", r["question"].lower()).strip() for r in questions
                     if r.get("gate") != "crisis")
    return {
        "window": {"from": since, "to": date.today().isoformat(), "days": days},
        "people": len({r["user"] for r in rows}),
        "people_per_active_day": round(statistics.mean(d["people"] for d in daily.values()), 1) if daily else 0,
        "questions": len(questions),
        "errors": sum(1 for r in rows if r.get("error")),
        "error_rate": round(sum(1 for r in rows if r.get("error")) / len(rows), 3) if rows else 0,
        "declined": Counter(r["gate"] for r in questions if r.get("gate") not in (None, "in_scope")),
        "content_gaps": sum(1 for r in answered if r.get("gap")),
        "audience": Counter(r.get("audience") or "not chosen" for r in questions),
        "topics": Counter(r.get("topic") or "unknown" for r in questions),
        "median_seconds": statistics.median(r["seconds"] for r in answered) if answered else None,
        "cost_usd": round(sum(r.get("cost_usd", 0) for r in rows), 4),
        "feedback": {"up": sum(1 for f in feedback if f.get("rating") == 1),
                     "down": sum(1 for f in feedback if f.get("rating") == -1)},
        "daily": daily,
        "top_questions": repeat.most_common(10),
        "recent_gaps": [r["question"] for r in answered if r.get("gap")][-10:],
    }


def _print(r: dict):
    w = r["window"]
    print(f"Usage {w['from']} to {w['to']}")
    print(f"  People (distinct browsers): {r['people']}, about {r['people_per_active_day']} per active day")
    print(f"  Questions: {r['questions']}   errors: {r['errors']} ({r['error_rate']:.1%})   "
          f"cost: ${r['cost_usd']:.2f}   median answer: "
          + (f"{r['median_seconds']}s" if r["median_seconds"] is not None else "n/a"))
    print(f"  Declined: {dict(r['declined']) or 'none'}   couldn't fully answer: {r['content_gaps']}")
    print(f"  Feedback: {r['feedback']['up']} up, {r['feedback']['down']} down")
    print(f"  Audience: {dict(r['audience'])}")
    print("  Topics: " + ", ".join(f"{t} {n}" for t, n in r["topics"].most_common()))
    print("\n  Day         people  questions  errors")
    for day, d in r["daily"].items():
        print(f"  {day}  {d['people']:6d}  {d['questions']:9d}  {d['errors']:6d}")
    if r["top_questions"]:
        print("\n  Most asked:")
        for q, n in r["top_questions"]:
            print(f"    {n:3d}  {q[:90]}")
    if r["recent_gaps"]:
        print("\n  Recent questions it couldn't fully answer (content to add or surface):")
        for q in r["recent_gaps"]:
            print(f"    - {q[:100]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--firestore", action="store_true", help="read the hosted beta's Firestore records")
    args = ap.parse_args()
    if args.firestore:
        config.LOG_BACKEND = "firestore"
    r = report(args.days)
    print(json.dumps(r, indent=1, default=list)) if args.json else _print(r)


if __name__ == "__main__":
    main()
