// A mixed quant interview (forge questions, then market making) in a real headless browser:
// the real interview page, with /api/interview/ws replaced by a fake socket that replays a
// recorded session (fake models) and moves on each time an answer is typed.
// Live bugs (Opera, Windows): the page went blank at the switch to the market game. The page
// had scrolled down during the questions; the market room is one screen tall, but hidden
// accessibility spans in the transcript escaped its scroll box, so the document stayed tall
// and the view was left far below the room.
//   node tests/market_switch_browser.cjs <events.json> <base url> <browser exe> <profile dir>
const fs = require("node:fs");
const { spawn } = require("node:child_process");
const assert = require("node:assert/strict");

const [, , eventsPath, base, browserExe, profileDir] = process.argv;
if (!eventsPath) { console.log("market switch browser: driven by tests/test_market_switch.py, skipped standalone"); process.exit(0); }
const EVENTS = fs.readFileSync(eventsPath, "utf8");
const PORT = 9300 + Math.floor(Math.random() * 600);

const FAKE_SOCKET = `(() => {
  const EVENTS = ${EVENTS};
  const Real = window.WebSocket;
  window.__errors = [];
  addEventListener("error", (e) => window.__errors.push(String(e.message)));
  window.WebSocket = function (url, protocols) {
    if (!String(url).includes("/api/interview/ws")) return new Real(url, protocols);
    let i = 0;
    const s = { readyState: 0, close() { s.readyState = 3; },
      send(d) { if (JSON.parse(d).type === "typed") setTimeout(next, 10); } };
    // Events up to the next "listening"; the next typed answer releases the rest.
    function next() {
      while (i < EVENTS.length) {
        const e = EVENTS[i++];
        s.onmessage && s.onmessage({ data: JSON.stringify(e) });
        if (e.type === "state" && e.value === "listening") return;
      }
    }
    setTimeout(() => { s.readyState = 1; s.onopen && s.onopen(); next(); }, 20);
    return s;
  };
  Object.assign(window.WebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
})();`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = spawn(browserExe, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profileDir}`,
    "--no-first-run", "--no-default-browser-check", "about:blank"], { stdio: "ignore" });
  try {
    let target;
    for (let k = 0; k < 100 && !target; k++) {
      try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page"); }
      catch {}
      // The debugger may be reachable before its first page exists.
      if (!target) await sleep(100);
    }
    assert.ok(target, "the browser opened a page");
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((r) => ws.addEventListener("open", r));
    let n = 0;
    const pending = new Map(), crashes = [];
    ws.addEventListener("message", ({ data }) => {
      const m = JSON.parse(data);
      if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
      if (m.method === "Runtime.exceptionThrown") crashes.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    });
    const cmd = (method, params = {}) => new Promise((r) => { const id = ++n; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
    const ev = async (expression) => (await cmd("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result?.result?.value;

    await cmd("Runtime.enable");
    await cmd("Page.enable");
    // A desktop window (the room gates out phone-sized screens), as in the live report (~1900 px).
    await cmd("Emulation.setDeviceMetricsOverride", { width: 1900, height: 1000, deviceScaleFactor: 1, mobile: false, screenWidth: 1920, screenHeight: 1080 });
    await cmd("Page.addScriptToEvaluateOnNewDocument", { source: FAKE_SOCKET });
    await cmd("Page.navigate", { url: `${base}/ui/interview` });
    for (let k = 0; k < 100 && !(await ev(`!!document.querySelector('button.track')`)); k++) await sleep(100);

    const started = await ev(`(async () => {
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      [...document.querySelectorAll("button.track")].find((b) => /quant/i.test(b.dataset.track || b.textContent))?.click();
      for (let k = 0; k < 50 && !document.querySelector('button.topic-chip[data-topic="Market making"]'); k++) await wait(100);
      for (const name of ["Probability", "Market making"]) document.querySelector('button.topic-chip[data-topic="' + name + '"]')?.click();
      document.getElementById("typed-practice").click();
      if (!document.getElementById("consent").checked) document.getElementById("consent").click();
      await wait(100);
      document.getElementById("start").click();
      await wait(300);
      return !document.getElementById("room").hidden;
    })()`);
    assert.equal(started, true, "the interview room opened");

    // Type an answer at every turn until the market game has been on screen for a few turns.
    // Live bug 3 (Opera, ~1900 px): "New message ↓" covered the interviewer's line. Once the page
    // is tall, the candidate scrolls up to read; at the next answer the button shows and must
    // cover no transcript text.
    let marketTurns = 0, armed = false, newLine = null;
    for (let k = 0; k < 400 && marketTurns < 3; k++) {
      await sleep(60);
      const turn = await ev(`(() => {
        const box = document.getElementById("type-answer"), done = document.getElementById("done");
        if (!box || box.closest("[hidden]") || done.disabled) return null;
        const market = document.getElementById("room").classList.contains("market");
        box.value = market ? "0 at 2000" : "My answer is one half."; box.dispatchEvent(new Event("input"));
        done.click();
        return market;
      })()`);
      if (turn === false && armed && !newLine) {
        await sleep(400);
        newLine = await ev(`(() => {
          const b = document.querySelector(".new-line");
          if (!b || b.hidden) return { shown: false };
          const r = b.getBoundingClientRect();
          // Transcript text is visible down to the top of the sticky dock (opaque); below it, it is hidden anyway.
          const dockTop = document.querySelector(".dock").getBoundingClientRect().top;
          const hits = [...document.querySelectorAll("#log .utterance .says, #log .utterance .speaker")].filter((t) => {
            const q = t.getBoundingClientRect(), bottom = Math.min(q.bottom, dockTop);
            return q.width > 0 && bottom > Math.max(0, q.top) && q.top < innerHeight && r.left < q.right && q.left < r.right && r.top < bottom && q.top < r.bottom;
          }).map((t) => t.textContent.slice(0, 40));
          return { shown: true, hits, rightAligned: r.right > document.querySelector(".dock .action-bar").getBoundingClientRect().right - 40 };
        })()`);
      }
      if (turn === false && !armed) {
        await sleep(1200);  // past the room's own smooth-scroll window, so the scroll counts as the candidate's
        armed = await ev(`(() => { const room = document.documentElement.scrollHeight - innerHeight;
          if (room < 600) return false; window.scrollTo(0, room - 400); return true; })()`);
        if (armed) await sleep(300);
      }
      if (turn === true) marketTurns++;
    }
    assert.ok(newLine && newLine.shown, `"New message" shows when scrolled up: ${JSON.stringify(newLine)}`);
    assert.deepEqual(newLine.hits, [], "New message covers no transcript text");
    assert.ok(newLine.rightAligned, "New message sits at the right, above the turn bar");
    assert.ok(marketTurns > 0, "the interview reached the market game");
    await sleep(300);

    const view = await ev(`(() => {
      const room = document.getElementById("room").getBoundingClientRect();
      return { top: room.top, bottom: room.bottom, height: innerHeight, scrollY,
               page: document.documentElement.scrollHeight, shell: document.querySelector(".shell").getBoundingClientRect().height,
               errors: window.__errors };
    })()`);
    assert.deepEqual(crashes, [], "no script errors");
    assert.deepEqual(view.errors, [], "no script errors");
    // The room is on screen, not scrolled away above an empty view.
    assert.ok(view.bottom > 0 && view.top < view.height, `the room is in view: ${JSON.stringify(view)}`);
    assert.ok(view.top > -100, `the room starts near the top of the view: ${JSON.stringify(view)}`);
    // Nothing in the transcript stretches the page past the room and footer.
    assert.ok(view.page <= view.shell + 400, `the page is no taller than its content: ${JSON.stringify(view)}`);
    console.log("market switch ok");
    ws.close();
  } finally {
    browser.kill();
  }
})().catch((e) => { console.error(e); process.exit(1); });
