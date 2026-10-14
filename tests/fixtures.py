"""A tiny stand-in for data/docs.json, so tests run anywhere (CI included) without the real index or network."""

from app.extract import join_pages

P = "https://www.price.utah.edu"
CS_PLAN = "https://www.cs.utah.edu/wp-content/uploads/2026/10/CS-Plan-4year.pdf"


def page(key_id, path, title, text, kind="page", site="price", base=P, date="2026-01-15T10:00:00",
         modified="2026-09-01T10:00:00", **extra):
    return {"key": f"{site}:{kind}:{key_id}", "site": site, "id": key_id, "type": kind, "url": base + path,
            "title": title, "date": date, "modified": modified, "text": text, **extra}


def fixture_docs() -> dict[str, dict]:
    docs = [
        page(1, "/future/request-information/info-sessions", "Engineering Info-Session",
             "Virtual info sessions introduce future students to engineering majors, admissions and campus "
             "life. Sessions are held monthly; register on this page."),
        page(2, "/tours", "Tours", "Tour the engineering buildings with a student ambassador. Tours run on "
             "weekdays during the semester."),
        page(3, "/scholarships", "Engineering Scholarships",
             "Engineering scholarships for first-year, transfer and continuing students. Apply through the "
             "university scholarship application."),
        page(4, "/tutoring-resources", "Tutoring Resources",
             "TA hours and department tutoring for engineering, math and physics courses."),
        page(5, "/2026/10/07/innovation-awards", "Innovation Awards Winners",
             "Students and faculty were recognized at the college's annual innovation awards.", kind="post",
             date="2026-10-07T09:00:00"),
        page("a1b2c3d4e5f6", "/wp-content/uploads/2026/10/CS-Plan-4year.pdf", "CS Plan 4 year",
             "Linked from: Computer Science\n\n" + join_pages([
                 "Computer Science B.S. Degree - Suggested 4-year Plans\n"
                 "Students who start with CS 1400 and Precalculus.\n"
                 "FALL semester | SPRING semester\n"
                 "CS 1400: Intro to Computer Programming 4 | CS 1410: Intro to Object-Oriented Prog\n"
                 "MATH 1080: Precalculus 5 | MATH 1210: Calculus I",
                 "Students who start with CS 1420 and Calculus I.\n"
                 "CS 1420: Accelerated Object-Oriented Prog 4 | CS 2420: Intro to Algs & Data Structures 4",
             ]), kind="pdf", site="cs", base="https://www.cs.utah.edu", date="", context="Computer Science"),
        page("0f1e2d3c4b5a", "/2024-2025/CS/Prospective_Students/choosing_between_1400_1420.php",
             "Computer Science Handbook 2024-2025: CS 1400 or CS 1420",
             "Where to start: CS 1400 followed by CS 1410 is the most common path. CS 1420 is an accelerated "
             "course for students with programming experience.", kind="handbook", site="cs",
             base="https://handbook.cs.utah.edu", date=""),
    ]
    return {d["key"]: d for d in docs}
