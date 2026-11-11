"""Measure the chat-summary PDF on real conversations, using evals/summaries.json.

    python -m evals.summaries                  # real API calls: each case chats with the bot, then saves its PDF
    python -m evals.summaries --only mech-salary

Each case runs its questions through the real bot, then makes the summary the way /api/summary does. Checks:
  made        a summary came back
  points      at least two key points survived the checks
  covers      the title, overview and key points mention every topic group in "covers"
  highlights  at least two "About the Price College" highlights survived the checks
  on_topic    every highlight comes from one of the case's departments or the college site
  keeps_note  an "out of date" note in the chat is kept in the key points (cases with "keeps_note")
  forbidden   none of "must_not_include" appears anywhere in the PDF's text
It also reports how many key points and highlights the checks dropped: figures that don't match the page,
links the chat didn't give, undated rankings and comparisons. The PDFs are saved next to the results so a
person can look at them.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from app import config
from app import summary as S
from app.chat import ChatEngine
from app.index import SearchIndex
from app.pricing import cost_usd
from app.store import Store
from evals.run import RESULTS_DIR, contains, norm

CASES_PATH = Path(__file__).parent / "summaries.json"


def grade(case: dict, out: dict | None) -> dict:
    if not out:
        return {"made": False}
    text = norm(" ".join([out["title"], out["overview"]] + [k["text"] for k in out["key_points"]]))
    everything = norm(text + " " + " ".join(i["text"] for i in out["next_steps"]) + " " +
                      " ".join(h["heading"] + " " + h["text"] for h in out["highlights"]))
    allowed = set(case.get("departments", [])) | {"price"}
    checks = {
        "made": True,
        "points": len(out["key_points"]) >= 2,
        "covers": all(any(contains(alt, text) for alt in group) for group in case.get("covers", [])),
        "highlights": len(out["highlights"]) >= 2,
        "on_topic": all(h["page"]["site"] in allowed for h in out["highlights"]),
        "forbidden": not any(contains(bad, everything) for bad in case.get("must_not_include", [])),
    }
    if case.get("keeps_note"):
        points = norm(" ".join(k["text"] for k in out["key_points"]))
        checks["keeps_note"] = any(contains(alt, points) for alt in case["keeps_note"])
    return checks


async def run(cases: list[dict]):
    if not config.ai_enabled():
        raise SystemExit("Set ANTHROPIC_API_KEY in .env first.")
    config.ANSWER_CACHE_HOURS = 0
    out_dir = RESULTS_DIR / f"summaries-{time.strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True)
    config.USAGE_PATH = out_dir / "usage.jsonl"  # keep eval traffic out of the real usage statistics
    engine = ChatEngine(SearchIndex(Store().docs))
    results, summary_cost = [], 0.0

    for c in cases:
        sid = f"eval-summary-{c['id']}-{int(time.time() * 1000) % 10**8}"
        started = time.time()
        for q in c["turns"]:
            async for _ in engine.answer(sid, q, c.get("audience")):
                pass
        sess = engine.sessions.get(sid)
        turns = S.chat_turns(sess.transcript)
        cited = {u for _, a in turns for _, u in S.MD_LINK_RE.findall(a)}
        pages = S.college_pages(engine.index, S.departments(turns), cited)
        data, usage = await S.write(engine.client, turns, pages)
        dollars = cost_usd(usage, config.MODEL)
        summary_cost += dollars
        out = S.check(data, turns, pages)
        if not (out["overview"] or out["key_points"]):
            out = None
        checks = grade(c, out)
        if out:
            out["titles"] = dict(sess.titles)
            (out_dir / f"{c['id']}.pdf").write_bytes(S.render(out))
        raw = {k: len(data.get(k) or []) for k in ("key_points", "next_steps", "highlights")}
        kept = {k: len(out[k]) if out else 0 for k in raw}
        row = {"id": c["id"], "passed": all(checks.values()), "checks": checks, "raw": raw, "kept": kept,
               "departments": S.departments(turns), "pages_offered": len(pages),
               "summary_cost_usd": round(dollars, 5), "seconds": round(time.time() - started, 1),
               "chat": sess.transcript, "model_output": data,
               "highlight_sources": [h["page"]["url"] for h in out["highlights"]] if out else []}
        results.append(row)
        engine.sessions.reset(sid)
        mark = "✓" if row["passed"] else "✗"
        failed = [k for k, v in checks.items() if not v]
        print(f"  {mark} {c['id']}: kept {kept['key_points']}/{raw['key_points']} points, "
              f"{kept['highlights']}/{raw['highlights']} highlights" + (f"  failed: {failed}" if failed else ""))

    chat_cost = 0.0
    if config.USAGE_PATH.exists():
        chat_cost = sum(json.loads(l).get("cost_usd") or 0 for l in config.USAGE_PATH.read_text().splitlines())
    raw_h = sum(r["raw"]["highlights"] for r in results)
    kept_h = sum(r["kept"]["highlights"] for r in results)
    raw_k = sum(r["raw"]["key_points"] for r in results)
    kept_k = sum(r["kept"]["key_points"] for r in results)
    report = {"cases": len(results), "passed": sum(r["passed"] for r in results),
              "by_check": {k: sum(r["checks"].get(k, False) for r in results if k in r["checks"])
                           for k in ("made", "points", "covers", "highlights", "on_topic", "keeps_note", "forbidden")},
              "key_points_kept": f"{kept_k}/{raw_k}", "highlights_kept": f"{kept_h}/{raw_h}",
              "summary_cost_usd": round(summary_cost, 4), "chat_cost_usd": round(chat_cost, 4)}
    (out_dir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results))
    (out_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nSummaries: {report['passed']}/{report['cases']} cases passed every check")
    for k, v in report["by_check"].items():
        n = sum(1 for r in results if k in r["checks"])
        if n:
            print(f"  {k:11} {v}/{n}")
    print(f"  kept by the checks: {kept_k}/{raw_k} key points, {kept_h}/{raw_h} highlights")
    print(f"  cost: ${summary_cost:.4f} for the summaries (${summary_cost / max(len(results), 1):.4f} each), "
          f"${chat_cost:.4f} for the chats")
    print(f"\nPDFs and results saved to {out_dir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated case ids")
    args = ap.parse_args()
    cases = json.loads(CASES_PATH.read_text())
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    asyncio.run(run(cases))


if __name__ == "__main__":
    main()
