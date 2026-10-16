/*
 * Price Engineering Assistant: embeddable chat widget (proof of concept).
 *
 * Embed on any page:
 *   <script src="http://localhost:8000/widget.js" defer></script>
 * Optional attributes:
 *   data-api="https://..."   API origin (defaults to wherever this script was loaded from)
 *   data-open="true"         open the panel on load
 *   data-load-fonts="false"  skip loading the fallback web fonts (the host page already has them)
 *   data-adobe-fonts="abc1234"  the university's Adobe Fonts project ID, to use the brand fonts
 *                               (Myriad Pro for text, Factoria for headings; brand.utah.edu/branding/typography)
 *
 * Everything renders inside a Shadow DOM so the host page's CSS can't leak in or out.
 */
(function () {
  "use strict";
  if (window.__priceAssistantLoaded) return;
  window.__priceAssistantLoaded = true;

  const script = document.currentScript;
  const API = (script && script.dataset.api) || (script ? new URL(script.src).origin : location.origin);
  const STORE_KEY = "price-assistant:v1";
  const MAX_LEN = 1000;

  const SUGGESTIONS = {
    prospective: [
      "What engineering majors can I study?",
      "How do I apply to the College of Engineering?",
      "Can I tour the engineering buildings?",
      "What engineering scholarships are there?",
    ],
    current: [
      "What would my first semester look like in computer science?",
      "Where can I get tutoring for my engineering classes?",
      "How do I find my department's academic advisor?",
      "What's happening in the college this week?",
    ],
  };
  const MIXED = [SUGGESTIONS.prospective[0], SUGGESTIONS.prospective[1], SUGGESTIONS.current[0], SUGGESTIONS.current[3]];

  const P = "https://www.price.utah.edu";
  const CONTACTS = [
    { title: "Future students", items: [
      ["Talk with an engineering adviser", `${P}/future/request-information/info-sessions`, "Info sessions on majors, admissions and registration"],
      ["Request information", `${P}/future/request-information`, "Get information sent to you"],
      ["Book a tour", `${P}/tours`, "See the engineering buildings in person"],
      ["Ask an Ambassador", `${P}/ambassadors`, "A current engineering student's perspective"],
    ] },
    { title: "Current students", items: [
      ["Your department's advisors", `${P}/academic-advisors`, "They own your degree plan; find yours by department"],
      ["Tutoring resources", `${P}/tutoring-resources`, "TA hours and department tutoring"],
    ] },
  ];

  // ---------------------------------------------------------------- icons
  const ICON = {
    spark: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2.5c.4 0 .7.3.8.7l.9 3.6a6 6 0 0 0 4.4 4.4l3.6.9a.8.8 0 0 1 0 1.6l-3.6.9a6 6 0 0 0-4.4 4.4l-.9 3.6a.8.8 0 0 1-1.6 0l-.9-3.6a6 6 0 0 0-4.4-4.4l-3.6-.9a.8.8 0 0 1 0-1.6l3.6-.9a6 6 0 0 0 4.4-4.4l.9-3.6c.1-.4.4-.7.8-.7Z"/><path fill="currentColor" opacity=".7" d="M19 1.5c.2 0 .4.1.4.3l.3 1.1c.2.6.6 1 1.2 1.2l1.1.3a.4.4 0 0 1 0 .8l-1.1.3c-.6.2-1 .6-1.2 1.2l-.3 1.1a.4.4 0 0 1-.8 0l-.3-1.1c-.2-.6-.6-1-1.2-1.2l-1.1-.3a.4.4 0 0 1 0-.8l1.1-.3c.6-.2 1-.6 1.2-1.2l.3-1.1c0-.2.2-.3.4-.3Z"/></svg>',
    close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    expand: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    shrink: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10h-6V4M4 14h6v6M14 10l7-7M10 14l-7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12a8 8 0 0 1 13.7-5.7L20 8.5M20 4v4.5h-4.5M20 12a8 8 0 0 1-13.7 5.7L4 15.5M4 20v-4.5h4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    send: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    up: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10v11H3V10h4Zm2 11h8.3a2 2 0 0 0 2-1.6l1.4-7A2 2 0 0 0 18.7 10H14l.8-4.3a1.6 1.6 0 0 0-2.9-1.2L9 9.5V21Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>',
    down: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 14V3h4v11h-4ZM15 3H6.7a2 2 0 0 0-2 1.6l-1.4 7A2 2 0 0 0 5.3 14H10l-.8 4.3a1.6 1.6 0 0 0 2.9 1.2L15 14.5V3Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>',
    copy: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>',
    page: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z M14 3v5h5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>',
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    chev: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };

  // ---------------------------------------------------------------- styles
  const CSS = `
:host { all: initial; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
.root {
  /* University of Utah core colors: Utah Red, Black, White, Zion Cinder Cone. Accents (Red Rocks,
     Salt Flat Grey, Mountain Green, Wasatch Sunrise) only for small details, per brand.utah.edu. */
  --red: #BE0000; --red-dark: #890000; --red-deep: #000000; --red-tint: #E2E6E6;
  --ink: #000000; --ink-2: #000000; --muted: #707271; --line: #E2E6E6;
  --bg: #ffffff; --surface: #ffffff; --dark: #000000; --focus: #000000;
  --ok: #6CC24A; --warn: #FFB81D;
  --head: "factoria", "Factoria", "Work Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --body: "myriad-pro", "Myriad Pro", "Open Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --label: "myriad-pro", "Myriad Pro", "Poppins", system-ui, -apple-system, "Segoe UI", sans-serif;
  --shadow: 0 24px 60px -12px rgba(27,29,31,.35), 0 4px 14px rgba(27,29,31,.12);
  font-family: var(--body); color: var(--ink); font-size: 15px; line-height: 1.55;
  position: fixed; right: 24px; bottom: 24px; z-index: 2147483000;
  display: flex; flex-direction: column; align-items: flex-end; gap: 14px;
  -webkit-font-smoothing: antialiased;
}
button { font: inherit; color: inherit; cursor: pointer; border: 0; background: none; padding: 0; }
svg { width: 100%; height: 100%; display: block; }

/* launcher */
.launcher {
  display: inline-flex; align-items: center; gap: 10px; height: 54px; padding: 0 22px 0 16px;
  background: var(--red); color: #fff; border-radius: 999px; box-shadow: 0 10px 28px -6px rgba(190,0,0,.55), 0 2px 6px rgba(0,0,0,.15);
  font-family: var(--label); font-weight: 600; font-size: 13px; letter-spacing: .08em; text-transform: uppercase;
  transition: transform .18s ease, background .18s ease, box-shadow .18s ease;
}
.launcher:hover { background: var(--red-dark); transform: translateY(-2px); }
.launcher:focus-visible, .icon-btn:focus-visible, .chip:focus-visible, .send:focus-visible, .src:focus-visible, .act:focus-visible, .nudge-x:focus-visible, .steps-toggle:focus-visible {
  outline: 3px solid var(--focus); outline-offset: 2px;
}
.launcher .ico { width: 24px; height: 24px; }
.root[data-open="true"] .launcher { width: 54px; padding: 0; justify-content: center; }
.root[data-open="true"] .launcher .txt { display: none; }
.launcher .x { display: none; width: 22px; height: 22px; }
.root[data-open="true"] .launcher .x { display: block; }
.root[data-open="true"] .launcher .ico { display: none; }

/* greeting nudge */
.nudge {
  position: relative; max-width: 270px; background: var(--surface); border-radius: 14px 14px 4px 14px;
  padding: 14px 34px 14px 16px; box-shadow: var(--shadow); font-size: 14px; color: var(--ink);
  animation: rise .35s ease both;
}
.nudge b { font-family: var(--head); font-weight: 600; display: block; margin-bottom: 2px; color: var(--dark); }
.nudge-x { position: absolute; top: 8px; right: 8px; width: 22px; height: 22px; padding: 4px; color: var(--muted); border-radius: 6px; }
.nudge-x:hover { background: var(--bg); }
.root[data-open="true"] .nudge { display: none; }

/* panel */
.panel {
  width: 400px; height: min(640px, calc(100vh - 110px)); background: var(--bg);
  border-radius: 16px; overflow: hidden; box-shadow: var(--shadow);
  display: none; flex-direction: column; transform-origin: bottom right;
}
.root[data-open="true"] .panel { display: flex; animation: pop .22s cubic-bezier(.2,.9,.3,1.2) both; }
.root[data-expanded="true"] .panel { width: min(760px, calc(100vw - 48px)); height: calc(100vh - 110px); }

.head {
  background: var(--red); color: #fff; padding: 14px 12px 14px 16px; display: flex; align-items: center; gap: 12px;
  border-bottom: 4px solid var(--red-deep);
}
.mark { width: 38px; height: 38px; border-radius: 10px; background: #fff; color: var(--red); padding: 8px; flex: none; }
.titles { flex: 1; min-width: 0; }
.title { font-family: var(--head); font-weight: 600; font-size: 16px; line-height: 1.2; }
.sub { font-size: 12px; opacity: .9; display: flex; align-items: center; gap: 6px; margin-top: 2px; white-space: nowrap; }
.sub-txt { overflow: hidden; text-overflow: ellipsis; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 2px rgba(255,255,255,.25); }
.dot.off { background: var(--warn); }
.icon-btn { width: 34px; height: 34px; padding: 8px; border-radius: 8px; color: #fff; opacity: .92; flex: none; }
.icon-btn:hover { background: rgba(255,255,255,.16); opacity: 1; }

.banner { background: var(--surface); color: var(--ink); font-size: 12.5px; padding: 8px 16px 8px 12px; border-left: 4px solid var(--warn); border-bottom: 1px solid var(--line); }

.log { flex: 1; overflow-y: auto; overscroll-behavior: contain; padding: 18px 16px 8px; display: flex; flex-direction: column; gap: 16px; scroll-behavior: smooth; }
.root[data-expanded="true"] .log { padding: 24px 12%; }

/* welcome */
.welcome { display: flex; flex-direction: column; gap: 12px; animation: rise .3s ease both; }
.welcome h2 { font-family: var(--head); font-weight: 700; font-size: 22px; line-height: 1.2; margin: 6px 0 0; color: var(--dark); }
.welcome h2 span { color: var(--red); }
.welcome p { margin: 0; color: var(--ink-2); font-size: 14px; }
.eyebrow { font-family: var(--label); font-size: 11px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; color: var(--red); }
.chips { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
.chip {
  text-align: left; background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: 11px 14px; font-size: 14px; color: var(--ink); display: flex; align-items: center; gap: 10px;
  transition: border-color .15s, box-shadow .15s, transform .15s;
}
.chip:hover { border-color: var(--red); box-shadow: 0 3px 10px -4px rgba(190,0,0,.35); transform: translateX(2px); }
.chip .c-ico { width: 16px; height: 16px; color: var(--red); flex: none; }

.welcome .bubble p + p { margin-top: 6px; }
.welcome .bubble ul { margin: 2px 0 8px; }
.welcome .bubble .fine { font-size: 12.5px; color: var(--muted); }
.aud { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 2px; }
.aud-label { font-size: 13px; color: var(--muted); margin-right: 2px; }
.seg { border: 1.5px solid var(--line); background: var(--surface); border-radius: 999px; padding: 6px 13px; font-size: 13px; font-weight: 600; color: var(--ink-2); }
.seg:hover { border-color: var(--red); }
.seg[aria-pressed="true"] { background: var(--red); border-color: var(--red); color: #fff; }
.tip { font-size: 12.5px; color: var(--muted); margin: 2px 0 0; }

/* tabs and contact */
.tabs { display: flex; gap: 4px; padding: 0 12px; background: var(--surface); border-bottom: 1px solid var(--line); }
.tab { padding: 9px 12px 8px; font-family: var(--label); font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); border-bottom: 3px solid transparent; }
.tab:hover { color: var(--ink); }
.tab[aria-selected="true"] { color: var(--red); border-bottom-color: var(--red); }
.contact { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 14px; }
.contact h3 { font-family: var(--head); font-size: 16px; margin: 0; color: var(--dark); }
.contact > p { margin: 0; font-size: 13.5px; color: var(--ink-2); }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.card-title { font-family: var(--label); font-size: 10.5px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; color: var(--red); }
.card a { color: var(--red); font-weight: 600; text-decoration: none; font-size: 14px; }
.card a:hover { text-decoration: underline; }
.card .c-note { display: block; font-size: 12.5px; color: var(--muted); margin-top: 1px; }
.card .line { font-size: 13.5px; color: var(--ink); }
.card.support { border-left: 4px solid var(--red); }
.tab:focus-visible, .seg:focus-visible, .card a:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }

/* messages */
.msg { display: flex; gap: 10px; max-width: 100%; animation: rise .22s ease both; }
.msg.user { justify-content: flex-end; }
.bubble { padding: 10px 14px; border-radius: 14px; font-size: 14.5px; overflow-wrap: anywhere; }
.user .bubble { background: var(--red); color: #fff; border-bottom-right-radius: 4px; max-width: 85%; white-space: pre-wrap; }
.avatar { width: 28px; height: 28px; border-radius: 8px; background: var(--red); color: #fff; padding: 6px; flex: none; margin-top: 2px; }
.bot-col { display: flex; flex-direction: column; gap: 8px; min-width: 0; flex: 1; }
.bot .bubble { background: var(--surface); border: 1px solid var(--line); border-top-left-radius: 4px; color: var(--ink); }
.bubble p { margin: 0 0 8px; } .bubble p:last-child { margin-bottom: 0; }
.bubble ul, .bubble ol { margin: 4px 0 8px; padding-left: 20px; } .bubble li { margin: 3px 0; }
.bubble a { color: var(--red); font-weight: 600; text-decoration: underline; text-underline-offset: 2px; text-decoration-thickness: 1px; }
.bubble a:hover { text-decoration-thickness: 2px; }
.bubble strong { font-weight: 700; color: var(--dark); }
.bubble h3, .bubble h4 { font-family: var(--head); font-size: 15px; margin: 10px 0 4px; color: var(--dark); }
.bubble code { background: var(--bg); padding: 1px 5px; border-radius: 4px; font-size: 13px; }
.bubble.error { background: var(--surface); border-color: var(--red); color: var(--ink); }
.cursor > :last-child::after, .cursor:empty::after { content: ""; display: inline-block; width: 7px; height: 15px; margin-left: 2px; vertical-align: -2px; background: var(--red); border-radius: 1px; animation: blink 1s steps(2) infinite; }

/* live activity (what the bot is searching / reading) */
.steps { font-size: 12.5px; color: var(--muted); display: flex; flex-direction: column; gap: 4px; }
.step { display: flex; align-items: center; gap: 8px; }
.step .s-ico { width: 14px; height: 14px; flex: none; color: var(--muted); }
.spin { width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--line); border-top-color: var(--red); animation: spin .8s linear infinite; flex: none; }
.steps-toggle { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--muted); align-self: flex-start; }
.steps-toggle .chev { width: 14px; height: 14px; transition: transform .15s; }
.steps-toggle[aria-expanded="true"] .chev { transform: rotate(90deg); }
.steps-toggle:hover { color: var(--ink); }

/* sources */
.sources { display: flex; flex-direction: column; gap: 6px; }
.src-label { font-family: var(--label); font-size: 10.5px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.src-list { display: flex; flex-wrap: wrap; gap: 6px; }
.src {
  display: inline-flex; align-items: center; gap: 6px; max-width: 100%; background: var(--surface); border: 1px solid var(--line);
  border-radius: 999px; padding: 5px 11px 5px 8px; font-size: 12.5px; color: var(--ink); text-decoration: none;
}
.src:hover { border-color: var(--red); color: var(--red); }
.src .p-ico { width: 14px; height: 14px; color: var(--red); flex: none; }
.src span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.src-date { font-style: normal; color: var(--muted); font-size: 11px; white-space: nowrap; }

.actions { display: flex; gap: 2px; }
.act { width: 28px; height: 28px; padding: 6px; border-radius: 7px; color: var(--muted); }
.act:hover { background: var(--line); color: var(--ink); }
.act[aria-pressed="true"] { color: var(--red); background: var(--red-tint); }

/* composer */
.compose { padding: 10px 12px 6px; background: var(--bg); }
.box { display: flex; align-items: flex-end; gap: 8px; background: var(--surface); border: 1.5px solid var(--line); border-radius: 14px; padding: 6px 6px 6px 14px; transition: border-color .15s, box-shadow .15s; }
.box:focus-within { border-color: var(--red); box-shadow: 0 0 0 3px rgba(190,0,0,.12); }
textarea {
  flex: 1; border: 0; outline: 0; resize: none; font: inherit; font-size: 14.5px; color: var(--ink); background: transparent;
  padding: 7px 0; max-height: 120px; min-height: 22px; line-height: 1.45;
}
textarea::placeholder { color: var(--muted); }
.send { width: 36px; height: 36px; border-radius: 10px; background: var(--red); color: #fff; padding: 8px; flex: none; transition: background .15s, opacity .15s; }
.send:hover { background: var(--red-dark); }
.send:disabled { opacity: .35; cursor: default; }
.foot { font-size: 11px; color: var(--muted); text-align: center; padding: 4px 16px 10px; background: var(--bg); }

@keyframes pop { from { opacity: 0; transform: translateY(12px) scale(.96); } to { opacity: 1; transform: none; } }
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes blink { 50% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { *, *::after { animation: none !important; transition: none !important; } }

/* phones: full-screen panel */
@media (max-width: 560px) {
  .root { right: 16px; bottom: 16px; }
  .root[data-open="true"] { inset: 0; right: 0; bottom: 0; gap: 0; }
  .root[data-open="true"] .launcher { display: none; }
  .panel, .root[data-expanded="true"] .panel { width: 100vw; height: 100dvh; border-radius: 0; }
  .root[data-expanded="true"] .log { padding: 18px 16px 8px; }
  .expand-btn { display: none; }
  .launcher { height: 50px; }
}
`;

  // ---------------------------------------------------------------- markdown (tiny + safe)
  function esc(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  // Only University of Utah links are clickable: if a page the bot read carried injected
  // instructions, they can't turn the answer into a link to somewhere else.
  function trustedLink(u) {
    try {
      const h = new URL(u.replace(/&amp;/g, "&")).hostname;
      return h === "utah.edu" || h.endsWith(".utah.edu");
    } catch (_) { return false; }
  }
  function inline(s) {
    return esc(s)
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, (_, t, u) =>
        trustedLink(u) ? `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>` : t)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }
  function markdown(src) {
    const out = [];
    let list = null, para = [];
    const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
    const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; } };
    for (const raw of src.split("\n")) {
      const line = raw.trimEnd();
      let m;
      if (!line.trim()) { flushPara(); flushList(); continue; }
      if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { flushPara(); if (!list || list.tag !== "ul") { flushList(); list = { tag: "ul", items: [] }; } list.items.push(m[1]); continue; }
      if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { flushPara(); if (!list || list.tag !== "ol") { flushList(); list = { tag: "ol", items: [] }; } list.items.push(m[1]); continue; }
      if ((m = line.match(/^#{1,4}\s+(.*)/))) { flushPara(); flushList(); out.push(`<h4>${inline(m[1])}</h4>`); continue; }
      if (list && /^\s{2,}\S/.test(raw)) { list.items[list.items.length - 1] += " " + line.trim(); continue; }
      flushList(); para.push(line.trim());
    }
    flushPara(); flushList();
    return out.join("");
  }

  // ---------------------------------------------------------------- state
  let state = { sessionId: null, messages: [], open: false, expanded: false, nudged: false, audience: null };
  try { Object.assign(state, JSON.parse(sessionStorage.getItem(STORE_KEY) || "{}")); } catch (_) {}
  const save = () => {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify({ ...state, messages: state.messages.slice(-40) })); } catch (_) {}
  };
  let busy = false;
  let aiEnabled = true;

  // A signed per-browser token from the server; rate limits apply per token (see docs/SECURITY.md).
  const TOKEN_KEY = "price-assistant:token";
  async function getToken(fresh) {
    if (!fresh) {
      try {
        const saved = JSON.parse(localStorage.getItem(TOKEN_KEY) || "null");
        if (saved && saved.expires > Date.now() + 60_000) return saved.token;
      } catch (_) {}
    }
    const r = await fetch(`${API}/api/token`, { method: "POST" });
    if (!r.ok) {
      let detail = "Couldn't start a chat session.";
      try { detail = (await r.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    const { token, ttl_hours } = await r.json();
    try { localStorage.setItem(TOKEN_KEY, JSON.stringify({ token, expires: Date.now() + ttl_hours * 3600_000 })); } catch (_) {}
    return token;
  }

  // ---------------------------------------------------------------- DOM
  const kit = script && (script.dataset.adobeFonts || "").replace(/[^a-z0-9]/gi, "");
  if (kit && !document.querySelector(`link[href*="typekit.net/${kit}"]`)) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `https://use.typekit.net/${kit}.css`;
    document.head.appendChild(link);
  }
  if (!kit && (!script || script.dataset.loadFonts !== "false")) {
    if (!document.querySelector('link[href*="Work+Sans"]')) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&family=Poppins:wght@500;600&family=Work+Sans:wght@500;600;700&display=swap";
      document.head.appendChild(link);
    }
  }

  const host = document.createElement("div");
  host.id = "price-assistant";
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
<style>${CSS}</style>
<div class="root" data-open="false" data-expanded="false">
  <section class="panel" role="dialog" aria-label="Price Engineering Assistant chat">
    <header class="head">
      <div class="mark">${ICON.spark}</div>
      <div class="titles">
        <div class="title">Price Assistant</div>
        <div class="sub"><span class="dot"></span><span class="sub-txt">Answers from college sites</span></div>
      </div>
      <button class="icon-btn new-btn" title="New conversation" aria-label="Start a new conversation">${ICON.refresh}</button>
      <button class="icon-btn expand-btn" title="Expand" aria-label="Expand chat">${ICON.expand}</button>
      <button class="icon-btn close-btn" title="Close" aria-label="Close chat">${ICON.close}</button>
    </header>
    <nav class="tabs" role="tablist" aria-label="Assistant sections">
      <button class="tab" role="tab" id="tab-chat" aria-selected="true" aria-controls="view-chat" data-tab="chat">Chat</button>
      <button class="tab" role="tab" id="tab-contact" aria-selected="false" aria-controls="view-contact" data-tab="contact" tabindex="-1">Contact</button>
    </nav>
    <div class="banner" hidden></div>
    <div class="log" id="view-chat" role="log" aria-live="polite" aria-labelledby="tab-chat"></div>
    <div class="contact" id="view-contact" role="tabpanel" aria-labelledby="tab-contact" hidden></div>
    <form class="compose">
      <div class="box">
        <textarea rows="1" maxlength="${MAX_LEN}" placeholder="Ask about programs, admissions, research…" aria-label="Your question"></textarea>
        <button class="send" type="submit" aria-label="Send" disabled>${ICON.send}</button>
      </div>
    </form>
    <div class="foot">AI can make mistakes; check the linked pages. Please don't share personal info like your uNID or grades.</div>
  </section>
  <div class="nudge" role="status" hidden>
    <b>Questions about Price Engineering?</b>
    Ask me about majors, admissions, research or student resources.
    <button class="nudge-x" aria-label="Dismiss">${ICON.close}</button>
  </div>
  <button class="launcher" aria-expanded="false" aria-label="Open the Price Engineering Assistant">
    <span class="ico">${ICON.spark}</span><span class="x">${ICON.close}</span><span class="txt">Ask Price</span>
  </button>
</div>`;
  document.body.appendChild(host);

  const $ = (sel) => shadow.querySelector(sel);
  const root = $(".root"), log = $(".log"), input = $("textarea"), sendBtn = $(".send"), launcher = $(".launcher");

  function setOpen(open) {
    state.open = open; save();
    root.dataset.open = String(open);
    launcher.setAttribute("aria-expanded", String(open));
    launcher.setAttribute("aria-label", open ? "Close the assistant" : "Open the Price Engineering Assistant");
    if (open) {
      $(".nudge").hidden = true; state.nudged = true; save();
      checkStatus();
      setTimeout(() => input.focus(), 50);
      scrollDown();
    } else {
      launcher.focus();
    }
  }
  function setExpanded(exp) {
    state.expanded = exp; save();
    root.dataset.expanded = String(exp);
    const b = $(".expand-btn");
    b.innerHTML = exp ? ICON.shrink : ICON.expand;
    b.setAttribute("aria-label", exp ? "Shrink chat" : "Expand chat");
    b.title = exp ? "Shrink" : "Expand";
  }

  let statusChecked = false;
  async function checkStatus() {
    if (statusChecked) return;
    statusChecked = true;
    try {
      const s = await (await fetch(`${API}/api/status`)).json();
      aiEnabled = !!s.ai_enabled;
      if (aiEnabled && (s.ai_issue === "no_credits" || s.ai_issue === "daily_budget")) {
        $(".dot").classList.add("off");
        $(".sub-txt").textContent = "Search only: AI paused";
        const b = $(".banner");
        b.hidden = false;
        b.textContent = s.ai_issue === "daily_budget"
          ? "AI answers are paused for the rest of today (daily usage limit). You'll see site-search results until then."
          : "AI answers are paused until the API account has credits. You'll see site-search results for now.";
      } else if (!aiEnabled) {
        $(".dot").classList.add("off");
        $(".sub-txt").textContent = "Demo mode: search only";
        const b = $(".banner");
        b.hidden = false;
        b.textContent = "AI is off until an API key is added. You'll see the raw site-search results for now.";
      }
    } catch (_) {
      statusChecked = false;
    }
  }

  const scrollDown = () => requestAnimationFrame(() => { log.scrollTop = state.messages.length ? log.scrollHeight : 0; });

  // ---------------------------------------------------------------- rendering
  function renderWelcome() {
    const w = document.createElement("div");
    w.className = "welcome";
    w.innerHTML = `
      <div class="msg bot"><div class="avatar">${ICON.spark}</div><div class="bot-col"><div class="bubble">
        <p><strong>Hi! I'm the Price Assistant.</strong> Skip digging through the college's websites. Just ask, and I'll find it and link the pages I used.</p>
        <ul>
          <li><strong>Plan courses</strong> from your major's 4-year plan</li>
          <li><strong>Find</strong> admissions steps, deadlines, scholarships</li>
          <li><strong>See what's on</strong> in the college this week</li>
          <li><strong>Reach</strong> the right advisor or office</li>
        </ul>
        <p class="fine">I can't see your records or do homework, and I don't replace your advisor.</p>
      </div></div></div>
      <div class="aud" role="group" aria-label="Which describes you?">
        <span class="aud-label">I'm a</span>
        <button class="seg" type="button" data-aud="prospective">Future student</button>
        <button class="seg" type="button" data-aud="current">Current student</button>
      </div>
      <div class="chips"></div>
      <p class="tip">Tip: mention your major or year, like "I'm starting computer science this fall. What would my first semester look like?"</p>`;
    const chips = w.querySelector(".chips");
    const paint = () => {
      const list = SUGGESTIONS[state.audience] || MIXED;
      chips.innerHTML = list.map((q) => `<button class="chip" type="button"><span class="c-ico">${ICON.spark}</span>${esc(q)}</button>`).join("");
      chips.querySelectorAll(".chip").forEach((c, i) => c.addEventListener("click", () => ask(list[i])));
      w.querySelectorAll(".seg").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.aud === state.audience)));
    };
    w.querySelectorAll(".seg").forEach((b) => b.addEventListener("click", () => {
      state.audience = state.audience === b.dataset.aud ? null : b.dataset.aud; save(); paint();
    }));
    paint();
    log.appendChild(w);
  }

  function renderContact() {
    const view = $(".contact");
    view.innerHTML = `
      <h3>Talk to a person</h3>
      <p>The assistant is a starting point. These people can give you answers for your situation.</p>
      ${CONTACTS.map((g) => `<div class="card"><div class="card-title">${esc(g.title)}</div>
        ${g.items.map(([label, url, note]) => `<div><a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)}</a><span class="c-note">${esc(note)}</span></div>`).join("")}
      </div>`).join("")}
      <div class="card"><div class="card-title">College office</div>
        <div class="line"><a href="tel:+18015816911">(801) 581-6911</a> · <a href="mailto:contact@coe.utah.edu">contact@coe.utah.edu</a></div>
        <div class="line">72 S. Central Campus Drive, WEB Room 1650</div>
        <div><a href="${P}/contact" target="_blank" rel="noopener">All college contacts</a></div>
      </div>
      <div class="card support"><div class="card-title">Need support right now?</div>
        <div class="line">Call or text <a href="tel:988">988</a> any time, or call the 24/7 crisis line at <a href="tel:+18015873000">801-587-3000</a>.</div>
        <div><a href="https://counselingcenter.utah.edu/services/crisis.php" target="_blank" rel="noopener">University Counseling Center crisis services</a></div>
      </div>`;
  }

  function setTab(tab) {
    const chat = tab === "chat";
    shadow.querySelectorAll(".tab").forEach((t) => {
      const on = t.dataset.tab === tab;
      t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1;
    });
    log.hidden = !chat; $(".compose").hidden = !chat; $(".contact").hidden = chat;
    if (!chat && !$(".contact").childElementCount) renderContact();
    if (chat) input.focus();
  }

  function renderUser(text) {
    const el = document.createElement("div");
    el.className = "msg user";
    el.innerHTML = `<div class="bubble"></div>`;
    el.querySelector(".bubble").textContent = text;
    log.appendChild(el);
    return el;
  }

  function renderBot(msg) {
    const el = document.createElement("div");
    el.className = "msg bot";
    el.innerHTML = `<div class="avatar">${ICON.spark}</div>
      <div class="bot-col">
        <div class="steps" hidden></div>
        <div class="bubble" hidden></div>
        <div class="sources" hidden></div>
        <div class="actions" hidden>
          <button class="act up" aria-label="Helpful" title="Helpful" aria-pressed="false">${ICON.up}</button>
          <button class="act down" aria-label="Not helpful" title="Not helpful" aria-pressed="false">${ICON.down}</button>
          <button class="act copy" aria-label="Copy answer" title="Copy">${ICON.copy}</button>
        </div>
      </div>`;
    log.appendChild(el);
    const view = {
      el,
      bubble: el.querySelector(".bubble"),
      steps: el.querySelector(".steps"),
      sources: el.querySelector(".sources"),
      actions: el.querySelector(".actions"),
    };
    if (msg) fillBot(view, msg);
    return view;
  }

  function fillBot(view, msg) {
    if (msg.text) { view.bubble.hidden = false; view.bubble.innerHTML = markdown(msg.text); }
    if (msg.error) { view.bubble.hidden = false; view.bubble.classList.add("error"); view.bubble.textContent = msg.error; }
    if (msg.steps && msg.steps.length) renderStepsCollapsed(view, msg.steps);
    if (msg.sources && msg.sources.items && msg.sources.items.length) renderSources(view, msg.sources);
    if (msg.text && !msg.error) wireActions(view, msg);
  }

  const TRANSIENT = /^(Thinking|Writing an answer)$/;
  function renderSteps(view, allSteps, live) {
    // "Thinking" / "Writing an answer" only matter while they're the current step.
    const steps = allSteps.filter((s, i) => !TRANSIENT.test(s) || i === allSteps.length - 1);
    view.steps.hidden = false;
    view.steps.innerHTML = steps.map((s, i) => {
      const active = live && i === steps.length - 1;
      return `<div class="step">${active ? '<span class="spin"></span>' : `<span class="s-ico">${ICON.check}</span>`}<span>${esc(s)}${active ? "…" : ""}</span></div>`;
    }).join("");
  }

  function renderStepsCollapsed(view, steps) {
    const done = steps.filter((s) => !TRANSIENT.test(s));
    if (!done.length) { view.steps.hidden = true; return; }
    view.steps.hidden = false;
    const reads = done.filter((s) => s.startsWith("Reading")).length;
    const parts = [];
    if (done.some((s) => s.startsWith("Search"))) parts.push("Searched the sites");
    if (reads) parts.push(`read ${reads} ${reads === 1 ? "page" : "pages"}`);
    if (done.some((s) => s.includes("events calendar"))) parts.push("checked the events calendar");
    const label = parts.length > 1 ? parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1] : parts[0] || "Done";
    view.steps.innerHTML = `<button class="steps-toggle" aria-expanded="false"><span class="chev">${ICON.chev}</span>${label}</button><div class="step-list" hidden></div>`;
    const btn = view.steps.querySelector(".steps-toggle"), list = view.steps.querySelector(".step-list");
    list.innerHTML = done.map((s) => `<div class="step"><span class="s-ico">${ICON.check}</span><span>${esc(s)}</span></div>`).join("");
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(open));
      list.hidden = !open;
    });
  }

  function renderSources(view, sources) {
    view.sources.hidden = false;
    view.sources.innerHTML = `<div class="src-label">${sources.kind === "cited" ? "Sources" : "Related pages"}</div>
      <div class="src-list">${sources.items.map((s) => `<a class="src" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer" title="${esc(s.url)}${s.updated ? ` (updated ${esc(s.updated)})` : ""}"><span class="p-ico">${ICON.page}</span><span>${esc(s.title)}</span>${s.updated ? `<em class="src-date">${esc(shortDate(s.updated))}</em>` : ""}</a>`).join("")}</div>`;
  }

  function shortDate(iso) {
    const d = new Date(iso + "T12:00:00");
    return isNaN(d) ? "" : d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
  }

  function wireActions(view, msg) {
    view.actions.hidden = false;
    const up = view.actions.querySelector(".up"), down = view.actions.querySelector(".down"), copy = view.actions.querySelector(".copy");
    const mark = () => {
      up.setAttribute("aria-pressed", String(msg.rating === 1));
      down.setAttribute("aria-pressed", String(msg.rating === -1));
    };
    mark();
    const rate = (r) => {
      msg.rating = msg.rating === r ? 0 : r; mark(); save();
      fetch(`${API}/api/feedback`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sessionId, rating: msg.rating, question: msg.question || "", answer: msg.text.slice(0, 8000) }),
      }).catch(() => {});
    };
    up.onclick = () => rate(1);
    down.onclick = () => rate(-1);
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(msg.text); copy.innerHTML = ICON.check; setTimeout(() => (copy.innerHTML = ICON.copy), 1200); } catch (_) {}
    };
  }

  function renderAll() {
    log.innerHTML = "";
    if (!state.messages.length) renderWelcome();
    for (const m of state.messages) m.role === "user" ? renderUser(m.text) : renderBot(m);
    scrollDown();
  }

  // ---------------------------------------------------------------- talking to the API
  async function ask(question) {
    question = question.trim().slice(0, MAX_LEN);
    if (!question || busy) return;
    busy = true; updateSend();
    if (log.hidden) setTab("chat");
    const w = log.querySelector(".welcome"); if (w) w.remove();

    state.messages.push({ role: "user", text: question }); save();
    renderUser(question);
    const msg = { role: "bot", text: "", steps: [], sources: null, question };
    const view = renderBot();
    log.setAttribute("aria-busy", "true");
    scrollDown();

    let frame = 0;
    const paint = () => {
      frame = 0;
      view.bubble.hidden = false;
      view.bubble.classList.add("cursor");
      view.bubble.innerHTML = markdown(msg.text);
      scrollDown();
    };

    try {
      const send = async (fresh) => fetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Chat-Token": await getToken(fresh) },
        body: JSON.stringify({ message: question, session_id: state.sessionId, audience: state.audience || undefined }),
      });
      let resp = await send(false);
      if (resp.status === 401) resp = await send(true);  // expired or server restarted: get a new token
      if (!resp.ok) {
        let detail = `Request failed (${resp.status}).`;
        try { detail = (await resp.json()).detail || detail; } catch (_) {}
        throw new Error(typeof detail === "string" ? detail : "Request failed.");
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) !== -1) {
          const chunk = buf.slice(0, cut); buf = buf.slice(cut + 2);
          let ev = "message", data = "";
          for (const line of chunk.split("\n")) {
            if (line.startsWith("event: ")) ev = line.slice(7);
            else if (line.startsWith("data: ")) data += line.slice(6);
          }
          const d = data ? JSON.parse(data) : {};
          if (ev === "session") { state.sessionId = d.id; save(); }
          else if (ev === "status") {
            msg.steps.push(d.text);
            if (!msg.text) renderSteps(view, msg.steps, true);
            scrollDown();
          } else if (ev === "delta") {
            if (!msg.text) view.steps.hidden = true;
            msg.text += d.text;
            if (!frame) frame = requestAnimationFrame(paint);
          } else if (ev === "replace") {
            msg.text = d.text; paint();
          } else if (ev === "sources") {
            msg.sources = { kind: d.kind, items: d.items };
          } else if (ev === "error") {
            msg.error = d.text;
          }
        }
      }
    } catch (err) {
      msg.error = err && err.message && !/fetch|network/i.test(err.message)
        ? err.message
        : "Couldn't reach the assistant server. Is it running?";
    }

    if (frame) cancelAnimationFrame(frame);
    view.bubble.classList.remove("cursor");
    if (msg.error && !msg.text) { msg.text = ""; }
    else if (msg.error) { msg.text += `\n\n_${msg.error}_`; delete msg.error; }
    view.steps.innerHTML = ""; view.steps.hidden = true;
    fillBot(view, msg);
    if (!msg.text && !msg.error) { msg.error = "No answer came back. Please try again."; fillBot(view, msg); }
    state.messages.push(msg); save();
    log.setAttribute("aria-busy", "false");
    busy = false; updateSend();
    scrollDown();
    input.focus();
  }

  function updateSend() {
    sendBtn.disabled = busy || !input.value.trim();
    input.placeholder = busy ? "Answering…" : "Ask about programs, admissions, research…";
  }

  // ---------------------------------------------------------------- events
  launcher.addEventListener("click", () => setOpen(!state.open));
  $(".close-btn").addEventListener("click", () => setOpen(false));
  $(".expand-btn").addEventListener("click", () => setExpanded(!state.expanded));
  $(".new-btn").addEventListener("click", () => {
    if (busy) return;
    if (state.sessionId) {
      fetch(`${API}/api/reset`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId }) }).catch(() => {});
    }
    state.sessionId = null; state.messages = []; save();
    renderAll(); input.focus();
  });
  shadow.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setTab(t.dataset.tab)));
  $(".tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const next = shadow.querySelector('.tab[aria-selected="false"]');
    setTab(next.dataset.tab); next.focus();
  });
  $(".nudge-x").addEventListener("click", () => { $(".nudge").hidden = true; state.nudged = true; save(); });
  $("form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value;
    input.value = ""; autosize(); ask(q);
  });
  const autosize = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 120) + "px"; updateSend(); };
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("form").requestSubmit(); }
  });
  shadow.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.open) setOpen(false); });

  // ---------------------------------------------------------------- boot
  renderAll();
  setExpanded(!!state.expanded);
  if (state.open || (script && script.dataset.open === "true")) setOpen(true);
  else if (!state.nudged) setTimeout(() => { if (!state.open) $(".nudge").hidden = false; }, 2500);

  window.PriceAssistant = { open: () => setOpen(true), close: () => setOpen(false), ask: (q) => { setOpen(true); ask(q); } };
})();
