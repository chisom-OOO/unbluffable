// Landing: track cards from the real template packs; the puzzle; the labelled sample.
// If the visitor hasn't interacted within 3 s, the sample previews silently (browsers block
// sound without a click). "Play with sound" speaks it with the browser's speech synthesis,
// each line appearing as it is spoken: the interviewer in one voice, the candidate in another
// (or, with a single voice, at a different pitch and rate). The mute setting is respected.
document.addEventListener("DOMContentLoaded", () => {
  // The landing page never redirects: every visitor, phones included (whose other pages
  // show the gate), stays here with the recorded replay. "Try an interview" goes straight to
  // setup; the welcome page (onboarding) is reached from the profile or the report, not forced.
  // With accounts, guests are offered sign-in first.
  const account = window.UBAccount;
  const showAccount = (s) => {
    const guest = s.enabled && !s.user;
    document.getElementById("account-cta").hidden = !guest;
    document.getElementById("prepare").hidden = guest;
  };
  account.whenReady.then(showAccount);
  document.addEventListener("ub-account", (e) => showAccount(e.detail));
  document.getElementById("signin-cta").addEventListener("click", () => account.openSignIn());

  const data = window.UB_FAKE;
  const { highlight, escapeHtml, reducedMotion, trackCard, pickVoice } = window.UB;
  const $ = (id) => document.getElementById(id);

  const tracks = $("tracks");
  tracks.setAttribute("role", "list");
  fetch("/api/interview/topics").then((r) => (r.ok ? r.json() : Promise.reject())).then((t) => {
    tracks.removeAttribute("aria-busy");
    tracks.innerHTML = t.tracks.map((track) =>
      trackCard(track, { href: `/ui/interview?track=${encodeURIComponent(track.id)}` })).join("");
  }).catch(() => { tracks.hidden = true; });

  $("landing-puzzle").textContent = data.puzzle.text;

  let lines = data.replay.lines;
  const body = $("replay-body"), bar = $("replay-bar"), toggle = $("replay-toggle"), note = $("replay-note");
  const toggleLabel = toggle.querySelector("span");
  const synth = window.speechSynthesis && typeof window.SpeechSynthesisUtterance === "function" ? window.speechSynthesis : null;
  const muted = () => $("mute")?.getAttribute("aria-pressed") === "true";

  // Build lines up front (hidden) so layout doesn't jump when they appear. A real recording
  // uses the interview's own layout (avatars, speaker and the challenge/nudge/hint tags).
  const TAG = { challenge: "Challenge", nudge: "Nudge", hint: "Hint" };
  let real = false;
  function buildNodes() {
    body.innerHTML = "";
    return lines.map((line, i) => {
      const el = document.createElement("div");
      if (real) {
        const interviewer = line.who === "interviewer", tag = interviewer && TAG[line.kind];
        el.className = `utterance ${interviewer ? "interviewer" : "candidate"}${tag ? ` is-${line.kind}` : ""}`;
        el.innerHTML = `<span class="avatar" aria-hidden="true">${interviewer ? "I" : "Y"}</span><div>`
          + `<div class="speaker"><span>${interviewer ? "Interviewer" : "Candidate"}</span>${tag ? `<span class="tag tag-${line.kind}">${tag}</span>` : ""}</div>`
          + `<p class="says">${escapeHtml(line.text)}</p></div>`;
      } else {
        el.className = "sampleline" + (line.kind === "challenge" ? " is-challenge" : "");
        const who = line.who === "interviewer" ? `Interviewer${line.kind === "challenge" ? " · Challenge" : ""}` : "Candidate";
        el.innerHTML = `<b>${who.toUpperCase()}</b><span class="says">“${escapeHtml(line.text)}”</span>`;
      }
      el.hidden = true;
      el.dataset.index = i;
      el.dataset.who = line.who;
      body.appendChild(el);
      return el;
    });
  }
  let nodes = buildNodes();
  let marked = lines.findIndex((l) => l.challenge);

  // A recording exported from a real interview (content/landing/recorded-interview.json), once
  // one is committed, replaces the scripted sample. Text only: lines, answers and timings.
  function fromRecording(rec) {
    if (!rec || rec.version !== 1 || rec.kind !== "unbluffable-recorded-interview" || !Array.isArray(rec.events)) return null;
    const first = rec.events.find((e) => e.type === "question");
    const out = [];
    for (const e of rec.events) {
      if (e.type === "interviewer_line" && e.text) out.push({ who: "interviewer", kind: e.kind, text: e.text });
      if (e.type === "answer_complete" && e.transcript) out.push({ who: "candidate", text: e.transcript });
    }
    return first && out.length >= 2 ? { puzzle: first.text, lines: out } : null;
  }
  fetch("/api/landing-recording").then((r) => (r.ok ? r.json() : null)).then((rec) => {
    const recording = fromRecording(rec);
    if (!recording || playing) return;
    stop("idle");
    real = true;
    lines = recording.lines;
    nodes = buildNodes();
    marked = -1;
    body.classList.add("real");
    $("landing-puzzle").textContent = recording.puzzle;
    document.querySelector(".sample-head .tag").textContent = "A real recorded interview";
  }).catch(() => {});

  function reset() {
    nodes.forEach((n) => { n.hidden = true; });
    if (marked >= 0) nodes[marked].querySelector(".says").textContent = `“${lines[marked].text}”`;
    bar.style.width = "0%";
  }
  function showLine(i) {
    nodes[i].hidden = false;
    if (real) body.scrollTop = body.scrollHeight;
    bar.style.width = `${((i + 1) / nodes.length) * 100}%`;
    // Once the challenge lands, mark the words it quotes in the candidate's line.
    if (lines[i].kind === "challenge" && marked >= 0) {
      nodes[marked].querySelector(".says").innerHTML = `“${highlight(lines[marked].text, lines[marked].challenge)}”`;
    }
  }

  let run = 0, timers = [], guards = [], playing = false;
  function setButton(state) {
    toggleLabel.textContent = state === "playing" ? "Stop" : state === "done" ? "Play again with sound" : "Play with sound";
  }
  function say(text) { note.textContent = text; note.hidden = !text; }
  function stop(state = "done") {
    run++;
    timers.forEach(clearTimeout); timers = [];
    const active = guards; guards = [];
    active.forEach((g) => g.cancel());
    synth?.cancel();
    playing = false;
    setButton(state);
  }
  function finished(id) { if (id === run) { playing = false; setButton("done"); } }

  // Text only: the silent preview, or a click when sound is off or unavailable.
  function playSilent(manual) {
    stop(manual ? "playing" : "idle");
    const id = run;
    playing = manual;
    reset();
    const step = reducedMotion() ? 900 : 2600;
    nodes.forEach((_, i) => timers.push(setTimeout(() => { if (id === run) showLine(i); }, i * step + 300)));
    timers.push(setTimeout(() => (manual ? finished(id) : id === run && setButton("idle")), nodes.length * step));
  }

  // With sound: each line appears when its speech starts; the next follows when it ends.
  // A line whose speech never starts or never ends still moves on (UBTurn.guardUtterance).
  function playSound() {
    stop("playing");
    const id = run;
    playing = true;
    reset();
    const interviewer = pickVoice();
    const candidate = pickVoice(interviewer);
    const distinct = candidate && interviewer && candidate !== interviewer;
    let i = 0;
    const next = () => {
      if (id !== run) return;
      if (i >= lines.length) { finished(id); return; }
      const index = i++, line = lines[index];
      const u = new SpeechSynthesisUtterance(line.text.replace(/^[…\s.]+/, ""));
      if (line.who === "candidate") {
        u.voice = distinct ? candidate : interviewer;
        if (!distinct) { u.pitch = 1.45; u.rate = 1.15; }
      } else {
        u.voice = interviewer;
      }
      let shown = false;
      const show = () => { if (!shown && id === run) { shown = true; showLine(index); } };
      const guard = window.UBTurn.guardUtterance(u, {
        text: u.text, rate: u.rate, onStart: show,
        onDone: (why) => {
          guards = guards.filter((g) => g !== guard);
          if (why === "cancel" && id !== run) return;
          show();
          timers.push(setTimeout(next, reducedMotion() ? 150 : 450));
        },
      });
      guards.push(guard);
      // Speech that never starts (no voice, a busy queue): show the line and carry on.
      timers.push(setTimeout(() => { if (!guard.started && id === run) { synth.cancel(); guard.cancel(); } }, 2500));
      synth.speak(u);
    };
    next();
  }

  toggle.addEventListener("click", () => {
    if (playing) { stop(); return; }
    if (!synth) { say("Your browser has no speech voice, so the sample plays as text."); playSilent(true); return; }
    if (muted()) { say("Sound is off. Unmute with the speaker button at the top to hear it."); playSilent(true); return; }
    say("");
    playSound();
  });
  document.addEventListener("ub-mute", (e) => {
    if (e.detail.muted && playing) { stop(); say("Sound is off. Unmute with the speaker button at the top to hear it."); }
    if (!e.detail.muted) say("");
  });

  // Silent preview after 3 s of no interaction (spec/01 Landing).
  let interacted = false;
  const mark = () => { interacted = true; };
  ["pointerdown", "keydown"].forEach((e) => addEventListener(e, mark, { once: true }));
  setTimeout(() => { if (!interacted) playSilent(false); }, 3000);
});
