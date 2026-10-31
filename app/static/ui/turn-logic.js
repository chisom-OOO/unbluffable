// Pure turn rules for the Exam Room, shared by the page and the Node unit test.
(() => {
  // Help offered at 60% of the guide (spec/01) only to a candidate who has been silent since the
  // question ended: never with a live transcript, typed text, or any speech heard this question.
  function shouldOfferHelp(s) {
    if (s.offered || s.answered || s.heard) return false;
    if (s.phase !== "listening" || s.speaking) return false;
    if ((s.liveText || "").trim() || (s.typedText || "").trim()) return false;
    return s.elapsed >= Math.round(s.guide * 0.6);
  }

  // Echo safety: without headphones the microphone is muted while a line is spoken. Some
  // browsers never fire the utterance's end event, so the line also ends on error, on cancel,
  // and at its estimated length plus 2 s (about 2.5 words a second at rate 1).
  function speechTimeoutMs(text, rate = 1) {
    const words = String(text || "").trim().split(/\s+/).filter(Boolean).length;
    return Math.round((words / 2.5) * 1000 / (rate || 1)) + 2000;
  }

  // Wires an utterance: onStart once it starts; onDone(reason, started) exactly once, on
  // "end", "error", "cancel" or "timeout". Returns { cancel }.
  function guardUtterance(u, { text, rate, onStart, onDone, setTimer = setTimeout, clearTimer = clearTimeout }) {
    let started = false, done = false, timer = null;
    const finish = (reason) => {
      if (done) return;
      done = true;
      if (timer !== null) clearTimer(timer);
      onDone(reason, started);
    };
    u.onstart = () => {
      if (done || started) return;
      started = true;
      onStart?.();
      timer = setTimer(() => finish("timeout"), speechTimeoutMs(text, rate));
    };
    u.onend = () => finish("end");
    u.onerror = () => finish("error");
    return { cancel: () => finish("cancel"), get started() { return started; } };
  }

  // Decision log 20: what still stands between the candidate and Start, as actions.
  // camera: off | waiting | ok | blocked | none | busy; mic: unchecked | listening | quiet |
  // ok | blocked | none | busy; connection: checking | ok | failed. Typed practice and replay
  // skip the camera and microphone.
  const CAMERA = { off: "Turn on your camera", waiting: "Wait for your camera picture", blocked: "Allow the camera in your browser",
                   none: "Connect a camera", busy: "Close other apps using the camera" };
  const MIC = { unchecked: "Test your microphone", listening: "Say something so we can hear you", quiet: "Say something so we can hear you",
                blocked: "Allow the microphone in your browser", none: "Connect a microphone", busy: "Close other apps using the microphone" };
  function gateProblems(s) {
    const out = [];
    if (!s.exempt && s.mic !== "ok") out.push({ key: "mic", state: s.mic, action: MIC[s.mic] || MIC.unchecked });
    if (!s.exempt && s.camera !== "ok") out.push({ key: "camera", state: s.camera, action: CAMERA[s.camera] || CAMERA.off });
    if (s.connection !== "ok") out.push({ key: "connection", state: s.connection,
      action: s.connection === "failed" ? "Check your connection and reload" : "Wait for the server to connect" });
    if (s.topics === 0) out.push({ key: "topics", state: "none", action: "Choose at least one topic" });
    if (!s.consent) out.push({ key: "consent", state: "unticked", action: "Tick the agreement" });
    return out;
  }

  // The browser's English voices, most human first: natural/neural voices, then Google's
  // UK/US English, then the rest, with robotic desktop voices last; British English first
  // within each group, then American, then other English.
  const NATURAL = /natural|neural|online|premium|enhanced|siri/i;
  const ROBOTIC = /desktop|espeak|compact|eloquence|\bbad\b|robot/i;
  function voiceTier(v) {
    if (NATURAL.test(v.name)) return 0;
    if (/^google (uk|us) english/i.test(v.name)) return 1;
    if (ROBOTIC.test(v.name)) return 3;
    return 2;
  }
  const langRank = (lang) => (/^en[-_]GB/i.test(lang) ? 0 : /^en[-_]US/i.test(lang) ? 1 : 2);
  function rankVoices(voices) {
    return voices.filter((v) => /^en/i.test(v.lang || ""))
      .map((v, i) => ({ v, i }))
      .sort((a, b) => voiceTier(a.v) - voiceTier(b.v) || langRank(a.v.lang) - langRank(b.v.lang)
                       || a.v.name.localeCompare(b.v.name) || a.i - b.i)
      .map(({ v }) => v);
  }
  const onlyRobotic = (voices) => { const ranked = rankVoices(voices); return ranked.length > 0 && ranked.every((v) => voiceTier(v) === 3); };

  const api = { shouldOfferHelp, speechTimeoutMs, guardUtterance, gateProblems, rankVoices, voiceTier, onlyRobotic };
  if (typeof module !== "undefined") module.exports = api;
  else window.UBTurn = api;
})();
