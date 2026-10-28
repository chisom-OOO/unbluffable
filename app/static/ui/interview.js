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

  let config = null, socket = null, sessionId = null;
  let phase = "ready";           // ready | listening | checking | finished
  let speaking = 0, speechGen = 0;
  let typing = false, capturing = false, captureRequested = false;
  let question = null, questionStart = 0, answeredThisQuestion = false, offered = false;
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

  function speak(text) {
    if (mute.getAttribute("aria-pressed") === "true" || !window.speechSynthesis) return;
    const u = new SpeechSynthesisUtterance(text);
    u.voice = pickVoice();
    const gen = speechGen;
    let started = false, ended = false;
    u.onstart = () => { if (gen !== speechGen) return; started = true; speaking++; speechChanged(); };
    const finish = () => {
      if (ended || gen !== speechGen) return;
      ended = true;
      if (started) { speaking = Math.max(0, speaking - 1); speechChanged(); }
    };
    u.onend = finish; u.onerror = finish;
    speechSynthesis.speak(u);
  }

  function cancelSpeech() {
    speechGen++; speaking = 0;
    window.speechSynthesis?.cancel();
    speechChanged();
  }

  // ---------- Transcript log ----------
  function addInterviewer(text, kind) {
    const el = document.createElement("div");
    const tag = KIND_TAG[kind];
    el.className = "utterance interviewer" + (tag ? ` is-${kind}` : "");
    el.innerHTML = `<div class="speaker"><span>Interviewer</span>${tag ? `<span class="tag tag-${kind}">${tag}</span>` : ""}</div>` +
      `<p class="says">${escapeHtml(text)}</p>`;
    log.appendChild(el);
    scrollTo(el);
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
        break;
      case "question":
        question = event;
        $("puzzle").textContent = event.text;
        $("puzzle-eyebrow").textContent = `Question ${event.number} of up to 4`;
        $("puzzle-kind").textContent = event.kind === "twin" ? "Same puzzle, new numbers" : "New puzzle";
        questionStart = Date.now(); answeredThisQuestion = false; offered = false;
        counts({ challenges: 0, nudges: 0, hints: 0 });
        updateTimer();
        break;
      case "interviewer_line":
        addInterviewer(event.text, event.kind);
        if (event.counts) counts(event.counts);
        speak(event.text);
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
        live.hidden = false;
        liveText.textContent = event.transcript;
        scrollTo(live);
        break;
      case "candidate_speech":
        if (headphones.checked && speaking > 0) cancelSpeech();  // barge-in only with headphones
        break;
      case "listening_prompt":
        addInterviewer(event.message, "prompt");
        speak(event.message);
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
        addInterviewer(event.acknowledgement, "ack");
        cancelSpeech();
        speak(event.acknowledgement);
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
    start.hidden = true;
    mic.hidden = false;
    phase = "checking";
    render();
    if (!typing) {
      try { await voice.open(); } catch { setTyping(true); setStatus("The microphone is unavailable, so you can type your answers instead."); }
    }
    socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/interview/ws`);
    socket.onopen = () => socket.send(JSON.stringify({ type: "begin", consent: true, headphones: headphones.checked }));
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
    if (on && capturing) voice.flush();  // close the open capture; its words come back as a turn
    render();
    if (on && phase === "listening") typeAnswer.focus();
    if (!on && phase === "listening" && !capturing && !captureRequested) openTurn();
  }
  typeToggle.addEventListener("click", () => setTyping(!typing));
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

  // ---------- Per-question time vs guide; help offered at 60% of the guide ----------
  const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  function updateTimer() {
    if (!question) return;
    const elapsed = Math.floor((Date.now() - questionStart) / 1000);
    const guide = question.guide_seconds;
    $("timer-text").textContent = fmt(elapsed);
    $("timer-guide").textContent = `${fmt(guide)} guide`;
    const timer = $("timer");
    timer.classList.toggle("over", elapsed > guide);
    timer.setAttribute("aria-label", `${fmt(elapsed)} elapsed, guide ${fmt(guide)}${elapsed > guide ? ", over guide" : ""}`);
    if (!answeredThisQuestion && !offered && elapsed >= Math.round(guide * 0.6) && phase === "listening" && speaking === 0) {
      offered = true;  // a "no" costs nothing (the server ignores it)
      const offer = "Is there anything you're stuck on?";
      addInterviewer(offer, "prompt");
      speak(offer);
    }
  }
  function startClock() {
    const tick = setInterval(() => { if (phase === "finished") { clearInterval(tick); return; } updateTimer(); }, 1000);
  }

  // ---------- Config: replay mode has no live microphone path ----------
  fetch("/api/voice/config").then((r) => (r.ok ? r.json() : Promise.reject())).then((c) => {
    config = c;
    if (c.mode === "replay") {
      setTyping(true);
      setStatus("Recorded replay mode: answers are typed and checked against recorded model calls.");
    }
  }).catch(() => setStatus("Voice configuration is unavailable. You can still type your answers."));

  start.disabled = !consent.checked;
  render();
});
