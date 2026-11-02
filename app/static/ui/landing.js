// Landing: the claim, the labelled sample playing out as live type, and the track choice.
// The sample follows the "Practise for [track]" selector: one per track, each from a real forge
// family (landing-samples.js). Choosing a track restarts it from the first line and plays it
// through, typed in as on first load, and spoken too when sound is on (reduced motion: the
// finished exchange at once). It ends with the twin: the same puzzle with new numbers, answered.
// If the visitor hasn't interacted within 3 s, the sample plays silently (browsers block sound
// without a click): the candidate's line types in, the number they commit to is underlined,
// the interviewer's challenge appears, then the recovery and the twin.
// "Play with sound" speaks it with the browser's speech synthesis: the interviewer reads the
// question, then each line appears as it is spoken, the interviewer in one voice and the
// candidate in a second voice (or, with a single voice, at a different pitch and rate). The
// mute setting is respected. Reduced motion shows the final state.
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

  const SAMPLES = window.UB_SAMPLES;
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
  // The select is as wide as the chosen track, so the sentence reads as one line; the sentence
  // keeps room for the longest track, so choosing one never moves the button. The width is the
  // text plus the select's own padding (room for the arrow) and border, plus slack for the
  // browser's inner padding; then it grows until nothing is clipped.
  const SLACK_EM = 0.5;
  const textWidth = (text) => { mirror.textContent = text; return mirror.getBoundingClientRect().width; };
  function fit() {
    const style = getComputedStyle(pick);
    const frame = ["paddingLeft", "paddingRight", "borderLeftWidth", "borderRightWidth"]
      .reduce((sum, side) => sum + (parseFloat(style[side]) || 0), 0);
    const slack = SLACK_EM * (parseFloat(style.fontSize) || 16);
    const room = (text) => Math.ceil(textWidth(text) + frame + slack);  // whole pixels, so the button never shifts
    const widest = Math.max(0, ...[...pick.options].map((option) => room(option.text)));
    let width = room(pick.options[pick.selectedIndex]?.text || "");
    pick.style.width = `${width}px`;
    for (let grow = 0; grow < 40 && pick.scrollWidth > pick.clientWidth; grow += 1) pick.style.width = `${++width}px`;
    const sentence = pick.closest(".pick");
    sentence.style.minWidth = "";
    sentence.style.minWidth = `min(100%, ${sentence.getBoundingClientRect().width + Math.max(0, widest - width)}px)`;
  }
  function choose() {
    const href = `/ui/interview?track=${encodeURIComponent(pick.value)}`;
    starts.forEach((a) => { if (a) a.href = href; });
    fit();
    swapSample();
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
  let refit;
  window.addEventListener("resize", () => { clearTimeout(refit); refit = setTimeout(fit, 120); });
  fit();

  // ---------- The sample ----------
  let sample = SAMPLES[pick.value] || SAMPLES.quant;
  $("landing-puzzle").textContent = sample.question;
  // The ending: the twin from the same family, and its correct one-line answer.
  const LEAD = "Now the same puzzle with new numbers:";
  const ending = (s) => [
    { who: "interviewer", kind: "twin", text: `${LEAD} ${s.twin.question}`, speech: `${LEAD} ${s.twin.spoken}` },
    { who: "candidate", text: s.twin.answer.text },
  ];
  let lines = [...sample.lines, ...ending(sample)];
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

  // A new track: its sample restarts from the first line and plays through, typed in, and
  // spoken too when sound is on (the speaker icon). Reduced motion: the finished exchange.
  // A real recording, once committed, stays whatever the track.
  function swapSample() {
    const next = SAMPLES[pick.value];
    if (real || !next || next === sample) return;
    stop("idle");
    say("");
    sample = next;
    $("landing-puzzle").textContent = sample.question;
    lines = [...sample.lines, ...ending(sample)];
    nodes = buildNodes();
    restarted = true;
    if (reducedMotion()) { showAll(); return; }
    if (synth && !muted()) playSound();
    else playSilent(false);
  }

  let run = 0, timers = [], guards = [], playing = false;
  let restarted = false;  // a track change has started the sample: the first-load timer leaves it alone
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

  // With sound: the interviewer reads the question, then each line appears when its speech
  // starts and the next follows when it ends. A line whose speech never starts or never ends
  // still moves on (UBTurn.guardUtterance).
  function playSound() {
    stop("playing");
    const id = run;
    playing = true;
    reset();
    const interviewer = pickVoice();
    const candidate = pickVoice(interviewer);
    const distinct = candidate && interviewer && candidate !== interviewer;
    const speakOne = (text, who, show) => {
      const u = new SpeechSynthesisUtterance(text);
      if (who === "candidate") {
        u.voice = distinct ? candidate : interviewer;
        if (!distinct) { u.pitch = 1.45; u.rate = 1.15; }
      } else {
        u.voice = interviewer;
      }
      let shown = false;
      const once = () => { if (!shown && id === run) { shown = true; show(u); } };
      const guard = window.UBTurn.guardUtterance(u, {
        text: u.text, rate: u.rate, onStart: once,
        onDone: (why) => {
          guards = guards.filter((g) => g !== guard);
          if (why === "cancel" && id !== run) return;
          once();
          timers.push(setTimeout(next, reducedMotion() ? 150 : 450));
        },
      });
      guards.push(guard);
      // Speech that never starts (no voice, a busy queue): show the line and carry on.
      timers.push(setTimeout(() => { if (!guard.started && id === run) { synth.cancel(); guard.cancel(); } }, 2500));
      synth.speak(u);
    };
    let i = -1;  // -1: the question, read by the interviewer
    const next = () => {
      if (id !== run) return;
      if (i >= lines.length) { finished(id); return; }
      const index = i++;
      if (index < 0) { speakOne(real ? $("landing-puzzle").textContent : sample.spoken, "interviewer", () => {}); return; }
      const line = lines[index];
      speakOne(line.speech || line.text, line.who, (u) => {
        if (line.who === "candidate" && !real && !reducedMotion()) typeLine(id, index, sayMs(line) / (u.rate || 1));
        else showLine(index);
      });
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
    if (restarted || playing || reducedMotion()) return;
    if (interacted) { stop("idle"); showAll(); } else playSilent(false);
  }, 3000);
});
