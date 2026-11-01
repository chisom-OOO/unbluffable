// /ui/byoq (decision log 38): upload or paste one question, confirm what the model read, then the
// check in code (POST /api/byoq/check, polled). Ready opens the room on /ui/interview?byoq=<token>.
// The image goes to the server once and is not kept here either: only the file input holds it.
document.addEventListener("DOMContentLoaded", () => {
  const { escapeHtml } = window.UB;
  const $ = (id) => document.getElementById(id);
  const MAX = 5 * 1024 * 1024;
  const TYPES = ["image/png", "image/jpeg"];
  const ORDER = ["reading", "solvers", "variants", "ready"];
  let read = null, polling = null;

  const show = (id, on = true) => { $(id).hidden = !on; };
  function status(text) { $("byoq-status").hidden = !text; $("byoq-status").textContent = text || ""; }
  function stage(name) {
    const at = ORDER.indexOf(name);
    $("byoq-steps").querySelectorAll("li").forEach((li, i) => {
      li.classList.toggle("done", i < at || name === "ready");
      li.classList.toggle("now", i === at && name !== "ready");
      if (i === at) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
  }
  function reset() {
    clearTimeout(polling);
    read = null;
    $("byoq-file").value = "";
    $("byoq-text").value = "";
    $("byoq-stated").value = "";
    ["byoq-confirm", "byoq-progress", "byoq-result"].forEach((id) => show(id, false));
    show("byoq-upload");
    status("");
  }

  async function sendRead(body, type) {
    status("");
    show("byoq-progress"); stage("reading");
    $("byoq-wait").textContent = "Reading your question.";
    try {
      const r = await fetch("/api/byoq/read", { method: "POST", headers: { "Content-Type": type }, body });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || "We couldn't read that. Try a sharper photo, or paste the question as text.");
      read = data;
      $("byoq-text").value = data.question_text;
      $("byoq-stated").value = data.stated_answer || "";
      $("byoq-read-by").textContent = `Read by ${data.model === "muse-spark-1.3" ? "Muse Spark 1.3" : "Muse Spark Open"}.`;
      $("byoq-flag").hidden = data.single_exact_numeric_answer;
      $("byoq-flag").textContent = data.single_exact_numeric_answer ? ""
        : "This doesn't look like a question with one exact number for an answer, so it can't be checked in code. Edit it if it was misread.";
      show("byoq-progress", false); show("byoq-upload", false); show("byoq-confirm");
      $("byoq-text").focus();
    } catch (error) {
      show("byoq-progress", false);
      status(error.message);
    }
  }

  function pick(file) {
    if (!file) return;
    if (!TYPES.includes(file.type)) { status("Upload a PNG or JPEG image, or paste the question as text."); return; }
    if (file.size > MAX) { status("That image is over 5 MB. Crop it to the one question and try again."); return; }
    sendRead(file, file.type);
    $("byoq-file").value = "";
  }
  $("byoq-file").addEventListener("change", (e) => pick(e.target.files[0]));
  const drop = $("byoq-drop");
  ["dragenter", "dragover"].forEach((k) => drop.addEventListener(k, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((k) => drop.addEventListener(k, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => pick(e.dataTransfer.files[0]));
  $("byoq-read-text").addEventListener("click", () => {
    const text = $("byoq-paste").value.trim();
    if (!text) { status("Paste one question to read."); return; }
    sendRead(JSON.stringify({ text }), "application/json");
  });
  $("byoq-restart").addEventListener("click", reset);

  $("byoq-check").addEventListener("click", async () => {
    const text = $("byoq-text").value.trim();
    if (!text) { status("The question is empty."); return; }
    status("");
    show("byoq-confirm", false); show("byoq-progress"); stage("solvers");
    $("byoq-wait").textContent = "This may take a minute or two.";
    try {
      const r = await fetch("/api/byoq/check", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, stated: $("byoq-stated").value.trim() || null, topic: read ? read.topic : null }) });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || "The check couldn't start. Try again in a minute.");
      if (data.second === "simulation") $("byoq-solvers-step").textContent = "Writing a solver and a simulation";
      poll(data.job);
    } catch (error) {
      show("byoq-progress", false); show("byoq-confirm");
      status(error.message);
    }
  });

  function poll(job) {
    polling = setTimeout(async () => {
      let data;
      try {
        const r = await fetch(`/api/byoq/check/${encodeURIComponent(job)}`);
        data = await r.json();
        if (!r.ok) throw new Error(data.detail);
      } catch (error) {
        show("byoq-progress", false);
        status((error && error.message) || "The check stopped. Start again.");
        return;
      }
      if (data.stage === "ready" || data.stage === "failed") { finish(data); return; }
      stage(data.stage);
      poll(job);
    }, 1500);
  }

  function finish(data) {
    show("byoq-progress", false); show("byoq-result");
    if (data.stage === "ready") {
      stage("ready");
      $("byoq-verdict").textContent = `Checked in code on ${data.variants} variants.`;
      $("byoq-detail").textContent = "You'll answer your question, then the same puzzle with new numbers. Not counted toward your rating.";
      $("byoq-next").innerHTML = `<a class="btn" href="${escapeHtml(data.href)}">Practise it →</a>`
        + `<button class="linkbtn" type="button" id="byoq-another">Check another question</button>`;
    } else {
      $("byoq-verdict").textContent = data.message || "We couldn't check this one in code, so we won't score it.";
      $("byoq-detail").textContent = data.similar ? `Try a similar question from the bank instead: ${data.similar.topic}.` : "";
      $("byoq-next").innerHTML = (data.similar ? `<a class="btn" href="${escapeHtml(data.similar.href)}">Try a similar question →</a>` : "")
        + `<button class="linkbtn" type="button" id="byoq-another">Use a different question</button>`;
    }
    $("byoq-another").addEventListener("click", reset);
    $("byoq-verdict").focus?.();
  }
});
