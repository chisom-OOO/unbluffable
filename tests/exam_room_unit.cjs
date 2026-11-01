// Pure JavaScript unit checks for the Exam Room turn rules: no browser, microphone or network.
const assert = require("node:assert/strict");
const path = require("node:path");
const { shouldOfferHelp } = require(path.resolve(__dirname, "../app/static/ui/turn-logic.js"));

// A candidate silent since the question ended, at 60% of a 2:00 guide.
const silent = { elapsed: 72, guide: 120, offered: false, answered: false, heard: false,
  phase: "listening", speaking: false, liveText: "", typedText: "" };

assert.equal(shouldOfferHelp(silent), true);
assert.equal(shouldOfferHelp({ ...silent, elapsed: 71 }), false, "not before 60% of the guide");
assert.equal(shouldOfferHelp({ ...silent, liveText: "so twenty are fraud and" }), false, "never over a live transcript");
assert.equal(shouldOfferHelp({ ...silent, heard: true }), false, "never after speech this question");
assert.equal(shouldOfferHelp({ ...silent, typedText: "20 fraud" }), false, "never while typing");
assert.equal(shouldOfferHelp({ ...silent, answered: true }), false, "not after an answer");
assert.equal(shouldOfferHelp({ ...silent, offered: true }), false, "once per question");
assert.equal(shouldOfferHelp({ ...silent, speaking: true }), false, "not while the interviewer speaks");
assert.equal(shouldOfferHelp({ ...silent, phase: "checking" }), false, "only while listening");
assert.equal(shouldOfferHelp({ ...silent, liveText: "   " }), true, "whitespace is not speech");
console.log("exam room turn rules ok");

// Echo safety: a browser that never fires the utterance's end event still unmutes.
const { guardUtterance, speechTimeoutMs, gateProblems } = require(path.resolve(__dirname, "../app/static/ui/turn-logic.js"));
{
  const timers = [];
  const fake = { setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimer: (id) => { timers[id - 1].cleared = true; } };
  let muted = false; const done = [];
  const u = {};  // an utterance whose onend never fires
  guardUtterance(u, { text: "You said 11/13. Can you walk me through it?", ...fake,
    onStart: () => { muted = true; }, onDone: (why, started) => { if (started) muted = false; done.push(why); } });
  u.onstart();
  assert.equal(muted, true, "muted while speaking");
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, speechTimeoutMs("You said 11/13. Can you walk me through it?"));
  assert.equal(timers[0].ms, Math.round(9 / 2.5 * 1000) + 2000, "estimated length plus 2 s");
  timers[0].fn();  // the end event never came
  assert.equal(muted, false, "unmuted by the timeout");
  assert.deepEqual(done, ["timeout"]);
  u.onend(); u.onerror();
  assert.deepEqual(done, ["timeout"], "finishes once");
}
for (const how of ["onerror", "cancel"]) {
  let muted = false; const done = [];
  const u = {};
  const g = guardUtterance(u, { text: "Hello", setTimer: () => 1, clearTimer: () => {},
    onStart: () => { muted = true; }, onDone: (why, started) => { if (started) muted = false; done.push(why); } });
  u.onstart();
  if (how === "cancel") g.cancel(); else u.onerror();
  assert.equal(muted, false, `unmuted on ${how}`);
  assert.deepEqual(done, [how === "cancel" ? "cancel" : "error"]);
}
{
  // Never started: nothing was muted, and a later cancel reports started = false.
  const seen = [];
  const g = guardUtterance({}, { text: "x", setTimer: () => 1, clearTimer: () => {}, onDone: (why, started) => seen.push([why, started]) });
  g.cancel();
  assert.deepEqual(seen, [["cancel", false]]);
}

