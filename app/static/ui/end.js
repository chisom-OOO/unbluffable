// Report. /ui/end?session=ID renders that session's report from /api/interview/ID/report;
// without a session there is nothing to show. The four labels below are the only verdict
// vocabulary (spec/01).
document.addEventListener("DOMContentLoaded", () => {
  const { escapeHtml, receiptHtml } = window.UB;
  const $ = (id) => document.getElementById(id);
  const sessionId = new URLSearchParams(location.search).get("session");

  function unavailable(text) {
    $("end-sub").textContent = text;
    $("result-tag").hidden = true;
    document.querySelectorAll(".section, .end-verdict, #stats").forEach((el) => { el.hidden = true; });
  }
  if (!sessionId) { unavailable("No report to show yet. A report appears here at the end of an interview."); return; }
  fetch(`/api/interview/${encodeURIComponent(sessionId)}/report`)
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(render)
    .catch(() => unavailable("This report is no longer available. Reports are kept in memory for the session only."));

  function render(e) {

    const ICON = {
      check: '<path d="M20 6 9 17l-5-5"/>',
      cross: '<path d="M18 6 6 18M6 6l12 12"/>',
      dash: '<path d="M5 12h14"/>',
      more: '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>',
    };
    const LABELS = {
      supports: { text: "Evidence supports understanding", cls: "verdict-supports", icon: "check" },
      misconception: { text: "Misconception detected", cls: "verdict-misconception", icon: "cross" },
      "not-shown": { text: "Understanding not shown", cls: "verdict-not-shown", icon: "dash" },
      "more-evidence": { text: "More evidence needed", cls: "verdict-more-evidence", icon: "more" },
    };
    const svg = (k) => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;

    if (e.drill) {
      // Drill mode (decision log 16): the check's result, not an interview label.
      const cleared = e.drill.result === "Cleared";
      $("end-title").textContent = "How the drill went";
      $("end-eyebrow").textContent = "Drill report";
      $("result-tag").textContent = "Drill complete";
      $("verdict").innerHTML =
        `<p class="verdict ${cleared ? "verdict-supports" : "verdict-misconception"}">${svg(cleared ? "check" : "cross")}<span>${escapeHtml(e.drill.result || "Not finished")}</span></p>` +
        `<p class="misconception-name">Drilled: ${escapeHtml(e.drill.misconception)}. ${escapeHtml(e.drill.note)}</p>`;
      $("end-sub").textContent = `${e.questions} question${e.questions === 1 ? "" : "s"}, including the check.`;
    } else {
      const L = LABELS[e.label];
      $("verdict").innerHTML =
        `<p class="verdict ${L.cls}">${svg(L.icon)}<span>${L.text}</span></p>` +
        (e.label === "misconception" && e.misconception
          ? `<p class="misconception-name">${escapeHtml(e.misconception)}: ${escapeHtml(e.misconception_note || "reading “fraud gets flagged” as “a flag is fraud”.")}</p>` : "");
      $("end-sub").textContent = `${e.questions} question${e.questions === 1 ? "" : "s"}. Scored on where you end up, discounted by the help it took.`;
    }

    // Decision log 20: which mode was used.
    $("conditions").hidden = !e.conditions;
    $("conditions").textContent = e.conditions || "";
    $("conditions").classList.toggle("warn", !!e.conditions && !/^Exam/.test(e.conditions));

    if (sessionId && e.drills && e.drills.length) {
      $("drills").hidden = false;
      $("drill-list").innerHTML = e.drills.map((d) =>
        `<div class="drill-row"><p>${escapeHtml(d.misconception)}</p>` +
        `<a class="btn btn-small" href="/ui/interview?drill=${encodeURIComponent(sessionId)}&m=${d.index}">Drill this mistake</a></div>`).join("");
    }
    $("tip-section").hidden = !e.tip;
    $("estimate-section").hidden = !(e.estimate && e.estimate.length);

    // Evidence you can check: one card per question. Each answer is quoted here and only here,
    // beside the exact value and the receipt (its words are not repeated inside the receipt).
    // The receipt's span (the number you committed to) is marked where it was said.
    const mark = (text, span) => {
      const safe = escapeHtml(text), needle = span ? escapeHtml(span) : "";
      const at = needle ? safe.lastIndexOf(needle) : -1;
      return at < 0 ? safe : `${safe.slice(0, at)}<mark>${needle}</mark>${safe.slice(at + needle.length)}`;
    };
    const quote = (text, receipt) =>
      `<blockquote class="evidence"><p>“${receipt && receipt.words === text ? mark(text, receipt.span) : escapeHtml(text)}”</p></blockquote>`;
    const numberLine = (said, exact) => said
      ? `<p class="check-line">You said <span class="mono">${escapeHtml(said)}</span>; the exact value is <span class="mono">${escapeHtml(exact)}</span>.</p>`
      : `<p class="check-line">No committed number; the exact value is <span class="mono">${escapeHtml(exact)}</span>.</p>`;
    $("evidence").innerHTML = (e.cards || []).map((c) =>
      `<article class="qcard" id="${escapeHtml(c.anchor)}" tabindex="-1"><header><h3>${escapeHtml(c.q)}</h3><span class="tag">${escapeHtml(c.outcome)}</span></header>` +
      c.words.map((w) => `<p class="qcard-when">${escapeHtml(w.when)}</p>${quote(w.text, c.receipt)}`).join("") +
      numberLine(c.said, c.exact) + receiptHtml(c.receipt, { words: false }) +
      (c.part2 ? `<div class="qcard-extra"><p class="qcard-when">Part 2 · not scored</p><p class="fine">${escapeHtml(c.part2.question)}</p>` +
        quote(c.part2.words, c.part2.receipt) + (c.part2.said ? numberLine(c.part2.said, c.part2.exact) : "") +
        receiptHtml(c.part2.receipt, { words: false }) + `</div>` : "") +
      (c.follow_up ? `<div class="qcard-extra"><p class="qcard-when">Follow-up · model-matched, not scored</p><p class="fine">${escapeHtml(c.follow_up.question)}</p>` +
        quote(c.follow_up.words, c.follow_up.receipt) + `<p class="check-line">${escapeHtml(c.follow_up.verdict)}</p>` +
        receiptHtml(c.follow_up.receipt, { words: false }) + `</div>` : "") +
      `</article>`).join("");

    const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    // Numbers only: each question's outcome and words are on its evidence card.
    $("stats").innerHTML = [
      `<div class="stat"><dt>Questions</dt><dd>${e.questions}</dd></div>`,
      `<div class="stat"><dt>Challenges</dt><dd>${e.challenges}</dd></div>`,
      `<div class="stat"><dt>Nudges</dt><dd>${e.nudges}</dd></div>`,
      `<div class="stat"><dt>Hints used</dt><dd>${e.hints.length}</dd></div>`,
      ...e.times.map((t) => {
        const over = t.seconds > t.guide;
        return `<div class="stat"><dt>${escapeHtml(t.q)} vs guide</dt><dd class="${over ? "over" : ""}">${fmt(t.seconds)}<small>guide ${fmt(t.guide)}${over ? " · over" : ""}</small></dd></div>`;
      }),
      ...(e.level == null ? [] : [`<div class="stat"><dt>Level reached</dt><dd>${e.level} of ${e.levels}<small>Shown apart from the label</small></dd></div>`]),
    ].join("");

    $("hints").innerHTML = e.hints.length
      ? e.hints.map((h) => `<li><span class="tag tag-hint">Hint</span><p class="says">${escapeHtml(h.text)}</p></li>`).join("")
      : `<li>No hints used.</li>`;

    $("tip").textContent = e.tip || "";

    // ---- Report (decision log 8): summary, doing well / improve, one tab per question ----
    // Breakdown items keep timings, help and the follow-up, without quoting your words again.
    const r = e.report;
    const item = (it) =>
      `<article class="report-item"><h3>${escapeHtml(it.title)}</h3>` +
      `<p>${escapeHtml(it.text)}</p>` +
      (it.question ? `<p class="fine">${escapeHtml(it.question)}</p>` : "") +
      (it.number
        ? `<p class="check-line">You said <span class="mono">${escapeHtml(it.number.said)}</span>; exact maths: <span class="mono">${escapeHtml(it.number.exact)}</span>.</p>`
        : it.verdict ? `<p class="check-line">${escapeHtml(it.verdict)}</p>` : "") +
      receiptHtml(it.receipt, { words: false }) + `</article>`;
    // Doing well / to improve: one line each, pointing at the question's evidence card.
    const pointer = (it) => `<li><span>${escapeHtml(it.title)}</span>` +
      (it.anchor ? ` <a href="#${escapeHtml(it.anchor)}">See ${escapeHtml(it.see)}</a>` : "") + `</li>`;
    $("overall").textContent = r.overall;
    $("well").innerHTML = r.well.length ? r.well.map(pointer).join("") : "<li>Nothing to single out yet.</li>";
    $("improve").innerHTML = r.improve.length ? r.improve.map(pointer).join("") : "<li>Nothing to single out yet.</li>";

    $("breakdown-tabs").innerHTML = r.breakdown.map((b, i) =>
      `<button type="button" role="tab" class="tab" id="tab-${i}" aria-controls="panel-${i}" aria-selected="${i === 0}" tabindex="${i === 0 ? 0 : -1}">${escapeHtml(b.tab)}</button>`).join("");
    $("breakdown-panels").innerHTML = r.breakdown.map((b, i) =>
      `<div role="tabpanel" class="tab-panel" id="panel-${i}" aria-labelledby="tab-${i}" tabindex="0"${i === 0 ? "" : " hidden"}>` +
      `<p class="tab-sub">${escapeHtml(b.sub)}</p>${b.items.map(item).join("")}</div>`).join("");

    const tabs = [...document.querySelectorAll('#breakdown-tabs [role="tab"]')];
    function select(i, focus) {
      tabs.forEach((t, j) => {
        t.setAttribute("aria-selected", String(j === i));
        t.tabIndex = j === i ? 0 : -1;
        $(`panel-${j}`).hidden = j !== i;
      });
      if (focus) tabs[i].focus();
    }
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(i, false));
      t.addEventListener("keydown", (ev) => {
        const last = tabs.length - 1;
        const to = { ArrowRight: i === last ? 0 : i + 1, ArrowLeft: i === 0 ? last : i - 1, Home: 0, End: last }[ev.key];
        if (to === undefined) return;
        ev.preventDefault();
        select(to, true);
      });
    });

    $("estimate").innerHTML = e.estimate.map((r) =>
      `<tr><td>${escapeHtml(r.label)}</td><td class="mono num-col">${escapeHtml(r.p)}</td></tr>`).join("");
  }
});
