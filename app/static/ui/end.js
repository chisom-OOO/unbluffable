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
    (e.misconception ? `<p class="misconception-name">${escapeHtml(e.misconception)}: reading “fraud gets flagged” as “a flag is fraud”.</p>` : "");

  $("end-sub").textContent = `${e.questions} questions. Only your opening answer to each question is scored.`;

  $("evidence").innerHTML = e.evidence.map((q) =>
    `<blockquote class="evidence"><p>“${highlight(q.quote, q.challenge)}”</p><footer>${escapeHtml(q.note)}</footer></blockquote>`).join("");

  $("check").innerHTML = `Exact check: you said <span class="mono">${escapeHtml(e.check.said)}</span>; the answer is <span class="mono">${escapeHtml(e.check.exact)}</span>.`;

  const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const over = e.time.seconds > e.time.guide;
  const levelBars = Array.from({ length: e.levels }, (_, i) => `<span class="${i < e.level ? "on" : ""}"></span>`).join("");
  $("stats").innerHTML = [
    `<div class="stat"><dt>Hints used</dt><dd>${e.hints.length}</dd></div>`,
    `<div class="stat"><dt>Nudges</dt><dd>${e.nudges}</dd></div>`,
    `<div class="stat"><dt>Time vs guide</dt><dd class="${over ? "over" : ""}">${fmt(e.time.seconds)}<small>guide ${fmt(e.time.guide)}${over ? " · over" : ""}</small></dd></div>`,
    `<div class="stat wide"><dt>After the challenge</dt><dd>${e.recovered ? `Recovered after ${e.nudges} nudges` : "Not recovered"}</dd></div>`,
    `<div class="stat wide"><dt>Level reached</dt><dd>${e.level} of ${e.levels}<small>Shown separately from the label.</small><div class="level-track" aria-hidden="true">${levelBars}</div></dd></div>`,
  ].join("");

  $("hints").innerHTML = e.hints.length
    ? e.hints.map((h) => `<li><span class="tag tag-hint">Hint</span><p class="says">${escapeHtml(h.text)}</p></li>`).join("")
    : `<li>No hints used.</li>`;

  $("tip").textContent = e.tip;

  $("estimate").innerHTML = e.estimate.map((r) =>
    `<tr><td>${escapeHtml(r.label)}</td><td class="mono num-col">${escapeHtml(r.p)}</td></tr>`).join("");
});