// The gate names the action. No microphone: "Connect a microphone" comes first.
{
  const base = { exempt: false, mic: "none", camera: "ok", connection: "ok", consent: true };
  assert.deepEqual(gateProblems(base).map((p) => p.action), ["Connect a microphone"]);
  assert.deepEqual(gateProblems({ ...base, mic: "listening" }).map((p) => p.action), ["Say something so we can hear you"]);
  assert.deepEqual(gateProblems({ ...base, mic: "blocked", camera: "blocked" }).map((p) => p.action),
    ["Allow the microphone in your browser", "Allow the camera in your browser"]);
  assert.deepEqual(gateProblems({ ...base, mic: "ok", connection: "failed", consent: false }).map((p) => p.action),
    ["Check your connection and reload", "Tick the agreement"]);
  assert.deepEqual(gateProblems({ ...base, exempt: true }), [], "typed practice skips the devices");
  assert.deepEqual(gateProblems({ ...base, mic: "ok" }), []);
  // An empty topic selection blocks Start, even in typed practice.
  assert.deepEqual(gateProblems({ ...base, mic: "ok", topics: 0 }).map((p) => p.action), ["Choose at least one topic"]);
  assert.deepEqual(gateProblems({ ...base, exempt: true, topics: 0 }).map((p) => p.key), ["topics"]);
  assert.deepEqual(gateProblems({ ...base, mic: "ok", topics: 2 }), []);
}
console.log("speech guard and gate ok");

// The interviewer's voice: most human first, British English first within a group, robotic last.
{
  const { rankVoices, onlyRobotic } = require(path.resolve(__dirname, "../app/static/ui/turn-logic.js"));
  const v = (name, lang) => ({ name, lang, voiceURI: name });
  const voices = [v("Microsoft David Desktop - English (United States)", "en-US"), v("Google US English", "en-US"),
                  v("Microsoft Sonia Online (Natural) - English (United Kingdom)", "en-GB"), v("Google UK English Female", "en-GB"),
                  v("Microsoft Aria Online (Natural) - English (United States)", "en-US"), v("Daniel", "en-GB"),
                  v("Thomas", "fr-FR"), v("Samantha (Enhanced)", "en-US"), v("eSpeak English", "en")];
  assert.deepEqual(rankVoices(voices).map((x) => x.name), [
    "Microsoft Sonia Online (Natural) - English (United Kingdom)",  // natural, en-GB
    "Microsoft Aria Online (Natural) - English (United States)", "Samantha (Enhanced)",  // natural, en-US
    "Google UK English Female", "Google US English",  // Google UK/US English
    "Daniel",  // everything else
    "Microsoft David Desktop - English (United States)", "eSpeak English",  // robotic last
  ]);
  assert.equal(onlyRobotic([v("Microsoft David Desktop", "en-US"), v("eSpeak English", "en")]), true, "suggest Edge or Chrome");
  assert.equal(onlyRobotic(voices), false);
  assert.equal(onlyRobotic([]), false);
}
console.log("voice ranking ok");

{
  const { groupModelCalls, modelFigures } = require(path.resolve(__dirname, "../app/static/ui/turn-logic.js"));
  const spark = (t, c) => ({ model: "muse-spark-1.3", job: "scoring_result", latency_s: t, estimated_cost_usd: c, mode: "live" });
  const groups = groupModelCalls([spark(1.0, 0.001), spark(3.0, 0.002), spark(2.0, 0.003),
    { model: "muse-spark-1.3", job: "endpoint_decision", latency_s: 0.4, estimated_cost_usd: null },
    { model: "muse-voice-transcribe", job: "transcription_model", latency_s: 40, audio_s: 40.2 },
    { model: "muse-voice-transcribe", job: "transcription_model", latency_s: 22, audio_s: 21.6 }]);
  assert.equal(groups.length, 3, "one row per model and job");
  const scoring = groups.find((g) => g.job === "scoring_result");
  assert.equal(scoring.count, 3);
  assert.equal(scoring.median, 2.0);
  assert.ok(Math.abs(scoring.cost - 0.006) < 1e-12);
  assert.deepEqual(modelFigures(scoring), ["3 calls", "median 2.0 s", "$0.0060"]);
  const asr = groups.find((g) => g.job === "transcription_model");
  assert.deepEqual(modelFigures(asr), ["live stream, 62 s of audio", "2 answers"], "audio seconds, never a latency");
  assert.deepEqual(modelFigures(groups.find((g) => g.job === "endpoint_decision")), ["1 call", "median 400 ms"]);
  assert.equal(groupModelCalls([spark(1, 0), spark(4, 0)])[0].median, 2.5, "even count: the middle two");
}
console.log("model panel grouping ok");

