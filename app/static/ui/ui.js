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
  // The interviewer's voice: the one chosen in the device check (remembered in this browser),
  // else the most human-sounding English voice (UBTurn.rankVoices). `not` skips one voice.
  function rankedVoices() {
    const all = window.speechSynthesis?.getVoices() || [];
    return window.UBTurn ? window.UBTurn.rankVoices(all) : all.filter((v) => /^en/i.test(v.lang || ""));
  }
  function pickVoice(not) {
    const ranked = rankedVoices().filter((v) => v !== not);
    const chosen = store.get("ub-voice");
    return (!not && ranked.find((v) => v.voiceURI === chosen)) || ranked[0] || null;
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

  // The profile (decision log 23), kept in this browser. One store per page, so a blocked
  // storage still keeps progress for this visit.
  const BLOCKED = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
  let profileStore = null;
  function profile() {
    if (!window.UBProfile) return null;
    if (!profileStore) {
      let local = null;
      try { local = window.localStorage; } catch { local = null; }
      profileStore = window.UBProfile.store(local || BLOCKED);
    }
    return profileStore;
  }
  // The rating shown for a profile: its default track, else the track with the most answers.
  function headlineTrack(p) {
    if (p.default_track) return p.default_track;
    const counts = {};
    p.answers.forEach((a) => { counts[a.t] = (counts[a.t] || 0) + 1; });
    return Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0] || null;
  }
  // The candidate's photo, else their initials, else a plain person icon. Decorative: the
  // name is said in the surrounding label.
  const PERSON = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>';
  // `circle`: the person icon also sits on the accent circle (the profile's large avatar).
  function avatarHtml(p, cls = "avatar-small", circle = false) {
    if (p.photo && window.UBProfile.validPhoto(p.photo)) return `<img class="avatar-img ${cls}" src="${p.photo}" alt="">`;
    const letters = window.UBProfile.initials(p.name);
    if (letters) return `<span class="avatar-initials ${cls}" aria-hidden="true">${escapeHtml(letters)}</span>`;
    return circle ? `<span class="avatar-initials avatar-person ${cls}" aria-hidden="true">${PERSON}</span>` : PERSON;
  }
  function initProfileLink() {
    const link = document.getElementById("profile-link");
    const S = profile();
    if (!link || !S) return;
    const p = S.load(), track = headlineTrack(p);
    const o = track ? window.UBProfile.overall(window.UBProfile.areaScores(p, track)) : null;
    const span = link.querySelector(".profile-rating");
    span.hidden = !o;
    span.textContent = o ? String(window.UBProfile.shown(o.rating)) : "";
    const icon = link.querySelector(".icon, .avatar-img, .avatar-initials");
    if (icon) icon.outerHTML = avatarHtml(p);
    link.querySelector(".profile-word").textContent = p.name || "Profile";
    link.setAttribute("aria-label", `${p.name ? `${p.name}'s profile` : "Profile"}${o ? `, rating estimate ${window.UBProfile.shown(o.rating)}` : ""}`);
  }

  // A photo for the profile: a square crop, 256 px, JPEG; quality steps down until it is
  // under 100 KB. `blob` is a file the candidate chose, or a fetched image (the Google photo).
  async function photoFromBlob(blob) {
    let source;
    try { source = await createImageBitmap(blob); } catch {
      source = await new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = URL.createObjectURL(blob);
      });
    }
    const w = source.width, h = source.height, side = Math.min(w, h);
    const canvas = Object.assign(document.createElement("canvas"), { width: 256, height: 256 });
    canvas.getContext("2d").drawImage(source, (w - side) / 2, (h - side) / 2, side, side, 0, 0, 256, 256);
    for (const quality of [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]) {
      const url = canvas.toDataURL("image/jpeg", quality);
      if (window.UBProfile.validPhoto(url)) return url;
    }
    throw new Error("too large");
  }

  // "Where this question came from": the forge's verification record for its family.
  function provenanceHtml(rows) {
    if (!rows || !rows.length) return "";
    return `<details class="receipt provenance"><summary>Where this question came from</summary><div class="receipt-body solo"><div><dl>`
      + rows.map((r) => `<div><dt>${escapeHtml(r.label)}</dt><dd>${r.key === "solver_code" ? `<pre class="code-block mono">${escapeHtml(r.text)}</pre>` : escapeHtml(r.text)}</dd></div>`).join("")
      + `</dl><p class="receipt-note"><a href="/ui/forge">Every family in the question bank</a></p></div></div></details>`;
  }

  // Decision log 35 (amends 26): the interview, setup, profile and report run on laptops and
  // tablets. Phones (smaller screen side under 700 px) and windows under 700 px wide get a
  // friendly screen instead (with a Copy link button); page scripts check desktopOnly() and
  // do not start.
  const tooSmall = () => window.UBDevice.phoneSized({ screenWidth: screen.width, screenHeight: screen.height, innerWidth: window.innerWidth });
  const desktopOnly = () => document.body?.dataset.desktopOnly === "true" && tooSmall();
  function initDesktopGate() {
    if (document.body.dataset.desktopOnly !== "true") return;
    // Only a blocked page reloads, once it is wide enough; a running interview is never reloaded.
    if (!tooSmall()) return;
    addEventListener("resize", () => { if (!tooSmall()) location.reload(); });
    document.documentElement.classList.add("desktop-gated");
    const gate = document.createElement("main");
    gate.className = "desktop-gate";
    gate.id = "gate-main";
    gate.innerHTML = `<section class="panel" aria-labelledby="gate-title">
      <svg class="gate-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="11" rx="1.5"/><path d="M2 19h20"/></svg>
      <h1 id="gate-title">Unbluffable needs a bigger screen, like a real interview</h1>
      <p class="muted">Open this on a laptop or tablet with a camera and microphone.</p>
      <label class="visually-hidden" for="gate-url">This page's link</label>
      <input class="text-input gate-url" id="gate-url" type="text" readonly value="${escapeHtml(location.href)}">
      <div class="welcome-actions">
        <button class="btn" type="button" id="copy-link">Copy link</button>
        <a class="btn secondary" href="/ui">See what Unbluffable is</a>
      </div>
      <p class="saved-note" id="copy-status" role="status" aria-live="polite"></p>
    </section>`;
    document.querySelector(".shell > header").after(gate);
    const status = (t) => { document.getElementById("copy-status").textContent = t; };
    document.getElementById("copy-link").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(location.href); status("Link copied."); }
      catch { const f = document.getElementById("gate-url"); f.focus(); f.select(); status("Select the link above and copy it."); }
    });
  }

  // iPad Safari plays speech only after a first utterance started inside a tap: call this
  // from the tap (Start, the speaker test). A silent one-space line, once per page.
  let speechUnlocked = false;
  function unlockSpeech() {
    if (speechUnlocked || !window.speechSynthesis || typeof window.SpeechSynthesisUtterance !== "function") return;
    speechUnlocked = true;
    const u = new SpeechSynthesisUtterance(" ");
    u.volume = 0;
    try { speechSynthesis.speak(u); } catch { speechUnlocked = false; }
  }
  // Touch-only devices (decision log 35), for the coding round's keyboard note.
  const touchOnly = () => window.UBDevice.touchOnly({ coarse: matchMedia("(pointer: coarse)").matches,
                                                     anyFine: matchMedia("(any-pointer: fine)").matches });
  const appleTouch = () => window.UBDevice.appleTouch(navigator);

  window.UB = { store, unlockSpeech, touchOnly, appleTouch, photoFromBlob, provenanceHtml, rankedVoices, desktopOnly, escapeHtml, highlight, reducedMotion, receiptHtml, trackCard, pickVoice, profile, headlineTrack, avatarHtml,
                refreshProfileLink: initProfileLink };
  document.addEventListener("DOMContentLoaded", () => { initDesktopGate(); initTheme(); initMute(); initProfileLink(); });
  document.addEventListener("ub-account", initProfileLink);
  // Signed in, the profile is also kept with the account: say so wherever the page says where it lives.
  document.addEventListener("ub-account", (e) => {
    if (!e.detail.user) return;
    document.querySelectorAll(".storage-line").forEach((el) => {
      el.textContent = "Signed in: your profile is kept with your account and synced across your devices. Interview answer text is never stored there.";
    });
  });
})();
