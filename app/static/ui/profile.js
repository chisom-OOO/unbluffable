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
    $("rating-track").textContent = track.name;
    $("rating").textContent = o ? String(P.shown(o.rating)) : "Not assessed yet";
    $("rating").classList.toggle("rating-big", !!o);
    $("rating").classList.toggle("rating-none", !o);
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
  function refresh() { rolesLine(); renderAbout(); if (current) renderTrack(); renderHistory(); window.UB.refreshProfileLink(); }

  // ---------- Identity card: avatar, display name and photo, in this browser only ----------
  function renderAbout() {
    $("avatar").innerHTML = window.UB.avatarHtml(profile, "avatar-big", true);
    $("identity-name").textContent = profile.name || "Add your name";
    $("identity-name").classList.toggle("placeholder", !profile.name);
    $("photo-remove").hidden = !profile.photo;
    $("avatar-button").setAttribute("aria-label", profile.photo ? "Change photo" : "Choose a photo");
  }
  function photoStatus(text) { $("photo-status").textContent = text; $("photo-status").hidden = !text; }

  // The name: pencil (or the name itself) opens the field; Save or Enter keeps it; Cancel or Esc undoes.
  function editName(on) {
    $("name-view").hidden = on;
    $("name-form").hidden = !on;
    if (on) {
      $("display-name").value = profile.name || "";
      $("display-name").focus();
      $("display-name").select();
    } else {
      $("name-edit").focus();
    }
  }
  let savedTimer = null;
  function saved(text) {
    clearTimeout(savedTimer);
    $("name-saved").textContent = text;
    $("name-saved").classList.remove("fade");
    savedTimer = setTimeout(() => $("name-saved").classList.add("fade"), 2000);
  }
  $("name-edit").addEventListener("click", () => editName(true));
  $("identity-name").addEventListener("click", () => editName(true));
  $("name-form").addEventListener("submit", (e) => {
    e.preventDefault();
    profile.name = $("display-name").value.trim().slice(0, P.NAME_MAX);
    const kept = S.save(profile);
    editName(false);
    renderAbout();
    window.UB.refreshProfileLink();
    saved(kept ? "Saved" : "Saved for this visit");
  });
  $("name-cancel").addEventListener("click", () => editName(false));
  $("display-name").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); editName(false); }
  });

  // A square crop, 256 px, JPEG; quality steps down until it is under 100 KB.
  async function resized(file) {
    let source;
    try { source = await createImageBitmap(file); } catch {
      source = await new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = URL.createObjectURL(file);
      });
    }
    const w = source.width, h = source.height, side = Math.min(w, h);
    const canvas = Object.assign(document.createElement("canvas"), { width: 256, height: 256 });
    canvas.getContext("2d").drawImage(source, (w - side) / 2, (h - side) / 2, side, side, 0, 0, 256, 256);
    for (const quality of [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]) {
      const url = canvas.toDataURL("image/jpeg", quality);
      if (P.validPhoto(url)) return url;
    }
    throw new Error("too large");
  }
  $("photo-choose").addEventListener("click", () => $("photo-input").click());
  $("avatar-button").addEventListener("click", () => $("photo-input").click());
  $("photo-input").addEventListener("change", async () => {
    const file = $("photo-input").files[0];
    $("photo-input").value = "";
    if (!file) return;
    try {
      profile.photo = await resized(file);
    } catch {
      photoStatus("That file isn't a picture this browser can read.");
      return;
    }
    const saved = S.save(profile);
    renderAbout();
    window.UB.refreshProfileLink();
    photoStatus(saved ? "Photo saved on this device." : "Photo kept for this visit only (storage is blocked).");
    $("photo-choose").focus();
  });
  $("photo-remove").addEventListener("click", () => {
    profile.photo = null;
    S.save(profile);
    renderAbout();
    window.UB.refreshProfileLink();
    photoStatus("Photo removed.");
    $("photo-choose").focus();
  });

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
  renderAbout();
  renderHistory();
  fetch("/api/interview/topics").then((r) => (r.ok ? r.json() : Promise.reject())).then((t) => {
    tracks = t.tracks;
    const asked = new URLSearchParams(location.search).get("track");
    const pick = [asked, profile.default_track, window.UB.headlineTrack(profile), t.default_track].find((id) => tracks.some((x) => x.id === id));
    select(pick || tracks[0].id);
    renderHistory();
  }).catch(() => { $("track-panel").hidden = true; status("Couldn't load the tracks. Check your connection and reload."); });
});
