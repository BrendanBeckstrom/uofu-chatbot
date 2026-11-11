"""The chat-summary PDF without an API key: what the checks keep, which pages become highlights, the PDF itself,
and the /api/summary endpoint, with a scripted fake Claude.

Run:  .venv/bin/python -m tests.test_summary
"""

import io
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import config, guard, scope
from app import summary as S
from app.chat import anon_user
from app.index import SearchIndex
from tests.fixtures import page

_tmp = Path(tempfile.mkdtemp())
config.USAGE_PATH = _tmp / "usage.jsonl"
guard.spend = guard.SpendGuard(0, _tmp / "spend.json")

RECENT = (date.today() - timedelta(days=40)).isoformat() + "T10:00:00"
MECH = "https://www.mech.utah.edu"
CAPSTONE = MECH + "/capstone/"
TURNS = [
    ("What's mechanical engineering like?",
     f"Seniors spend a year on a design project in teams of 4-6 ([Capstone]({CAPSTONE})). The average starting "
     "salary of $64,488 is from a page last updated in 2023, so it may be out of date; call 801-581-6441."),
    ("What's a good cake recipe?", scope.DECLINE),
]


def docs():
    return {d["key"]: d for d in [
        page(1, "/research/robotics", "Robotics lab", "The robotics lab builds walking robots with 12 students.",
             site="mech", base=MECH, modified=RECENT),
        page(2, "/research/old-lab", "Old lab", "An old robotics lab page from long ago.", site="mech", base=MECH,
             modified="2018-01-01T10:00:00"),
        page(3, "/capstone", "Capstone", "Capstone robotics projects for seniors.", site="mech", base=MECH,
             modified=RECENT),
        page(4, "/bme-lab", "BME robotics", "Biomedical robotics lab.", site="bme", base="https://www.bme.utah.edu",
             modified=RECENT),
        page(5, "/scholarships", "Engineering Scholarships",
             "The college awards up to 290 engineering scholarships each year.", modified=RECENT),
        page(6, "/2026/team-wins", "Student team wins design contest", "Mechanical students won.", kind="post",
             site="mech", base=MECH, date=RECENT),
        page(7, "/2026/seminar", "Seminar: soft robots", "A talk on soft robots.", kind="post", site="mech",
             base=MECH, date=RECENT),
    ]}


class FakeClient:
    def __init__(self, data):
        self.data, self.requests = data, []
        self.messages = self

    async def create(self, **kw):
        self.requests.append(kw)
        return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(self.data))],
                  usage=NS(input_tokens=4000, output_tokens=600, cache_read_input_tokens=0,
                           cache_creation_input_tokens=0))


