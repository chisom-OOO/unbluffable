// Interview preview: hands-free after one Start tap (decision log 4), with fake data.
// The mic shows Listening / Thinking / Speaking on its own; Done is only a fallback.
// No microphone, model or speech calls are made here; the real voice path lives in /practice and voice/.
document.addEventListener("DOMContentLoaded", () => {
  const data = window.UB_FAKE;
  const { highlight, escapeHtml, reducedMotion } = window.UB;
  const $ = (id) => document.getElementById(id);

  const start = $("start"), mic = $("mic"), micState = $("mic-state"), done = $("done");
  const log = $("log"), live = $("live"), liveText = $("live-text"), editRow = $("edit-row");
  const typePanel = $("type-panel"), typeAnswer = $("type-answer"), typeToggle = $("type-toggle");
  const mute = $("mute");

  $("puzzle").textContent = data.puzzle.text;
  $("puzzle-kind").textContent = data.puzzle.kind;

  const STATE_TEXT = {
    ready: "One tap starts the interview",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    finished: "Preview ends here",
  };

  const reduced = reducedMotion();
  const T = {
    beforeTalk: reduced ? 600 : 1200,   // candidate starts talking
    word: 150,                          // live transcript pace
    endPause: reduced ? 900 : 1400,     // pause read as "finished" (end-of-answer detection)
    think: reduced ? 400 : 900,
  };

  let state = "ready";
  let turn = 0;
  let hints = 0, nudges = 0, challenges = 0;
  let typing = false, answered = false, offered = false;
  let editing = null;
  let timers = [];
  let streamTimer = null;
  let speakTimer = null, pendingThen = null;

  const later = (fn, ms) => { const id = setTimeout(fn, ms); timers.push(id); return id; };
  function cancelListening() {
    timers.forEach(clearTimeout); timers = [];
    clearInterval(streamTimer); streamTimer = null;
  }

  function setState(next) {
    state = next;
    mic.dataset.state = next === "listening" || next === "thinking" || next === "speaking" ? next : "idle";
    micState.textContent = typing && next === "listening" ? "Waiting for your typed answer" : STATE_TEXT[next];
    done.disabled = next !== "listening";
    typeToggle.disabled = next === "ready" || next === "finished";
    document.querySelector(".action-bar").classList.toggle("ready", next === "ready");
  }

  function scrollTo(el) {
    el.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }

  function addInterviewer(text, kind) {
    const el = document.createElement("div");
    const tags = { hint: "Hint", nudge: "Nudge", challenge: "Challenge" };
    el.className = "utterance interviewer" + (tags[kind] ? ` is-${kind}` : "");
    const tag = tags[kind] ? `<span class="tag tag-${kind}">${tags[kind]}</span>` : "";
    el.innerHTML = `<div class="speaker"><span>Interviewer</span>${tag}</div><p class="says">${escapeHtml(text)}</p>`;
    log.appendChild(el);
    scrollTo(el);
    return el;
  }

  function addCandidate(text) {
    const el = document.createElement("div");
    el.className = "utterance candidate";
    el.innerHTML = `<div class="speaker"><span>You</span></div><p class="says">${escapeHtml(text)}</p>`;
    log.appendChild(el);
    scrollTo(el);
    return el;
  }

  function updateCounts() {
    $("help-count").textContent = `Challenges ${challenges} · Nudges ${nudges} · Hints ${hints}`;
  }

  function fillModels() {
    $("model-rows").innerHTML = data.models.map((m) =>
      `<tr><td class="mono">${escapeHtml(m.model)}</td><td>${escapeHtml(m.job)}</td>` +
      `<td class="mono num-col">${m.ms >= 1000 ? (m.ms / 1000).toFixed(1) + " s" : m.ms + " ms"}</td>` +
      `<td class="mono num-col">${escapeHtml(m.cost)}</td></tr>`).join("");
  }
  $("model-rows").innerHTML = `<tr><td colspan="4">Nothing yet. Rows appear after your answer.</td></tr>`;

  // Interviewer "speaks" for a time proportional to the line (simulated; muted just shortens it).
  function speak(text, kind, then) {
    setState("speaking");
    addInterviewer(text, kind);
    const ms = mute.getAttribute("aria-pressed") === "true" ? 400 : Math.min(5000, 900 + text.length * 28);
    pendingThen = then;
    speakTimer = setTimeout(() => { speakTimer = pendingThen = null; then && then(); }, ms);
  }

  function think(then) {
    setState("thinking");
    setTimeout(then, T.think);
  }

  // ---- Listening: the mic is open; the candidate talks; a pause ends the answer ----
  function listen() {
    const script = data.script[turn];
    if (!script) return;
    setState("listening");
    if (typing) { typeAnswer.value = script.candidate; return; }

    live.hidden = false;
    editRow.hidden = true;
    liveText.hidden = false;
    liveText.textContent = "";

    later(() => {
      scrollTo(live);
      const words = script.candidate.split(" ");
      let i = 0;
      streamTimer = setInterval(() => {
        liveText.textContent = words.slice(0, ++i).join(" ");
        if (i >= words.length) {
          clearInterval(streamTimer); streamTimer = null;
          editRow.hidden = false;
          later(() => submit(takeLiveText()), T.endPause);
        }
      }, T.word);
    }, T.beforeTalk);
  }

  // Editing pauses end-of-answer detection; Done (or Space) sends.
  $("edit-btn").addEventListener("click", () => {
    cancelListening();
    editing = document.createElement("textarea");
    editing.className = "transcript-edit";
    editing.setAttribute("aria-label", "Edit your transcript, then press Done");
    editing.value = data.script[turn].candidate;
    liveText.hidden = true;
    editRow.hidden = true;
    live.insertBefore(editing, editRow);
    editing.focus();
  });

  function takeLiveText() {
    cancelListening();
    let text = liveText.textContent.trim() || data.script[turn].candidate;
    if (editing) { text = editing.value.trim() || text; editing.remove(); editing = null; }
    live.hidden = true;
    return text;
  }

  // ---- An answer is in: think, then the interviewer replies and the mic reopens ----
  function submit(text) {
    if (state !== "listening") return;
    const script = data.script[turn];
    answered = true;
    const node = addCandidate(text);
    think(() => {
      fillModels();
      if (script.challenge) node.querySelector(".says").innerHTML = highlight(text, script.challenge);
      const kind = script.reply.kind === "close" ? null : script.reply.kind;
      // The challenge is its own help step (decision log 3b), counted apart from nudges.
      if (kind === "challenge") challenges++;
      else if (kind === "hint") hints++;
      else if (kind) nudges++;
      if (kind) updateCounts();
      speak(script.reply.text, kind, () => {
        turn++;
        if (script.reply.kind === "close") {
          setState("finished");
          $("finish").hidden = false;
          scrollTo($("finish"));
          $("finish").querySelector("a").focus({ preventScroll: true });
        } else {
          listen();
        }
      });
    });
  }

  // Done is a fallback for noisy rooms or typed answers.
  function finishNow() {
    if (state !== "listening") return;
    if (typing) {
      const text = typeAnswer.value.trim();
      if (!text) return;
      typeAnswer.value = "";
      submit(text);
    } else {
      submit(takeLiveText());
    }
  }
  done.addEventListener("click", finishNow);

  // ---- Start: the one tap (browsers need a gesture for mic and speech) ----
  function begin() {
    start.hidden = true;
    mic.hidden = false;
    startClock();
    speak("Take your time. Talk me through it out loud.", null, listen);
  }
  start.addEventListener("click", begin);

  // ---- Typed answers ----
  typeToggle.addEventListener("click", () => {
    typing = !typing;
    typeToggle.setAttribute("aria-pressed", String(typing));
    typeToggle.textContent = typing ? "Use voice" : "Type instead";
    typePanel.hidden = !typing;
    if (state === "listening") {
      cancelListening();
      live.hidden = true;
      if (editing) { editing.remove(); editing = null; }
      listen();
      if (typing) typeAnswer.focus();
    }
  });
  typeAnswer.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); finishNow(); }
  });

  mute.addEventListener("click", () => {
    const on = mute.getAttribute("aria-pressed") !== "true";
    mute.setAttribute("aria-pressed", String(on));
    mute.setAttribute("aria-label", on ? "Unmute interviewer" : "Mute interviewer");
  });

  // ---- Space = Done while listening (unless typing into a field) ----
  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space" && e.key !== " ") return;
    const t = e.target;
    const editable = t.closest && t.closest("textarea, input, select, [contenteditable='true']");
    if (editable || state !== "listening") return;
    e.preventDefault();
    finishNow();
  }, true);

  // ---- Timer vs guide, and help offered at 60% of the guide ----
  const guide = data.puzzle.guideSeconds;
  const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  $("timer-guide").textContent = `${fmt(guide)} guide`;
  function startClock() {
    let elapsed = 0;
    const tick = setInterval(() => {
      if (state === "finished") { clearInterval(tick); return; }
      elapsed++;
      $("timer-text").textContent = fmt(elapsed);
      const timer = $("timer");
      timer.classList.toggle("over", elapsed > guide);
      timer.setAttribute("aria-label", `${fmt(elapsed)} elapsed, guide ${fmt(guide)}${elapsed > guide ? ", over guide" : ""}`);
      if (!answered && !offered && elapsed >= Math.round(guide * 0.6) && state === "listening" && !streamTimer) {
        offered = true;
        cancelListening();
        live.hidden = true;
        speak(data.offerHelp, null, listen);
      }
    }, 1000);
  }

  setState("ready");
  // Preview only: arriving from the landing's Start tap begins straight away.
  if (new URLSearchParams(location.search).get("start") === "1") begin();
});
