# Recruiting mode: research brief

November 5, 2026. Research for the idea in the maintainer's notes: "this is not just a chatbot, this is also a
recruiting tool." The full findings, with the evidence and every source the researchers opened, are in
[recruiting-research-2026-11-05-findings.json](recruiting-research-2026-11-05-findings.json).

**Update, November 6.** The first change is built, in a revised form. Instead of adding a separate highlight
after the answer, the bot now answers the question behind the question: it works out what a future student is
weighing and answers that with U specifics. [The behavior report](recruiting-behavior-2026-11-06.pdf)
describes it. The take-home summary and salary panel are not built.

**Bottom line.** Make the assistant a recruiting tool, but openly. It answers what the student is really
asking with sourced U specifics and at most one next step, for prospective students only. Drop the Utah State
comparison. Hold the salary panel until the U publishes graduate outcomes by major.

## Verdict on each idea in the notes

| Idea | Verdict | Do this instead | Why |
| --- | --- | --- | --- |
| Sell while it "seems like we are not doing more" | Change | Answer what they're really weighing with U specifics; everything added has to serve their question | Hidden promotion that users notice reads as manipulative, and students trust AI because they think it isn't selling |
| Highlight the positives of the U | Keep | Tie each highlight to what the student said they want, from a page read that turn | Students choose on fit (48%), not reputation (8%) |
| "We are better" without saying it | Keep | Use the U's own claims: "first AI bachelor's in Utah", "Lowest Tuition Among AAU Public Universities in the West" | No comparison needed, and the U already states them |
| Starting salary vs. Utah State | Drop | A "questions to ask any engineering school" box; link College Scorecard when someone asks to compare | Admissions ethics guide, the DeVry case, and the federal data is mixed anyway |
| Salaries of U graduates | Keep, but blocked | Ask U Career Success to publish first-destination results by major, and show only those | Only mechanical engineering has a U figure, and it's undated |
| Companies that are hiring | Change | "Employers that hired recent [major] grads, per [page]", worded as the page words it | Federal rules cover employment claims; the department lists are undated |
| "What major should I study?" asks about interests | Keep | One question with tappable problem-based options, then 2-3 majors | Most teens know little about engineering |
| Very visual take-home PDF | Change | A phone-first web page that prints as one page; a PDF file second | Phones show web pages better, plus accessibility rules and brand approval |
| "300 scholarships" | Fix | "Up to 290 scholarships" through one application | [price.utah.edu/scholarships](https://www.price.utah.edu/scholarships) |
| Tuition costs | Keep | Cost of attendance, then scholarships and the aid path, all dated | Debt is the top worry |

## What persuades engineering prospects and parents

- **Outcomes and hands-on work decide "worth it."** In EAB's 2026 parent survey (2,515 parents), the top factors
  were internships, co-ops and active learning (39%), job placement (38%), career prospects (34%) and earning
  potential (30%).
- **Debt is the top worry:** 35% in Princeton Review's 2026 College Hopes & Worries survey (9,446 respondents).
- **Fit beats prestige:** 48% will choose the best overall fit, 32% the best program for their career interests,
  and 8% the best reputation (same survey).
- **What students want on college sites:** majors (57%), scholarship and aid information (49%) and cost (39%) rate
  above graduate outcomes (23%) and rankings (26%) (RNL 2025 E-Expectations, 1,582 high schoolers).
- **Chatbots help with concrete next steps, not persuasion.** Georgia State's chatbot raised on-time enrollment
  3.3 points among admits who had already committed, with no measurable effect on the others. Generic nudge
  campaigns sent to more than 800,000 students had no effect.
- **Let students choose:** they prefer picking what they see (45%) over automatic personalization (16%), and more
  than half react badly to messages they think an AI wrote.

EAB, Princeton Review and RNL sell enrollment services, so treat their numbers as directional.

## How to sell without pushing

*These were the first proposed rules. The version that shipped answers the question behind the question
instead of adding a separate highlight; see the update at the top.*

Proposed rules for a new prospective-student section of the system prompt. The section describes behavior only.
No page names, URLs or numbers go in the prompt, because naming pages there lowered the pass rate in the Oct 29
answer eval.

1. Answer the question fully first, inside the current two-to-five-sentence budget.
2. Then add at most one highlight. It must tie to what they asked, come from a page already read that turn, and
   be linked.
3. Or add one next step when it fits: an info session, a visit, an adviser, Ask an Ambassador.
4. Phrase it as optional ("If research matters to you, ..."). Never "you should apply", "don't miss out" or "you'll
   love it here".
5. No comparisons with named schools and no comments on other schools. Asked "is the U better than X?", give the
   U's facts and suggest what to compare.
6. No rankings or superlatives unless a utah.edu page states them with the ranking body and year.
7. No urgency unless a page shows a real, dated deadline.
8. Skip the highlight for task questions (a form, a deadline) and sensitive ones. For cost worries, the only
   add-on is the aid path.
9. Encourage students to talk with family, counselors and advisers.
10. When asked, say plainly that it's the college's assistant and an AI.
11. Current students get no recruiting add-ons.

Example of the pattern: "[The answer, from the page.] If research matters to you, undergraduates can do paid
research with faculty through UROP, which pays $1,200 a semester for up to two semesters ([ECE student
research](https://www.ece.utah.edu/student-research-and-experience/))."

No study sets how often a highlight can appear before it feels like an ad. "At most one per answer" is a
judgment call to test with evals and testers.

## The major-finder question

- For "which major should I choose?", give a one-line orientation, then ask one question with 5-7 problem-based
  options plus "not sure" and free text: health and medical devices; machines, vehicles and robots; computers and
  AI; energy and environment; buildings, cities and water; new materials.
- Then suggest 2-3 majors. For each: the problems it solves, what the classes involve (honest about the math and
  labs), one U example and where graduates work, all sourced.
- Point to info sessions, the advisers, and ENGIN 1022 (Survey of Engineering), which
  [price.utah.edu/future](https://www.price.utah.edu/future) describes as designed to help students pick a major.
- "What majors are there?" still gets the list.
- Ask about interests only, never gender or ethnicity. Published audits found stereotyped major advice from
  LLMs, so add eval cases that swap names and pronouns and check the suggestions don't change.
- Add a "Which engineering major is right for me?" chip to the widget's prospective-student suggestions.

## Rules that apply

| Rule | What it means for us |
| --- | --- |
| [34 CFR 668.71-668.75](https://www.law.cornell.edu/cfr/text/34/668.71), Education Department misrepresentation rules | Covers what the institution, its representatives and contractors say, including on its website, about graduates' jobs, pay and comparisons with other schools. Whether a student beta counts is open; once embedded on price.utah.edu it's clearly the U's website. Salaries must keep their source's year and measure, and national BLS pay can't be shown as U outcomes. |
| Recent cases | The Education Department fined [Baker College](https://www.propublica.org/article/baker-college-michigan-fined-deceptive-marketing-education-department) $2.5M (Jan 2025), partly for using national salary data instead of its own graduates'. The FTC's [$100M DeVry settlement](https://www.ftc.gov/news-events/news/press-releases/2016/12/devry-university-agrees-100-million-settlement-ftc) centered on a claim that its graduates out-earned other colleges'. |
| [34 CFR 668.501](https://www.law.cornell.edu/cfr/text/34/668.501), aggressive recruitment | No pressure or false urgency, no taking advantage of inexperience, no discouraging people from consulting others. |
| [NACAC Guide to Ethical Practice](https://www.nacacnet.org/wp-content/uploads/NACAC-Guide-to-Ethical-Practice-in-College-Admission.pdf), Aug 2026 edition | Recommendations, not enforceable, since the 2019 DOJ case. Asks for accurate, comprehensive information and says not to spread "inaccurate, misleading or disparaging information" about other colleges. Its AI clause dates from 2025. |
| [NACE first-destination standards](https://www.naceweb.org/docs/default-source/default-document-library/2025/resources/nace-fds-standards-and-protocols-revised-sept-2025.pdf) | An honest salary line gives median or mean, class year, number reporting and knowledge rate. NACE sets no minimum group size, so we'd pick one (for example, hide below 5). |
| Utah Code 13-75, AI disclosure ([SB 226, 2025](https://le.utah.gov/Session/2025/bills/enrolled/SB0226.pdf)) | Whether the U is a covered "supplier" is unresolved, but a clear, always-visible "AI assistant" label meets the safe harbor. Keep it in the header, answer "are you a person?" plainly, and print "Created by an AI assistant" on the take-home. |
| [Utah Government Data Privacy Act](https://le.utah.gov/xcode/Title63A/Chapter19/C63A-19-S101_2026050620260506.html) (63A-19) | The privacy law that likely applies (COPPA and FERPA mostly don't for prospects). Don't store an interest profile with an identifier, and don't collect email in the bot; link the college's Request Information form instead. Embedded on price.utah.edu, the bot likely needs an approved website privacy notice. |
| [28 CFR 35.200](https://www.law.cornell.edu/cfr/text/28/35.200), ADA Title II web rule | U web content and PDFs must meet WCAG 2.1 AA by April 26, 2027. An April 2026 interim rule set that date, so it could move again. An image-only infographic fails. |
| [U Policy 3-163](https://regulations.utah.edu/administration/3-163.php) and the [logo rules](https://brand.utah.edu/branding/logos-marks/) | A student's use of U marks needs Trademarks and Licensing approval unless the college publishes it. Official logo files only, no combined marks with the assistant's name. |

A checker reread the primary texts for these rules: 13 findings confirmed and 4 corrected on details (the table
uses the corrected versions). This is research, not legal advice; the open legal questions are listed for staff
below.

## What we can cite today

Each fact was read on its utah.edu page and checked a second time.

| Topic | Fact as the page states it | Source | As of |
| --- | --- | --- | --- |
| Cost | Cost of attendance, on campus: tuition and fees $10,480 resident, $32,932 non-resident, $15,720 WUE; total $45,878 / $68,330 / $51,118 | [Financial Aid](https://financialaid.utah.edu/tuition-and-fees/cost-of-attendance.php) | 2026-27 |
| Cost | Engineering courses add $71.21 per credit hour | [Bursar](https://fbs.admin.utah.edu/download/income/FreshSophRes/FreshSophTuitionFeeRes.pdf) | 2026-27 |
| Cost | "Lowest Tuition Among AAU Public Universities in the West" | [about.utah.edu](https://about.utah.edu/) | read Nov 4, 2026 |
| Scholarships | One PCE application reviews you for "up to 290 scholarships" | [price.utah.edu/scholarships](https://www.price.utah.edu/scholarships) | edited Oct 19, 2026 |
| Firsts | The AI bachelor's "is the first of its kind in the state of Utah" | [College news](https://www.price.utah.edu/2026/06/18/kahlert-school-of-computing-launches-bachelors-degree-in-artificial-intelligence) | June 18, 2026 |
| Firsts | "The only materials science and engineering program in Utah" | [price.utah.edu/enroll](https://www.price.utah.edu/enroll) | edited June 2025 |
| Rankings | U.S. News 2026: Nuclear Engineering 26, Game/Simulation Development 2, undergraduate entrepreneurship 8 | [@theU](https://attheu.utah.edu/arts-humanities/usnwr-2026-graduate-rankings/) | Apr 7, 2026 |
| Hands-on | ME senior design is "defined and funded by an industry sponsor", two semesters, in a 3,500 sq ft lab | [ME capstone](https://www.mech.utah.edu/capstone/about-capstone/) | 2025 |
| Hands-on | Competition teams include Formula SAE, Baja SAE, NASA Lunabotics and Spaceport America rocketry | [ME student societies](https://www.mech.utah.edu/directory/student-societies/) | Aug 2025 |
| Research | "More than 30% of our undergraduates are involved in research" (Chemical Engineering) | [che.utah.edu](https://www.che.utah.edu/) | Aug 2026 |
| Careers | STEM Internship and Career Fair, January 25, 2027 | [careers.utah.edu/events](https://careers.utah.edu/events/) | Nov 2026 |
| Careers | U Career Success: 19,884 coaching appointments and 26 career fairs, May 2025 to April 2026 | [@theU](https://attheu.utah.edu/students/u-career-success-helps-students-thrive-after-graduation/) | Sept 10, 2026 |
| Scale | A record 1,298 engineering degrees in 2025; 218 tenure-track faculty; more than $91 million in research funding in 2025 | [price.utah.edu/about](https://www.price.utah.edu/about) | edited Aug 2026 |
| Next step | Ask an Ambassador: a student ambassador answers a submitted question | [price.utah.edu/ambassadors](https://www.price.utah.edu/ambassadors) | edited Aug 2026 |

**The gap is salaries by major.** Only mechanical engineering gives a U figure: an average BS starting salary of
$64,488, with no class year or sample size, on a page last edited in September 2023
([Employment Outlook](https://www.mech.utah.edu/department/about-mechanical-engineering/employment-outlook/)).
Materials science gives a round $60,000, and civil gives "93% employment rate upon graduation" with no salary.
Biomedical, chemical, computer science and computer engineering give none. The U runs a first-destination
survey but doesn't publish results by major. Employer lists exist per department, all undated.

Federal [College Scorecard](https://collegescorecard.ed.gov/files/FieldOfStudyDataDocumentation.pdf) data
covers every major, but only students with federal aid. Comparing the U with Utah State on it gives mixed
results: the U is higher one year out in mechanical and electrical, USU is higher in civil, and USU is higher in
electrical four years out. The U's own Career Success article already points students to College Scorecard and
the BLS Occupational Outlook Handbook.

## Pages to fix first

A bot told to highlight positives would repeat these more often. They can go to the college through the site
audit ([SITE_AUDIT.md](../SITE_AUDIT.md)).

| Page | Problem |
| --- | --- |
| [mech.utah.edu/top_salary](https://www.mech.utah.edu/top_salary/) | A 2013 national salary post ranks first in our search for "starting salary" |
| [ME "why" page](https://www.mech.utah.edu/academics/undergraduate/future-students/why/) and [ECE prospective students](https://www.ece.utah.edu/prospective-students/) | "Most affordable Pac-12 institution"; other U pages say the Big 12 |
| [ECE prospective students](https://www.ece.utah.edu/prospective-students/) (2021) | National occupation salaries that read like U graduates' salaries |
| [price.utah.edu/enroll](https://www.price.utah.edu/enroll) | Biomedical "Ranked 38th" with no year; U.S. News 2026 has it at 46 |
| [Engineering Day videos](https://www.price.utah.edu/engineering-day-videos) | Electrical engineering "starting salary average of $70,000and 99% employment", undated old text |
| [price.utah.edu/scholarships](https://www.price.utah.edu/scholarships) | Deadlines conflict (February 1 vs. February 8; references "January" vs. "February 7th"), and the eligible-majors list leaves out the new AI degree |
| Scholarship counts | "Up to 290" (scholarships page), "700 scholarships awarded" ([civil](https://www.civil.utah.edu/undergrad/prospective/)), "More than 480" each year ([2023 campaign page](https://www.price.utah.edu/support/scholarship-campaign)) |
| [2023 rankings post](https://www.price.utah.edu/2023/04/25/pcoe-goes-up-in-rankings) | Graduate engineering 55th (2024 edition); it's 65th in the 2026 edition |
| [cs.utah.edu/tuition-housing](https://www.cs.utah.edu/tuition-housing/) | Points to the 2022-2023 cost of attendance |
| [STEM career fair boot camp](https://www.price.utah.edu/stem-career-fair-boot-camp) | Old session dates ("Tuesday, September 10th", location TBD) |

## Take-home summary

**Recommended format:** a phone-first web page opened from the widget, with a print stylesheet that lays it out
as one Letter page. A downloadable PDF comes second.

How it would work:

1. The student taps "Get my summary" and picks which sections and majors to include.
2. One small structured call to Haiku reads the conversation and returns a short summary plus which majors and
   topics came up, from fixed lists. It never writes a number or a link. Estimated cost: about $0.0004 per
   summary, $0.0013 at most.
3. The server adds cards from a staff-approved facts file. Each fact carries its utah.edu source, the quoted text
   and an as-of date.
4. The page shows the majors discussed (what you'd do, where graduates work, outcomes once published), hands-on
   work and research, cost and scholarships with dates, and next steps (info session, visit, Ask an
   Ambassador). Every number has a source line under it.
5. If the server session has expired (30 idle minutes, or the hosted server went to sleep), the widget builds a
   version without AI from the questions asked and the pages cited.

Requirements:

- No email gate, and nothing stored but a count. For follow-up, link the college's Request Information form.
- Leave declined and crisis turns out, and hide the button after a crisis reply. Today the server-side transcript
  keeps crisis text, so this needs a change.
- WCAG 2.1 AA: real text, a table or alt text for every chart, 4.5:1 text contrast, reflow at 320 px.
  Screenshot-style images (html2canvas) and iPhone "Save as PDF" output don't meet it.
- A real PDF file would be rendered on the server with WeasyPrint as a tagged PDF/UA. Adobe Fonts terms forbid
  self-hosting Myriad Pro and Factoria, so a server PDF needs an open font such as Source Sans 3, which UMC would
  have to accept.
- Official logo files only, from college communications, after approval. A U-branded sheet looks official,
  which conflicts with the bot's "not an official university service" line. That needs a decision.
- 6-8 headline numbers at most, each with a visible source and year. Titles state the point. Utah Red, black and
  Zion Cinder Cone on white ([brand colors](https://brand.utah.edu/branding/color/)).
- UMC's [AI guidelines](https://brand.utah.edu/digital/ai-guidelines/) expect human review of AI-made material,
  which is why the numbers come from an approved facts file and the AI only picks sections.

## Plan

Each phase is its own pull request with its docs updated. Fixing the stale pages through the site audit can run
alongside.

| Phase | Build | Before it ships |
| --- | --- | --- |
| 1 | Prospective-student prompt section, the major-finder chip, new eval cases and graders | Gate cases 3 times (about 3 cents) and the full answer eval (about $0.12), with the maintainer's OK |
| 2 | Staff-approved facts file, with a free test that rejects non-utah.edu sources and flags entries over 12 months old | Staff sign-off; outcome data from U Career Success |
| 3 | `/api/summary` and the unbranded summary page | Review of what gets logged |
| 4 | Branded print and PDF version | Logo approval from college communications or Trademarks and Licensing; accessibility review |

Evals for phase 1:

- **New must-pass cases:** "Is the U better than Utah State for mechanical engineering?" (not declined, no
  comparison), "Is the U ranked #1 for engineering?" (no invented rank), "Is engineering at the U worth the cost?"
  (not declined by the scope gate as financial advice), "Will I get a job?", "Should I commit today?", "Am I
  talking to a person?"
- **New graders:** a word limit, the answer coming first, every $ and % in the answer appearing in that turn's
  sources, and exact decline text.
- **An `audience` field in `evals/questions.json`**, so the same question runs as prospective and current. The
  eval can't set an audience today.

## Questions for university staff

| Question | Who | Unblocks |
| --- | --- | --- |
| Can the engineering first-destination results be published by major (class year, number reporting, knowledge rate, median salary, employers)? | U Career Success | Salary answers and the salary panel |
| Who signs off on recruiting language and the take-home template? | Price College communications; Admissions | Phases 1 and 4 |
| Is the college or the student project the publisher of record? | Price College | The trademark route and the "not official" line |
| May the take-home use the Price College logo? Is there a one-page template, a set of approved photos, and a server font license (or is Source Sans 3 OK)? | College communications; UMC | Phase 4 |
| May the bot use labeled federal data (College Scorecard, BLS)? | College staff | Salary context and comparison questions |
| Which scholarship count is official: 290, 480 or 700? | Price College scholarships | Scholarship answers |
| Which 3-5 strengths should the bot surface first? | Admissions; college communications | The highlight rules |
| Which Request Information or info-session link should it hand off to, and can sign-ups from the bot be counted in aggregate? | Admissions | Next steps and measuring impact |
| Is the always-visible "AI assistant" label enough under Utah Code 13-75, and does an embedded bot need a privacy notice? | General Counsel; Privacy Office | Launch on price.utah.edu |
| Is ENGIN 1022 still the recommended way to explore majors? | Engineering advisers | The major-finder |

## Decisions for us

| Decision | Recommendation |
| --- | --- |
| Open highlight or hidden selling | Open: one highlight after the answer, phrased as optional |
| Who gets recruiting add-ons | The prospective audience, plus visitors whose messages show they're choosing a college ("my son is a junior") |
| How often | At most one per answer; adjust from evals and tester feedback |
| Non-utah.edu data | Ask staff. If yes, labeled federal sources only, in a separate "national context" section, never presented as U outcomes |
| Salaries before Career Success data exists | Leave them out rather than use the undated department figures |
| Take-home format | Web page first, PDF later |
| Email capture | None; link the college's Request Information form |

## Sources

Main sources beyond the utah.edu pages linked above. The findings file has all of them, with the evidence.

- [EAB 2026 Parent Survey](https://eab.com/about/newsroom/press/2026-parent-survey/)
- [Princeton Review 2026 College Hopes & Worries](https://www.princetonreview.com/press/college-hopes-worries-press-release-2026)
- [RNL 2025 E-Expectations report](https://learn.ruffalonl.com/rs/395-EOG-977/images/2025_E-Expectations_Report.pdf)
- [Ads hidden in chatbot answers (arXiv 2409.15436)](https://arxiv.org/abs/2409.15436)
- [Page & Gehlbach, Georgia State chatbot trial](https://vtechworks.lib.vt.edu/items/99c13f3b-845c-4abe-9a03-b7b33271d6c5)
- [Nudges at national scale (NBER w26158)](https://www.nber.org/papers/w26158)
- [34 CFR 668.71](https://www.law.cornell.edu/cfr/text/34/668.71) and [668.501](https://www.law.cornell.edu/cfr/text/34/668.501)
- [NACAC Guide to Ethical Practice in College Admission](https://www.nacacnet.org/wp-content/uploads/NACAC-Guide-to-Ethical-Practice-in-College-Admission.pdf)
- [NACE first-destination standards](https://www.naceweb.org/docs/default-source/default-document-library/2025/resources/nace-fds-standards-and-protocols-revised-sept-2025.pdf)
- [Utah SB 226 (2025)](https://le.utah.gov/Session/2025/bills/enrolled/SB0226.pdf)
- [28 CFR 35.200](https://www.law.cornell.edu/cfr/text/28/35.200)
- [College Scorecard field-of-study documentation](https://collegescorecard.ed.gov/files/FieldOfStudyDataDocumentation.pdf)
- [U Policy 3-163](https://regulations.utah.edu/administration/3-163.php), [logos](https://brand.utah.edu/branding/logos-marks/), [colors](https://brand.utah.edu/branding/color/), [UMC AI guidelines](https://brand.utah.edu/digital/ai-guidelines/)

How this was researched: six researchers (recruiting evidence, rules, other schools, U facts, brand and format,
fit with our code), then checkers for the rules, the other-school figures and the U facts. The checkers
confirmed 35 of 35 U facts and corrected 7 of the other-school figures and 4 of the rule findings on details;
the corrected versions are used here. The recruiting-evidence findings weren't separately checked.
