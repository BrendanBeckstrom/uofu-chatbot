"""Talk to the assistant one message at a time, for exploratory testing by people or agents.

    python -m evals.converse serve                       # a separate eval server on port 8001; leave it running
    python -m evals.converse say p01 "What engineering majors are there?" --audience prospective
    python -m evals.converse say p01 "Which one has the most hands-on labs?"

`say` continues the conversation named in its first argument (p01 above). It prints the answer, its sources,
what the bot did, the time and the cost, and appends the exchange to evals/results/converse/<name>.jsonl.
--audience is what the visitor picked on the welcome screen (prospective or current); leave it out to test
someone who didn't pick.

The eval server answers every question fresh (no answer cache), has looser rate limits, never re-crawls the
sites, and writes its usage log next to the transcripts. Test traffic stays out of data/usage.jsonl and the
hosted beta's records. Each answer is a real API call (about $0.001).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

OUT = Path(__file__).parent / "results" / "converse"
PORT = 8001
URL = os.getenv("CONVERSE_URL", f"http://127.0.0.1:{PORT}")


def serve():
    OUT.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "ANSWER_CACHE_HOURS": "0", "AUTO_SYNC": "false", "BETA_PASSWORD": "", "LOG_BACKEND": "files",
           "USAGE_PATH": str(OUT / "usage.jsonl"), "FEEDBACK_PATH": str(OUT / "feedback.jsonl"),
           "TOKEN_LIMITS": "30/60,2000/86400", "IP_LIMITS": "120/60,5000/86400", "GLOBAL_CHAT_LIMITS": "120/60,5000/3600"}
    os.execvpe(sys.executable, [sys.executable, "-m", "uvicorn", "app.server:app", "--port", str(PORT)], env)


def _token(client: httpx.Client, path: Path, fresh: bool = False) -> str:
    if path.exists() and not fresh:
        return path.read_text().strip()
    r = client.post("/api/token")
    r.raise_for_status()
    path.write_text(r.json()["token"])
    return path.read_text()


def say(name: str, message: str, audience: str | None):
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / f"{name}.jsonl"
    turns = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    audience = audience or (turns[0].get("audience") if turns else None)
    body = {"message": message, "session_id": turns[-1]["session_id"] if turns else None}
    if audience:
        body["audience"] = audience

    rec = {"name": name, "turn": len(turns) + 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "audience": audience,
           "message": message, "answer": "", "sources": [], "steps": [], "error": None}
    started = time.time()
    with httpx.Client(base_url=URL, timeout=180) as client:
        token_path = OUT / f"{name}.token"
        for attempt in (0, 1):
            headers = {"X-Chat-Token": _token(client, token_path, fresh=bool(attempt))}
            with client.stream("POST", "/api/chat", json=body, headers=headers) as r:
                if r.status_code == 401 and not attempt:
                    continue
                if r.status_code != 200:
                    r.read()
                    sys.exit(f"The server answered {r.status_code}: {r.text}")
                event = None
                for line in r.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        d = json.loads(line[6:])
                        if event == "session":
                            rec["session_id"] = d["id"]
                        elif event == "status":
                            rec["steps"].append(d["text"])
                        elif event == "delta":
                            rec["answer"] += d["text"]
                        elif event == "replace":
                            rec["answer"] = d["text"]
                        elif event == "sources":
                            rec["sources"] = d["items"]
                            rec["sources_kind"] = d["kind"]
                        elif event == "usage":
                            rec.update({k: d.get(k) for k in ("gate", "cost_usd", "question_id")})
                        elif event == "error":
                            rec["error"] = d["text"]
            break
    rec["seconds"] = round(time.time() - started, 1)
    with log.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    cost = f"${rec['cost_usd']:.4f}" if rec.get("cost_usd") is not None else "n/a"
    print(f"ANSWER (turn {rec['turn']}, {rec['seconds']} s, {cost}, gate: {rec.get('gate') or 'n/a'}):\n")
    print(rec["answer"] or "(no answer)")
    if rec["error"]:
        print(f"\nERROR: {rec['error']}")
    if rec["sources"]:
        print(f"\nSOURCES ({rec.get('sources_kind')}):")
        for s in rec["sources"]:
            print(f"- {s.get('title')} | {s.get('url')}" + (f" | updated {s['updated']}" if s.get("updated") else ""))
    print("\nWHAT IT DID: " + " → ".join(rec["steps"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    s = sub.add_parser("say")
    s.add_argument("name", help="conversation name, e.g. p01")
    s.add_argument("message")
    s.add_argument("--audience", choices=["prospective", "current"])
    args = ap.parse_args()
    serve() if args.cmd == "serve" else say(args.name, args.message, args.audience)


if __name__ == "__main__":
    main()
