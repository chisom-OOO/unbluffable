// Interview preview: a scripted run through idle → listening → thinking → speaking, with fake data.
// No microphone, model or speech calls are made here; the real voice path lives in /practice and voice/.
document.addEventListener("DOMContentLoaded", () => {
  const data = window.UB_FAKE;
  const { highlight, escapeHtml, reducedMotion } = window.UB;
  const $ = (id) => document.getElementById(id);

  const mic = $("mic"), micState = $("mic-state"), done = $("done"), stuck = $("stuck");
  const log = $("log"), live = $("live"), liveText = $("live-text"), editRow = $("edit-row");
  const typePanel = $("type-panel"), typeAnswer = $("type-answer"), typeToggle = $("type-toggle");
  const mute = $("mute");

  $("puzzle").textContent = data.puzzle.text;
  $("puzzle-kind").textContent = data.puzzle.kind;

  const STATE_TEXT = {
    idle: "Tap to talk",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Interviewer speaking",
    finished: "Interview finished",
  };
  const MIC_LABEL = {
    idle: "Start talking",
    listening: "Finish answer",
    thinking: "Interviewer is thinking",
    speaking: "Interrupt the interviewer",
    finished: "Interview finished",
  };

  let state = "idle";
  let turn = 0;
  let hints = 0, nudges = 0;
  let streamTimer = null, editing = null, answered = false, offered = false;
  let typing = false;
  let speakTimer = null, pendingThen = null;

  function setState(next) {
    state = next;
    mic.dataset.state = next === "finished" ? "idle" : next;
    mic.setAttribute("aria-label", MIC_LABEL[next]);
    micState.textContent = STATE_TEXT[next];
    mic.disabled = next === "thinking" || next === "finished";
    done.disabled = !(next === "listening" || (typing && next === "idle"));
    stuck.disabled = next === "thinking" || next === "speaking" || next === "finished";
  }

  function scrollTo(el) {
    el.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
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
    $("help-count").textContent = `Hints ${hints} · Nudges ${nudges}`;
  }

  function fillModels() {
    $("model-rows").innerHTML = data.models.map((m) =>
      `<tr><td class="mono">${escapeHtml(m.model)}</td><td>${escapeHtml(m.job)}</td>` +
      `<td class="mono num-col">${m.ms >= 1000 ? (m.ms / 1000).toFixed(1) + " s" : m.ms + " ms"}</td>` +
      `<td class="mono num-col">${escapeHtml(m.cost)}</td></tr>`).join("");
  }
  $("model-rows").innerHTML = `<tr><td colspan="4">Nothing yet. Rows appear after your answer.</td></tr>`;

  // Interviewer "speaks" for a time proportional to the line (simulated; muted just skips the wait).
  function speak(text, kind, then) {
    setState("speaking");
    const el = addInterviewer(text, kind);
    const ms = mute.getAttribute("aria-pressed") === "true" ? 400 : Math.min(5000, 900 + text.length * 28);
    pendingThen = then;
    speakTimer = setTimeout(() => { speakTimer = pendingThen = null; then && then(el); }, ms);
  }

  function think(then) {
    setState("thinking");
    setTimeout(then, reducedMotion() ? 400 : 900);
  }

  // ---- Listening ----
  function startListening() {
    const script = data.script[turn];
    if (!script) return;
    setState("listening");
    live.hidden = false;
    editRow.hidden = true;
    liveText.hidden = false;
    liveText.textContent = "";
    scrollTo(live);

    const words = script.candidate.split(" ");
    let i = 0;
    clearInterval(streamTimer);
    streamTimer = setInterval(() => {
      liveText.textContent = words.slice(0, ++i).join(" ");
      if (i >= words.length) { clearInterval(streamTimer); streamTimer = null; editRow.hidden = false; }
    }, 150);
  }

  function beginEdit() {
    clearInterval(streamTimer); streamTimer = null;
    editing = document.createElement("textarea");
    editing.className = "transcript-edit";
    editing.setAttribute("aria-label", "Edit your transcript before sending");
    editing.value = data.script[turn].candidate;
    liveText.hidden = true;
    editRow.hidden = true;
    live.insertBefore(editing, editRow);
    editing.focus();
  }
  $("edit-btn").addEventListener("click", beginEdit);

  function takeLiveText() {
    clearInterval(streamTimer); streamTimer = null;
    let text = data.script[turn].candidate;
    if (editing) { text = editing.value.trim() || text; editing.remove(); editing = null; }
    live.hidden = true;
    return text;
  }

  // ---- Submitting an answer (voice Done, Space, or typed) ----
  function submit(text) {
    const script = data.script[turn];
    answered = true;
    const node = addCandidate(text);
    think(() => {
      fillModels();
      if (script.challenge) node.querySelector(".says").innerHTML = highlight(text, script.challenge);
      const kind = script.reply.kind === "close" ? null : script.reply.kind;
      if (kind === "nudge") { nudges++; updateCounts(); }
      speak(script.reply.text, kind, () => {
        turn++;
        if (script.reply.kind === "close") {
          setState("finished");
          $("finish").hidden = false;
          scrollTo($("finish"));
          $("finish").querySelector("a").focus({ preventScroll: true });
        } else {
          setState("idle");
        }
      });
    });
  }

  function finishAnswer() {
    if (state === "listening") submit(takeLiveText());
    else if (typing && state === "idle" && typeAnswer.value.trim()) {
      const text = typeAnswer.value.trim();
      typeAnswer.value = "";
      submit(text);
    }
  }

  mic.addEventListener("click", () => {
    if (state === "idle") startListening();
    else if (state === "listening") finishAnswer();
    // Barge-in: stop the interviewer; the line stays on screen.
    else if (state === "speaking") { clearTimeout(speakTimer); const then = pendingThen; speakTimer = pendingThen = null; then && then(); }
  });
  done.addEventListener("click", finishAnswer);

  // ---- I'm stuck: ask, candidate says what's wrong, then a hint ----
  stuck.addEventListener("click", () => {
    if (state === "listening") { clearInterval(streamTimer); streamTimer = null; live.hidden = true; if (editing) { editing.remove(); editing = null; } }
    speak(data.stuck.ask, null, () => {
      setState("listening");
      addCandidate(data.stuck.candidate);
      think(() => {
        hints++; updateCounts();
        speak(data.stuck.hint, "hint", () => setState("idle"));
      });
    });
  });

  // ---- Typed answers ----
  typeToggle.addEventListener("click", () => {
    typing = !typing;
    typeToggle.setAttribute("aria-pressed", String(typing));
    typeToggle.textContent = typing ? "Use voice" : "Type instead";
    typePanel.hidden = !typing;
    if (typing) { typeAnswer.value = data.script[turn]?.candidate ?? ""; typeAnswer.focus(); }
    setState(state);
  });
  typeAnswer.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); finishAnswer(); }
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
    finishAnswer();
  }, true);

  // ---- Timer vs guide, and help offered at 60% of the guide ----
  const guide = data.puzzle.guideSeconds;
  const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  $("timer-guide").textContent = `${fmt(guide)} guide`;
  let elapsed = 0;
  const tick = setInterval(() => {
    if (state === "finished") { clearInterval(tick); return; }
    elapsed++;
    $("timer-text").textContent = fmt(elapsed);
    const timer = $("timer");
    timer.classList.toggle("over", elapsed > guide);
    timer.setAttribute("aria-label", `${fmt(elapsed)} elapsed, guide ${fmt(guide)}${elapsed > guide ? ", over guide" : ""}`);
    if (!answered && !offered && elapsed >= Math.round(guide * 0.6) && state === "idle") {
      offered = true;
      speak(data.offerHelp, null, () => setState("idle"));
    }
  }, 1000);

  // Opening line.
  addInterviewer("Take your time. Talk me through it out loud.", null);
  setState("idle");
});
