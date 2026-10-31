// Profile page (decision log 23): per-track rating estimate, strength radar ("Placement" and
// "Now"), the same numbers as a table, past interviews, and export / import / clear.
document.addEventListener("DOMContentLoaded", () => {
  const { escapeHtml } = window.UB;
  const P = window.UBProfile;
  const $ = (id) => document.getElementById(id);
  const S = window.UB.profile();
  let profile = S.load();
  $("storage-note").hidden = S.ok;

  const LABELS = { supports: "Evidence supports understanding", misconception: "Misconception detected",
                   "not-shown": "Understanding not shown", "more-evidence": "More evidence needed" };
  let tracks = [], current = null;

  function rolesLine() {
    const names = P.ROLES.filter((r) => profile.roles.includes(r.id))
      .map((r) => (r.id === "other" && profile.other_text ? `Other: ${profile.other_text}` : r.name));
    $("roles-line").textContent = names.length ? `Preparing for: ${names.join(", ")}.` : "";
  }

  function renderTabs() {
    $("track-tabs").innerHTML = tracks.map((t) =>
      `<button type="button" role="tab" class="tab" id="tab-${t.id}" aria-controls="track-panel" aria-selected="${t.id === current}" tabindex="${t.id === current ? 0 : -1}" data-track="${t.id}">${escapeHtml(t.name)}</button>`).join("");
    $("track-panel").setAttribute("aria-labelledby", `tab-${current}`);
  }

  function renderTrack() {
    const track = tracks.find((t) => t.id === current);
    const scores = P.areaScores(profile, current, track.areas);
    const o = P.overall(scores);
    $("rating").textContent = o ? String(P.shown(o.rating)) : "Not assessed yet";
    $("rating").classList.toggle("rating-big", !!o);
    $("band").textContent = o ? `${P.band(o.rating)} · interviews start at ${P.startLevel(o.rating)}` : "";
    $("rating-basis").textContent = o
      ? `Estimate based on ${o.answers} answer${o.answers === 1 ? "" : "s"} across ${o.areas} area${o.areas === 1 ? "" : "s"}.`
      : "Take the placement interview, or answer two questions in an area, for a first estimate.";
    $("placement-link").href = `/ui/interview?placement=1&track=${encodeURIComponent(current)}`;
    $("placement-link").textContent = profile.placement[current] ? "Take placement again →" : "Find my starting level →";
    $("practise-link").href = `/ui/interview?track=${encodeURIComponent(current)}`;
    $("placement-link").hidden = $("practise-link").hidden = !track.available;

    const placed = profile.placement[current]?.scores || {};
    const now = Object.fromEntries(scores.map((s) => [s.area, s.score]));
    const chart = P.radar(track.areas, [
      { key: "placement", name: "Placement", values: placed },
      { key: "now", name: "Now", values: now },
    ], `${track.name} strength areas: placement and now, 0 to 100`);
    // Fewer than 3 assessed areas: no shape, the table below carries the numbers.
    $("radar-figure").hidden = !chart.svg;
    $("radar-empty").hidden = !!chart.svg;
    $("radar").innerHTML = chart.svg;
    $("radar-missing").hidden = !chart.missing.length;
    $("radar-missing").textContent = chart.missing.length ? `Not assessed yet: ${chart.missing.join(", ")}.` : "";
    const cell = (v) => (v === null || v === undefined ? `<td class="num muted-cell">Not assessed yet</td>` : `<td class="num">${P.shown(v)}</td>`);
    $("area-rows").innerHTML = scores.map((s) =>
      `<tr><th scope="row">${escapeHtml(s.area)}</th>${cell(placed[s.area])}${cell(s.score)}<td class="num">${s.total}</td></tr>`).join("");
  }

  function renderHistory() {
    const rows = [...profile.history].reverse();
    $("history").hidden = !rows.length;
    $("history-empty").hidden = !!rows.length;
    const name = (id) => tracks.find((t) => t.id === id)?.name || id;
    const change = (h) => (h.after === null ? "Not rated yet" : h.before === null ? `${P.shown(h.after)} (first estimate)`
      : `${P.shown(h.before)} → ${P.shown(h.after)}`);
    $("history-rows").innerHTML = rows.map((h) =>
      `<tr><td>${escapeHtml(h.date)}</td><td>${escapeHtml(name(h.track))}</td><td>${escapeHtml(h.placement ? "Placement" : h.topics || "")}</td>` +
      `<td>${escapeHtml(LABELS[h.label] || "")}</td><td class="mono">${escapeHtml(change(h))}</td></tr>`).join("");
  }

  function select(id, focus) {
    current = id;
    renderTabs();
    renderTrack();
    if (focus) $(`tab-${id}`).focus();
  }
  $("track-tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-track]"); if (b) select(b.dataset.track); });
  $("track-tabs").addEventListener("keydown", (e) => {
    const i = tracks.findIndex((t) => t.id === current), last = tracks.length - 1;
    const to = { ArrowRight: i === last ? 0 : i + 1, ArrowLeft: i === 0 ? last : i - 1, Home: 0, End: last }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    select(tracks[to].id, true);
  });

  function status(text) { $("data-status").textContent = text; $("data-status").hidden = !text; }
  function refresh() { rolesLine(); if (current) renderTrack(); renderHistory(); }

  $("export").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([P.exportJson(profile)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `unbluffable-progress-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status("Progress exported.");
  });
  $("import").addEventListener("change", async () => {
    const file = $("import").files[0];
    $("import").value = "";
    if (!file) return;
    try {
      profile = P.importJson(await file.text());
      S.save(profile);
      refresh();
      status(S.ok ? "Progress imported." : "Progress imported for this visit only (storage is blocked).");
    } catch (error) {
      status(`Couldn't import that file. ${error.message || ""}`.trim());
    }
  });
  $("clear").addEventListener("click", () => {
    if (!confirm("Clear your roles, ratings and interview history from this browser? This can't be undone.")) return;
    S.clear();
    profile = P.empty();
    profile.onboarded = "skipped";  // don't send them back through onboarding
    S.save(profile);
    refresh();
    status("Your data was cleared.");
  });

  rolesLine();
  renderHistory();
  fetch("/api/interview/topics").then((r) => (r.ok ? r.json() : Promise.reject())).then((t) => {
    tracks = t.tracks;
    const asked = new URLSearchParams(location.search).get("track");
    const pick = [asked, profile.default_track, window.UB.headlineTrack(profile), t.default_track].find((id) => tracks.some((x) => x.id === id));
    select(pick || tracks[0].id);
    renderHistory();
  }).catch(() => { $("track-panel").hidden = true; status("Couldn't load the tracks. Check your connection and reload."); });
});
