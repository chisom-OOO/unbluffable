// End card, rendered from fake data. The four labels below are the only verdict vocabulary (spec/01).
document.addEventListener("DOMContentLoaded", () => {
  const e = window.UB_FAKE.end;
  const { highlight, escapeHtml } = window.UB;
  const $ = (id) => document.getElementById(id);

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

  const L = LABELS[e.label];
  $("verdict").innerHTML =
    `<p class="verdict ${L.cls}">${svg(L.icon)}<span>${L.text}</span></p>` +
    (e.label === "misconception" && e.misconception ? `<p class="misconception-name">${escapeHtml(e.misconception)}: reading “fraud gets flagged” as “a flag is fraud”.</p>` : "");

  $("end-sub").textContent = `${e.questions} questions. Scored on where you end up, discounted by the help it took.`;

  $("evidence").innerHTML = e.evidence.map((q) =>
    `<blockquote class="evidence"><p>“${highlight(q.quote, q.challenge)}”</p><footer>${escapeHtml(q.note)}</footer></blockquote>`).join("");

  $("check").innerHTML = e.checks.map((c) =>
    `${escapeHtml(c.q)}, exact check: you said <span class="mono">${escapeHtml(c.said)}</span>; the answer is <span class="mono">${escapeHtml(c.exact)}</span>.`).join("<br>");

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
    `<div class="stat wide"><dt>After the challenge</dt><dd>${e.recovered ? `Recovered after ${e.nudges} nudge${e.nudges === 1 ? "" : "s"}` : "Not recovered"}</dd></div>`,
    `<div class="stat wide"><dt>Level reached</dt><dd>${e.level} of ${e.levels}<small>Shown separately from the label.</small><div class="level-track" aria-hidden="true">${levelBars}</div></dd></div>`,
  ].join("");

  $("hints").innerHTML = e.hints.length
    ? e.hints.map((h) => `<li><span class="tag tag-hint">Hint</span><p class="says">${escapeHtml(h.text)}</p></li>`).join("")
    : `<li>No hints used.</li>`;

  $("tip").textContent = e.tip;

  $("estimate").innerHTML = e.estimate.map((r) =>
    `<tr><td>${escapeHtml(r.label)}</td><td class="mono num-col">${escapeHtml(r.p)}</td></tr>`).join("");
});
