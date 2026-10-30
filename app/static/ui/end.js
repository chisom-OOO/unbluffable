// End card. /ui/end?session=ID renders that session's report from /api/interview/ID/report;
// /ui/end alone renders the labelled sample from fake data. The four labels below are the
// only verdict vocabulary (spec/01).
document.addEventListener("DOMContentLoaded", () => {
  const { highlight, escapeHtml, receiptHtml } = window.UB;
  const $ = (id) => document.getElementById(id);
  const sessionId = new URLSearchParams(location.search).get("session");

  if (!sessionId) { render(window.UB_FAKE.end); return; }
  $("result-tag").textContent = "Your result";
  document.title = "Your result · Unbluffable";
  fetch(`/api/interview/${encodeURIComponent(sessionId)}/report`)
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(render)
    .catch(() => {
      $("end-sub").textContent = "This report is no longer available. Reports are kept in memory for the session only.";
      $("result-tag").hidden = true;
      document.querySelectorAll(".section, .end-verdict, .report-cols").forEach((el) => { el.hidden = true; });
    });

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

    if (sessionId && e.drills && e.drills.length) {
      $("drills").hidden = false;
      $("drill-list").innerHTML = e.drills.map((d) =>
        `<div class="drill-row"><p>${escapeHtml(d.misconception)}</p>` +
        `<a class="btn btn-small" href="/ui/interview?drill=${encodeURIComponent(sessionId)}&m=${d.index}">Drill this mistake</a></div>`).join("");
    }
    $("tip-section").hidden = !e.tip;
    $("estimate-section").hidden = !(e.estimate && e.estimate.length);

    $("evidence").innerHTML = e.evidence.map((q) =>
      `<blockquote class="evidence"><p>“${q.challenge ? highlight(q.quote, q.challenge) : escapeHtml(q.quote)}”</p><footer>${escapeHtml(q.note)}</footer>${receiptHtml(q.receipt)}</blockquote>`).join("");

    $("check").innerHTML = e.checks.map((c) =>
      `<div class="check-row">${escapeHtml(c.q)}, exact check: you said <span class="mono">${escapeHtml(c.said)}</span>; the answer is <span class="mono">${escapeHtml(c.exact)}</span>.${receiptHtml(c.receipt)}</div>`).join("") +
      (e.follow_ups || []).map((f) =>
      `<div class="check-row">${escapeHtml(f.q)}, follow-up: ${escapeHtml(f.verdict)}.${receiptHtml(f.receipt)}</div>`).join("");

    const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    const levelBars = Array.from({ length: e.levels }, (_, i) => `<span class="${i < e.level ? "on" : ""}"></span>`).join("");
    $("stats").innerHTML = [
      `<div class="stat"><dt>Challenges</dt><dd>${e.challenges}</dd></div>`,
      `<div class="stat"><dt>Nudges</dt><dd>${e.nudges}</dd></div>`,
      `<div class="stat"><dt>Hints used</dt><dd>${e.hints.length}</dd></div>`,
      ...e.times.map((t) => {
        const over = t.seconds > t.guide;
        return `<div class="stat"><dt>${escapeHtml(t.q)} vs guide</dt><dd class="${over ? "over" : ""}">${fmt(t.seconds)}<small>guide ${fmt(t.guide)}${over ? " · over" : ""}</small></dd></div>`;
      }),
      // The challenge is its own help step (decision log 3b), so it is not counted as a nudge here.
      ...(e.outcomes
        ? e.outcomes.map((o) => `<div class="stat wide"><dt>${escapeHtml(o.q)}</dt><dd>${escapeHtml(o.text)}${receiptHtml(o.receipt)}</dd></div>`)
        : [`<div class="stat wide"><dt>After the challenge</dt><dd>${e.recovered ? `Recovered after ${e.nudges} nudge${e.nudges === 1 ? "" : "s"}` : "Not recovered"}</dd></div>`]),
      ...(e.level == null ? [] : [`<div class="stat wide"><dt>Level reached</dt><dd>${e.level} of ${e.levels}<small>Shown separately from the label.</small><div class="level-track" aria-hidden="true">${levelBars}</div></dd></div>`]),
    ].join("");

    $("hints").innerHTML = e.hints.length
      ? e.hints.map((h) => `<li><span class="tag tag-hint">Hint</span><p class="says">${escapeHtml(h.text)}</p></li>`).join("")
      : `<li>No hints used.</li>`;

    $("tip").textContent = e.tip || "";

    // ---- Report (decision log 8): summary, doing well / improve, one tab per question ----
    const r = e.report;
    const item = (it) =>
      `<article class="report-item"><h3>${escapeHtml(it.title)}</h3>` +
      `<p>${escapeHtml(it.text)}</p>` +
      (it.quote ? `<p class="report-quote">“${escapeHtml(it.quote)}”</p>` : "") +
      (it.number
        ? `<p class="check-line">You said <span class="mono">${escapeHtml(it.number.said)}</span>; exact maths: <span class="mono">${escapeHtml(it.number.exact)}</span>.</p>`
        : it.verdict ? `<p class="check-line">${escapeHtml(it.verdict)}</p>` : "") +
      `<p class="chips">${(it.seen_names || it.seen.map((n) => `Question ${n}`)).map((s) => `<span class="chip">Seen in: ${escapeHtml(s)}</span>`).join("")}</p>` +
      receiptHtml(it.receipt) + `</article>`;
    $("overall").textContent = r.overall;
    $("well").innerHTML = r.well.map(item).join("");
    $("improve").innerHTML = r.improve.map(item).join("");

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
