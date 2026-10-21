export const meta = {
  name: 'site-audit',
  description: 'Find outdated, conflicting or broken information on the Price College websites and verify each finding live',
  whenToUse: 'Before a semester or a report. Run `python -m audit.scan --links` first; see docs/SITE_AUDIT.md.',
  phases: [
    { title: 'Find', detail: 'one agent per topic reads the saved sites and checks the live pages and official sources' },
    { title: 'Verify', detail: 'a skeptic per topic re-checks every finding live and tries to refute it' },
  ],
}

// args: { date: "YYYY-MM-DD", scan: "audit/results/<date>/scan.json" }
const DATE = (args && args.date) || 'today'
const SCAN = (args && args.scan) || `audit/results/${DATE}/scan.json`

const COMMON = `You are auditing the University of Utah Price College of Engineering websites (price.utah.edu and the
department sites ece, mech, bme, che, civil, mse and cs .utah.edu) for information that is outdated, contradictory,
unreachable or unreadable. The results go into an internal report for the Price Engineering Assistant team. Today is ${DATE}.

Tools (run from the repository root):
- \`.venv/bin/python -m audit.lookup search "<words>"\` searches our saved copy of the sites (pages, PDFs, handbooks).
- \`.venv/bin/python -m audit.lookup page <url>\` prints a saved page's full text and when it was last updated.
- \`.venv/bin/python -m audit.lookup events --days 120\` lists the college events calendar, live.
- ${SCAN} holds the automatic scan's candidates: stale_pages, passed_dates, image_only_pdfs, leftover_pages and
  dead_links. Read it with Python. Candidates are leads, not findings.
- WebFetch for live pages: only utah.edu sites, one request at a time, at most 30 in total. Confirm every finding on
  the live page today, because the saved copy can be a few days old.

Rules:
- Read-only. Don't edit any file in the repository, don't run app.sync or anything that writes to data/, and don't
  call /api/chat or anything else that uses the Claude API.
- Report problems a student, parent or staff member could act on: wrong, outdated, contradictory, unreachable or
  unreadable information. Skip style and typos, and skip old news posts (they're dated by nature) unless an evergreen
  page relies on them.
- Quote the exact text (30 words at most) from every page involved, with its URL and its last-updated date when the
  page shows one. For a conflict, quote both sides and name the authoritative source when there is one: the Registrar
  for academic dates; Admissions, Financial Aid or the Bursar for admissions and costs; a department's own page over
  the college-wide directory for that department.
- Severity: high = someone could act on it and be wrong (a deadline, requirement, cost, contact or eligibility rule);
  medium = outdated or confusing but unlikely to cause a wrong decision; low = housekeeping.
- Owner: who should fix it, e.g. "College web team", "Chemical Engineering advising", "College calendar editor, with
  the Registrar".
- At most 15 findings, most important first. The same problem on several pages is one finding listing every page.
- Known problems listed in your topic were found earlier. Re-check each live and include it only if it still holds.`

const TOPICS = [
  {
    key: 'admissions-costs',
    title: 'Admissions, costs, scholarships and financial aid',
    prompt: `Cover the college's future-student and admissions pages, scholarships and financial-aid pages, each
department's prospective-student, transfer and graduate-admissions pages (deadlines, application fees, GPA or test
requirements), and anything quoting tuition or fees. Compare them with admissions.utah.edu, financialaid.utah.edu
(including WUE), bursar.utah.edu and gradschool.utah.edu.
Known: price.utah.edu/scholarships gives the scholarship deadline as February 1 in newer sections and February 8 in
older ones, and price.utah.edu/financial-aid says February 8. A ChemE graduate page mentions fees "Starting January 1,
2021".`,
  },
  {
    key: 'calendar-events',
    title: 'Academic calendar, events and recurring programs',
    prompt: `Compare the college events calendar (audit.lookup events) with the Registrar's academic calendars
(registrar.utah.edu/academic-calendars/fall2026.php and spring2027.php) for drop, withdrawal, registration and
graduation-application dates. Then check event and program pages that show dates (Engineering Day, open houses, info
sessions, career fairs, camps and K-12 programs, seminar series, banquets and dinners) for past dates presented as
upcoming, or upcoming events missing from the calendar. Use the scan's passed_dates candidates.
Known: the calendar's fall 2026 "last day to withdraw" entries appear two weeks earlier than the Registrar's;
Engineering Day (Saturday, November 14, 2026) isn't on the calendar.`,
  },
  {
    key: 'advising-contacts',
    title: 'Advising, people and contact information',
    prompt: `Compare the college-wide advisor directory (price.utah.edu/academic-advisors) with each department's
own advising page (che, mech, civil, ece, bme, mse, cs, and the CS handbook's advising pages): names, roles,
undergraduate vs graduate assignments, emails, phones, rooms, booking links and drop-in hours. Also check main
contact pages and staff directories for contacts that disagree between pages. Don't guess whether someone has left
the university; report only disagreements, dead contact links and contact pages that point to nothing.
Known: the college directory and the ChemE advising page disagree about the ChemE undergraduate advisor; the ECE
advisors page lists advisors the college directory doesn't.`,
  },
  {
    key: 'policies-requirements',
    title: 'Academic policies, requirements and degree plans',
    prompt: `Look for conflicting or outdated rules a current student relies on: GPA and grade minimums, course
repeat limits, admission to the major or "full major", change-of-major rules, graduation requirements, minors and
certificates. Compare each department's policy pages, handbooks (PDFs), flowcharts and 4-year plans, and the CS
handbook site. Also flag plans or handbooks presented as current whose catalog year is older than 2025-26 when a
newer one exists, and plans whose credit totals don't add up.
Known: the Chemical Engineering 2025-26 handbook says a course may be attempted three times on page 10 and two times
(third with approval) on page 23.`,
  },
  {
    key: 'housekeeping',
    title: 'Broken, stale, leftover and unreadable pages',
    prompt: `Work mainly from the scan file. Triage its dead_links (live-check the ones on pages students use),
stale_pages that are still linked from recently updated pages, leftover_pages (URLs ending -dnu, -2, -old and similar
that are still public) and image_only_pdfs (plans or forms whose content is only an image, which screen readers and
search can't read). Report the ones that matter to students or staff, grouped by owner, and say in not_checked how
many candidates you didn't get to.
Known: the "Which Engineering Major Should I Choose?" PDF linked from the majors, future-students and outreach pages
returns 404; the Engineering Floor page links housing.utah.edu/applications, which returns 404; 2018 pages under
price.utah.edu/student-organizations-dnu/ are public; the Chemical Engineering 4-year and 5-year plans are images.`,
  },
]

