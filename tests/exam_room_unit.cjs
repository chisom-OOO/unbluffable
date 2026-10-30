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
