// Coding rounds in the Exam Room (decision logs 26 and 27): a full-viewport workspace. Left:
// tabs "Problem | Conversation" (the transcript moves into the Conversation tab). Right: the
// toolbar (Python status, Reset, font size, Run Ctrl+' and Submit Ctrl+Enter), a banner with
// the interviewer's latest line, the editor (CodeMirror 5, pinned on cdnjs; a plain text area
// if it can't load) and a collapsible console "Test results | Output". Python runs in a Web
// Worker (py-worker.js, Pyodide). interview.js owns the socket and the transcript; it passes
// `send` (which waits for an open voice capture to close first).
(() => {
  // ---------- Pure helpers (also used by the Node unit check) ----------
  const escapeText = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // "minimise_largest_group_total" -> "Minimise largest group total"
  function titleFromName(name) {
    const words = String(name || "").split("_").filter(Boolean).join(" ");
    return words ? words[0].toUpperCase() + words.slice(1) : "Coding problem";
  }

  // The statement as body text: parameter names (and `backticked` words) as inline code, and
  // "nonempty"-style words hyphenated. Deterministic; the stored statement is never changed.
  const HYPHENATE = { nonempty: "non-empty", nonnegative: "non-negative", nonzero: "non-zero", nonpositive: "non-positive",
                      nondecreasing: "non-decreasing", nonincreasing: "non-increasing" };
  function statementHtml(statement, names) {
    let html = escapeText(statement || "");
    html = html.replace(/`([^`]+)`/g, (_, w) => `\u0000${w}\u0001`);
    html = html.replace(/\b(non(?:empty|negative|zero|positive|decreasing|increasing))\b/gi,
                        (w) => (w[0] === "N" ? "N" + HYPHENATE[w.toLowerCase()].slice(1) : HYPHENATE[w.toLowerCase()]));
    const sorted = [...new Set(names || [])].filter((n) => /^[A-Za-z_]\w*$/.test(n)).sort((a, b) => b.length - a.length);
    if (sorted.length) {
      const re = new RegExp(`(\\u0000[^\\u0001]*\\u0001)|\\b(${sorted.join("|")})\\b`, "g");
      html = html.replace(re, (m, kept, name) => kept || `\u0000${name}\u0001`);
    }
    html = html.replace(/\u0000([^\u0001]*)\u0001/g, (_, w) => `<code>${w}</code>`);
    return html.split(/\n{2,}/).map((p) => `<p>${p.trim()}</p>`).join("");
  }

  // "values = [26, 29], groups = 3" (Python-style spacing)
  const pyValue = (v) => (Array.isArray(v) ? `[${v.map(pyValue).join(", ")}]` : JSON.stringify(v));
  function inputLine(names, args) {
    return args.map((a, i) => `${names[i] || `arg${i + 1}`} = ${pyValue(a)}`).join(", ");
  }

  // Lines in `now` that weren't in `before` (and the reverse): a cheap measure of an edit.
  function changedLines(before, now) {
    const a = before.split("\n").map((l) => l.trim()).filter(Boolean), b = now.split("\n").map((l) => l.trim()).filter(Boolean);
    const inA = new Set(a), inB = new Set(b);
    return b.filter((l) => !inA.has(l)).length + a.filter((l) => !inB.has(l)).length;
  }

  if (typeof module !== "undefined") {
    module.exports = { titleFromName, statementHtml, inputLine, changedLines };
    return;
  }

  // ---------- The page ----------
  const CM = "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/";
  const PAUSE_MS = 20000;            // a 20 s typing pause may prompt a question about the code
  const EDIT_SETTLE_MS = 3000, EDIT_LINES = 4;  // a notable edit: 4+ changed lines, then 3 s still
  const EXAMPLES_MS = 15000, TESTS_MS = 30000;  // after Python has loaded
  const FONT = { min: 11, max: 22, key: "ub-code-font" }, SPLIT = { min: 25, max: 65, key: "ub-code-split" };
  const CONSOLE = { min: 80, max: 520, key: "ub-code-console" };
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.UB.escapeHtml(String(t));
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
                  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private window */ } } };

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const tag = Object.assign(document.createElement("script"), { src });
      tag.onload = resolve; tag.onerror = reject;
      document.head.appendChild(tag);
    });
  }
  function loadCss(href) {
    document.head.appendChild(Object.assign(document.createElement("link"), { rel: "stylesheet", href }));
  }

  // ---------- Python in a worker; a run that takes too long ends the worker ----------
  class Runner {
    constructor(onStatus) { this.onStatus = onStatus; this.seq = 0; this.start(); }
    start() {
      this.worker = new Worker("/ui-static/py-worker.js");
      this.ready = new Promise((resolve, reject) => {
        this.worker.addEventListener("message", (e) => {
          if (e.data.ready) { this.onStatus("Python ready", "ok"); resolve(); }
          if (e.data.failed) { this.onStatus("Python couldn't load. Check your connection and reload.", "bad"); reject(new Error(e.data.failed)); }
        });
      });
      this.onStatus("Loading Python…", "wait");
    }
    async run(code, fn, cases, timeoutMs) {
      await this.ready;
      const id = ++this.seq;
      return new Promise((resolve) => {
        const timer = setTimeout(() => {
          this.worker.terminate();
          this.start();
          resolve({ timeout: true, stdout: "", results: cases.map(() => ({ ok: false, timeout: true, error: "Timed out" })) });
        }, timeoutMs);
        const listen = (e) => {
          if (e.data.id !== id) return;
          clearTimeout(timer);
          this.worker.removeEventListener("message", listen);
          resolve(e.data.compile_error ? { compile_error: e.data.compile_error, stdout: e.data.stdout || "", results: cases.map(() => ({ ok: false, error: e.data.compile_error })) }
                                       : { results: e.data.results, stdout: e.data.stdout || "" });
        };
        this.worker.addEventListener("message", listen);
        this.worker.postMessage({ id, code, fn, cases });
      });
    }
  }

  let spec = null, editor = null, runner = null, send = null, open = false, pauseTimer = null, editTimer = null, lastSent = "";
  let starter = "", names = [], lastOutputs = null, selectLeft = null, selectConsole = null;
  const code = () => (editor && editor.getValue ? editor.getValue() : $("code-editor").value);
  const status = (t, state) => { $("py-status").textContent = t; if (state) $("py-status").dataset.state = state; };

  async function makeEditor(initial) {
    const area = $("code-editor");
    area.value = initial;
    try {
      loadCss(CM + "codemirror.min.css");
      await loadScript(CM + "codemirror.min.js");
      await loadScript(CM + "mode/python/python.min.js");
      editor = window.CodeMirror.fromTextArea(area, { mode: "python", lineNumbers: true, indentUnit: 4, tabSize: 4,
                                                      indentWithTabs: false,
                                                      extraKeys: { Tab: (cm) => cm.replaceSelection("    ") } });
      editor.on("change", typed);
    } catch {
      editor = null;  // the plain text area still works
      area.addEventListener("input", typed);
    }
    applyFont(Number(store.get(FONT.key)) || 14);
  }

  function setCode(text) { if (editor) editor.setValue(text); else $("code-editor").value = text; }

  function typed() {
    clearTimeout(pauseTimer); clearTimeout(editTimer);
    if (!open) return;
    pauseTimer = setTimeout(() => {
      const now = code();
      if (open && now.trim() && now !== lastSent) { lastSent = now; send({ type: "code_pause", code: now }); }
    }, PAUSE_MS);
    editTimer = setTimeout(() => {
      const now = code();
      if (open && now.trim() && changedLines(lastSent || starter, now) >= EDIT_LINES) {
        lastSent = now; send({ type: "code_edit", code: now });
      }
    }, EDIT_SETTLE_MS);
  }

  // ---------- Layout: tabs, splitters, font size, console ----------
  function tabs(list, onChange) {
    const buttons = [...list.querySelectorAll('[role="tab"]')];
    const select = (b, focus) => {
      buttons.forEach((x) => {
        const on = x === b;
        x.setAttribute("aria-selected", String(on));
        x.tabIndex = on ? 0 : -1;
        $(x.getAttribute("aria-controls")).hidden = !on;
      });
      if (focus) b.focus();
      onChange?.(b);
    };
    buttons.forEach((b) => b.addEventListener("click", () => select(b)));
    list.addEventListener("keydown", (e) => {
      const i = buttons.indexOf(document.activeElement);
      if (i < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      const next = e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      select(buttons[next], true);
    });
    return select;
  }

  function applyFont(px) {
    const size = Math.max(FONT.min, Math.min(FONT.max, px));
    document.documentElement.style.setProperty("--code-font", `${size}px`);
    store.set(FONT.key, String(size));
    $("font-down").disabled = size <= FONT.min; $("font-up").disabled = size >= FONT.max;
    editor?.refresh();
  }
  const fontNow = () => Number(getComputedStyle(document.documentElement).getPropertyValue("--code-font").replace("px", "")) || 14;

  function applySplit(pct) {
    const v = Math.max(SPLIT.min, Math.min(SPLIT.max, Math.round(pct)));
    $("room").style.setProperty("--ws-left", `${v}%`);
    $("ws-split").setAttribute("aria-valuenow", String(v));
    store.set(SPLIT.key, String(v));
    editor?.refresh();
  }
  function applyConsole(px) {
    const v = Math.max(CONSOLE.min, Math.min(CONSOLE.max, Math.round(px)));
    $("coding-pane").style.setProperty("--console-h", `${v}px`);
    $("ws-hsplit").setAttribute("aria-valuenow", String(v));
    store.set(CONSOLE.key, String(v));
    editor?.refresh();
  }
  function drag(handle, onMove) {
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      handle.classList.add("dragging");
      const up = () => { handle.classList.remove("dragging"); handle.removeEventListener("pointermove", onMove); handle.removeEventListener("pointerup", up); };
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", up);
    });
  }
  function setConsoleOpen(on) {
    $("ws-console-body").hidden = !on;
    $("ws-hsplit").hidden = !on;
    $("coding-pane").classList.toggle("console-closed", !on);
    $("console-toggle").setAttribute("aria-expanded", String(on));
    $("console-toggle").textContent = on ? "Hide" : "Show";
    editor?.refresh();
  }

  function layout() {
    // The transcript, Done and the self-view move into the workspace (listeners stay attached).
    const conv = $("ws-conversation");
    ["log", "live", "type-panel", "finish"].forEach((id) => conv.appendChild($(id)));
    $("ws-done-slot").appendChild($("done"));
    $("ws-cam-slot").appendChild($("selfview"));
    document.body.classList.add("coding-mode");
    ["ws-title", "ws-pill", "drawer-toggle", "ws-left", "ws-split"].forEach((id) => { $(id).hidden = false; });
    selectLeft = tabs(document.querySelector("#ws-left .ws-tabs"), (b) => { if (b.id === "tab-conversation") $("ws-dot").hidden = true; });
    selectConsole = tabs(document.querySelector("#ws-console .ws-tabs"));
    applySplit(Number(store.get(SPLIT.key)) || 40);
    applyConsole(Number(store.get(CONSOLE.key)) || 200);
    drag($("ws-split"), (e) => { const r = $("room").getBoundingClientRect(); applySplit(((e.clientX - r.left) / r.width) * 100); });
    drag($("ws-hsplit"), (e) => { const r = $("coding-pane").getBoundingClientRect(); applyConsole(r.bottom - e.clientY); });
    $("ws-split").addEventListener("keydown", (e) => {
      const step = { ArrowLeft: -2, ArrowRight: 2 }[e.key];
      if (step) { e.preventDefault(); applySplit(Number($("ws-split").getAttribute("aria-valuenow")) + step); }
    });
    $("ws-hsplit").addEventListener("keydown", (e) => {
      const step = { ArrowUp: 20, ArrowDown: -20 }[e.key];
      if (step) { e.preventDefault(); applyConsole(Number($("ws-hsplit").getAttribute("aria-valuenow")) + step); }
    });
    $("console-toggle").addEventListener("click", () => setConsoleOpen($("ws-console-body").hidden));
    $("font-down").addEventListener("click", () => applyFont(fontNow() - 1));
    $("font-up").addEventListener("click", () => applyFont(fontNow() + 1));
    $("reset-code").addEventListener("click", () => {
      if (code() !== starter && !window.confirm("Reset your code to the starting signature?")) return;
      setCode(starter);
    });
    $("ws-banner-close").addEventListener("click", () => { $("ws-banner").hidden = true; });
    // Run: Ctrl+' ; Submit: Ctrl+Enter (not while typing an answer in the Conversation tab).
    document.addEventListener("keydown", (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.target.id === "type-answer") return;
      if (e.key === "'" && !$("run-examples").disabled) { e.preventDefault(); runExamples(); }
      if (e.key === "Enter" && !$("submit-code").disabled) { e.preventDefault(); submit(); }
    });
  }

  // ---------- The problem tab ----------
  function problem(s) {
    names = s.parameters.map((p) => p.name);
    $("ws-ptitle").textContent = titleFromName(s.function_name);
    $("ws-chips").innerHTML = [s.difficulty, s.topic].filter(Boolean).map((c) => `<span class="tag">${esc(c)}</span>`).join("");
    $("ws-statement").innerHTML = statementHtml(s.statement, names)
      + `<p class="ws-signature">Implement <code>${esc(s.signature.replace(/:$/, ""))}</code>.</p>`;
    $("ws-examples").innerHTML = s.examples.map((ex, i) => `<div class="ws-example"><h3>Example ${i + 1}</h3>`
      + `<p><span class="ws-k">Input:</span> <code>${esc(inputLine(names, ex.args))}</code></p>`
      + `<p><span class="ws-k">Output:</span> <code>${esc(ex.expected)}</code></p></div>`).join("");
    const p = s.provenance;
    if (p) {
      $("ws-provenance-text").textContent = `Written by ${p.author}: its solver reproduced the verified answer on ${p.solver_reproduced}/${p.variants} `
        + `variants through this signature, and ${p.wrong_methods} wrong method${p.wrong_methods === 1 ? " was" : "s were"} verified in code. `
        + "Your outputs are compared exactly with the stored answers.";
      $("ws-provenance").hidden = false;
    }
  }

  // ---------- The console ----------
  function caseHtml(label, args, expected, r) {
    const ok = r && r.ok && expected != null && r.value === expected;
    const got = !r ? "" : r.ok ? `<code>${esc(r.value)}</code>` : `<span class="bad">${esc(r.error)}</span>`;
    return `<div class="code-case ${r ? (ok ? "ok" : "bad") : ""}"><div class="code-case-head"><strong>${esc(label)}</strong>`
      + `${r && expected != null ? `<span class="code-mark">${ok ? "Passed" : "Failed"}</span>` : r ? `<span class="code-mark">Failed</span>` : ""}</div>`
      + `<dl><div><dt>Input</dt><dd><code>${esc(inputLine(names, args))}</code></dd></div>`
      + `<div><dt>Expected</dt><dd>${expected == null ? `<span class="fine">Hidden (not one of the examples)</span>` : `<code>${esc(expected)}</code>`}</dd></div>`
      + (r ? `<div><dt>Got</dt><dd>${got}</dd></div>` : "") + `</dl></div>`;
  }
  function showExamples(results) {
    $("code-results").innerHTML = spec.examples.map((ex, i) => caseHtml(`Example ${i + 1}`, ex.args, ex.expected, results ? results[i] : null)).join("");
  }
  function showOutput(stdout) {
    $("code-output").textContent = stdout && stdout.trim() ? stdout : "Nothing printed. print() output from Run and Submit shows here.";
  }

  async function runExamples() {
    $("run-examples").disabled = true;
    status("Running the examples…", "wait");
    const out = await runner.run(code(), spec.function_name, spec.examples.map((e) => e.args), EXAMPLES_MS);
    status(out.timeout ? "The examples took too long (over 15 s)." : out.compile_error ? out.compile_error : "Examples run.", out.timeout || out.compile_error ? "bad" : "ok");
    showExamples(out.results);
    showOutput(out.stdout);
    setConsoleOpen(true);
    selectConsole($("tab-results"));
    lastSent = code();
    send({ type: "code_run", code: lastSent, results: out.results });
    $("run-examples").disabled = !open;
  }

  async function submit() {
    $("submit-code").disabled = $("run-examples").disabled = true;
    status(`Running all ${spec.tests.length} tests…`, "wait");
    const out = await runner.run(code(), spec.function_name, spec.tests, TESTS_MS);
    status(out.timeout ? "The tests took too long (over 30 s)." : out.compile_error ? out.compile_error : "Submitted.", out.timeout || out.compile_error ? "bad" : "ok");
    showOutput(out.stdout);
    lastOutputs = out.results;
    lastSent = code();
    send({ type: "code_submit", code: lastSent, outputs: out.results });
  }

  window.UBCoding = {
    // A coding question arrived: lay out the workspace and get the editor and Python ready.
    async enter(publicSpec, sendFn) {
      spec = publicSpec; send = sendFn;
      document.getElementById("room").classList.add("coding");
      $("coding-pane").hidden = false;
      layout();
      problem(spec);
      showExamples(null);
      runner = runner || new Runner(status);
      starter = `${spec.signature}\n    pass\n`;
      await makeEditor(starter);
      $("run-examples").onclick = runExamples;
      $("submit-code").onclick = submit;
    },
    opened() { open = true; $("run-examples").disabled = $("submit-code").disabled = false; },
    closed() {
      open = false; clearTimeout(pauseTimer); clearTimeout(editTimer);
      $("run-examples").disabled = $("submit-code").disabled = $("reset-code").disabled = true;
      if (editor) editor.setOption("readOnly", true); else $("code-editor").readOnly = true;
    },
    // A submit's result: "47 / 50 passed", the first failing case, and the receipt (a named
    // wrong method when the outputs match one). A hidden test's expected value is never shown.
    result(event) {
      const left = event.submits_left, all = event.passed === event.total;
      const named = (event.receipt?.rows || []).find((r) => r.key === "forge_method");
      const idx = Number.isInteger(event.first_failing) ? event.first_failing : -1;
      let failing = "";
      if (!all && idx >= 0) {
        const shown = spec.examples.find((ex) => JSON.stringify(ex.args) === JSON.stringify(spec.tests[idx]));
        failing = caseHtml("First failing case", spec.tests[idx], shown ? shown.expected : null, (lastOutputs || [])[idx]);
      }
      $("code-results").innerHTML = `<div class="code-verdict ${all ? "ok" : "bad"}"><strong>${event.passed} / ${event.total} passed</strong>`
        + (all ? "" : left > 0 ? ` · ${left} submit${left === 1 ? "" : "s"} left` : " · no submits left")
        + (named ? `<p class="code-named">${esc(named.text)}</p>` : "")
        + `${window.UB.receiptHtml(event.receipt, { words: false })}</div>${failing}`;
      setConsoleOpen(true);
      selectConsole($("tab-results"));
      $("submits-left").textContent = all || left === 0 ? "" : `${left} submit${left === 1 ? "" : "s"} left`;
      if (open && !all && left > 0) $("submit-code").disabled = $("run-examples").disabled = false;
      status(all ? "All tests passed." : "Not all tests passed.", all ? "ok" : "bad");
    },
    // The interviewer spoke: a dot on the Conversation tab and the line as a banner over the editor.
    interviewerSaid(text) {
      if (!spec) return;
      if ($("tab-conversation").getAttribute("aria-selected") !== "true") $("ws-dot").hidden = false;
      $("ws-banner-text").textContent = text;
      $("ws-banner").hidden = false;
    },
    // The status pill: Listening / Speaking / Checking (from interview.js's render).
    status(state) {
      if (!spec) return;
      const label = { listening: "Listening", speaking: "Speaking", checking: "Checking", finished: "Finished" }[state] || "Waiting";
      $("ws-pill").textContent = label;
      $("ws-pill").dataset.state = state;
    },
    get active() { return !!spec; },
    get editing() { return open; },
  };
})();