const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          kind: { type: 'string', enum: ['conflict', 'outdated', 'passed_date', 'dead_link', 'missing', 'unreadable', 'leftover_page'] },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          pages: {
            type: 'array',
            items: {
              type: 'object',
              properties: { url: { type: 'string' }, says: { type: 'string' }, page_updated: { type: 'string' } },
              required: ['url', 'says'],
            },
          },
          official_url: { type: 'string' },
          official_says: { type: 'string' },
          why_it_matters: { type: 'string' },
          suggested_fix: { type: 'string' },
          owner: { type: 'string' },
        },
        required: ['title', 'kind', 'severity', 'pages', 'why_it_matters', 'suggested_fix', 'owner'],
      },
    },
    covered: { type: 'array', items: { type: 'string' } },
    not_checked: { type: 'array', items: { type: 'string' } },
  },
  required: ['findings', 'covered', 'not_checked'],
}

const VERDICTS = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          index: { type: 'integer' },
          verdict: { type: 'string', enum: ['confirmed', 'refuted', 'uncertain'] },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          reason: { type: 'string' },
          correction: { type: 'string' },
        },
        required: ['index', 'verdict', 'severity', 'reason'],
      },
    },
  },
  required: ['verdicts'],
}

function verifyPrompt(topic, findings) {
  return `${COMMON}

## Your job: try to refute these findings about "${topic.title}"
Another agent reported the findings below. For each one, open the cited pages live with WebFetch and look for a
reason it's wrong: the page no longer says this; the two statements refer to different programs, terms, student
groups or years; the "official" source isn't actually authoritative; the date is clearly labeled as past; the link
works when followed in a browser; or the severity is overstated. If you can't see the evidence on the live page,
the verdict is "refuted". Use "uncertain" only when the pages are reachable but genuinely ambiguous.
Return a verdict for every index, a severity (keep or adjust), a one-sentence reason, and a correction when a detail
in the finding is wrong but the problem is real.

Findings (index: finding):
${findings.map((f, i) => `${i}: ${JSON.stringify(f)}`).join('\n')}`
}

const results = await pipeline(
  TOPICS,
  t => agent(`${COMMON}\n\n## Your topic: ${t.title}\n${t.prompt}`, { label: `find:${t.key}`, phase: 'Find', schema: FINDINGS }),
  (found, t) => {
    if (!found) return { topic: t.key, title: t.title, findings: [], covered: [], not_checked: ['the finder agent failed'] }
    const base = { topic: t.key, title: t.title, covered: found.covered, not_checked: found.not_checked }
    if (!found.findings.length) return { ...base, findings: [] }
    return agent(verifyPrompt(t, found.findings), { label: `verify:${t.key}`, phase: 'Verify', schema: VERDICTS })
      .then(v => ({
        ...base,
        findings: found.findings.map((f, i) => ({
          ...f,
          verdict: (v && v.verdicts.find(x => x.index === i)) || { verdict: 'unverified', severity: f.severity, reason: 'the verifier did not return a verdict' },
        })),
      }))
  },
)

const all = results.filter(Boolean)
const count = k => all.reduce((n, r) => n + r.findings.filter(f => f.verdict.verdict === k).length, 0)
log(`confirmed ${count('confirmed')}, uncertain ${count('uncertain')}, refuted ${count('refuted')}, unverified ${count('unverified')}`)
return all
