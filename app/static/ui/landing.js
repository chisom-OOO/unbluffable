// Landing: the claim, the labelled sample playing out as live type, and the track choice.
// If the visitor hasn't interacted within 3 s, the sample plays silently (browsers block sound
// without a click): the candidate's line types in, the number they commit to is underlined,
// the interviewer's challenge appears, then the recovery and "Same puzzle, new numbers."
// "Play with sound" speaks it with the browser's speech synthesis, each line appearing as it is
// spoken: the interviewer in one voice, the candidate in another (or, with a single voice, at a
// different pitch and rate). The mute setting is respected. Reduced motion shows the final state.
document.addEventListener("DOMContentLoaded", () => {
  // The landing page never redirects: every visitor, phones included (whose other pages
  // show the gate), stays here with the recorded replay. "Start an interview" goes straight to
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
  const { escapeHtml, reducedMotion, pickVoice } = window.UB;
  const $ = (id) => document.getElementById(id);

  // ---------- "Practise for [track] interviews" ----------
  // The options come from the real template packs; the static ones stand in until they load.
  const pick = $("track-pick");
  const starts = [$("prepare"), document.querySelector("#account-cta a")];
  const mirror = document.createElement("span");
  mirror.setAttribute("aria-hidden", "true");
  mirror.style.cssText = "position:absolute;visibility:hidden;white-space:pre;font:inherit;font-weight:500";
  pick.parentElement.appendChild(mirror);
  function fit() {  // the select is as wide as the chosen track, so the sentence reads as one line
    mirror.textContent = pick.options[pick.selectedIndex]?.text || "";
    pick.style.width = `calc(${mirror.offsetWidth}px + 1.25em)`;
  }
  function choose() {
    const href = `/ui/interview?track=${encodeURIComponent(pick.value)}`;
    starts.forEach((a) => { if (a) a.href = href; });
    fit();
  }
  pick.addEventListener("change", choose);
  fetch("/api/interview/topics").then((r) => (r.ok ? r.json() : Promise.reject())).then((t) => {
    const live = t.tracks.filter((track) => track.available);
    if (!live.length) return;
    const keep = pick.value;
    pick.innerHTML = live.map((track) => `<option value="${escapeHtml(track.id)}">${escapeHtml(track.name)}</option>`).join("");
    pick.value = live.some((track) => track.id === keep) ? keep : live[0].id;
    choose();
  }).catch(() => {});
  document.fonts?.ready.then(fit);
  fit();

  // ---------- The sample ----------
  $("landing-puzzle").textContent = data.puzzle.text;
  const CODA = { who: "interviewer", kind: "twin", text: "Same puzzle, new numbers." };
  let lines = [...data.replay.lines, CODA];
  const body = $("replay-body"), toggle = $("replay-toggle"), note = $("replay-note");
  const toggleLabel = toggle.querySelector("span");
  const synth = window.speechSynthesis && typeof window.SpeechSynthesisUtterance === "function" ? window.speechSynthesis : null;
  const muted = () => $("mute")?.getAttribute("aria-pressed") === "true";

  // Every line is in the page from the start, for screen readers and so the layout never
  // jumps: an invisible full copy holds the space, and the visible copy is typed over it.
  const LABEL = { challenge: "Interviewer · Challenge", nudge: "Interviewer · Nudge", hint: "Interviewer · Hint" };
  let real = false;
  function parts(line) {  // the committed words (the ones the challenge quotes), if any
    const at = line.challenge ? line.text.indexOf(line.challenge) : -1;
    return at < 0 ? null : [at, at + line.challenge.length];
  }
  function markup(line, n = line.text.length, lit = false) {
    const t = line.text, hit = parts(line);
    if (!hit) return escapeHtml(t.slice(0, n));
    const [a, b] = hit;
    return escapeHtml(t.slice(0, Math.min(n, a)))
      + (n > a ? `<span class="hit${lit ? " on" : ""}">${escapeHtml(t.slice(a, Math.min(n, b)))}</span>` : "")
      + (n > b ? escapeHtml(t.slice(b, n)) : "");
  }
  function buildNodes() {
    body.innerHTML = "";
    return lines.map((line) => {
      const el = document.createElement("div");
      const interviewer = line.who === "interviewer";
      el.className = `line pending${line.kind === "challenge" ? " is-challenge" : ""}${line.kind === "twin" ? " coda" : ""}`;
      el.innerHTML = `<span class="who">${interviewer ? LABEL[line.kind] || "Interviewer" : "Candidate"}</span>`
        + `<p class="says"><span class="ghost" aria-hidden="true">${markup(line)}</span>`
        + `<span class="typed" aria-hidden="true"></span><span class="visually-hidden">${escapeHtml(line.text)}</span></p>`;
      body.appendChild(el);
      return el;
    });
  }
  let nodes = buildNodes();

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
    body.classList.add("real");
    $("landing-puzzle").textContent = recording.puzzle;
    $("sample-tag").textContent = "A real recorded interview";
    if (reducedMotion()) showAll();
  }).catch(() => {});

  let run = 0, timers = [], guards = [], playing = false;
  const later = (id, ms, fn) => timers.push(setTimeout(() => { if (id === run) fn(); }, ms));
  const typed = (i) => nodes[i].querySelector(".typed");

  function reset() {
    nodes.forEach((n, i) => { n.classList.add("pending"); typed(i).innerHTML = ""; });
  }
  // A whole line at once: the interviewer's, a recording's, or any line under reduced motion.
  function showLine(i, lit = true) {
    nodes[i].classList.remove("pending");
    typed(i).innerHTML = markup(lines[i], undefined, lit);
    if (real) body.scrollTop = body.scrollHeight;
  }
  function showAll() { lines.forEach((_, i) => showLine(i)); }
  // The candidate's line, typed at about speaking pace; then the committed number is underlined.
  function typeLine(id, i, ms, done) {
    const line = lines[i], total = line.text.length, step = Math.max(18, ms / total);
    nodes[i].classList.remove("pending");
    for (let n = 1; n <= total; n++) {
      later(id, n * step, () => { typed(i).innerHTML = markup(line, n) + (n < total ? '<span class="caret"></span>' : ""); });
    }
    later(id, total * step + 120, () => {
      typed(i).querySelector(".hit")?.classList.add("on");
      done?.();
    });
    return total * step;
  }
  // How long a line takes to say or read, in ms (used for typing pace and the silent gaps).
  const sayMs = (line) => Math.min(4200, 650 + line.text.length * 42);

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
    if (reducedMotion()) { showAll(); finished(id); if (!manual) setButton("idle"); return; }
    reset();
    let t = 300;
    lines.forEach((line, i) => {
      if (line.who === "candidate" && !real) {
        const ms = sayMs(line) * 0.8;
        later(id, t, () => typeLine(id, i, ms));
        t += ms + 900;
      } else {
        later(id, t, () => showLine(i));
        t += real ? 2200 : sayMs(line) * 0.6 + 700;
      }
    });
    later(id, t, () => (manual ? finished(id) : setButton("idle")));
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
      const show = () => {
        if (shown || id !== run) return;
        shown = true;
        if (line.who === "candidate" && !real && !reducedMotion()) typeLine(id, index, sayMs(line) / (u.rate || 1));
        else showLine(index);
      };
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
    if (playing) { stop(); showAll(); return; }
    if (!synth) { say("Your browser has no speech voice, so the sample plays as text."); playSilent(true); return; }
    if (muted()) { say("Sound is off. Unmute with the speaker button at the top to hear it."); playSilent(true); return; }
    say("");
    playSound();
  });
  document.addEventListener("ub-mute", (e) => {
    if (e.detail.muted && playing) { stop(); showAll(); say("Sound is off. Unmute with the speaker button at the top to hear it."); }
    if (!e.detail.muted) say("");
  });

  // Reduced motion: the final state from the start. Otherwise the candidate's turn waits with
  // a caret, and the silent preview starts after 3 s of no interaction (spec/01 Landing).
  if (reducedMotion()) showAll();
  else {
    const first = lines.findIndex((l) => l.who === "candidate");
    if (first >= 0) { nodes[first].classList.remove("pending"); typed(first).innerHTML = '<span class="caret"></span>'; }
  }
  let interacted = false;
  const mark = () => { interacted = true; };
  ["pointerdown", "keydown"].forEach((e) => addEventListener(e, mark, { once: true }));
  // A visitor who is already clicking or typing gets the finished exchange, not motion.
  setTimeout(() => {
    if (playing || reducedMotion()) return;
    if (interacted) { stop("idle"); showAll(); } else playSilent(false);
  }, 3000);
});
