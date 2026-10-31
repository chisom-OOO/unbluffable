// /ui/forge: every family in the question bank by track, from /api/interview/forge (the families'
// verification records): topic, variants checked, wrong methods verified, and totals.
document.addEventListener("DOMContentLoaded", () => {
  const { escapeHtml } = window.UB;
  const $ = (id) => document.getElementById(id);
  const NAMES = { quant: "Quant", ib: "Investment banking", consulting: "Consulting", software: "Software engineering" };
  const n = (x, one, many = `${one}s`) => `${x} ${x === 1 ? one : many}`;
  const totals = (t) => [
    n(t.families, "family", "families"), `${t.variants_checked} of ${t.variants} variants reproduced by the solver`,
    `${n(t.wrong_methods_verified, "wrong method")} verified in code`,
    `${t.families_with_verified_methods} of ${t.families} families with verified wrong methods`];

  fetch("/api/interview/forge").then((r) => (r.ok ? r.json() : Promise.reject())).then((data) => {
    $("forge-totals").removeAttribute("aria-busy");
    $("forge-totals").innerHTML = totals(data.totals).map((t) => `<span>${escapeHtml(t)}</span>`).join("");
    $("forge-tracks").innerHTML = data.tracks.map((track) => {
      const rows = track.families.map((f) => `<tr><td class="mono">${escapeHtml(f.template_id)}</td><td>${escapeHtml(f.topic)}</td>`
        + `<td class="hide-narrow">${escapeHtml(f.difficulty)}</td>`
        + `<td class="num">${f.solver_passed ? `${f.variants_checked}/${f.variants}` : "not verified"}</td>`
        + `<td>${f.wrong_methods_verified ? `${f.wrong_methods.length}<span class="hide-narrow">: ${escapeHtml(f.wrong_methods.join(", "))}</span>` : "none verified"}</td></tr>`).join("");
      const t = track.totals;
      return `<section class="panel" aria-labelledby="track-${escapeHtml(track.id)}"><h2 id="track-${escapeHtml(track.id)}">${escapeHtml(NAMES[track.id] || track.id)}</h2>`
        + `<p class="fine">${totals(t).map(escapeHtml).join(" · ")}</p><div class="table-scroll"><table class="forge-table">`
        + `<caption class="visually-hidden">${escapeHtml(NAMES[track.id] || track.id)} families</caption>`
        + `<thead><tr><th scope="col">Family</th><th scope="col">Topic</th><th scope="col" class="hide-narrow">Level</th>`
        + `<th scope="col" class="num">Variants checked</th><th scope="col">Wrong methods verified</th></tr></thead>`
        + `<tbody>${rows}</tbody><tfoot><tr><td colspan="2">Total</td><td class="hide-narrow"></td>`
        + `<td class="num">${t.variants_checked}/${t.variants}</td><td>${t.wrong_methods_verified}</td></tr></tfoot></table></div></section>`;
    }).join("");
  }).catch(() => { $("forge-totals").textContent = "Couldn't load the question bank. Reload to try again."; });
});
