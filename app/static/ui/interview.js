// Exam Room interview, wired to /api/interview/ws (server session, engine scoring).
// Hands-free after one Start tap (decision log 4). The indicator shows real state only
// (decision log 5): Listening while a capture or typed turn is open, "Checking your working"
// while the server's check runs, Speaking from SpeechSynthesis start/end events.
// Decision log 20: Start stays locked until the camera shows a picture, the microphone picks
// up sound and the server answers; "Can't use a camera or mic?" switches to typed practice,
// labelled "Not exam conditions". Done is a fallback for noisy rooms.
document.addEventListener("DOMContentLoaded", () => {
  const { highlight, escapeHtml, reducedMotion, receiptHtml, trackCard } = window.UB;
  const voice = window.UBVoice;
  const $ = (id) => document.getElementById(id);

  const start = $("start"), mic = $("mic"), micState = $("mic-state"), done = $("done");
  const log = $("log"), live = $("live"), liveText = $("live-text");
  const typePanel = $("type-panel"), typeAnswer = $("type-answer");
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
  // Device gate (decision log 20)
  let connected = false, micHeard = false, cameraOk = false, typedPractice = false, replay = false;

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
    $("mic-sub").textContent = typing ? "Type your answer, then Done or Ctrl+Enter" : "Speak naturally · hands-free";
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

  // `spokenLength`: when the words said differ from the text shown (spoken maths), speech
  // boundaries reveal the shown text in proportion.
  function revealer(target, text, spokenLength = text.length) {
    const words = text.split(" ");
    let shown = 0, timer = null, watchdog = null, byBoundary = false;
    const show = (n) => { shown = Math.min(words.length, Math.max(shown, n)); target.textContent = words.slice(0, shown).join(" "); };
    const r = {
      start() {
        if (!reveals.has(r)) return;
        show(1);
        timer = setInterval(() => { if (!byBoundary) { show(shown + 1); if (shown >= words.length) clearInterval(timer); } }, WORD_MS);
      },
      boundary(charIndex) {
        if (!reveals.has(r)) return;
        byBoundary = true;
        const at = spokenLength === text.length ? charIndex : Math.round(charIndex * text.length / spokenLength);
        show(text.slice(0, at).split(" ").length);
      },
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
  function addInterviewer(text, kind, receipt, speech) {
    const el = document.createElement("div");
    const tag = KIND_TAG[kind];
    el.className = "utterance interviewer" + (tag ? ` is-${kind}` : "");
    el.innerHTML = `<span class="avatar" aria-hidden="true">I</span><div>` +
      `<div class="speaker"><span>Interviewer</span>${tag ? `<span class="tag tag-${kind}">${tag}</span>` : ""}</div>` +
      `<p class="says"><span class="visually-hidden">${escapeHtml(text)}</span><span class="typed" aria-hidden="true"></span></p>` +
      receiptHtml(receipt) + `</div>`;
    log.appendChild(el);
    scrollTo(el);
    const said = speech || text;
    const reveal = revealer(el.querySelector(".typed"), text, said.length);
    if (reduced || muted() || !window.speechSynthesis) reveal.finish();
    speak(said, reveal);
  }

  function addCandidate(text) {
    const el = document.createElement("div");
    el.className = "utterance candidate";
    el.innerHTML = `<span class="avatar" aria-hidden="true">Y</span><div>` +
      `<div class="speaker"><span>You</span></div><p class="says">${escapeHtml(text)}</p></div>`;
    log.appendChild(el);
    scrollTo(el);
    return el;
  }

  function counts(c) {
    $("help-count").textContent = `Challenges ${c.challenges} · Nudges ${c.nudges} · Hints ${c.hints}`;
  }

  // What each model call did, by the event that reports it.
  const JOBS = {
    transcription_model: "Transcript of your answer", endpoint_decision: "Whether you had finished",
    challenge_result: "Your committed number", scoring_result: "Quoted reasoning", follow_up_result: "Follow-up (model-matched)",
  };
  function modelRow(model, job) {
    if (!model || !model.model) return;
    const rows = $("model-rows");
    if (rows.dataset.empty !== "no") { rows.innerHTML = ""; rows.dataset.empty = "no"; }
    const time = model.latency_s == null ? null : model.latency_s >= 1 ? `${model.latency_s.toFixed(1)} s` : model.latency_s < 0.001 ? "under 1 ms" : `${Math.round(model.latency_s * 1000)} ms`;
    const cost = model.estimated_cost_usd == null ? null : `$${model.estimated_cost_usd.toFixed(4)}`;
    const row = document.createElement("div");
    row.className = "modelrow";
    row.innerHTML = `<div><strong class="mono">${escapeHtml(model.model)}${model.mode === "replay" ? " (recorded)" : ""}</strong>` +
      `<small>${escapeHtml(JOBS[job] || job)}</small></div>` +
      `<div class="nums mono">${[time, cost].filter(Boolean).join("<br>")}</div>`;
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
        $("puzzle-eyebrow").textContent = (event.kind === "check" ? "Drill check"
          : event.kind === "drill" ? `Drill question ${event.number} of up to 3` : `Question ${event.number} of up to 4`)
          + ` · guide ${fmt(event.guide_seconds)}`;
        $("puzzle-kind").textContent = ({ twin: "Same puzzle, new numbers", drill: "Aimed at one mistake",
                                          check: "New numbers, no help" }[event.kind] || "New puzzle")
          + (event.difficulty ? ` · ${event.difficulty}` : "");
        finishReveals();
        questionStart = Date.now(); answeredThisQuestion = false; offered = false; heard = false;
        $("why").hidden = true; $("why").open = false;
        counts({ challenges: 0, nudges: 0, hints: 0 });
        updateTimer();
        break;
      case "scored":
        $("why").hidden = !event.why;
        $("why-text").textContent = event.why || "";
        if (event.meter) showMeter(event.meter);
        break;
      case "part2":
        $("puzzle").textContent = event.text;
        $("puzzle-kind").textContent = "Part 2 · not scored";
        finishReveals();
        break;
      case "follow_up":
        $("puzzle").textContent = event.text;
        $("puzzle-kind").textContent = "Follow-up · model-matched, not scored";
        finishReveals();
        break;
      case "follow_up_result":
        modelRow(event.model, event.type);
        break;
      case "interviewer_line":
        addInterviewer(event.text, event.kind, event.receipt, event.speech);
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
        modelRow(event.model, event.type);
        break;
      case "scoring_result":
        modelRow(event.model, event.type);
        break;
      case "transcription_model":
        modelRow(event.model, event.type);
        break;
      case "endpoint_decision":
        modelRow(event.model, event.type);
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

  // ---------- Evidence meter (decision log 16): model estimates after each scored answer ----------
  function showMeter(m) {
    $("meter-empty").hidden = true;
    $("meter-rows").innerHTML = m.estimate.map((r) => {
      const pct = Math.round(r.p * 100);
      return `<div class="meter-row"><dt><span>${escapeHtml(r.label)}</span><span class="mono meter-pct">${pct}%</span></dt>` +
        `<dd><span class="meter-bar" aria-hidden="true"><span style="width:${pct}%"></span></span></dd></div>`;
    }).join("");
    $("meter-line").textContent = m.line;
    $("meter-line").hidden = !m.line;
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
    if (!gateOpen()) { updateGate(); return; }
    setStatus("");
    consent.disabled = true;
    topicSelect.disabled = true;
    document.querySelectorAll('input[name="level"]').forEach((r) => { r.disabled = true; });
    stopMeter();
    $("setup-view").hidden = true;
    $("room").hidden = false;
    $("practice-tag").hidden = !typedPractice;
    $("selfview").hidden = !window.UBCamera?.attachSelf();  // the camera stays on, local only
    window.scrollTo(0, 0);
    phase = "checking";
    render();
    if (!typing) {
      try { await voice.open(); } catch { setTyping(true); setStatus("The microphone is unavailable, so you can type your answers instead."); }
    }
    socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/interview/ws`);
    const level = document.querySelector('input[name="level"]:checked')?.value || "Easy";
    socket.onopen = () => socket.send(JSON.stringify(drill
      ? { type: "begin", consent: true, headphones: headphones.checked, drill }
      : { type: "begin", consent: true, headphones: headphones.checked, pack: chosenTrack, topic: topicSelect.value || null, level,
          typed_practice: typedPractice }));
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

  // ---------- Typed answers: typed practice, replay mode, or a microphone that fails ----------
  function setTyping(on) {
    typing = on;
    typePanel.hidden = !on;
    finishReveals();
    if (on && capturing) voice.flush();  // close the open capture; its words come back as a turn
    render();
    if (on && phase === "listening") typeAnswer.focus();
    if (!on && phase === "listening" && !capturing && !captureRequested) openTurn();
  }
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
  consent.addEventListener("change", () => { updateGate(); if (consent.checked) setStatus(""); });

  // ---------- Device gate (decision log 20): Start unlocks once everything is checked ----------
  const exempt = () => typedPractice || replay;
  function missing() {
    const need = [];
    if (!exempt() && !cameraOk) need.push("the camera shows a picture");
    if (!exempt() && !micHeard) need.push("the microphone picks up sound");
    if (!connected) need.push("the server connects");
    if (!consent.checked) need.push("you tick the agreement");
    return need;
  }
  const gateOpen = () => missing().length === 0;
  function updateGate() {
    const need = missing();
    start.disabled = need.length > 0;
    const list = need.length > 1 ? `${need.slice(0, -1).join(", ")} and ${need[need.length - 1]}` : need[0];
    $("gate-note").textContent = need.length ? `Start unlocks once ${list}.`
      : replay ? "Recorded replay mode: answers are typed." : typedPractice ? "Typed practice: not exam conditions." : "Ready when you are.";
  }
  document.addEventListener("ub-camera", (e) => { cameraOk = e.detail.ok; updateGate(); });
  $("typed-practice").addEventListener("click", () => {
    typedPractice = !typedPractice;
    $("typed-practice").textContent = typedPractice ? "Use camera and mic instead" : "Can't use a camera or mic?";
    setTyping(typedPractice || replay);
    updateGate();
  });

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
    const check = $("mic-check");
    try {
      await voice.open();
    } catch {
      note.textContent = "The microphone is blocked or missing.";
      note.className = "device-note bad";
      check.textContent = "Not working"; check.className = "check-state bad";
      return;
    }
    if (!micHeard) {
      note.textContent = "Say something: the bar should move. Nothing is sent.";
      note.className = "device-note";
      check.textContent = "Listening for sound"; check.className = "check-state";
    }
    const bar = $("mic-meter");
    const draw = () => {
      const level = voice.level();
      bar.style.width = `${Math.round(level * 100)}%`;
      if (!micHeard && level > 0.08) {
        micHeard = true;
        check.textContent = "Sound picked up"; check.className = "check-state ok";
        note.textContent = "Your microphone works. Nothing was sent."; note.className = "device-note ok";
        updateGate();
      }
      meterFrame = requestAnimationFrame(draw);
    };
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
    connected = true;
    $("connection-state").textContent = "Connected"; $("connection-state").className = "check-state ok";
    $("connection-note").textContent = "Connected to the Unbluffable server.";
    if (c.mode === "replay") {
      replay = true;
      setTyping(true);
      $("typed-practice-row").hidden = true;
      setStatus("Recorded replay mode: answers are typed and checked against recorded model calls.");
    }
    updateGate();
  }).catch(() => {
    $("connection-state").textContent = "Not connected"; $("connection-state").className = "check-state bad";
    $("connection-note").textContent = "Can't reach the server. Check your connection and reload.";
    $("connection-note").className = "device-note bad";
  });

  // ---------- Drill mode (decision log 16): /ui/interview?drill=<report session>&m=<n> ----------
  const query = new URLSearchParams(location.search);
  const drill = query.get("drill") ? { session: query.get("drill"), index: Number(query.get("m")) } : null;
  if (drill) {
    $("setup").querySelector(".picker").hidden = true;
    $("setup-title").textContent = "Prepare your drill";
    $("choose-title").textContent = "Drill one mistake";
    $("setup-sub").textContent = "Up to 3 questions aimed at one mistake, then a check with new numbers. Check your camera and microphone, then just talk.";
    $("puzzle").textContent = "The interviewer reads the first drill question when you start.";
    $("puzzle-eyebrow").textContent = "Drill · up to 3 questions, then a check";
  }

  // ---------- Track cards, then topic (template "pack"; tracks being added can't be picked) ----------
  const trackBox = $("track");
  const topicSelect = $("topic");
  let tracks = [], chosenTrack = null;
  const showTopics = () => {
    const track = tracks.find((t) => t.id === chosenTrack);
    if (!track) return;
    topicSelect.replaceChildren(...track.topics.map((o) => {
      const option = document.createElement("option");
      option.value = o.id;
      option.textContent = o.count == null ? o.name : `${o.name} (${o.count} template${o.count === 1 ? "" : "s"})`;
      option.selected = o.id === track.default;
      return option;
    }));
  };
  function pickTrack(id, focus) {
    chosenTrack = id;
    trackBox.querySelectorAll("button.track").forEach((b) => {
      const on = b.dataset.track === id;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    showTopics();
  }
  trackBox.addEventListener("click", (e) => {
    const b = e.target.closest("button.track");
    if (b && !topicSelect.disabled) pickTrack(b.dataset.track);
  });
  trackBox.addEventListener("keydown", (e) => {
    const open = [...trackBox.querySelectorAll("button.track")];
    const at = open.findIndex((b) => b.dataset.track === chosenTrack);
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!step || at < 0) return;
    e.preventDefault();
    pickTrack(open[(at + step + open.length) % open.length].dataset.track, true);
  });
  fetch("/api/interview/topics").then((r) => (r.ok ? r.json() : Promise.reject())).then((t) => {
    tracks = t.tracks;
    const asked = tracks.find((x) => x.id === query.get("track") && x.available);
    const first = asked ? asked.id : t.default_track;
    trackBox.innerHTML = tracks.map((x) => trackCard(x, { selected: x.id === first })).join("");
    pickTrack(first);
  }).catch(() => {
    topicSelect.replaceChildren(new Option("Default", ""));
  });

  updateGate();
  render();
});
