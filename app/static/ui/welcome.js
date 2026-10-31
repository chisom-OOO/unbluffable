// First-visit onboarding (decision log 23): one skippable screen of roles, then the offer of
// a placement interview. Roles stay in this browser; only when "Share" is ticked are the
// roles and the "Other" text sent to /api/interest, which logs them and stores nothing.
// With accounts (Firebase): only after a first sign-in, "Make it yours" (name and photo) comes
// first; guests are sent back, since nothing of theirs is kept before they sign in.
document.addEventListener("DOMContentLoaded", () => window.UBAccount.whenReady.then((acct) => {
  if (window.UB.desktopOnly()) return;  // decision log 26: laptop or desktop only
  const { escapeHtml } = window.UB;
  const P = window.UBProfile;
  const $ = (id) => document.getElementById(id);
  const S = window.UB.profile();
  const profile = S.load();
  $("storage-note").hidden = S.ok;
  const account = window.UBAccount;
  if (acct.enabled && !acct.user) { location.replace("/ui"); return; }

  // ---------- Make it yours (first sign-in only) ----------
  const first = acct.enabled && acct.user && (account.firstTime || new URLSearchParams(location.search).get("first") === "1")
    && profile.onboarded !== "done";
  let photo = profile.photo;
  const preview = () => { $("make-avatar").innerHTML = window.UB.avatarHtml({ name: $("make-name").value, photo }, "avatar-big", true); };
  const makeStatus = (t) => { $("make-status").textContent = t; $("make-status").hidden = !t; };
  if (first) {
    $("make-step").hidden = false;
    $("roles-step").hidden = true;
    $("make-name").value = profile.name || acct.user.name || "";
    $("google-photo-row").hidden = !acct.user.photoURL;
    if (acct.user.photoURL && !photo) document.querySelector('input[name="make-photo"][value="google"]').checked = true;
    if (photo) document.querySelector('input[name="make-photo"][value="upload"]').checked = true;
    preview();
    $("make-title").focus();
  }
  $("make-name").addEventListener("input", preview);
  document.querySelectorAll('input[name="make-photo"]').forEach((radio) => radio.addEventListener("change", async () => {
    makeStatus("");
    if (radio.value === "upload" && radio.checked) $("make-photo-input").click();
    if (radio.value === "none" && radio.checked) { photo = null; preview(); }
    if (radio.value === "google" && radio.checked) {
      try { photo = await window.UB.photoFromBlob(await (await fetch(acct.user.photoURL)).blob()); }
      catch { photo = null; makeStatus("Couldn't use the Google photo here, so your initials show for now. You can upload one instead."); }
      preview();
    }
  }));
  $("make-photo-input").addEventListener("change", async () => {
    const file = $("make-photo-input").files[0];
    $("make-photo-input").value = "";
    if (!file) return;
    try { photo = await window.UB.photoFromBlob(file); } catch { makeStatus("That file isn't a picture this browser can read."); }
    preview();
  });
  $("make-continue").addEventListener("click", () => {
    Object.assign(profile, { name: $("make-name").value.trim().slice(0, P.NAME_MAX), photo, identity_at: new Date().toISOString() });
    S.save(profile);
    window.UB.refreshProfileLink();
    $("make-step").hidden = true;
    $("roles-step").hidden = false;
    $("roles-title").setAttribute("tabindex", "-1");
    $("roles-title").focus();
  });

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
    Object.assign(profile, { onboarded: "done", roles, other_text: other, default_track: P.defaultTrack(roles),
                             roles_at: new Date().toISOString() });
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
}));
