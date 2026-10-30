// First-visit onboarding (decision log 23): one skippable screen of roles, then the offer of
// a placement interview. Roles stay in this browser; only when "Share" is ticked are the
// roles and the "Other" text sent to /api/interest, which logs them and stores nothing.
document.addEventListener("DOMContentLoaded", () => {
  const { escapeHtml } = window.UB;
  const P = window.UBProfile;
  const $ = (id) => document.getElementById(id);
  const S = window.UB.profile();
  const profile = S.load();
  $("storage-note").hidden = S.ok;

  const chosen = new Set(profile.roles);
  $("roles").innerHTML = P.ROLES.map((r) =>
    `<button type="button" class="topic-chip" aria-pressed="${chosen.has(r.id)}" data-role="${r.id}">${escapeHtml(r.name)}</button>`).join("");
  $("other-text").value = profile.other_text || "";
  const sync = () => {
    $("roles").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(chosen.has(b.dataset.role))));
    $("other-row").hidden = !chosen.has("other");
  };
  sync();
  $("roles").addEventListener("click", (e) => {
    const id = e.target.closest("button[data-role]")?.dataset.role;
    if (!id) return;
    if (chosen.has(id)) chosen.delete(id); else chosen.add(id);
    sync();
    if (id === "other" && chosen.has("other")) $("other-text").focus();
  });

  $("skip").addEventListener("click", () => {
    profile.onboarded = "skipped";
    S.save(profile);
    location.href = "/ui";
  });

  $("continue").addEventListener("click", () => {
    const roles = P.ROLES.map((r) => r.id).filter((id) => chosen.has(id));
    const other = chosen.has("other") ? $("other-text").value.trim().slice(0, 200) : "";
    Object.assign(profile, { onboarded: "done", roles, other_text: other, default_track: P.defaultTrack(roles) });
    S.save(profile);
    if ($("share").checked && roles.length) {
      fetch("/api/interest", { method: "POST", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ roles, other_text: other }) }).catch(() => {});
    }
    // Then offer placement on the chosen track.
    fetch("/api/interview/topics").then((r) => (r.ok ? r.json() : Promise.reject())).then((t) => {
      const track = t.tracks.find((x) => x.id === profile.default_track && x.available)
        || t.tracks.find((x) => x.id === t.default_track);
      if (track) {
        $("placement-go").href = `/ui/interview?placement=1&track=${encodeURIComponent(track.id)}`;
        $("placement-text").textContent = `Five ${track.name} questions, one from each of five strength areas, starting at Medium. `
          + "Challenges and help work as in any interview. You get a starting rating estimate and your first strength chart.";
      }
    }).catch(() => {});
    $("roles-step").hidden = true;
    $("placement-step").hidden = false;
    $("placement-step").focus();
  });
});
