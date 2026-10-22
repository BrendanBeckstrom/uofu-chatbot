// The hosted beta's server sleeps when nobody is using it and takes up to about two minutes to start again
// (docs/DEPLOY.md). Cloud Run turns away requests that arrive while it starts, and the browser sees those as
// network errors. PriceWake.ready() polls /api/status until the server answers, showing a "Starting up" screen
// meanwhile, and resolves with the status.
window.PriceWake = (() => {
  const API = window.PRICE_ASSISTANT_API || "";
  const GIVE_UP_MS = 180_000, RETRY_MS = 3_000, SHOW_AFTER_MS = 800;
  const BLOCK_U = "https://www.price.utah.edu/wp-content/uploads/2023/01/cropped-block-u1-300x300.png";
  let pending = null, screen = null;

  const CSS = `
    .pw-wake { position: fixed; inset: 0; z-index: 2147483647; display: grid; place-items: center; padding: 24px 16px;
      background: #fff; color: #000; font: 16px/1.6 "Open Sans", system-ui, sans-serif; text-align: center; }
    .pw-box { max-width: 440px; }
    .pw-mark { position: relative; width: 112px; height: 112px; margin: 0 auto 28px; display: grid; place-items: center; }
    .pw-mark img { width: 60px; height: 60px; }
    .pw-ring { position: absolute; inset: 0; border-radius: 50%; border: 5px solid #E2E6E6; border-top-color: #BE0000;
      animation: pw-spin 1.1s linear infinite; }
    .pw-wake[data-state="failed"] .pw-ring { animation: none; border-top-color: #E2E6E6; }
    .pw-wake h1 { font: 700 24px/1.25 "Work Sans", system-ui, sans-serif; margin: 0 0 8px; }
    .pw-wake p { margin: 0 0 12px; }
    .pw-fine { font-size: 14px; color: #707271; }
    .pw-wake button { margin-top: 8px; font: 600 15px/1 "Work Sans", system-ui, sans-serif; color: #fff; background: #BE0000;
      border: 0; border-radius: 4px; padding: 13px 28px; cursor: pointer; }
    .pw-wake button:hover { background: #890000; }
    .pw-wake button:focus-visible { outline: 2px solid #000; outline-offset: 2px; }
    @keyframes pw-spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .pw-ring { animation-duration: 4s; } }`;

  function show() {
    if (screen) return;
    screen = document.createElement("div");
    screen.className = "pw-wake";
    screen.innerHTML = `<style>${CSS}</style>
      <div class="pw-box" role="status" aria-live="polite">
        <div class="pw-mark"><span class="pw-ring"></span><img src="${BLOCK_U}" alt="University of Utah"></div>
        <h1>Starting up the assistant…</h1>
        <p>This may take up to 2 minutes.</p>
        <p class="pw-fine">The AI runs on a backend server we use just for beta testing. It sleeps when no one is
          using it, so the first visit after a quiet spell has to wake it up.</p>
      </div>`;
    const mount = () => document.body.append(screen);
    document.body ? mount() : document.addEventListener("DOMContentLoaded", mount);
  }

  function hide() {
    if (screen) screen.remove();
    screen = null;
  }

  function fail() {
    show();
    screen.dataset.state = "failed";
    screen.querySelector(".pw-box").innerHTML = `${screen.querySelector(".pw-mark").outerHTML}
      <h1>The assistant isn't responding</h1>
      <p>Its server didn't start within 3 minutes. Please try again in a few minutes.</p>
      <button type="button">Try again</button>`;
    screen.querySelector("button").addEventListener("click", () => location.reload());
  }

  async function poll() {
    const start = Date.now();
    const timer = setTimeout(show, SHOW_AFTER_MS);
    for (;;) {
      const left = GIVE_UP_MS - (Date.now() - start);
      try {
        // A request that arrives first may be held until the server is up, so allow up to the time that's left.
        const r = await fetch(`${API}/api/status`, { cache: "no-store", signal: AbortSignal.timeout(Math.max(left, 5_000)) });
        if (r.ok) {
          const status = await r.json();
          clearTimeout(timer);
          hide();
          return status;
        }
      } catch (_) {}
      show();
      if (Date.now() - start >= GIVE_UP_MS) {
        clearTimeout(timer);
        fail();
        throw new Error("server_not_responding");
      }
      await new Promise((res) => setTimeout(res, RETRY_MS));
    }
  }

  // Concurrent callers share one wait; a finished wait isn't reused, so a later call checks the server again.
  function ready() {
    if (!pending) pending = poll().finally(() => { pending = null; });
    return pending;
  }

  return { ready };
})();