{
  const { titleFromName, statementHtml, inputLine, changedLines } = require(path.resolve(__dirname, "../app/static/ui/coding-ui.js"));
  assert.equal(titleFromName("minimise_largest_group_total"), "Minimise largest group total");
  assert.equal(statementHtml("Split values into exactly groups nonempty consecutive parts.", ["values", "groups"]),
    "<p>Split <code>values</code> into exactly <code>groups</code> non-empty consecutive parts.</p>");
  assert.equal(statementHtml("Return `k` if a<b", ["a"]), "<p>Return <code>k</code> if <code>a</code>&lt;b</p>", "escaped, backticks kept");
  assert.equal(statementHtml("Each groupsize counts.", ["groups"]), "<p>Each groupsize counts.</p>", "whole words only");
  assert.equal(inputLine(["values", "groups"], [[26, 29, 23], 3]), "values = [26, 29, 23], groups = 3");
  assert.equal(changedLines("def f(x):\n    pass\n", "def f(x):\n    a = 1\n    b = 2\n    return a\n"), 4);
}
console.log("coding workspace helpers ok");

{
  const T = require(path.resolve(__dirname, "../app/static/ui/turn-logic.js"));
  // Numbers said naturally; never a symbol.
  assert.equal(T.speakable("You said 2/3. Why?"), "You said two thirds. Why?");
  assert.equal(T.speakable("About 15% of 3.2m users pay $5."), "About 15 percent of 3 point 2 million users pay 5 dollars.");
  assert.equal(T.speakable("It costs $3.2bn"), "It costs 3 point 2 billion dollars");
  assert.equal(T.speakable("Is 7 - 3 = 4?"), "Is 7 minus 3 equals 4?");
  assert.equal(T.speakable("max_gain([-11, 16])"), "max gain minus 11, 16");
  assert.equal(T.speakable("17/250 and 1/2"), "17 over 250 and one half");
  assert.ok(!/[%$=+*_#/<>()[\]{}|`^]/.test(T.speakable("a*b + c/d = (e) [f] {g} <h> #i `j` |k| ^l 50% $3")), "no symbol is read");
  // Sentence by sentence, but never at a decimal point or "e.g.".
  assert.deepEqual(T.sentences("Good. Now 3.5 is close, e.g. near four. Next?"), ["Good.", "Now 3.5 is close, e.g. near four.", "Next?"]);
  assert.equal(T.SPEECH_RATE, 0.92, "slightly slower than normal");
  assert.equal(T.SENTENCE_PAUSE_MS, 400, "a short pause between sentences");
  // Openers: rotated, never before a question or right after an acknowledgement, never twice in a row.
  const st = {};
  const a = T.withOpener("That is the end of the interview.", "close", st);
  const b = T.withOpener("Go ahead and code it in Python.", "prompt", st);
  const c = T.withOpener("The first die is 4. Update your market.", "reveal", st);
  assert.ok(a !== "That is the end of the interview." && b === "Go ahead and code it in Python." && c !== "The first die is 4. Update your market.");
  assert.notEqual(a.split(" ")[0], c.split(" ")[0], "rotated");
  assert.equal(T.withOpener("What do you get for the posterior alpha?", "nudge", {}), "What do you get for the posterior alpha?");
  assert.equal(T.withOpener("Now the long statement continues here.", "prompt", { justAcknowledged: true }), "Now the long statement continues here.");
  assert.equal(T.withOpener("Is this a question about something?", "close", {}), "Is this a question about something?");
  assert.equal(T.naturalVoice({ name: "Microsoft Libby Online (Natural) - English (United Kingdom)" }), true);
  assert.equal(T.naturalVoice({ name: "Google UK English Female" }), false);
}
console.log("interviewer delivery ok");

{
  const { callsLine, listText, sameList } = require(path.resolve(__dirname, "../app/static/ui/coding-ui.js"));
  assert.equal(callsLine("RecentMax", { init: [2], ops: [["push", [5]], ["max", []], ["full", []]] }), "RecentMax(2); push(5); max(); full()");
  assert.equal(listText([null, "5", "True"]), "[None, 5, True]");
  assert.equal(sameList([null, "5"], [null, "5"]), true);
  assert.equal(sameList([null, "5"], ["0", "5"]), false, "a void call that returns something fails");
  assert.equal(sameList([null, "5"], [null]), false);
}
console.log("class specs in the page ok");
