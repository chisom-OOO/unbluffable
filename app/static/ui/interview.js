// Exam Room interview, wired to /api/interview/ws (server session, engine scoring).
// Hands-free after one Start tap (decision log 4). The indicator shows real state only
// (decision log 5): Listening while a capture or typed turn is open, "Checking your working"
// while the server's check runs, Speaking from SpeechSynthesis start/end events.
// Decision log 20: Start only begins once the camera shows a picture, the microphone picks
// up sound and the server answers. Pressed earlier, it opens a dialog saying what is missing
// and what to do. "Can't use a camera or mic?" switches to typed practice, labelled "Not exam
// conditions"; so does a microphone that fails after Start. Done is a fallback for noisy rooms.
document.addEventListener("DOMContentLoaded", () => {
  if (window.UB.desktopOnly()) return;  // decision log 35: laptops and tablets, not phones
  const { highlight, escapeHtml, reducedMotion, receiptHtml, trackCard } = window.UB;
  const voice = window.UBVoice;
  const $ = (id) => document.getElementById(id);

  const start = $("start"), mic = $("mic"), micState = $("mic-state"), done = $("done");
  const log = $("log"), live = $("live"), liveText = $("live-text");
  const typePanel = $("type-panel"), typeAnswer = $("type-answer");
  const mute = $("mute"), consent = $("consent"), headphones = $("headphones"), status = $("status");

  const KIND_TAG = { challenge: "Challenge", nudge: "Nudge", hint: "Hint", trade: "Trade", reveal: "Reveal", clarify: "Fact" };
  const reduced = reducedMotion();
  const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  // Pace for revealing an interviewer line when the voice sends no word boundaries.
  const WORD_MS = 320;

  let config = null, socket = null, sessionId = null;
  let phase = "ready";           // ready | starting | listening | checking | finished
  let speaking = 0, speechGen = 0;
  let typing = false, capturing = false, captureRequested = false;
  let question = null, questionStart = 0, answeredThisQuestion = false, offered = false;
  let heard = false;  // any candidate speech, live transcript or typing since this question began
  let lastCandidate = null;
  // Device gate (decision log 20): see UBTurn.gateProblems for the states.
  let connection = "checking", micStatus = "unchecked", camera = "off", typedPractice = false, replay = false;
  let drillMistake = null;
  let micFailurePending = false;  // told to the server between captures

  // ---------- Indicator: derived from real state only ----------
  function render() {
    let shown = phase;
    if (speaking > 0 && phase !== "finished") shown = "speaking";
    const text = {
      ready: "One tap starts the interview",
      starting: "Starting the interview",
      listening: typing ? "Your turn — type your answer" : "Your turn — speak when ready",
      checking: "Checking your working",  // only after an answer
      speaking: "Interviewer speaking",
      finished: "Interview finished",
    }[shown];
    mic.dataset.state = shown === "checking" ? "thinking" : (["ready", "starting", "finished"].includes(shown) ? "idle" : shown);
    document.querySelector(".action-bar").dataset.turn = shown;
    micState.textContent = text;
    window.UBCoding?.status(shown === "ready" ? "waiting" : shown);
    done.disabled = phase !== "listening" || (!typing && !capturing);
    $("mic-sub").textContent = typing ? "Type your answer, then Done or Ctrl+Enter" : "Your answer ends when you pause, or press Done.";
    document.querySelector(".action-bar").classList.toggle("ready", phase === "ready");
  }

  function setStatus(message) { status.textContent = message || ""; status.hidden = !message; }

  function scrollTo(el) {
    if (marketRoom()) { atLatest = true; log.scrollTop = log.scrollHeight; return; }
    el.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }
  // Market making: the transcript has its own scroll under the scorecard. It follows the latest
  // line (including lines still typing in) unless you have scrolled up to read.
  const marketRoom = () => $("room").classList.contains("market");
  let atLatest = true;
  log.addEventListener("scroll", () => { atLatest = log.scrollHeight - log.scrollTop - log.clientHeight < 40; });
  new MutationObserver(() => { if (marketRoom() && atLatest) log.scrollTop = log.scrollHeight; })
    .observe(log, { childList: true, subtree: true, characterData: true });

  // ---------- Speech: real SpeechSynthesis events drive "Speaking" ----------
  let muting = 0;  // lines being spoken that mute the microphone (not the device-check test line)
  function speechChanged() {
    const talking = speaking > 0;
    voice.mute(window.UBTurn.micShouldMute({ headphones: headphones.checked, mutingLines: muting }));  // no echo without headphones
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
  // A more human delivery: the line is said sentence by sentence (about 400 ms apart) at rate
  // 0.92, with numbers as words and no symbols (UBTurn.speakable). The whole line counts as one
  // spoken line: "Speaking" and the echo-safety mute hold through the pauses.
  function speak(text, reveal, { mutes = true } = {}) {
    if (muted() || !window.speechSynthesis) { reveal?.finish(); return; }
    const T = window.UBTurn;
    const parts = T.sentences(T.speakable(text));
    const voice = window.UB.pickVoice();
    const gen = speechGen;
    let counted = false, finished = false, index = 0, offset = 0, current = null, pause = null;
    const line = { started: false };
    const end = () => {
      if (finished) return;
      finished = true;
      clearTimeout(pause);
      guards.delete(line);
      reveal?.finish();
      if (!counted || gen !== speechGen) return;
      speaking = Math.max(0, speaking - 1);
      if (mutes) muting = Math.max(0, muting - 1);
      speechChanged();
    };
    line.cancel = () => { current?.cancel(); end(); };
    const next = () => {
      if (finished || gen !== speechGen || index >= parts.length) { end(); return; }
      const part = parts[index++], at = offset;
      offset += part.length + 1;
      const u = new SpeechSynthesisUtterance(part);
      u.voice = voice;
      u.lang = voice?.lang || "en-GB";  // no voice list yet (iPad Safari): still English
      u.rate = T.SPEECH_RATE;
      current = T.guardUtterance(u, {
        text: part, rate: u.rate,
        onStart: () => {
          if (gen !== speechGen) return;
          line.started = true;
          if (counted) return;
          counted = true; speaking++; if (mutes) muting++;
          speechChanged();
          reveal?.start();
        },
        onDone: (reason) => {
          current = null;
          if (reason === "cancel" || gen !== speechGen) { end(); return; }
          pause = setTimeout(next, index < parts.length ? T.SENTENCE_PAUSE_MS : 0);
        },
      });
      u.onboundary = (e) => { if (gen === speechGen && e.name === "word") reveal?.boundary(at + e.charIndex); };
      speechSynthesis.speak(u);
    };
    guards.add(line);
    next();
    reveal?.watch(() => line.started);
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
  // `transcript` (a question line): the question is already at the top, so the transcript keeps
  // only what was said around it, "Okay, try this one. (question above)"; the whole line is
  // spoken as usual and shows at once.
  function addInterviewer(text, kind, receipt, speech, transcript) {
    const el = document.createElement("div");
    const tag = KIND_TAG[kind];
    el.className = "utterance interviewer" + (tag ? ` is-${kind}` : "");
    const short = transcript ? [transcript.lead, transcript.above ? "(question above)" : "", transcript.after].filter(Boolean).join(" ") : null;
    const body = transcript
      ? [transcript.lead && escapeHtml(transcript.lead), transcript.above ? `<span class="above">(question above)</span>` : "",
         transcript.after && escapeHtml(transcript.after)].filter(Boolean).join(" ")
      : "";
    el.innerHTML = `<span class="avatar" aria-hidden="true">I</span><div>` +
      `<div class="speaker"><span>Interviewer</span>${tag ? `<span class="tag tag-${kind}">${tag}</span>` : ""}</div>` +
      (transcript
        ? `<p class="says">${body}</p>`
        : `<p class="says"><span class="visually-hidden">${escapeHtml(text)}</span><span class="typed" aria-hidden="true"></span></p>`) +
      receiptHtml(receipt) + `</div>`;
    log.appendChild(el);
    scrollTo(el);
    // A short rotated opener before some statements (spoken only), never in a question.
    const said = kind === "ack" ? (speech || text) : window.UBTurn.withOpener(speech || text, kind, openers);
    openers.justAcknowledged = kind === "ack";
    const reveal = transcript ? revealer(document.createElement("span"), short) : revealer(el.querySelector(".typed"), text, window.UBTurn.speakable(said).length);
    if (transcript || reduced || muted() || !window.speechSynthesis) reveal.finish();
    speak(said, reveal);
  }
  const openers = { n: 0, lastHadOpener: false, justAcknowledged: false };

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
    $("help-count").hidden = !(c.challenges || c.nudges || c.hints);  // nothing to count yet
  }

  // What each model call did, by the event that reports it.
  const JOBS = {
    transcription_model: "Transcript of your answer", endpoint_decision: "Whether you had finished",
    challenge_result: "Your committed number", scoring_result: "Quoted reasoning", follow_up_result: "Follow-up (model-matched)",
    behavioural_judged: "Quotes for each step (model-judged)",
    conversational_judged: "Quotes for each key point (model-judged)",
    coding_plan: "Your approach, quoted", coding_question: "A question about your code",
    coding_follow_up: "The follow-up question", coding_judge: "Your follow-up answer (model-judged)",
    market_quote: "Your bid and offer, read from your words", market_question: "Which question to ask about your logic",
    case_quotes: "Quotes for each point (model-judged)", case_facts: "Which clarifying facts you asked about",
  };
  // Decision log 27: one row per model and job (count, median time, total cost); a live
  // transcription stream shows its audio seconds, not a latency.
  const modelCalls = [];
  function modelRow(model, job) {
    if (!model || !model.model) return;
    modelCalls.push({ ...model, job });
    const groups = window.UBTurn.groupModelCalls(modelCalls);
    // Muse Spark Open is served from Baseten (llm/client.py); its row says so.
    const host = (m) => (/muse-spark-open/.test(m) ? `<small class="model-host">open weights · Baseten</small>` : "");
    $("model-rows").innerHTML = groups.map((g) => `<div class="modelrow"><div><strong class="mono">${escapeHtml(g.model)}${g.recorded ? " (recorded)" : ""}</strong>`
      + host(g.model) + `<small>${escapeHtml(JOBS[g.job] || g.job)}</small></div>`
      + `<div class="nums mono">${window.UBTurn.modelFigures(g).map(escapeHtml).join("<br>")}</div></div>`).join("");
    $("models-summary-count").textContent = ` · ${modelCalls.length} call${modelCalls.length === 1 ? "" : "s"}`;
  }

  // ---------- Market making (decision log 28): the market panel beside the transcript ----------
  // Fair value is never shown during a round; P&L appears at settlement.
  const signed = (x) => (String(x).startsWith("-") ? `−${String(x).slice(1)}` : `+${x}`);
  // Before the first quote: one line on how to quote. After: the latest quote large, the
  // interviewer's trades and the reveals one line each, then position and P&L.
  function marketState(e) {
    const quoted = e.quotes.length > 0;
    $("market-hint").hidden = quoted;
    $("market-card").hidden = !quoted;
    if (!quoted) { $("market-settle-line").hidden = true; return; }
    const last = e.quotes[e.quotes.length - 1], prev = e.quotes[e.quotes.length - 2];
    $("market-bid").textContent = last.bid;
    $("market-ask").textContent = last.ask;
    $("market-stage").textContent = (prev && prev.stage === last.stage ? "Tightened" : last.stage === 0 ? "Opening quote" : `After reveal ${last.stage}`)
      + (e.quotes.length > 1 ? ` · earlier ${e.quotes.slice(0, -1).map((q) => `${q.bid} at ${q.ask}`).join(", ")}` : "");
    // side +1: you bought (the interviewer sold at your bid); -1: you sold (they bought at your offer).
    $("market-trades").textContent = e.trades.map((t) => t.side > 0 ? `sold to you at ${t.price}` : `bought from you at ${t.price}`).join(" · ");
    $("market-trade-line").hidden = !e.trades.length;
    $("market-revealed").textContent = e.revealed.join(" · ");
    $("market-reveal-line").hidden = !e.revealed.length;
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
        drillMistake = event.drill || null;  // the mistake a drill aims at (decision log 16)
        startCountdown(event.session_seconds);
        break;
      case "question":
        question = event;
        if (event.kind === "coding") {
          window.UBCoding.enter(event.coding, sendCode);
        } else if (window.UBCoding.active) {
          window.UBCoding.spoken(event);  // a spoken question after the coding round (Design concepts)
        }
        $("puzzle").textContent = event.text;
        $("provenance").innerHTML = window.UB.provenanceHtml(event.provenance_rows);
        $("market-panel").hidden = event.kind !== "market";
        $("room").classList.toggle("market", event.kind === "market");
        $("case-panel").hidden = event.kind !== "case";
        $("puzzle-eyebrow").textContent = (event.opener ? "Spoken opener · then a coding round"
          : event.kind === "check" ? "Drill check"
          : event.kind === "market" ? `Market ${event.number} of ${event.market.rounds}`
          : event.kind === "behavioural" ? `Behavioural question ${event.number} of ${event.of || 2}`
          : event.kind === "conversational" ? `${event.topic} question ${event.number} of ${event.conversational.of}`
          : event.kind === "case" ? `Full case · ${event.case.title}`
          : event.kind === "coding" ? "Coding round"
          : event.kind === "drill" ? `Drill question ${event.number} of up to 3`
          : placement ? `Placement question ${event.number} of 5` : `Question ${event.number} of up to 4`)
          + ` · guide ${fmt(event.guide_seconds)}`;
        $("puzzle-kind").textContent = ({ twin: "Same puzzle, new numbers", drill: "Aimed at one mistake",
                                          check: "New numbers, no help", coding: "Python · code while you talk",
                                          market: "Market making · graded exactly",
                                          conversational: `${event.conversational?.topic || ""} · model-judged, not exact`,
                                          case: "Consulting case · calculations exact, the rest model-judged",
                                          behavioural: `${event.behavioural_type === "situational" ? "What would you do" : "Tell me about a time"} · model-judged, not exact` }[event.kind] || "New puzzle")
          + (event.difficulty ? ` · ${event.difficulty}` : "");
        // Drill questions name the mistake they aim at; the check (no help) does not.
        if (event.kind === "drill" && drillMistake) $("puzzle-kind").textContent = `Mistake: ${drillMistake}`;
        finishReveals();
        questionStart = Date.now(); answeredThisQuestion = false; offered = false; heard = false;
        $("why").hidden = true; $("why").open = false;
        counts({ challenges: 0, nudges: 0, hints: 0 });
        updateTimer();
        break;
      case "scored":
        $("why").hidden = !event.why;
        $("why-text").textContent = event.why || "";
        $("why").open = !!event.why;  // shown only once the twin is scored, so it opens by itself
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
        addInterviewer(event.text, event.kind, event.receipt, event.speech, event.kind === "question" ? event.transcript : null);
        window.UBCoding.interviewerSaid(event.text);
        if (event.counts) counts(event.counts);
        // A reveal arrives as a line before the next market state: show it on the scorecard now.
        if (event.kind === "reveal" && !$("market-panel").hidden) {
          const said = event.text.replace(/\s*Update your market\.?\s*$/, "");
          $("market-revealed").textContent = [$("market-revealed").textContent, said].filter(Boolean).join(" · ");
          $("market-reveal-line").hidden = false;
        }
        break;
      case "market_state":
        marketState(event);
        break;
      case "market_settle":
        $("market-pnl").textContent = `${signed(event.realised_pnl)} realised · ${signed(event.expected_pnl)} expected`;
        $("market-settle").textContent = `pays ${event.payoff} (${event.draws})`;
        $("market-settle-line").hidden = false;
        break;
      case "market_model":
        modelRow(event.model, event.job);
        break;
      // Decision log 30: a full case. Facts appear only once asked; an exhibit shows as a table.
      case "case_fact":
        $("case-facts").insertAdjacentHTML("beforeend", event.facts.map((f) =>
          `<p class="case-fact"><strong>${escapeHtml(f.topic)}:</strong> ${escapeHtml(f.answer)}</p>`).join(""));
        break;
      case "case_stage":
        $("case-stage").textContent = { exhibit_calculation: "Exhibit: calculate exactly", insight: "What the numbers tell you",
          brainstorm: "Ideas", recommendation: "Your recommendation", follow_up_twist: "New information" }[event.kind] || "";
        if (event.exhibit) {
          const x = event.exhibit;
          $("case-exhibit").innerHTML = `<table class="market-quotes exhibit"><caption>${escapeHtml(x.title)}</caption>`
            + `<thead><tr>${x.columns.map((c) => `<th scope="col">${escapeHtml(c)}</th>`).join("")}</tr></thead>`
            + `<tbody>${x.rows.map((r) => `<tr>${r.map((v, i) => (i === 0 ? `<th scope="row">${escapeHtml(String(v))}</th>`
                : `<td class="mono">${escapeHtml(String(v))}</td>`)).join("")}</tr>`).join("")}</tbody></table>`;
        }
        break;
      case "case_judged":
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
        stated = event.stated_number || null;
        modelRow(event.model, event.type);
        break;
      case "scoring_result":
        verdictRow(stated || event.extraction?.committed_answer_text, event.observation);
        stated = null;
        modelRow(event.model, event.type);
        break;
      case "transcription_model":
        modelRow(event.model, event.type);
        break;
      case "conversational_judged":
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
      case "coding_part":
        window.UBCoding.part(event);
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

  // ---------- The verdict, inline under the answer ----------
  // The number you committed to, checked in code. The exact answer itself is not shown while
  // the question is open (a challenge must not give it away); the report shows it.
  let stated = null;
  const VERDICT = { correct: ["ok", "matches the exact answer"], named_wrong: ["wrong", "not the exact answer"],
                    other_wrong: ["wrong", "not the exact answer"], recited: ["wrong", "not the exact answer"] };
  function verdictRow(number, observation) {
    const v = VERDICT[observation];
    if (!v || !number || !lastCandidate) return;
    lastCandidate.querySelector(".verdict-row")?.remove();
    lastCandidate.querySelector(".says").insertAdjacentHTML("afterend",
      `<p class="verdict-row ${v[0]}"><span>You said <b class="mono">${escapeHtml(number)}</b></span>`
      + `<span>${v[1]}</span><span>checked in code</span></p>`);
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
    // iPad Safari: audio and speech start only inside the tap, so before any await.
    if (!typing) voice.unlock();
    window.UB.unlockSpeech();
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
    $("puzzle").textContent = "";  // the question itself replaces it once asked
    phase = "starting";
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
            typed_practice: typedPractice, ...(chosenRole ? { role: chosenRole } : {}) }));
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
  let showChecks = false;
  $("show-checks").addEventListener("click", () => { showChecks = !showChecks; updateGate(); });
  function updateGate() {
    const need = problems();
    const allOk = micStatus === "ok" && camera === "ok" && connection === "ok";
    $("all-passed").hidden = !allOk;
    $("device-details").hidden = allOk && !showChecks;
    $("show-checks").textContent = showChecks ? "Hide checks" : "Show checks";
    $("show-checks").setAttribute("aria-expanded", String(showChecks));
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

  // iPad and iPhone Safari may list no microphone until one is allowed, and always have a
  // built-in one: an empty list there means "not asked yet", not "none".
  const noListYet = () => window.UB.appleTouch() && !voice.isOpen;
  let testing = 0;
  async function testMic(deviceId) {
    const run = ++testing;
    micHeardReset();
    if (!navigator.mediaDevices?.getUserMedia || !(await listInputs()).length && !noListYet()) { voice.close(); setMic("none"); return; }
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
  $("mic-test").addEventListener("click", () => { voice.unlock(); testMic($("mic-device").value || undefined); });
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
  if (navigator.mediaDevices) listInputs().then((inputs) => { if (!inputs.length && !noListYet()) setMic("none"); });
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
    voiceTip();
  }
  // One line when the chosen voice isn't a Natural/Online one.
  function voiceTip() { $("voice-tip").hidden = window.UBTurn.naturalVoice(window.UB.pickVoice()); }
  if (window.UB.appleTouch()) {  // Edge on an iPad has Safari's voices: the tip names the iPad setting
    $("voice-tip").textContent = "For a more natural voice, download an Enhanced English voice in Settings, Accessibility, Spoken Content, Voices.";
  }
  if (window.speechSynthesis) {
    listVoices();
    speechSynthesis.addEventListener?.("voiceschanged", listVoices);
  }
  $("voice-select").addEventListener("change", () => {
    window.UB.store.set("ub-voice", $("voice-select").value);
    voiceTip();
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
    $("puzzle").textContent = "Press Start and the interviewer will read the first drill question.";
    $("puzzle-eyebrow").textContent = "Drill · up to 3 questions, then a check";
  }

  // ---------- Track cards, target role, then topics (setup redesign) ----------
  // Each track has target roles; a role's chips are its live topics, Core and Supporting shown,
  // Specialist under "More topics". No chip selected = a role-weighted mix (about 70% Core, 25%
  // Supporting, 5% Specialist). The last role and selection are remembered per track (this browser).
  const trackBox = $("track");
  const topicBox = $("topic");
  let tracks = [], chosenTrack = null, chosenRole = null, chosenTopics = new Set(), topicsKnown = false, picking = true;
  const BEHAVIOURAL = "Behavioural";  // decision log 24: model-judged
  const MARKET = "Market making";  // decision log 28: graded exactly
  const trackOf = () => tracks.find((t) => t.id === chosenTrack);
  const roleOf = () => (trackOf()?.roles || []).find((r) => r.id === chosenRole) || null;
  const chips = () => roleOf()?.chips || [];
  // Decision log 37: chips combine freely (mix.js); only special formats chosen = no level to pick.
  const isSpecial = (id) => chips().some((c) => c.id === id && c.kind !== "topic");
  // Topics sent with Start: the chosen chips ([] = the role-weighted mix); null when topics failed to load.
  const sentTopics = () => (topicsKnown ? [...chosenTopics] : null);
  // A role needs no chip (none = the mix); drills and placement choose their own questions.
  function topicCount() { return 1; }
  const topicKey = () => `ub-topics:${chosenTrack}:${chosenRole}`;
  function loadTopics() {
    let saved = null;
    try { saved = JSON.parse(window.UB.store.get(topicKey()) || "null"); } catch { saved = null; }
    const ids = new Set(chips().map((c) => c.id));
    return new Set(Array.isArray(saved) ? saved.filter((id) => ids.has(id)) : []);
  }
  function saveTopics() { window.UB.store.set(topicKey(), JSON.stringify([...chosenTopics])); }
  const specialOnly = () => chosenTopics.size > 0 && [...chosenTopics].every(isSpecial);
  function syncTopics() {
    document.querySelectorAll("#topic button.topic-chip, #topic-more button.topic-chip")
      .forEach((b) => b.setAttribute("aria-pressed", String(chosenTopics.has(b.dataset.topic))));
    const n = chosenTopics.size, role = roleOf();
    const behaviouralOn = chosenTopics.has(BEHAVIOURAL), marketOn = chosenTopics.has(MARKET);
    const talkOn = chips().some((c) => chosenTopics.has(c.id) && (c.kind === "conversational" || c.kind === "design"));
    // Several chips with a special format: what runs, in order ("Probability, Mental math, then a market-making game.").
    const mix = window.UBMix.note(chips(), [...chosenTopics], trackOf()?.mix);
    $("topics-note").textContent = mix ? mix
      : n === 0 ? (role?.opener ? "No specific topics selected - a probability or expected-value opener, then a coding round."
                                                           : "No specific topics selected - use a role-weighted mix.")
      : behaviouralOn ? "Behavioural: two questions, each with one follow-up. Model-judged, not exact; kept out of your rating."
      : marketOn ? "Market making: two games. Quote a bid and an offer; the interviewer trades against you. Graded exactly."
      : talkOn ? "Two conversational questions, each with a follow-up and a twist. Model-judged, not exact (a capacity number is checked exactly); kept out of your rating."
      : `${n} topic${n === 1 ? "" : "s"} selected.`;
    $("topics-note").classList.remove("bad");
    syncFormat();
    updateGate();
  }
  const chipHtml = (c) => `<button type="button" class="topic-chip" aria-pressed="false" data-topic="${escapeHtml(c.id)}" data-tier="${c.tier}">`
    + `<span class="tick" aria-hidden="true"></span><span>${escapeHtml(c.name)}</span></button>`;
  function showTopics() {
    chosenTopics = loadTopics();
    topicBox.removeAttribute("aria-busy");
    trackBox.removeAttribute("aria-busy");
    const main = chips().filter((c) => c.tier !== "specialist"), more = chips().filter((c) => c.tier === "specialist");
    topicBox.innerHTML = main.map(chipHtml).join("");
    $("topic-more").innerHTML = more.map(chipHtml).join("");
    $("more-topics").hidden = more.length === 0;
    $("more-topics").open = more.some((c) => chosenTopics.has(c.id));
    topicBox.closest(".topics-field").hidden = placement || chips().length === 0;
    syncTopics();
  }
  function setTopics(next) { if (!picking) return; chosenTopics = next; saveTopics(); syncTopics(); }
  function lockTopics() {
    picking = false;
    $("setup").querySelectorAll(".picker button").forEach((b) => { b.disabled = true; });
  }
  const chipClick = (e) => {
    const id = e.target.closest("button.topic-chip")?.dataset.topic;
    if (!id) return;
    setTopics(new Set(window.UBMix.toggle([...chosenTopics], id)));
  };
  topicBox.addEventListener("click", chipClick);
  $("topic-more").addEventListener("click", chipClick);
  $("topics-clear").addEventListener("click", () => setTopics(new Set()));

  // The target role: a listbox with a checkmark on the chosen role.
  const roleKey = () => `ub-role:${chosenTrack}`;
  function renderRoles() {
    const roles = trackOf()?.roles || [];
    $("role-field").hidden = placement || !!drill || roles.length === 0;
    $("role-list").innerHTML = roles.map((r) => `<li role="option" id="role-${escapeHtml(r.id)}" data-role="${escapeHtml(r.id)}"`
      + ` aria-selected="${r.id === chosenRole}" aria-disabled="${!r.available}" class="role-option${r.available ? "" : " off"}">`
      + `<span class="role-check" aria-hidden="true">${r.id === chosenRole ? "✓" : ""}</span><span>${escapeHtml(r.name)}</span>`
      + `${r.available ? "" : '<span class="tag">Being added</span>'}</li>`).join("");
    const role = roleOf();
    $("role-name").textContent = role ? role.name : "Choose a role";
    $("role-note").hidden = !role?.note;
    $("role-note").textContent = role?.note || "";
  }
  function pickRole(id) {
    const role = (trackOf()?.roles || []).find((r) => r.id === id && r.available);
    if (!role) return;
    chosenRole = id;
    window.UB.store.set(roleKey(), id);
    renderRoles();
    showTopics();
  }
  function openRoles(open) {
    $("role-list").hidden = !open;
    $("role-button").setAttribute("aria-expanded", String(open));
    if (open) {
      const at = $("role-list").querySelector('[aria-selected="true"]') || $("role-list").querySelector('[aria-disabled="false"]');
      $("role-list").focus();
      if (at) $("role-list").setAttribute("aria-activedescendant", at.id);
    }
  }
  $("role-button").addEventListener("click", () => { if (picking) openRoles($("role-list").hidden); });
  $("role-list").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-role]");
    if (!li || li.getAttribute("aria-disabled") === "true") return;
    pickRole(li.dataset.role);
    openRoles(false);
    $("role-button").focus();
  });
  $("role-list").addEventListener("keydown", (e) => {
    const options = [...$("role-list").querySelectorAll('li[aria-disabled="false"]')];
    const current = $("role-list").getAttribute("aria-activedescendant");
    let at = Math.max(0, options.findIndex((o) => o.id === current));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      at = (at + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
      $("role-list").setAttribute("aria-activedescendant", options[at].id);
      options.forEach((o, i) => o.classList.toggle("active", i === at));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (options[at]) pickRole(options[at].dataset.role);
      openRoles(false);
      $("role-button").focus();
    } else if (e.key === "Escape" || e.key === "Tab") {
      openRoles(false);
      if (e.key === "Escape") $("role-button").focus();
    }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".role-select")) openRoles(false); });

  // A role from the profile's roles (welcome page), else the one last chosen here, else the first.
  function startingRole() {
    const roles = (trackOf()?.roles || []).filter((r) => r.available);
    const asked = query.get("role");
    let saved = null;
    try { saved = window.UB.store.get(roleKey()); } catch { saved = null; }
    const fromProfile = (window.UB.profile()?.load().roles || []).includes("quant_dev") && chosenTrack === "quant" ? "quant_dev" : null;
    return (roles.find((r) => r.id === asked) || roles.find((r) => r.id === saved) || roles.find((r) => r.id === fromProfile) || roles[0])?.id || null;
  }
  function pickTrack(id, focus) {
    chosenTrack = id;
    trackBox.querySelectorAll("button.track").forEach((b) => {
      const on = b.dataset.track === id;
      b.setAttribute("aria-checked", String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    chosenRole = startingRole();
    renderRoles();
    showTopics();
    levelFromProfile();
  }
  // Software and Quantitative Development are coding rounds; special formats alone have no level.
  const codingChosen = () => !placement && !drill && !!roleOf()?.coding;
  function syncFormat() {
    const role = roleOf();
    $("levels").hidden = placement || codingChosen() || specialOnly();
    $("coding-note").hidden = !codingChosen() || specialOnly();
    $("coding-note").textContent = role?.opener
      ? "Quantitative development: one spoken probability or expected-value question, then a coding round in Python (talk through your approach, code it while you explain, then run the tests)."
      : "Software interviews are a coding round in Python: talk through your approach, code it in the editor while you explain, then run the tests.";
  }

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
    const asked = tracks.find((x) => x.id === (query.get("track") === "quant_dev" ? "quant" : query.get("track")) && x.available);
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
