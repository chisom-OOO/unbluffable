// Exam Room interview, wired to /api/interview/ws (server session, engine scoring).
// Hands-free after one Start tap (decision log 4). The indicator shows real state only
// (decision log 5): Listening while a capture or typed turn is open, "Checking your working"
// while the server's check runs, Speaking from SpeechSynthesis start/end events.
// Decision log 20: Start only begins once the camera shows a picture, the microphone picks
// up sound and the server answers. Pressed earlier, it opens a dialog saying what is missing
// and what to do. "Can't use a camera or mic?" switches to typed practice, labelled "Not exam
// conditions"; so does a microphone that fails after Start. Done is a fallback for noisy rooms.
document.addEventListener("DOMContentLoaded", () => {
  if (window.UB.desktopOnly()) return;  // decision log 26: laptop or desktop only
  const { highlight, escapeHtml, reducedMotion, receiptHtml, trackCard } = window.UB;
  const voice = window.UBVoice;
  const $ = (id) => document.getElementById(id);

  const start = $("start"), mic = $("mic"), micState = $("mic-state"), done = $("done");
  const log = $("log"), live = $("live"), liveText = $("live-text");
  const typePanel = $("type-panel"), typeAnswer = $("type-answer");
  const mute = $("mute"), consent = $("consent"), headphones = $("headphones"), status = $("status");

  const KIND_TAG = { challenge: "Challenge", nudge: "Nudge", hint: "Hint", trade: "Trade", reveal: "Reveal" };
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
  // Device gate (decision log 20): see UBTurn.gateProblems for the states.
  let connection = "checking", micStatus = "unchecked", camera = "off", typedPractice = false, replay = false;
  let micFailurePending = false;  // told to the server between captures

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
  let muting = 0;  // lines being spoken that mute the microphone (not the device-check test line)
  function speechChanged() {
    const talking = speaking > 0;
    voice.mute(!headphones.checked && muting > 0);  // no echo without headphones
    if (capturing && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "interviewer_speaking", value: talking, headphones: headphones.checked }));
    }
    render();
  }


  const muted = () => mute.getAttribute("aria-pressed") === "true";

  // `reveal` (optional) types the line out as it is spoken; it never delays the mic.
  // The microphone is unmuted on the end event, on error, on cancel, or at the line's
  // estimated length plus 2 s, whichever comes first (UBTurn.guardUtterance).
  // `mutes: false` (the device check's test line) never mutes the microphone.
  const guards = new Set();
  function speak(text, reveal, { mutes = true } = {}) {
    if (muted() || !window.speechSynthesis) { reveal?.finish(); return; }
    const u = new SpeechSynthesisUtterance(text);
    u.voice = window.UB.pickVoice();
    const gen = speechGen;
    let counted = false;
    const guard = window.UBTurn.guardUtterance(u, {
      text, rate: u.rate,
      onStart: () => {
        if (gen !== speechGen) return;
        counted = true; speaking++; if (mutes) muting++;
        speechChanged();
        reveal?.start();
      },
      onDone: () => {
        guards.delete(guard);
        reveal?.finish();
        if (!counted || gen !== speechGen) return;
        speaking = Math.max(0, speaking - 1);
        if (mutes) muting = Math.max(0, muting - 1);
        speechChanged();
      },
    });
    guards.add(guard);
    u.onboundary = (e) => { if (gen === speechGen && e.name === "word") reveal?.boundary(e.charIndex); };
    speechSynthesis.speak(u);
    reveal?.watch(() => guard.started);
  }

  function cancelSpeech() {
    const active = [...guards];
    speechGen++; speaking = 0; muting = 0;
    for (const g of active) g.cancel();
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
    behavioural_judged: "Quotes for each step (model-judged)",
    coding_plan: "Your approach, quoted", coding_question: "A question about your code",
    coding_follow_up: "The follow-up question", coding_judge: "Your follow-up answer (model-judged)",
    market_quote: "Your bid and offer, read from your words", market_question: "Which question to ask about your logic",
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

  // ---------- Market making (decision log 28): the market panel beside the transcript ----------
  // Fair value is never shown during a round; P&L appears at settlement.
  const signed = (x) => (String(x).startsWith("-") ? `−${String(x).slice(1)}` : `+${x}`);
  function marketState(e) {
    $("market-revealed").innerHTML = e.revealed.length ? `<ul>${e.revealed.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`
      : `<p class="fine">Nothing revealed yet.</p>`;
    $("market-quotes").innerHTML = e.quotes.length ? e.quotes.map((q, i) =>
      `<tr${i === e.quotes.length - 1 ? ' class="latest"' : ""}><td>${i > 0 && e.quotes[i - 1].stage === q.stage ? "Tightened" : q.stage === 0 ? "Opening" : `After reveal ${q.stage}`}</td>`
      + `<td class="mono">${escapeHtml(q.bid)}</td><td class="mono">${escapeHtml(q.ask)}</td></tr>`).join("")
      : `<tr><td colspan="3" class="empty">No quote yet.</td></tr>`;
    $("market-trades").textContent = e.trades.length ? e.trades.map((t) => `${t.side > 0 ? "Bought" : "Sold"} at ${t.price}`).join(" · ") : "None yet";
    $("market-position").textContent = e.position === 0 ? "Flat" : `${e.position > 0 ? "Long" : "Short"} ${Math.abs(e.position)}`;
    $("market-pnl").textContent = "At settlement";
  }

  // ---------- Turns ----------
  async function openTurn() {
    phase = "listening";
    live.hidden = true;
    render();
    if (typing) {
      tellMicFailure();
      if (!window.UBCoding.editing) typeAnswer.focus({ preventScroll: true });  // never pull focus out of the code editor
      return;
    }
    try {
      await voice.open();
    } catch {
      micFailed();
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
    tellMicFailure();
    typeAnswer.value = "";
    phase = "checking";
    render();
    socket.send(JSON.stringify({ type: "typed", transcript: text }));
  }

  // ---------- Coding rounds: a code message never interrupts an open capture ----------
  // The relay only listens for "done" during a capture, so a run, pause or submit waits
  // until the capture has closed and the server is listening again.
  let pendingCode = null;
  function sendCode(message) {
    if (capturing || captureRequested) {
      pendingCode = message;
      if (capturing) voice.flush();
      return;
    }
    socket.send(JSON.stringify(message));
  }
  $("drawer-toggle").addEventListener("click", () => {
    const open = $("rail").classList.toggle("open");
    $("drawer-toggle").setAttribute("aria-expanded", String(open));
  });

  // ---------- A text-only timeline of this interview (exported only with consent) ----------
  const timeline = { started: null, events: [] };
  const KEEP = {
    question: (e) => ({ number: e.number, kind: e.kind, text: e.text, topic: e.topic || null, difficulty: e.difficulty || null }),
    part2: (e) => ({ text: e.text }),
    follow_up: (e) => ({ text: e.text }),
    interviewer_line: (e) => ({ kind: e.kind, text: e.text, receipt: e.receipt || null }),
    answer_complete: (e) => ({ transcript: e.transcript }),
    session_end: (e) => ({ label: e.label || null, behavioural: !!e.behavioural, timed_out: !!e.timed_out }),
  };
  function record(e) {
    if (!KEEP[e.type]) return;
    if (timeline.started === null) timeline.started = performance.now();
    timeline.events.push({ t: Math.round(performance.now() - timeline.started), type: e.type, ...KEEP[e.type](e) });
  }
  $("export-consent").addEventListener("change", () => { $("export-timeline").disabled = !$("export-consent").checked; });
  $("export-timeline").addEventListener("click", () => {
    if (!$("export-consent").checked) return;
    const end = timeline.events.find((e) => e.type === "session_end");
    const file = { version: 1, kind: "unbluffable-recorded-interview", exported_at: new Date().toISOString(),
                   label: end ? end.label : null, events: timeline.events };
    const url = URL.createObjectURL(new Blob([JSON.stringify(file, null, 2)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `unbluffable-interview-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  function handle(event) {
    record(event);
    switch (event.type) {
      case "session":
        sessionId = event.id;
        startCountdown(event.session_seconds);
        break;
      case "question":
        question = event;
        if (event.kind === "coding") {
          window.UBCoding.enter(event.coding, sendCode);
        }
        $("puzzle").textContent = event.text;
        $("provenance").innerHTML = window.UB.provenanceHtml(event.provenance_rows);
        $("market-panel").hidden = event.kind !== "market";
        $("puzzle-eyebrow").textContent = (event.kind === "check" ? "Drill check"
          : event.kind === "market" ? `Market ${event.number} of ${event.market.rounds}`
          : event.kind === "behavioural" ? `Behavioural question ${event.number} of 2`
          : event.kind === "coding" ? "Coding round"
          : event.kind === "drill" ? `Drill question ${event.number} of up to 3`
          : placement ? `Placement question ${event.number} of 5` : `Question ${event.number} of up to 4`)
          + ` · guide ${fmt(event.guide_seconds)}`;
        $("puzzle-kind").textContent = ({ twin: "Same puzzle, new numbers", drill: "Aimed at one mistake",
                                          check: "New numbers, no help", coding: "Python · code while you talk",
                                          market: "Market making · graded exactly",
                                          behavioural: `${event.behavioural_type === "situational" ? "What would you do" : "Tell me about a time"} · model-judged, not exact` }[event.kind] || "New puzzle")
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
      case "market_state":
        marketState(event);
        break;
      case "market_settle":
        $("market-pnl").textContent = `${signed(event.realised_pnl)} realised · ${signed(event.expected_pnl)} expected`;
        $("market-revealed").insertAdjacentHTML("beforeend", `<p class="market-settle"><strong>Settled at ${escapeHtml(event.payoff)}</strong> (${escapeHtml(event.draws)})</p>`);
        break;
      case "market_model":
        modelRow(event.model, event.job);
        break;
      case "state":
        if (event.value === "listening" && pendingCode) {  // the code message waited for the capture to close
          socket.send(JSON.stringify(pendingCode));
          pendingCode = null;
          break;
        }
        if (event.value === "listening") openTurn();
        if (event.value === "checking") { phase = "checking"; render(); }
        break;
      case "ready":
        capturing = true; captureRequested = false;
        voice.startStreaming(socket);
        speechChanged();
        if (pendingCode) voice.flush();  // close this capture so the code message can go
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
      case "behavioural_judged":
        modelRow(event.model, event.type);
        break;
      case "coding_model":
        modelRow(event.model, event.job);
        break;
      case "coding_open":
        window.UBCoding.opened();
        break;
      case "coding_closed":
        window.UBCoding.closed();
        break;
      case "coding_speech":
        addCandidate(event.text);
        break;
      case "coding_result":
        window.UBCoding.result(event);
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
        // Coding rounds close captures to send code; an empty one is not worth a message.
        if (!(window.UBCoding.active && /intelligible/i.test(event.message || ""))) setStatus(event.message);
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

  // ---------- A microphone that fails after Start (decision log 20) ----------
  // In exam conditions the rest of the session becomes typed practice, and the report says so.
  // The server hears it between captures (a capture only listens for "done").
  function micFailed() {
    if (capturing && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "done" }));
    capturing = false; captureRequested = false;
    voice.stopStreaming();
    voice.close();
    if (!typedPractice && !replay) {
      typedPractice = true;
      micFailurePending = true;
      $("practice-tag").hidden = false;
    }
    setStatus("The microphone stopped working, so the rest is typed practice: not exam conditions.");
    setTyping(true);
  }
  function tellMicFailure() {
    if (!micFailurePending || socket?.readyState !== WebSocket.OPEN || capturing || captureRequested) return;
    socket.send(JSON.stringify({ type: "mic_failed" }));
    micFailurePending = false;
  }
  document.addEventListener("ub-mic-ended", () => {
    if (!$("room").hidden) { if (!typing) micFailed(); return; }
    micHeardReset();
    setMic("none");
  });

  // ---------- Start: the one tap (browsers need a gesture for mic and speech) ----------
  async function begin() {
    if (!gateOpen()) { openGateDialog(); return; }
    setStatus("");
    consent.disabled = true;
    lockTopics();
    document.querySelectorAll('input[name="level"]').forEach((r) => { r.disabled = true; });
    stopMeter();
    if (gateDialog.open) gateDialog.close();
    $("setup-view").hidden = true;
    $("room").hidden = false;
    $("practice-tag").hidden = !typedPractice;
    $("selfview").hidden = !window.UBCamera?.attachSelf();  // the camera stays on, local only
    window.scrollTo(0, 0);
    phase = "checking";
    render();
    if (!typing) {
      // Before the socket opens: the begin message then says typed practice.
      try { await voice.open(); } catch { micFailed(); micFailurePending = false; }
    }
    socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/interview/ws`);
    const level = document.querySelector('input[name="level"]:checked')?.value || "Easy";
    socket.onopen = () => socket.send(JSON.stringify(drill
      ? { type: "begin", consent: true, headphones: headphones.checked, drill }
      : placement
        ? { type: "begin", consent: true, headphones: headphones.checked, pack: chosenTrack, placement: true, typed_practice: typedPractice }
        : { type: "begin", consent: true, headphones: headphones.checked, pack: chosenTrack, topics: sentTopics(), level,
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

  // The mute button itself is shared (ui.js) and remembered across pages.
  document.addEventListener("ub-mute", (e) => { if (e.detail.muted) cancelSpeech(); });
  headphones.addEventListener("change", speechChanged);
  consent.addEventListener("change", () => { updateGate(); if (consent.checked) setStatus(""); });

  // ---------- Device gate (decision log 20): Start never goes dead ----------
  // Start stays clickable, styled as not ready; pressed early it opens the dialog below.
  const gateDialog = $("gate-dialog");
  const problems = () => window.UBTurn.gateProblems({
    exempt: typedPractice || replay, mic: micStatus, camera, connection, consent: consent.checked, topics: topicCount() });
  const gateOpen = () => problems().length === 0;
  function updateGate() {
    const need = problems();
    start.classList.toggle("not-ready", need.length > 0);
    $("gate-note").textContent = need.length ? need.map((p) => p.action).join(" · ")
      : replay ? "Recorded replay mode: answers are typed." : typedPractice ? "Typed practice: not exam conditions." : "Ready when you are.";
    if (gateDialog.open) renderGateDialog();
  }
  document.addEventListener("ub-camera", (e) => { camera = e.detail.reason || (e.detail.ok ? "ok" : "off"); updateGate(); });
  function setTypedPractice(on) {
    typedPractice = on;
    $("typed-practice").textContent = typedPractice ? "Use camera and mic instead" : "Can't use a camera or mic?";
    setTyping(typedPractice || replay);
    updateGate();
  }
  $("typed-practice").addEventListener("click", () => setTypedPractice(!typedPractice));

  // ---------- The dialog: what is missing and what to do, in plain steps ----------
  const ADDRESS_BAR = ["Click the camera or microphone icon in the address bar.", "Choose Allow.", "Reload this page."];
  const NO_SOUND = { title: "No sound yet", text: ["Say something; the bar should move.", "If it stays flat, choose another input below."], devices: true };
  const STEPS = {
    mic: {
      none: { title: "No microphone found", text: ["Connect a microphone (headphones with a mic work), then press Test microphone."], button: ["Test again", "mic"] },
      blocked: { title: "Microphone blocked", text: ADDRESS_BAR, button: ["Try again", "mic"] },
      busy: { title: "Microphone not responding", text: ["Close other apps that use the microphone, then press Test again."], button: ["Test again", "mic"] },
      unchecked: { title: "Microphone not tested yet", text: ["Press Test microphone and allow it when the browser asks."], button: ["Test microphone", "mic"] },
      listening: NO_SOUND, quiet: NO_SOUND,
    },
    camera: {
      none: { title: "No camera found", text: ["Connect a camera (a built-in or USB webcam works), then press Turn on camera."], button: ["Turn on camera", "camera"] },
      blocked: { title: "Camera blocked", text: ADDRESS_BAR, button: ["Try again", "camera"] },
      busy: { title: "Camera not responding", text: ["Close other apps that use the camera, then press Try again."], button: ["Try again", "camera"] },
      off: { title: "Camera off", text: ["Press Turn on camera and allow it when the browser asks."], button: ["Turn on camera", "camera"] },
      waiting: { title: "Waiting for a picture", text: ["Check nothing covers the camera. If no picture appears, press Try again."], button: ["Try again", "camera"] },
    },
    connection: {
      failed: { title: "Server not connected", text: ["Check your connection and reload."], button: ["Reload", "reload"] },
      checking: { title: "Connecting to the server", text: ["This takes a moment. If it doesn't connect, check your connection and reload."] },
    },
    topics: { none: { title: "No topic chosen", text: ["Choose at least one topic, or press Select all."], button: ["Select all", "topics-all"] } },
    consent: { unticked: { title: "Agreement not ticked", text: ["Tick the box agreeing that your answer text is kept for this practice session."], button: ["Go to the agreement", "consent"] } },
  };
  function renderGateDialog() {
    const need = problems();
    if (!need.length) { gateDialog.close(); return; }
    const focused = gateDialog.contains(document.activeElement) ? document.activeElement.dataset.action || document.activeElement.id : null;
    $("gate-steps").innerHTML = need.map((p) => {
      const s = STEPS[p.key][p.state] || Object.values(STEPS[p.key])[0];
      const lines = s.text.length > 1 ? `<ol class="substeps">${s.text.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ol>` : `<p>${escapeHtml(s.text[0])}</p>`;
      const devices = s.devices ? `<div class="field"><label for="gate-mic-device">Input</label><select id="gate-mic-device">${$("mic-device").innerHTML}</select></div>` +
        `<div class="devicebar" aria-hidden="true"><span id="gate-mic-meter"></span></div>` : "";
      const button = s.button ? `<button class="btn secondary btn-small" type="button" data-action="${s.button[1]}">${s.button[0]}</button>` : "";
      return `<li class="gate-step"><strong>${escapeHtml(s.title)}</strong>${lines}${devices}${button}</li>`;
    }).join("");
    const select = $("gate-mic-device");
    if (select) { select.value = $("mic-device").value; select.addEventListener("change", () => chooseMic(select.value)); }
    if (focused) (gateDialog.querySelector(`[data-action="${focused}"]`) || $(focused) || $("gate-dialog-title")).focus();
  }
  function openGateDialog() {
    renderGateDialog();
    if (!problems().length) return;
    gateDialog.showModal();
    $("gate-dialog-title").focus();
  }
  let focusAfterClose = null;
  gateDialog.addEventListener("close", () => {
    if ($("setup-view").hidden) return;
    (focusAfterClose || start).focus();
    focusAfterClose = null;
  });
  gateDialog.addEventListener("click", (e) => {
    const action = e.target.closest("[data-action]")?.dataset.action;
    if (action === "mic") testMic($("mic-device").value || undefined);
    if (action === "camera") window.UBCamera?.start();
    if (action === "reload") location.reload();
    if (action === "topics-all") { selectAllTopics(); focusAfterClose = topicBox.querySelector("button.topic-chip"); gateDialog.close(); }
    if (action === "consent") { focusAfterClose = consent; gateDialog.close(); }
  });
  $("dialog-typed").addEventListener("click", () => {
    if (!typedPractice) setTypedPractice(true);
    gateDialog.close();
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
    if (!question || window.UBCoding.active) return;  // a coding round offers no help prompt
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

  // ---------- Device check before the first question (decision log 20) ----------
  // The microphone level is read locally from an AnalyserNode; nothing is sent. The meter
  // starts by itself once the page has microphone permission; Test microphone retries.
  const SOUND = 0.04;       // level (RMS x 4) that counts as sound
  const FLAT_MS = 6000;     // no sound for this long: suggest another microphone
  let meterFrame = null, flatTimer = null, micInputs = [];
  function stopMeter() { if (meterFrame) cancelAnimationFrame(meterFrame); meterFrame = null; clearTimeout(flatTimer); }
  function inputName() {
    const d = voice.device();
    const chosen = micInputs.find((i) => i.deviceId && i.deviceId === (d?.id || $("mic-device").value));
    return d?.label || chosen?.label || "this microphone";
  }
  const MIC_TEXT = {
    unchecked: ["Not checked", "", () => "Stays on this device; nothing is sent."],
    none: ["No microphone", "bad", () => "No microphone found. Connect one or use typed practice."],
    blocked: ["Blocked", "bad", () => "The browser is blocking the microphone. Allow it from the icon in the address bar, then reload."],
    busy: ["Not responding", "bad", () => "The microphone is in use by another app or not responding. Close other apps using it, then test again."],
    listening: ["Listening for sound", "", (n) => `Say something: the bar should move. Using ${n}. Nothing is sent.`],
    quiet: ["No sound yet", "bad", (n) => `No sound from ${n}. Try another microphone.`],
    ok: ["Sound picked up", "ok", (n) => `Your microphone works (${n}). Nothing was sent.`],
  };
  function setMic(state) {
    micStatus = state;
    const [check, cls, note] = MIC_TEXT[state];
    $("mic-check").textContent = check; $("mic-check").className = `check-state${cls ? ` ${cls}` : ""}`;
    $("mic-note").textContent = note(inputName()); $("mic-note").className = `device-note${cls ? ` ${cls}` : ""}`;
    updateGate();
  }
  function micHeardReset() { stopMeter(); $("mic-meter").style.width = "0%"; }

  // Inputs from enumerateDevices (local only). Labels appear once the microphone is allowed.
  async function listInputs() {
    try { micInputs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput"); }
    catch { micInputs = []; }
    const current = voice.device()?.id || $("mic-device").value;
    $("mic-device").innerHTML = micInputs.map((d, i) =>
      `<option value="${escapeHtml(d.deviceId)}">${escapeHtml(d.label || `Microphone ${i + 1}`)}</option>`).join("");
    if (micInputs.some((d) => d.deviceId === current)) $("mic-device").value = current;
    $("mic-device-row").hidden = micInputs.length === 0;
    return micInputs;
  }

  let testing = 0;
  async function testMic(deviceId) {
    const run = ++testing;
    micHeardReset();
    if (!navigator.mediaDevices?.getUserMedia || !(await listInputs()).length) { voice.close(); setMic("none"); return; }
    try {
      await voice.open(deviceId ? { deviceId } : {});
    } catch (error) {
      if (run === testing) setMic({ NotAllowedError: "blocked", SecurityError: "blocked", NotFoundError: "none", OverconstrainedError: "none" }[error?.name] || "busy");
      return;
    }
    if (run !== testing) return;
    await listInputs();
    setMic("listening");
    flatTimer = setTimeout(() => { if (micStatus === "listening") setMic("quiet"); }, FLAT_MS);
    const draw = () => {
      const level = voice.level();
      const width = `${Math.round(level * 100)}%`;
      $("mic-meter").style.width = width;
      const mirror = $("gate-mic-meter");
      if (mirror) mirror.style.width = width;
      if (micStatus !== "ok" && level > SOUND) { clearTimeout(flatTimer); setMic("ok"); }
      meterFrame = requestAnimationFrame(draw);
    };
    draw();
  }
  function chooseMic(id) { $("mic-device").value = id; testMic(id); }
  $("mic-test").addEventListener("click", () => testMic($("mic-device").value || undefined));
  $("mic-device").addEventListener("change", () => chooseMic($("mic-device").value));

  // Start the meter by itself once the microphone is allowed; follow permission and device changes.
  function permissionSeen(state) {
    if (!$("room").hidden) return;
    if (state === "granted" && !["ok", "listening"].includes(micStatus)) testMic();
    if (state === "denied") setMic("blocked");
  }
  if (navigator.permissions?.query) {
    navigator.permissions.query({ name: "microphone" }).then((p) => {
      permissionSeen(p.state);
      p.onchange = () => permissionSeen(p.state);
    }).catch(() => {});
  }
  navigator.mediaDevices?.addEventListener?.("devicechange", async () => {
    if (!$("room").hidden) return;
    const inputs = await listInputs();
    if (!inputs.length) { voice.close(); micHeardReset(); setMic("none"); }
    else if (micStatus === "none") testMic();
  });
  if (navigator.mediaDevices) listInputs().then((inputs) => { if (!inputs.length) setMic("none"); });
  $("speaker-test").addEventListener("click", () => {
    const note = $("speaker-note");
    if (!window.speechSynthesis) { note.textContent = "This browser has no speech voice; lines will appear as text."; note.className = "device-note bad"; return; }
    if (mute.getAttribute("aria-pressed") === "true") { note.textContent = "The interviewer is muted; unmute to hear the test line."; return; }
    speechSynthesis.cancel();
    speak("Okay. Talk me through how you'd approach this, and tell me the number you commit to.", null, { mutes: false });  // never mutes the microphone check
    note.textContent = "Playing a preview.";
  });

  // The interviewer's voice: ranked most human first; the choice is remembered in this browser.
  function listVoices() {
    const ranked = window.UB.rankedVoices();
    $("voice-row").hidden = ranked.length === 0;
    if (!ranked.length) return;
    const chosen = window.UB.pickVoice();
    $("voice-select").innerHTML = ranked.map((v) =>
      `<option value="${escapeHtml(v.voiceURI)}"${v === chosen ? " selected" : ""}>${escapeHtml(v.name)} (${escapeHtml(v.lang)})</option>`).join("");
    if (window.UBTurn.onlyRobotic(window.speechSynthesis.getVoices())) {
      $("speaker-note").textContent = "This browser only has robotic-sounding voices. Edge or Chrome have more natural ones.";
    }
  }
  if (window.speechSynthesis) {
    listVoices();
    speechSynthesis.addEventListener?.("voiceschanged", listVoices);
  }
  $("voice-select").addEventListener("change", () => {
    window.UB.store.set("ub-voice", $("voice-select").value);
    $("speaker-test").click();  // hear it straight away
  });

  // ---------- Config: connection check, and replay mode has no live microphone path ----------
  fetch("/api/voice/config").then((r) => (r.ok ? r.json() : Promise.reject())).then((c) => {
    config = c;
    connection = "ok";
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
    connection = "failed";
    updateGate();
    $("connection-state").textContent = "Not connected"; $("connection-state").className = "check-state bad";
    $("connection-note").textContent = "Can't reach the server. Check your connection and reload.";
    $("connection-note").className = "device-note bad";
  });

  // ---------- Drill mode (decision log 16): /ui/interview?drill=<report session>&m=<n> ----------
  // Placement (decision log 23): /ui/interview?placement=1&track=<id>, one question from each
  // of five strength areas, starting at Medium; topics and level are not chosen.
  const query = new URLSearchParams(location.search);
  const placement = query.get("placement") === "1" && !query.get("drill");
  if (placement) {
    $("setup-title").textContent = "Find your starting level";
    $("setup-sub").textContent = "Five questions, one from each of five strength areas of the track, starting at Medium. Challenges and help work as usual.";
    $("puzzle-eyebrow").textContent = "Placement · 5 questions";
    document.querySelector(".topics-field").hidden = true;
    $("levels").hidden = true;
    $("topic-note").hidden = true;
  }
  const drill = query.get("drill") ? { session: query.get("drill"), index: Number(query.get("m")) } : null;
  if (drill) {
    $("setup").querySelector(".picker").hidden = true;
    $("setup-title").textContent = "Prepare your drill";
    $("choose-title").textContent = "Drill one mistake";
    $("setup-sub").textContent = "Up to 3 questions aimed at one mistake, then a check with new numbers. Check your camera and microphone, then just talk.";
    $("puzzle").textContent = "The interviewer reads the first drill question when you start.";
    $("puzzle-eyebrow").textContent = "Drill · up to 3 questions, then a check";
  }

  // ---------- Track cards, then topics (template "pack"; tracks being added can't be picked) ----------
  // Topics are toggle chips, all selected by default; the last selection is remembered per
  // track (this browser only). A track with no topics hides the picker.
  const trackBox = $("track");
  const topicBox = $("topic");
  let tracks = [], chosenTrack = null, chosenTopics = new Set(), topicsKnown = false, picking = true;
  const trackTopics = () => (tracks.find((t) => t.id === chosenTrack)?.topics || []).filter((o) => o.id !== "Mixed");
  const BEHAVIOURAL = "Behavioural";  // decision log 24: runs on its own, model-judged
  const MARKET = "Market making";  // decision log 28: runs on its own, graded exactly
  const SOLO = new Set([BEHAVIOURAL, MARKET]);
  const forgeTopics = () => trackTopics().filter((o) => !SOLO.has(o.id)).map((o) => o.id);
  const allTopics = () => new Set(forgeTopics().length ? forgeTopics() : trackTopics().map((o) => o.id));
  // Topics sent with Start: null (the server's default) when the list failed or there are none.
  const sentTopics = () => (topicsKnown && trackTopics().length ? [...chosenTopics] : null);
  // Drills choose their own questions.
  function topicCount() { return drill || placement || !sentTopics() ? 1 : chosenTopics.size; }
  const topicKey = () => `ub-topics:${chosenTrack}`;
  function loadTopics() {
    let saved = null;
    try { saved = JSON.parse(window.UB.store.get(topicKey()) || "null"); } catch { saved = null; }
    const ids = new Set(trackTopics().map((o) => o.id));
    const kept = Array.isArray(saved) ? saved.filter((id) => ids.has(id)) : [];
    const solo = kept.find((id) => SOLO.has(id));
    if (solo) return new Set([solo]);
    return kept.length ? new Set(kept) : allTopics();
  }
  function saveTopics() { window.UB.store.set(topicKey(), JSON.stringify([...chosenTopics])); }
  function syncTopics() {
    topicBox.querySelectorAll("button.topic-chip").forEach((b) => b.setAttribute("aria-pressed", String(chosenTopics.has(b.dataset.topic))));
    const n = chosenTopics.size, all = forgeTopics().length;
    const behaviouralOn = chosenTopics.has(BEHAVIOURAL), marketOn = chosenTopics.has(MARKET);
    $("topics-note").textContent = n === 0 ? "Choose at least one topic."
      : behaviouralOn ? "Behavioural: two questions, each with one follow-up. Model-judged, not exact; kept out of your rating."
      : marketOn ? "Market making: two games. Quote a bid and an offer; the interviewer trades against you. Graded exactly."
      : n === all ? "All topics selected." : `${n} of ${all} topics selected.`;
    $("topics-note").classList.toggle("bad", n === 0);
    $("levels").hidden = placement || behaviouralOn || marketOn || codingChosen();  // no ladder for these rounds
    updateGate();
  }
  function showTopics() {
    chosenTopics = loadTopics();
    topicBox.removeAttribute("aria-busy");
    trackBox.removeAttribute("aria-busy");
    topicBox.innerHTML = trackTopics().map((o) =>
      `<button type="button" class="topic-chip" aria-pressed="false" data-topic="${escapeHtml(o.id)}">${escapeHtml(o.name)}</button>`).join("");
    topicBox.closest(".topics-field").hidden = placement || trackTopics().length === 0;
    syncTopics();
  }
  function setTopics(next) { if (!picking) return; chosenTopics = next; saveTopics(); syncTopics(); }
  function selectAllTopics() { setTopics(allTopics()); }
  function lockTopics() {
    picking = false;
    $("setup").querySelectorAll(".picker button").forEach((b) => { b.disabled = true; });
  }
  topicBox.addEventListener("click", (e) => {
    const id = e.target.closest("button.topic-chip")?.dataset.topic;
    if (!id) return;
    let next = new Set(chosenTopics);
    if (next.has(id)) next.delete(id);
    else if (SOLO.has(id)) next = new Set([id]);  // runs on its own
    else { SOLO.forEach((s) => next.delete(s)); next.add(id); }
    setTopics(next);
  });
  $("topics-all").addEventListener("click", selectAllTopics);
  $("topics-clear").addEventListener("click", () => setTopics(new Set()));
  function pickTrack(id, focus) {
    chosenTrack = id;
    trackBox.querySelectorAll("button.track").forEach((b) => {
      const on = b.dataset.track === id;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    showTopics();
    levelFromProfile();
    $("coding-note").hidden = !codingChosen();
    syncFormat();
  }
  // Decision log 27: a track with coding specs (Software) is always a coding round.
  const codingChosen = () => !placement && !drill && !!tracks.find((t) => t.id === chosenTrack)?.coding;
  function syncFormat() { $("levels").hidden = placement || codingChosen() || [...SOLO].some((s) => chosenTopics.has?.(s)); }

  // Decision log 23: the start level follows this track's rating estimate (< 40 Easy,
  // 40-69 Medium, 70+ Hard); it can still be changed here.
  function levelFromProfile() {
    const P = window.UBProfile, S = window.UB.profile();
    const o = P && S ? P.overall(P.areaScores(S.load(), chosenTrack)) : null;
    $("level-note").hidden = !o;
    if (!o) return;
    const level = P.startLevel(o.rating);
    const radio = document.querySelector(`input[name="level"][value="${level}"]`);
    if (radio && !radio.disabled) radio.checked = true;
    $("level-note").textContent = `Start level from your rating estimate: ${P.shown(o.rating)} (${P.band(o.rating)}).`;
  }
  trackBox.addEventListener("click", (e) => {
    const b = e.target.closest("button.track");
    if (b && picking) pickTrack(b.dataset.track);
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
    const profileTrack = tracks.find((x) => x.id === window.UB.profile()?.load().default_track && x.available);
    const first = asked ? asked.id : profileTrack ? profileTrack.id : t.default_track;
    trackBox.innerHTML = tracks.map((x) => trackCard(x, { selected: x.id === first })).join("");
    topicsKnown = true;
    pickTrack(first);
  }).catch(() => {
    trackBox.innerHTML = "";
    topicBox.innerHTML = "";
    trackBox.removeAttribute("aria-busy"); topicBox.removeAttribute("aria-busy");
    $("topics-note").textContent = "Topics couldn't load; the interview uses all topics.";
  });

  updateGate();
  render();
});
