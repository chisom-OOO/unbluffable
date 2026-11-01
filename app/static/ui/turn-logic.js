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

  // Echo safety (decision log 35 keeps it on tablets): the microphone is muted while the
  // interviewer speaks a line that mutes, unless the candidate is using headphones.
  const micShouldMute = ({ headphones, mutingLines }) => !headphones && mutingLines > 0;

  // The browser's English voices, most human first: natural/neural voices, then Google's
  // UK/US English, then the rest, with robotic desktop voices last; British English first
  // within each group, then American, then other English.
  const NATURAL = /natural|neural|online|premium|enhanced|siri/i;
  const ROBOTIC = /desktop|espeak|compact|eloquence|\bbad\b|robot/i;
  // Apple's novelty and Eloquence voices (Safari on iPad and Mac): robotic, so ranked last.
  const APPLE_NOVELTY = /^(Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Good News|Jester|Organ|Superstar|Trinoids|Whisper|Wobble|Zarvox|Fred|Junior|Ralph|Kathy|Eddy|Flo|Grandma|Grandpa|Reed|Rocko|Sandy|Shelley)(\s*\(|$)/;
  const APPLE_ROBOTIC_URI = /eloquence/i;
  function voiceTier(v) {
    if (NATURAL.test(v.name)) return 0;
    if (/^google (uk|us) english/i.test(v.name)) return 1;
    if (ROBOTIC.test(v.name) || APPLE_NOVELTY.test(v.name || "") || APPLE_ROBOTIC_URI.test(v.voiceURI || "")) return 3;
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

  // Decision log 27: "Which model did what" groups calls by model and job: the count, the
  // median time and the total cost. A live transcription stream reports its audio seconds
  // (summed), never a latency.
  function groupModelCalls(calls) {
    const groups = new Map();
    for (const c of calls) {
      if (!c || !c.model) continue;
      const key = `${c.model}|${c.job}`;
      const g = groups.get(key) || { model: c.model, job: c.job, count: 0, times: [], cost: null, audio: null, recorded: false };
      g.count += 1;
      if (c.audio_s != null) g.audio = (g.audio || 0) + c.audio_s;
      else if (c.latency_s != null) g.times.push(c.latency_s);
      if (c.estimated_cost_usd != null) g.cost = (g.cost || 0) + c.estimated_cost_usd;
      g.recorded = g.recorded || c.mode === "replay";
      groups.set(key, g);
    }
    return [...groups.values()].map((g) => {
      const t = [...g.times].sort((a, b) => a - b), mid = Math.floor(t.length / 2);
      const median = t.length ? (t.length % 2 ? t[mid] : (t[mid - 1] + t[mid]) / 2) : null;
      return { model: g.model, job: g.job, count: g.count, median, cost: g.cost, audio: g.audio, recorded: g.recorded };
    });
  }
  function fmtSeconds(s) {
    return s == null ? null : s >= 1 ? `${s.toFixed(1)} s` : s < 0.001 ? "under 1 ms" : `${Math.round(s * 1000)} ms`;
  }
  // The figures shown for a group: "3 calls · median 1.2 s · $0.0031" or "live stream, 62 s of audio".
  function modelFigures(g) {
    if (g.audio != null) return [`live stream, ${Math.round(g.audio)} s of audio`, g.count > 1 ? `${g.count} answers` : null].filter(Boolean);
    return [`${g.count} call${g.count === 1 ? "" : "s"}`, g.median == null ? null : `median ${fmtSeconds(g.median)}`,
            g.cost == null ? null : `$${g.cost.toFixed(4)}`].filter(Boolean);
  }

  // ---------- A more human delivery (browser speech only) ----------
  const SPEECH_RATE = 0.97, SENTENCE_PAUSE_MS = 250;
  const ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                + "sixteen seventeen eighteen nineteen").split(" ");
  const TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split(" ");
  const ORD = { 2: "half", 3: "third", 4: "quarter", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth",
                11: "eleventh", 12: "twelfth", 20: "twentieth", 30: "thirtieth", 40: "fortieth", 50: "fiftieth", 60: "sixtieth",
                70: "seventieth", 80: "eightieth", 90: "ninetieth", 100: "hundredth" };
  function words(n) {
    if (n < 20) return ONES[n];
    if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? "-" + ONES[n % 10] : "");
    if (n < 1000) return ONES[Math.floor(n / 100)] + " hundred" + (n % 100 ? " and " + words(n % 100) : "");
    return null;
  }
  function ordinal(n) {
    if (ORD[n]) return ORD[n];
    if (n > 12 && n < 20) return words(n) + "th";
    if (n > 20 && n < 100) return TENS[Math.floor(n / 10)] + "-" + (n % 10 === 2 ? "second" : n % 10 === 1 ? "first" : ORD[n % 10]);
    return null;
  }
  // "2/3" -> "two thirds"; "1/2" -> "one half"; out of range: "17 over 250".
  function fractionWords(a, b) {
    const num = words(a), den = ordinal(b);
    if (num === null || den === null || b < 2) return `${a} over ${b}`;
    return `${num} ${a === 1 ? den : den === "half" ? "halves" : den + "s"}`;
  }
  const decimal = (whole, digits) => `${whole} point ${digits.split("").join(" ")}`;
  const SCALE = { k: "thousand", m: "million", mn: "million", bn: "billion", b: "billion", thousand: "thousand", million: "million", billion: "billion" };
  const CURRENCY = { "$": "dollars", "£": "pounds", "€": "euros" };

  // What the voice says: numbers as words a person would say, never a symbol.
  function speakable(text) {
    let s = ` ${String(text || "")} `;
    s = s.replace(/([$£€])\s?(\d+(?:\.\d+)?)\s?(bn|mn|[kmb]|thousand|million|billion)?\b/gi,
                  (_, c, n, scale) => ` ${n}${scale ? " " + SCALE[scale.toLowerCase()] : ""} ${CURRENCY[c]} `);
    s = s.replace(/(\d+(?:\.\d+)?)\s?(bn|mn|[kmb])\b/gi, (_, n, scale) => `${n} ${SCALE[scale.toLowerCase()]}`);
    s = s.replace(/(\d+(?:\.\d+)?)\s?%/g, "$1 percent");
    s = s.replace(/(?<![\d/.])(\d{1,3})\s?\/\s?(\d{1,3})(?![\d/]|\.\d)/g, (_, a, b) => fractionWords(Number(a), Number(b)));
    s = s.replace(/(\d+)\.(\d+)/g, (_, w, d) => decimal(w, d));
    s = s.replace(/(\d),(?=\d{3}\b)/g, "$1");  // 100,000 -> 100000
    s = s.replace(/(\d)\s*[×x*]\s*(\d)/g, "$1 times $2");
    s = s.replace(/[()[\]{}]/g, " ");
    s = s.replace(/\s[−-]\s(?=\d)/g, " minus ").replace(/(^|\s)[−-](?=\d)/g, "$1minus ").replace(/\s[−–—-]\s/g, ", ");
    const SYMBOLS = [[/≤|<=/g, " at most "], [/≥|>=/g, " at least "], [/≈|~/g, " about "], [/=/g, " equals "], [/\+/g, " plus "],
                     [/</g, " less than "], [/>/g, " more than "], [/&/g, " and "], [/→|->/g, " to "], [/·/g, ", "],
                     [/\//g, " per "], [/[()[\]{}*_#`|^\\]/g, " "]];
    for (const [re, said] of SYMBOLS) s = s.replace(re, said);
    return s.replace(/\s+([,.?!;:])/g, "$1").replace(/\s+/g, " ").trim();
  }

  // Sentence by sentence; never at a decimal point or after "e.g.", "i.e.", "vs.", "Mr.", "Dr.".
  function sentences(text) {
    const out = [];
    let start = 0;
    const re = /[.!?]+["”')]?\s+(?=["“(]?[A-Z0-9])/g;
    let m;
    while ((m = re.exec(text))) {
      const before = text.slice(start, m.index + 1);
      if (/\b(?:e\.g|i\.e|vs|Mr|Mrs|Ms|Dr|etc)\.$/i.test(before.trim())) continue;
      out.push(text.slice(start, m.index + m[0].trimEnd().length).trim());
      start = m.index + m[0].length;
    }
    const rest = text.slice(start).trim();
    if (rest) out.push(rest);
    return out.length ? out : [String(text || "")];
  }

  // A short natural opener before some statements ("Okay.", "Right, so...", "Got it."), rotated,
  // never before or inside a question, never twice in a row, never after an acknowledgement.
  const OPENERS = ["Okay.", "Right, so", "Got it.", "Alright."];
  const NO_OPENER = new Set(["question", "follow_up", "probe", "challenge", "nudge", "hint"]);
  function withOpener(text, kind, state) {
    const t = String(text || "").trim();
    const eligible = !NO_OPENER.has(kind) && !t.endsWith("?") && !/^(?:okay|ok|right|got it|alright|sure|thanks|thank you|good|great|sorry|just)\b/i.test(t)
      && !state.justAcknowledged && !state.lastHadOpener && t.split(/\s+/).length > 3;
    state.lastHadOpener = false;
    if (!eligible) return t;
    const opener = OPENERS[(state.n = (state.n || 0) + 1) % OPENERS.length];
    state.lastHadOpener = true;
    return opener.endsWith(",") || opener === "Right, so" ? `${opener} ${t[0].toLowerCase()}${t.slice(1)}` : `${opener} ${t}`;
  }

  // The tip for a voice that isn't one of the natural (Edge "Online (Natural)") voices.
  const naturalVoice = (v) => !!v && /natural|online|neural|premium|enhanced|siri/i.test(v.name || "");

  const api = { micShouldMute, shouldOfferHelp, speechTimeoutMs, guardUtterance, gateProblems, rankVoices, voiceTier, onlyRobotic,
                groupModelCalls, modelFigures, speakable, sentences, withOpener, naturalVoice, fractionWords,
                SPEECH_RATE, SENTENCE_PAUSE_MS };
  if (typeof module !== "undefined") module.exports = api;
  else window.UBTurn = api;
})();
