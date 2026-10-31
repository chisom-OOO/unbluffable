// Coding rounds in the Exam Room (decision log 26): the editor (CodeMirror 5, pinned on
// cdnjs; a plain text area if it can't load), Python in a Web Worker (py-worker.js, Pyodide),
// Run examples / Submit, and the results panel. interview.js owns the socket and the
// transcript; it passes `send` (which waits for an open voice capture to close first).
(() => {
  const CM = "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/";
  const PAUSE_MS = 20000;            // a 20 s typing pause may prompt a question about the code
  const EXAMPLES_MS = 15000, TESTS_MS = 30000;  // after Python has loaded
  const $ = (id) => document.getElementById(id);
  const esc = (t) => window.UB.escapeHtml(String(t));

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
          if (e.data.ready) { this.onStatus("Python ready"); resolve(); }
          if (e.data.failed) { this.onStatus("Python couldn't load. Check your connection and reload."); reject(new Error(e.data.failed)); }
        });
      });
      this.onStatus("Loading Python…");
    }
    async run(code, fn, cases, timeoutMs) {
      await this.ready;
      const id = ++this.seq;
      return new Promise((resolve) => {
        const timer = setTimeout(() => {
          this.worker.terminate();
          this.start();
          resolve({ timeout: true, results: cases.map(() => ({ ok: false, timeout: true, error: "Timed out" })) });
        }, timeoutMs);
        const listen = (e) => {
          if (e.data.id !== id) return;
          clearTimeout(timer);
          this.worker.removeEventListener("message", listen);
          resolve(e.data.compile_error ? { compile_error: e.data.compile_error, results: cases.map(() => ({ ok: false, error: e.data.compile_error })) }
                                       : { results: e.data.results });
        };
        this.worker.addEventListener("message", listen);
        this.worker.postMessage({ id, code, fn, cases });
      });
    }
  }

  let spec = null, editor = null, runner = null, send = null, open = false, pauseTimer = null, lastSent = "";
  const code = () => (editor && editor.getValue ? editor.getValue() : $("code-editor").value);
  const status = (t) => { $("py-status").textContent = t; };
  const fmtArgs = (args) => args.map((a) => JSON.stringify(a)).join(", ");

  async function makeEditor(initial) {
    const area = $("code-editor");
    area.value = initial;
    try {
      loadCss(CM + "codemirror.min.css");
      await loadScript(CM + "codemirror.min.js");
      await loadScript(CM + "mode/python/python.min.js");
      editor = window.CodeMirror.fromTextArea(area, { mode: "python", lineNumbers: true, indentUnit: 4, tabSize: 4,
                                                      indentWithTabs: false, viewportMargin: Infinity,
                                                      extraKeys: { Tab: (cm) => cm.replaceSelection("    ") } });
      editor.on("change", typed);
    } catch {
      editor = null;  // the plain text area still works
      area.addEventListener("input", typed);
    }
  }

  function typed() {
    clearTimeout(pauseTimer);
    if (!open) return;
    pauseTimer = setTimeout(() => {
      const now = code();
      if (open && now.trim() && now !== lastSent) { lastSent = now; send({ type: "code_pause", code: now }); }
    }, PAUSE_MS);
  }

  function showExamples(results) {
    $("code-results").innerHTML = `<h3>Examples</h3>` + spec.examples.map((ex, i) => {
      const r = results ? results[i] : null;
      const ok = r && r.ok && r.value === ex.expected;
      const got = !r ? "" : r.ok ? `<span class="mono">${esc(r.value)}</span>` : `<span class="bad">${esc(r.error)}</span>`;
      return `<div class="code-case ${r ? (ok ? "ok" : "bad") : ""}"><code>${esc(spec.function_name)}(${esc(fmtArgs(ex.args))})</code>`
        + `<span>expected <span class="mono">${esc(ex.expected)}</span>${r ? ` · got ${got}` : ""}</span></div>`;
    }).join("");
  }

  async function runExamples() {
    $("run-examples").disabled = true;
    status("Running the examples…");
    const out = await runner.run(code(), spec.function_name, spec.examples.map((e) => e.args), EXAMPLES_MS);
    status(out.timeout ? "The examples took too long (over 15 s)." : out.compile_error ? out.compile_error : "Examples run.");
    showExamples(out.results);
    lastSent = code();
    send({ type: "code_run", code: lastSent, results: out.results });
    $("run-examples").disabled = !open;
  }

  async function submit() {
    $("submit-code").disabled = $("run-examples").disabled = true;
    status(`Running all ${spec.tests.length} tests…`);
    const out = await runner.run(code(), spec.function_name, spec.tests, TESTS_MS);
    status(out.timeout ? "The tests took too long (over 30 s)." : out.compile_error ? out.compile_error : "Submitted.");
    lastSent = code();
    send({ type: "code_submit", code: lastSent, outputs: out.results });
  }

  window.UBCoding = {
    // A coding question arrived: lay out the room and get the editor and Python ready.
    async enter(publicSpec, sendFn) {
      spec = publicSpec; send = sendFn;
      document.getElementById("room").classList.add("coding");
      $("coding-pane").hidden = false;
      $("coding-examples").innerHTML = `<pre class="signature mono">${esc(spec.signature)}</pre>`
        + `<ul class="example-list">${spec.examples.map((e) => `<li><code>${esc(spec.function_name)}(${esc(fmtArgs(e.args))})</code> → <span class="mono">${esc(e.expected)}</span></li>`).join("")}</ul>`;
      showExamples(null);
      runner = runner || new Runner(status);
      await makeEditor(`${spec.signature}\n    pass\n`);
      $("run-examples").onclick = runExamples;
      $("submit-code").onclick = submit;
    },
    opened() { open = true; $("run-examples").disabled = $("submit-code").disabled = false; },
    closed() { open = false; clearTimeout(pauseTimer); $("run-examples").disabled = $("submit-code").disabled = true;
               if (editor) editor.setOption("readOnly", true); else $("code-editor").readOnly = true; },
    result(event) {
      const left = event.submits_left;
      $("code-results").insertAdjacentHTML("afterbegin",
        `<div class="code-verdict ${event.passed === event.total ? "ok" : "bad"}"><strong>${event.passed}/${event.total} tests passed</strong>`
        + (event.passed === event.total ? "" : left > 0 ? ` · ${left} submit${left === 1 ? "" : "s"} left` : " · no submits left")
        + `${window.UB.receiptHtml(event.receipt, { words: false })}</div>`);
      $("submits-left").textContent = event.passed === event.total || left === 0 ? "" : `${left} submit${left === 1 ? "" : "s"} left`;
      if (open && event.passed !== event.total && left > 0) $("submit-code").disabled = $("run-examples").disabled = false;
      status(event.passed === event.total ? "All tests passed." : "Not all tests passed.");
    },
    get active() { return !!spec; },
    get editing() { return open; },
  };
})();
