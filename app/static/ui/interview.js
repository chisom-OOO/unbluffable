// Exam Room interview, wired to /api/interview/ws (server session, engine scoring).
// Hands-free after one Start tap (decision log 4). The indicator shows real state only
// (decision log 5): Listening while a capture or typed turn is open, "Checking your working"
// while the server's check runs, Speaking from SpeechSynthesis start/end events.
// Done is a fallback; Type instead completes a whole interview without the microphone.
document.addEventListener("DOMContentLoaded", () => {
  const { highlight, escapeHtml, reducedMotion } = window.UB;
  const voice = window.UBVoice;
  const $ = (id) => document.getElementById(id);

  const start = $("start"), mic = $("mic"), micState = $("mic-state"), done = $("done");
  const log = $("log"), live = $("live"), liveText = $("live-text");
  const typePanel = $("type-panel"), typeAnswer = $("type-answer"), typeToggle = $("type-toggle");
  const mute = $("mute"), consent = $("consent"), headphones = $("headphones"), status = $("status");

  const KIND_TAG = { challenge: "Challenge", nudge: "Nudge", hint: "Hint" };
  const reduced = reducedMotion();
  const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  // Pace for revealing an interviewer line when the voice sends no word boundaries.
  const WORD_MS = 320;

  let config = null, socket = null, sessionId = null;
  let phase = "ready";           // ready | listening | checking | finished
  let speaking = 0, speechGen = 0;
  let typing = false, capturing = false, captureRequested = false;
  let question = null, questionStart = 0, answeredThisQuestion = false, offered = false;
  let heard = false;  // any candidate speech, live transcript or typing since this question began
  let lastCandidate = null;

  // ---------- Indicator: derived from real state only ----------
  function render() {
    let shown = phase;
    if (speaking > 0 && phase !== "finished") shown = "speaking";
    const text = {
      ready: "One tap starts the interview",
      listening: typing ? "Listening for your typed answer" : "Listening",
      checking: "Checking your working",
      speaking: "Speaking",
      finished: "Interview finished",
    }[shown];
    mic.dataset.state = shown === "checking" ? "thinking" : (shown === "ready" || shown === "finished" ? "idle" : shown);
    micState.textContent = text;
    done.disabled = phase !== "listening" || (!typing && !capturing);
    typeToggle.disabled = phase === "finished";
    document.querySelector(".action-bar").classList.toggle("ready", phase === "ready");
  }

  function setStatus(message) { status.textContent = message || ""; status.hidden = !message; }

  function scrollTo(el) { el.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" }); }

  // ---------- Speech: real SpeechSynthesis events drive "Speaking" ----------
  function speechChanged() {
    const talking = speaking > 0;
    if (!headphones.checked) voice.mute(talking);  // no echo without headphones
    if (capturing && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "interviewer_speaking", value: talking, headphones: headphones.checked }));
    }
    render();
  }

  function pickVoice() {
    const voices = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"))
      .sort((a, b) => a.name.localeCompare(b.name));
    return voices.find((v) => /Natural|Online/i.test(v.name)) || voices.find((v) => v.lang === "en-GB")
      || voices.find((v) => v.lang === "en-US") || voices[0] || null;
  }

  const muted = () => mute.getAttribute("aria-pressed") === "true";

  // `reveal` (optional) types the line out as it is spoken; it never delays the mic.
  function speak(text, reveal) {
    if (muted() || !window.speechSynthesis) { reveal?.finish(); return; }
    const u = new SpeechSynthesisUtterance(text);
    u.voice = pickVoice();
    const gen = speechGen;
    let started = false, ended = false;
    u.onstart = () => {
      if (gen !== speechGen) return;
      started = true; speaking++; speechChanged();
      reveal?.start();
    };
    u.onboundary = (e) => { if (gen === speechGen && e.name === "word") reveal?.boundary(e.charIndex); };
    const finish = () => {
      reveal?.finish();
      if (ended || gen !== speechGen) return;
      ended = true;
      if (started) { speaking = Math.max(0, speaking - 1); speechChanged(); }
    };
    u.onend = finish; u.onerror = finish;
    speechSynthesis.speak(u);
    reveal?.watch(() => started);
  }

  function cancelSpeech() {
    speechGen++; speaking = 0;
    window.speechSynthesis?.cancel();
    finishReveals();
    speechChanged();
  }

  // ---------- Interviewer lines type out as they are spoken ----------
  // Screen readers get the whole line once (a visually hidden copy); the typed-out copy is aria-hidden.
  const reveals = new Set();
  function finishReveals() { for (const r of [...reveals]) r.finish(); }

  function revealer(target, text) {
    const words = text.split(" ");
    let shown = 0, timer = null, watchdog = null, byBoundary = false;
    const show = (n) => { shown = Math.min(words.length, Math.max(shown, n)); target.textContent = words.slice(0, shown).join(" "); };
    const r = {
      start() {
        if (!reveals.has(r)) return;
        show(1);
        timer = setInterval(() => { if (!byBoundary) { show(shown + 1); if (shown >= words.length) clearInterval(timer); } }, WORD_MS);
      },
      boundary(charIndex) { if (reveals.has(r)) { byBoundary = true; show(text.slice(0, charIndex).split(" ").length); } },
      // If speech never starts (nothing speaking or queued), show the line rather than leave it blank.
      watch(started) {
        if (!reveals.has(r)) return;
        watchdog = setInterval(() => {
          if (started()) { clearInterval(watchdog); return; }
          if (!speechSynthesis.speaking && !speechSynthesis.pending) r.finish();
        }, 1000);
      },
      finish() {
        clearInterval(timer); clearInterval(watchdog);
        show(words.length);
        reveals.delete(r);
      },
    };
    reveals.add(r);
    return r;
  }

  // ---------- Transcript log ----------
  // Adds a line and speaks it. Muted, reduced motion or no speech voice: the line shows at once.
  function addInterviewer(text, kind) {
    const el = document.createElement("div");
    const tag = KIND_TAG[kind];
    el.className = "utterance interviewer" + (tag ? ` is-${kind}` : "");
    el.innerHTML = `<div class="speaker"><span>Interviewer</span>${tag ? `<span class="tag tag-${kind}">${tag}</span>` : ""}</div>` +
      `<p class="says"><span class="visually-hidden">${escapeHtml(text)}</span><span class="typed" aria-hidden="true"></span></p>`;
    log.appendChild(el);
    scrollTo(el);
    const reveal = revealer(el.querySelector(".typed"), text);
    if (reduced || muted() || !window.speechSynthesis) reveal.finish();
    speak(text, reveal);
  }

  function addCandidate(text) {
    const el = document.createElement("div");
    el.className = "utterance candidate";
    el.innerHTML = `<div class="speaker"><span>You</span></div><p class="says">${escapeHtml(text)}</p>`;
    log.appendChild(el);
    scrollTo(el);
    return el;
  }

  function counts(c) {
    $("help-count").textContent = `Challenges ${c.challenges} · Nudges ${c.nudges} · Hints ${c.hints}`;
  }

  function modelRow(model) {
    if (!model || !model.model) return;
    const rows = $("model-rows");
    if (rows.dataset.empty !== "no") { rows.innerHTML = ""; rows.dataset.empty = "no"; }
    const ms = model.latency_s == null ? "" : model.latency_s >= 1 ? `${model.latency_s.toFixed(1)} s` : `${Math.round(model.latency_s * 1000)} ms`;
    const cost = model.estimated_cost_usd == null ? "" : `$${model.estimated_cost_usd.toFixed(4)}`;
    const row = document.createElement("tr");
    row.innerHTML = `<td class="mono">${escapeHtml(model.model)}${model.mode === "replay" ? " (recorded)" : ""}</td>` +
      `<td>${escapeHtml(model.job || "")}</td><td class="mono num-col">${ms}</td><td class="mono num-col">${cost}</td>`;
    rows.appendChild(row);
  }

  // ---------- Turns ----------
  async function openTurn() {
    phase = "listening";
    live.hidden = true;
    render();
    if (typing) { typeAnswer.focus({ preventScroll: true }); return; }
    try {
      await voice.open();
    } catch {
      setStatus("The microphone is unavailable, so you can type your answers instead.");
      setTyping(true);
      return;
    }
    voice.attach(socket);
    captureRequested = true;
    socket.send(JSON.stringify({
      type: "capture", sample_rate: 16000, headphones: headphones.checked, interviewer_speaking: speaking > 0,
    }));
  }

  function sendTyped() {
    const text = typeAnswer.value.trim();
    if (!text || phase !== "listening") return;
    finishReveals();
    if (!consent.checked) { setStatus("Please agree that your answer text is kept before sending."); return; }
    typeAnswer.value = "";
    phase = "checking";
    render();
    socket.send(JSON.stringify({ type: "typed", transcript: text }));
  }

  function handle(event) {
    switch (event.type) {
      case "session":
        sessionId = event.id;
        startCountdown(event.session_seconds);
        break;
      case "question":
        question = event;
        $("puzzle").textContent = event.text;
        $("puzzle-eyebrow").textContent = `Question ${event.number} of up to 4 · guide ${fmt(event.guide_seconds)}`;
        $("puzzle-kind").textContent = (event.kind === "twin" ? "Same puzzle, new numbers" : "New puzzle")
          + (event.difficulty ? ` · ${event.difficulty}` : "");
        finishReveals();
        questionStart = Date.now(); answeredThisQuestion = false; offered = false; heard = false;
        counts({ challenges: 0, nudges: 0, hints: 0 });
        updateTimer();
        break;
      case "part2":
        $("puzzle").textContent = event.text;
        $("puzzle-kind").textContent = "Part 2 · not scored";
        finishReveals();
        break;
      case "interviewer_line":
        addInterviewer(event.text, event.kind);
        if (event.counts) counts(event.counts);
        break;
      case "state":
        if (event.value === "listening") openTurn();
        if (event.value === "checking") { phase = "checking"; render(); }
        break;
      case "ready":
        capturing = true; captureRequested = false;
        voice.startStreaming(socket);
        speechChanged();
        break;
      case "transcript":
        if (event.transcript && event.transcript.trim()) heard = true;
        live.hidden = false;
        liveText.textContent = event.transcript;
        scrollTo(live);
        break;
      case "candidate_speech":
        heard = true;
        if (headphones.checked && speaking > 0) cancelSpeech();  // barge-in only with headphones
        break;
      case "listening_prompt":
        addInterviewer(event.message, "prompt");
        break;
      case "capture_stopped":
        capturing = false;
        voice.stopStreaming();
        render();
        break;
      case "answer_complete":
        live.hidden = true;
        answeredThisQuestion = true;
        lastCandidate = addCandidate(event.transcript);
        cancelSpeech();  // the turn moved on: any line still typing out finishes now
        addInterviewer(event.acknowledgement, "ack");
        break;
      case "challenge_result":
        modelRow(event.model);
        break;
      case "scoring_result":
        modelRow(event.model);
        break;
      case "transcription_model":
        modelRow(event.model);
        break;
      case "endpoint_decision":
        modelRow(event.model);
        break;
      case "model_error":
        setStatus(event.message);
        break;
      case "error":
        capturing = false; captureRequested = false;
        voice.stopStreaming();
        setStatus(event.message);
        render();
        break;
      case "session_end":
        finish(event);
        break;
    }
    if (event.type === "interviewer_line" && event.kind === "challenge" && lastCandidate) {
      const said = event.text.match(/^You said (.+?)\. /);
      if (said) lastCandidate.querySelector(".says").innerHTML = highlight(lastCandidate.querySelector(".says").textContent, said[1]);
    }
  }

  function finish(event) {
    finishReveals();
    phase = "finished";
    capturing = false;
    voice.close();
    const link = $("finish").querySelector("a");
    link.href = `/ui/end?session=${encodeURIComponent(sessionId)}`;
    $("finish").hidden = false;
    scrollTo($("finish"));
    render();
    link.focus({ preventScroll: true });
    socket?.close();
  }

  // ---------- Start: the one tap (browsers need a gesture for mic and speech) ----------
  async function begin() {
    if (!consent.checked) { setStatus("Please agree that your answer text is kept before starting."); consent.focus(); return; }
    setStatus("");
    consent.disabled = true;
    topicSelect.disabled = true;
    document.querySelectorAll('input[name="level"]').forEach((r) => { r.disabled = true; });
    stopMeter();
    $("device-check").hidden = true;
    start.hidden = true;
    mic.hidden = false;
    phase = "checking";
    render();
    if (!typing) {
      try { await voice.open(); } catch { setTyping(true); setStatus("The microphone is unavailable, so you can type your answers instead."); }
    }
    socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/interview/ws`);
    const level = document.querySelector('input[name="level"]:checked')?.value || "Easy";
    socket.onopen = () => socket.send(JSON.stringify({ type: "begin", consent: true, headphones: headphones.checked,
                                                       topic: topicSelect.value || null, level }));
    socket.onmessage = ({ data }) => handle(JSON.parse(data));
    socket.onclose = () => {
      if (phase !== "finished") { phase = "finished"; voice.close(); setStatus("The connection closed. Reload to start again."); render(); }
    };
    startClock();
  }
  start.addEventListener("click", begin);

  // ---------- Done: fallback for noisy rooms, or send a typed answer ----------
  function finishNow() {
    if (phase !== "listening") return;
    finishReveals();
    if (typing) sendTyped();
    else if (capturing) { done.disabled = true; voice.flush(); }
  }
  done.addEventListener("click", finishNow);

  // ---------- Type instead ----------
  function setTyping(on) {
    typing = on;
    typeToggle.setAttribute("aria-pressed", String(on));
    typeToggle.textContent = on ? "Use voice" : "Type instead";
    typePanel.hidden = !on;
    finishReveals();
    if (on && capturing) voice.flush();  // close the open capture; its words come back as a turn
    render();
    if (on && phase === "listening") typeAnswer.focus();
    if (!on && phase === "listening" && !capturing && !captureRequested) openTurn();
  }
  typeToggle.addEventListener("click", () => setTyping(!typing));
  typeAnswer.addEventListener("input", () => { if (typeAnswer.value.trim()) heard = true; });
  typeAnswer.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendTyped(); }
  });

  mute.addEventListener("click", () => {
    const on = mute.getAttribute("aria-pressed") !== "true";
    mute.setAttribute("aria-pressed", String(on));
    mute.setAttribute("aria-label", on ? "Unmute interviewer" : "Mute interviewer");
    if (on) cancelSpeech();
  });
  headphones.addEventListener("change", speechChanged);
  consent.addEventListener("change", () => { start.disabled = !consent.checked; if (consent.checked) setStatus(""); });

  // Space = Done while listening (unless typing into a field)
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space" && e.key !== " ") return;
    const t = e.target;
    if ((t.closest && t.closest("textarea, input, select, button, [contenteditable='true']")) || phase !== "listening") return;
    e.preventDefault();
    finishNow();
  }, true);

  // ---------- Help offered at 60% of the per-question guide (shown in the question label) ----------
  function updateTimer() {
    if (!question) return;
    const elapsed = Math.floor((Date.now() - questionStart) / 1000);
    const guide = question.guide_seconds;
    const offer = window.UBTurn.shouldOfferHelp({
      elapsed, guide, offered, phase, heard, answered: answeredThisQuestion, speaking: speaking > 0,
      liveText: live.hidden ? "" : liveText.textContent, typedText: typeAnswer.value,
    });
    if (offer) {
      offered = true;  // a "no" costs nothing (the server ignores it)
      addInterviewer("Is there anything you're stuck on?", "prompt");
    }
  }
  function startClock() {
    const tick = setInterval(() => { if (phase === "finished") { clearInterval(tick); return; } updateTimer(); }, 1000);
  }

  // ---------- Session countdown (decision log 10); the length comes from the server ----------
  // At 0:00 the interviewer finishes the current question, then closes (the server decides).
  function startCountdown(seconds) {
    if (!seconds) return;
    const el = $("countdown"), ends = Date.now() + seconds * 1000;
    el.classList.remove("pending");
    const tick = () => {
      const left = Math.max(0, Math.ceil((ends - Date.now()) / 1000));
      $("countdown-text").textContent = left > 0 ? `${fmt(left)} left` : "0:00 · finishing this question";
      el.classList.toggle("low", left <= 60);
      el.setAttribute("aria-label", left > 0 ? `${fmt(left)} left in the session` : "Time is up; finishing this question");
      if (left > 0 && phase !== "finished") setTimeout(tick, 1000);
      if (phase === "finished") el.classList.add("pending");
    };
    tick();
  }

  // ---------- Device check before the first question (decision log 10) ----------
  // Mic level is read locally from an AnalyserNode; nothing is sent. The camera is not touched.
  let meterFrame = null;
  function stopMeter() { if (meterFrame) cancelAnimationFrame(meterFrame); meterFrame = null; }
  $("mic-test").addEventListener("click", async () => {
    const note = $("mic-note");
    try {
      await voice.open();
    } catch {
      note.textContent = "The microphone is blocked or missing. You can type your answers instead.";
      note.className = "device-note bad";
      return;
    }
    note.textContent = "Say something: the bar should move. Nothing is sent.";
    note.className = "device-note ok";
    const bar = $("mic-meter");
    const draw = () => { bar.style.width = `${Math.round(voice.level() * 100)}%`; meterFrame = requestAnimationFrame(draw); };
    stopMeter(); draw();
  });
  $("speaker-test").addEventListener("click", () => {
    const note = $("speaker-note");
    if (!window.speechSynthesis) { note.textContent = "This browser has no speech voice; lines will appear as text."; note.className = "device-note bad"; return; }
    if (mute.getAttribute("aria-pressed") === "true") { note.textContent = "The interviewer is muted; unmute to hear the test line."; return; }
    speak("This is how the interviewer will sound.");
    note.textContent = "Playing a test line.";
  });

  // ---------- Config: connection check, and replay mode has no live microphone path ----------
  fetch("/api/voice/config").then((r) => (r.ok ? r.json() : Promise.reject())).then((c) => {
    config = c;
    $("connection-note").textContent = "Connected to the Unbluffable server.";
    $("connection-note").className = "device-note ok";
    if (c.mode === "replay") {
      setTyping(true);
      setStatus("Recorded replay mode: answers are typed and checked against recorded model calls.");
    }
  }).catch(() => {
    $("connection-note").textContent = "Can't reach the server. Check your connection and reload.";
    $("connection-note").className = "device-note bad";
    setStatus("Voice configuration is unavailable. You can still type your answers.");
  });

  // ---------- Topic picker: accepted forge templates per topic, Mixed, and the fraud alert ----------
  const topicSelect = $("topic");
  fetch("/api/interview/topics").then((r) => (r.ok ? r.json() : Promise.reject())).then((t) => {
    topicSelect.replaceChildren(...t.topics.map((o) => {
      const option = document.createElement("option");
      option.value = o.id;
      option.textContent = o.count == null ? o.name : `${o.name} (${o.count} template${o.count === 1 ? "" : "s"})`;
      option.selected = o.id === t.default;
      return option;
    }));
  }).catch(() => {
    topicSelect.replaceChildren(new Option("Default", ""));
  });

  start.disabled = !consent.checked;
  render();
});
