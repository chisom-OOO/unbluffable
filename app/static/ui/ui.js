// Shared helpers for the Exam Room screens: theme toggle, safe storage, highlighting.
(function () {
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage blocked */ } },
  };

  function currentTheme() {
    const set = document.documentElement.getAttribute("data-theme");
    if (set) return set;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function syncToggle(btn) {
    const next = currentTheme() === "dark" ? "light" : "dark";
    btn.setAttribute("aria-label", `Switch to ${next} theme`);
    btn.title = `Switch to ${next} theme`;
  }

  function initTheme() {
    const btn = document.querySelector(".theme-toggle");
    if (!btn) return;
    syncToggle(btn);
    btn.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      store.set("ub-theme", next);
      syncToggle(btn);
    });
  }

  // Mute (the interviewer's voice, and the landing sample): one setting, remembered in this
  // browser when storage allows. Pages hear changes as a "ub-mute" event.
  let muted = store.get("ub-muted") === "true";
  function initMute() {
    const btn = document.getElementById("mute");
    if (!btn) return;
    const sync = () => {
      btn.setAttribute("aria-pressed", String(muted));
      btn.setAttribute("aria-label", muted ? "Unmute interviewer" : "Mute interviewer");
    };
    sync();
    btn.addEventListener("click", () => {
      muted = !muted;
      store.set("ub-muted", String(muted));
      sync();
      document.dispatchEvent(new CustomEvent("ub-mute", { detail: { muted } }));
    });
  }

  // An English speech voice: natural-sounding first, then British, then American. `not`
  // skips one voice, so a second speaker can sound different.
  function pickVoice(not) {
    const voices = (window.speechSynthesis?.getVoices() || []).filter((v) => v.lang.startsWith("en") && v !== not)
      .sort((a, b) => a.name.localeCompare(b.name));
    return voices.find((v) => /Natural|Online/i.test(v.name)) || voices.find((v) => v.lang === "en-GB")
      || voices.find((v) => v.lang === "en-US") || voices[0] || null;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // Wrap the challenged substring (last occurrence: the committed claim, not an earlier correct restatement).
  function highlight(text, challenged) {
    const safe = escapeHtml(text);
    if (!challenged) return safe;
    const needle = escapeHtml(challenged);
    const at = safe.lastIndexOf(needle);
    if (at < 0) return safe;
    return safe.slice(0, at)
      + `<mark class="challenged">${needle}<span class="visually-hidden"> (challenged)</span></mark>`
      + safe.slice(at + needle.length);
  }

  const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Receipt (decision log 16): the candidate's exact words beside the exact computation.
  // `words: false` leaves the words out where they are already quoted just above.
  function receiptHtml(r, { words: withWords = true } = {}) {
    if (!r) return "";
    let words = `<p class="receipt-none">No words of yours are behind this line.</p>`;
    if (r.words) {
      const safe = escapeHtml(r.words), needle = r.span ? escapeHtml(r.span) : "";
      const at = needle ? safe.lastIndexOf(needle) : -1;
      const marked = at < 0 ? safe : `${safe.slice(0, at)}<mark>${needle}</mark>${safe.slice(at + needle.length)}`;
      words = `<blockquote class="receipt-words">“${marked}”</blockquote>`;
    }
    const rows = r.rows.map((row) => `<div><dt>${escapeHtml(row.label)}</dt><dd>${escapeHtml(row.text)}</dd></div>`).join("");
    return `<details class="receipt"><summary>Receipt</summary><div class="receipt-body${withWords ? "" : " solo"}">` +
      (withWords ? `<div><p class="receipt-head">Your words</p>${words}</div>` : "") +
      `<div><p class="receipt-head">Computation</p><dl>${rows}</dl>` +
      (r.note ? `<p class="receipt-note">${escapeHtml(r.note)}</p>` : "") + `</div></div></details>`;
  }

  // Track cards from /api/interview/topics (template "pack"; missing means Quant): "Live",
  // or "Being added" for a track with no templates, which can't be picked.
  const trackNote = (t) => (t.available ? "Live" : "Being added");
  function trackCard(t, { href, selected } = {}) {
    const inner = `<strong>${escapeHtml(t.name)}</strong><small>${trackNote(t)}</small>`;
    if (!t.available) return `<div class="track" role="${href ? "listitem" : "radio"}" aria-disabled="true" aria-checked="false" data-track="${escapeHtml(t.id)}">${inner}</div>`;
    if (href) return `<a class="track" role="listitem" href="${href}" data-track="${escapeHtml(t.id)}">${inner}</a>`;
    return `<button type="button" class="track" role="radio" aria-checked="${selected}" tabindex="${selected ? 0 : -1}" data-track="${escapeHtml(t.id)}">${inner}</button>`;
  }

  window.UB = { store, escapeHtml, highlight, reducedMotion, receiptHtml, trackCard, pickVoice };
  document.addEventListener("DOMContentLoaded", () => { initTheme(); initMute(); });
})();