def main():
    # ---- which turns and departments -----------------------------------------------------------
    turns = S.chat_turns([r for q, a in TURNS for r in (("user", q), ("assistant", a))])
    assert [q for q, _ in turns] == ["What's mechanical engineering like?"], "declined turns are left out"
    assert S.departments(turns) == ["mech"]
    assert S.departments([("Tell me about chemical engineering", "Chemical engineering students... see ME too.")]) \
        == ["che"], "'tell me' isn't Mechanical Engineering, and a passing mention isn't the chat's topic"
    print("✓ declined and crisis turns stay out; the chat's departments are found")

    index = SearchIndex(docs())
    pages = S.college_pages(index, ["mech"], {CAPSTONE})
    urls = [p["url"] for p in pages]
    assert MECH + "/research/robotics" in urls and config.SITE + "/scholarships" in urls
    assert MECH + "/research/old-lab" not in urls, "pages over 2 years old aren't highlights"
    assert MECH + "/capstone" not in urls, "pages the chat already cited aren't repeated"
    assert all(p["site"] in ("mech", "price") for p in pages), "only the chat's departments and the college"
    assert MECH + "/2026/team-wins" in urls, "the department's newest news posts are candidates"
    assert MECH + "/2026/seminar" not in urls, "routine notices like seminars aren't"
    print("✓ highlights come from recent pages of the chat's departments that it didn't already cite")

    # ---- the checks ------------------------------------------------------------------------------
    robotics = 1 + urls.index(MECH + "/research/robotics")
    scholarships = 1 + urls.index(config.SITE + "/scholarships")
    data = {
        "title": "Mechanical engineering at the U",
        "overview": "You asked what mechanical engineering is like.",
        "key_points": [
            {"text": "Seniors work in teams of 4-6 on a year-long design project.", "url": CAPSTONE},
            {"text": "The $64,488 starting salary is from 2023 and may be out of date.", "url": "https://evil.example/x"},
            {"text": "Graduates earn $120,000.", "url": ""},
        ],
        "next_steps": [{"text": "Call the Mechanical Engineering office at 801-581-6441.", "url": ""}],
        "highlights": [
            {"heading": "Walking robots", "text": "The robotics lab builds walking robots with 12 students.",
             "page": robotics, "stat": "12", "stat_label": "students"},
            {"heading": "Scholarships", "text": "Up to 290 engineering scholarships a year.", "page": scholarships,
             "stat": "290", "stat_label": "scholarships"},
            {"heading": "Made up", "text": "A lab with 99 robots.", "page": robotics, "stat": "", "stat_label": ""},
            {"heading": "Robots", "text": "The robotics lab builds walking robots.", "page": robotics,
             "stat": "5", "stat_label": "robots"},
            {"heading": "Dated", "text": f"In {RECENT[:4]}, the robotics lab builds walking robots.", "page": robotics,
             "stat": "", "stat_label": ""},
            {"heading": "Ranked", "text": "The robotics lab is ranked among the best.", "page": robotics,
             "stat": "", "stat_label": ""},
            {"heading": "Compared", "text": "Better than Utah State for robotics.", "page": robotics,
             "stat": "", "stat_label": ""},
            {"heading": "Nowhere", "text": "No such page.", "page": 99, "stat": "", "stat_label": ""},
        ],
    }
    out = S.check(data, turns, pages)
    assert [k["text"][:8] for k in out["key_points"]] == ["Seniors ", "The $64,"], out["key_points"]
    assert out["key_points"][0]["url"] == CAPSTONE and out["key_points"][1]["url"] == "", "only links the chat gave"
    assert [h["heading"] for h in out["highlights"]] == ["Walking robots", "Scholarships", "Robots", "Dated"], \
        "the page's own date counts as part of the page"
    assert out["highlights"][2]["stat"] == "", "a figure the page doesn't show is dropped, the highlight kept"
    page_text = "a $30 million grant; up to $100 per semester for clubs; 290 scholarships"
    assert S.big_number("30", "million NSF grant", page_text) == ("$30 million", "NSF grant")
    assert S.big_number("100", "dollars per semester", page_text) == ("", ""), "small amounts stay in the text"
    assert S.big_number("290", "scholarships", page_text) == ("290", "scholarships")
    assert S.dated_ranking(f"Ranked 38th by U.S. News in {date.today().year}")
    assert not S.dated_ranking("No. 82 in the world (2010)")
    print("✓ checks drop made-up figures, outside links, undated rankings and comparisons with other schools")

    # ---- the PDF ---------------------------------------------------------------------------------
    out["titles"] = {CAPSTONE: "Capstone Senior Design"}
    pdf = S.render(out)
    catalog = PdfReader(io.BytesIO(pdf)).trailer["/Root"]
    assert "/StructTreeRoot" in catalog and catalog["/Lang"] == "en", "a tagged PDF screen readers can follow"
    page_html = S.page_html(out, date.today())
    assert "About the Price College" in page_html and "Capstone Senior Design" in page_html
    assert "Written by AI" in page_html and "not an official University of Utah service" in page_html
    no_highlights = S.page_html({**out, "highlights": []}, date.today())
    assert "About the Price College" not in no_highlights
    print("✓ the PDF renders, accessible, with the AI disclosure; no highlights means no About section")

    # ---- the endpoint ----------------------------------------------------------------------------
    from app import server
    server.syncer.maybe_sync = lambda: False
    server.engine.index = index
    client = TestClient(server.app)
    token = client.post("/api/token").json()["token"]
    headers = {"X-Chat-Token": token}
    assert client.post("/api/summary", json={"session_id": "nosuchsession"}).status_code == 401
    assert client.post("/api/summary", json={"session_id": "nosuchsession"}, headers=headers).status_code == 404

    sess = server.engine.sessions.get("summary-test-1")
    sess.user = anon_user(guard.verify_token(token))
    sess.transcript = [r for q, a in TURNS for r in (("user", q), ("assistant", a))]
    fake = FakeClient(data)
    server.engine.client = fake
    guard.summary_limiter.hits.clear()
    r = client.post("/api/summary", json={"session_id": sess.id}, headers=headers)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf", (r.status_code, r.text[:200])
    assert r.content.startswith(b"%PDF") and "attachment" in r.headers["content-disposition"]
    sent = fake.requests[0]["messages"][0]["content"]
    assert "cake" not in sent and "<college_pages>" in sent, "declined turns never reach the model"
    assert guard.spend.spent > 0, "the call counts toward the daily budget"

    r2 = client.post("/api/summary", json={"session_id": sess.id}, headers=headers)
    assert r2.status_code == 200 and len(fake.requests) == 1, "a second download of the same chat is free"

    other = client.post("/api/token").json()["token"]
    r3 = client.post("/api/summary", json={"session_id": sess.id}, headers={"X-Chat-Token": other})
    assert r3.status_code == 404, "another browser can't download this chat"

    empty = server.engine.sessions.get("summary-test-2")
    empty.user = anon_user(guard.verify_token(token))
    assert client.post("/api/summary", json={"session_id": empty.id}, headers=headers).status_code == 422
    print("✓ endpoint: token and the chat's own browser required, PDF returned, repeat download cached")
    server.engine.client = None
    print("All summary checks passed.")


if __name__ == "__main__":
    main()
