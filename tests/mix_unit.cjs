// Setup chips (decision log 37): chips combine freely, and the topics note says what runs, in order.
const assert = require("node:assert/strict");
const path = require("node:path");
const X = require(path.resolve(__dirname, "../app/static/ui/mix.js"));

const quantChips = [
  { id: "Probability", name: "Probability", kind: "topic" },
  { id: "Mental math", name: "Mental math", kind: "topic" },
  { id: "Market making", name: "Market making", kind: "market" },
];
const quantMix = [{ format: "forge", note: null }, { format: "market", note: "a market-making game" }];
const ibChips = [
  { id: "DCF", name: "DCF", kind: "topic" },
  { id: "Behavioural", name: "Behavioural", kind: "behavioural" },
  { id: "Conceptual questions", name: "Conceptual questions", kind: "conversational" },
];
const ibMix = [{ format: "behavioural", note: "one behavioural question with its follow-up" }, { format: "forge", note: null },
               { format: "conversational", note: "one conceptual question" }, { format: "cases", note: "a case" }];

// Toggling: a special chip no longer swaps out the others, and the others don't swap it out.
assert.deepEqual(X.toggle(["Probability"], "Market making"), ["Probability", "Market making"]);
assert.deepEqual(X.toggle(["Market making"], "Probability"), ["Market making", "Probability"]);
assert.deepEqual(X.toggle(["Market making", "Probability"], "Market making"), ["Probability"]);
assert.deepEqual(X.toggle([], "Behavioural"), ["Behavioural"]);

// The note lists what runs, in the defaults table's order (the server's "mix" for the track).
assert.equal(X.note(quantChips, ["Market making", "Probability", "Mental math"], quantMix),
             "Probability, Mental math, then a market-making game.");
assert.equal(X.note(ibChips, ["DCF", "Behavioural"], ibMix), "One behavioural question with its follow-up, then DCF.");
assert.equal(X.note(ibChips, ["Conceptual questions", "DCF", "Behavioural"], ibMix),
             "One behavioural question with its follow-up, DCF, then one conceptual question.");
// Specials only, mixed with each other.
assert.equal(X.note(ibChips, ["Conceptual questions", "Behavioural"], ibMix),
             "One behavioural question with its follow-up, then one conceptual question.");
// Not a mix: a single special chip alone, or regular topics only, keep the existing notes (null).
assert.equal(X.note(quantChips, ["Market making"], quantMix), null);
assert.equal(X.note(quantChips, ["Probability", "Mental math"], quantMix), null);
assert.equal(X.note(quantChips, [], quantMix), null);
// A software mix: the coding round's topics, then one design question.
const swChips = [{ id: "Graphs", name: "Graphs", kind: "topic" }, { id: "Design concepts", name: "Design concepts", kind: "design" }];
const swMix = [{ format: "coding", note: null }, { format: "design", note: "one design-concepts question" }];
assert.equal(X.note(swChips, ["Design concepts", "Graphs"], swMix), "A coding round on Graphs, then one design-concepts question.");
assert.equal(X.isMix(quantChips, ["Market making", "Probability"]), true);
assert.equal(X.isMix(quantChips, ["Market making"]), false);
assert.equal(X.isMix(quantChips, ["Probability", "Mental math"]), false);
console.log("mix_unit: ok");
