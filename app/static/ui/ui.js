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
  function receiptHtml(r) {
    if (!r) return "";
    let words = `<p class="receipt-none">No words of yours are behind this line.</p>`;
    if (r.words) {
      const safe = escapeHtml(r.words), needle = r.span ? escapeHtml(r.span) : "";
      const at = needle ? safe.lastIndexOf(needle) : -1;
      const marked = at < 0 ? safe : `${safe.slice(0, at)}<mark>${needle}</mark>${safe.slice(at + needle.length)}`;
      words = `<blockquote class="receipt-words">“${marked}”</blockquote>`;
    }
    const rows = r.rows.map((row) => `<div><dt>${escapeHtml(row.label)}</dt><dd>${escapeHtml(row.text)}</dd></div>`).join("");
    return `<details class="receipt"><summary>Receipt</summary><div class="receipt-body">` +
      `<div><p class="receipt-head">Your words</p>${words}</div>` +
      `<div><p class="receipt-head">Computation</p><dl>${rows}</dl>` +
      (r.note ? `<p class="receipt-note">${escapeHtml(r.note)}</p>` : "") + `</div></div></details>`;
  }

  window.UB = { store, escapeHtml, highlight, reducedMotion, receiptHtml };
  document.addEventListener("DOMContentLoaded", initTheme);
})();
