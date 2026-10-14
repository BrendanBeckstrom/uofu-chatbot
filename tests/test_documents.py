"""Which planning PDFs get picked, and how versions of one document are matched.

Run:  .venv/bin/python -m tests.test_documents
"""

import asyncio
import io
import tempfile
from pathlib import Path

import httpx
import pypdf

from app import documents
from app.documents import _family, _year, pretty_title, select_pdfs
from app.extract import _label_plan_years, join_pages, split_pages
from app.wp import PoliteClient

C = "https://www.civil.utah.edu/wp-content/uploads"
CS = "https://www.cs.utah.edu/wp-content/uploads"


def found(*urls, site="civil"):
    return {u: {"site": site, "linked_from": [["Undergraduate", "https://example.utah.edu/"]]} for u in urls}


def main():
    assert _year(f"{C}/2026/05/2026-2027-Civil-Flowchart-Engineering-Math_ADA.pdf") == 2027
    assert _year(f"{CS}/2026/07/CS-Requirements-26-27.pdf") == 2027
    assert _year(f"{CS}/2026/10/CS-Plan-4year.pdf") == 2026, "no year in the name: use the upload folder"
    print("✓ years come from the file name, else the upload folder")

    same = [f"{C}/2026/01/2024-2025-Civil-Flowchart-Engineering-Math-Technical-Elective_ADA.pdf",
            f"{C}/2026/01/2025-2026-Civil-Flowchart-Engineering-Math-TE-1-1_ADA.pdf",
            f"{C}/2026/05/2026-2027-Civil-Flowchart-Engineering-Math_ADA.pdf"]
    assert len({_family("civil", u) for u in same}) == 1, [_family("civil", u) for u in same]
    four, five = (f"https://www.mech.utah.edu/wp-content/uploads/2022/06/{n}-year-Flow-Chart-Engineering-Math-21-22.pdf"
                  for n in (4, 5))
    assert _family("mech", four) != _family("mech", five), "4-year and 5-year plans are different documents"
    print("✓ versions of one document share a family; 4- and 5-year plans don't")

    picked = select_pdfs(found(*same))
    assert list(picked) == [same[-1]], picked
    picked = select_pdfs(found(
        f"{C}/2026/06/5A_Towers-and-Bridges_-Civil-Engineering-Lesson-Plan.pdf",
        f"{C}/2026/02/full-campus-map.pdf",
        f"{C}/2014/08/ECE-5320-Sample-Final-Exam.pdf",
        f"{C}/2020/01/UG_Handbook_2013.pdf",
        "https://www.rideuta.com/-/media/Rail_Map_plan.pdf",
        f"{C}/2026/10/Graduate_Handbook_2026-2027_0819_-ADA.pdf",
    ))
    assert list(picked) == [f"{C}/2026/10/Graduate_Handbook_2026-2027_0819_-ADA.pdf"], picked
    print("✓ only current planning documents on utah.edu are kept")

    grid = [  # PDF layout text: each year's label sits beside the middle of its rows
        "Track A: Students who start with CS 1420.",
        "                 CS 1420: Accelerated Prog      4    CS 2420: Data Structures   4",
        " Freshman year   MATH 1210: Calculus I          4    MATH 1220: Calculus II     4",
        "   (16 credits)",
        "                 CS 2100: Discrete Mathematics  3    CS 3810: Organization      3",
        " Sophomore year  CS 3500: Software Practice I   4    CS 3505: Software Practice 3",
        "   (13 credits)",
    ]
    out = _label_plan_years(grid)
    assert out.index("[Freshman year (16 credits)]") == 1, out
    assert out[out.index("[Sophomore year (13 credits)]") + 1] == grid[4], "CS 2100 opens sophomore year"
    assert _label_plan_years(grid[:3]) == grid[:3], "unchecked totals: leave the text alone"
    print("✓ degree plans: each year's rows are found from its credit total")

    assert pretty_title(f"{CS}/2026/10/CS-Plan-4year.pdf") == "CS Plan 4 year"
    pages = ["first page", "", "third page"]
    assert split_pages(join_pages(pages)) == {1: "first page", 3: "third page"}
    print("✓ titles and page markers round-trip")

    asyncio.run(refresh_cycle())
    print("All document checks passed.")


async def refresh_cycle():
    """First sync downloads; an unchanged file costs one 304; a new extractor version re-downloads."""
    buf = io.BytesIO()
    w = pypdf.PdfWriter(); w.add_blank_page(612, 792); w.write(buf)
    url = f"{CS}/2026/10/CS-Plan-4year.pdf"
    seen = []

    def handler(request):
        seen.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=buf.getvalue(), headers={"etag": '"v1"', "content-type": "application/pdf"})

    tmp = Path(tempfile.mkdtemp())
    documents.STATE_PATH, documents.PDF_DIR = tmp / "documents.json", tmp / "pdfs"
    documents.discover_pdfs = lambda: {url: {"site": "cs", "linked_from": [["Computer Science", "https://x"]]}}
    client = PoliteClient(0, transport=httpx.MockTransport(handler))
    try:
        assert await documents.DocumentSync(client).sync(include_handbook=False) == (1, 0)
        assert await documents.DocumentSync(client).sync(include_handbook=False) == (0, 0), "unchanged: 304"
        saved = documents.DocumentSync(client)
        saved.state[url]["extractor"] = 0
        assert await saved.sync(include_handbook=False) == (1, 0), "older extractor: re-read the saved file"
        assert len(seen) == 2, "re-extraction uses the saved PDF, not the network"
        for f in documents.PDF_DIR.iterdir():
            f.unlink()
        saved = documents.DocumentSync(client)
        saved.state[url]["extractor"] = 0
        assert await saved.sync(include_handbook=False) == (1, 0), "no saved file: download again"
    finally:
        await client.aclose()
    assert seen == [None, '"v1"', None], seen
    print("✓ refresh: changed files re-read, unchanged ones cost one 304, extractor upgrades re-read offline")


if __name__ == "__main__":
    main()
