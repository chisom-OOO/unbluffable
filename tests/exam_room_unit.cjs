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
