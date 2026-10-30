// Profile maths and storage (decision log 23): no browser, no network.
const assert = require("node:assert/strict");
const path = require("node:path");
const P = require(path.resolve(__dirname, "../app/static/ui/profile-core.js"));

const ans = (a, v, extra = {}) => ({ s: "x", t: "quant", a, v, p: false, d: "", ...extra });
const near = (x, y) => assert.ok(Math.abs(x - y) < 1e-9, `${x} != ${y}`);

// --- Area scores, overall rating, bands and start levels (pinned) ---
{
  const p = { ...P.empty(), answers: [ans("Probability", 0.85), ans("Probability", 0), ans("Probability", 0.3),
                                      ans("Statistics", 1), ans("Statistics", 0.6), ans("Combinatorics", 0.85)] };
  const scores = P.areaScores(p, "quant", ["Probability", "Statistics", "Combinatorics", "Expectations"]);
  near(scores[0].score, 115 / 3);                  // 100 x (0.85 + 0 + 0.3) / 3 = 38.33
  near(scores[1].score, 80);                       // 100 x (1 + 0.6) / 2
  assert.equal(scores[2].score, null);             // one answer: not assessed yet
  assert.equal(scores[3].score, null);             // none
  const o = P.overall(scores);
  near(o.rating, (115 / 3 + 80) / 2);              // 59.17
  assert.deepEqual([P.shown(o.rating), o.answers, o.areas], [59, 5, 2]);
  assert.deepEqual([P.band(o.rating), P.startLevel(o.rating)], ["Developing", "Medium"]);
  assert.deepEqual([P.band(scores[0].score), P.startLevel(scores[0].score)], ["Starting", "Easy"]);
  assert.deepEqual([P.band(80), P.startLevel(80)], ["Strong", "Hard"]);
  assert.equal(P.overall(P.areaScores(P.empty(), "quant", ["Probability"])), null);
}
// Band and level edges use the rating as shown (rounded).
for (const [r, b, l] of [[0, "Starting", "Easy"], [39.4, "Starting", "Easy"], [39.5, "Developing", "Medium"],
                         [59.4, "Developing", "Medium"], [59.5, "Interview-ready", "Medium"], [69.4, "Interview-ready", "Medium"],
                         [69.5, "Interview-ready", "Hard"], [79.4, "Interview-ready", "Hard"], [79.5, "Strong", "Hard"], [100, "Strong", "Hard"]]) {
  assert.deepEqual([P.band(r), P.startLevel(r)], [b, l], `rating ${r}`);
}
assert.equal(P.band(null), null);
assert.equal(P.startLevel(null), null);

// The last 10 answers only.
{
  const p = { ...P.empty(), answers: [ans("Probability", 0), ans("Probability", 0), ...Array(10).fill(0).map(() => ans("Probability", 1))] };
  const [s] = P.areaScores(p, "quant", ["Probability"]);
  assert.deepEqual([s.score, s.n, s.total], [100, 10, 12]);
}
// A placement answer assesses its area on its own; other tracks don't count.
{
  const p = { ...P.empty(), answers: [ans("DCF", 0.85, { t: "ib", p: true }), ans("Probability", 1)] };
  near(P.areaScores(p, "ib", ["DCF"])[0].score, 85);
  assert.equal(P.areaScores(p, "ib", ["Probability"])[0].score, null);
}

// --- Applying a report: once per session, with before and after ---
{
  const p = P.empty();
  const placement = { track: "quant", placement: true, topics: "Placement", label: "supports", rating_items: [
    { area: "Probability", value_float: 0.85 }, { area: "Statistics", value_float: 0 }, { area: "Combinatorics", value_float: 1 },
    { area: "Expectations", value_float: 0.3 }, { area: "Stochastic processes", value_float: 0.6 }] };
  const first = P.applyReport(p, placement, "s1", "2026-10-30", null);
  assert.equal(first.before, null);
  near(first.after, (85 + 0 + 100 + 30 + 60) / 5);   // 55: the starting rating
  assert.deepEqual(Object.keys(p.placement.quant.scores).length, 5);
  assert.equal(P.applyReport(p, placement, "s1", "2026-10-30", null), first, "the same session counts once");
  assert.equal(p.answers.length, 5);
  const next = P.applyReport(p, { track: "quant", rating_items: [{ area: "Probability", value_float: 1 }, { area: null, value_float: 1 }] },
                             "s2", "2026-10-31", null);
  assert.deepEqual(next.areas.map((a) => [a.area, P.shown(a.before), P.shown(a.after)]), [["Probability", 85, 93]]);
  near(next.after, (92.5 + 0 + 100 + 30 + 60) / 5);
  assert.equal(p.answers.length, 6, "an item with no area is not rated");
}

// --- Roles set the default track ---
assert.equal(P.defaultTrack(["other", "consulting", "quant"]), "quant");
assert.equal(P.defaultTrack(["other"]), null);
assert.equal(P.defaultTrack([]), null);

// --- Export and import round trip; bad files are refused ---
{
  const p = P.empty();
  p.onboarded = "done"; p.roles = ["ib", "other"]; p.other_text = "Actuarial"; p.default_track = "ib";
  P.applyReport(p, { track: "ib", placement: true, rating_items: [{ area: "DCF", value_float: 0.6 }] }, "s9", "2026-10-30", null);
  assert.deepEqual(P.importJson(P.exportJson(p)), p);
  assert.throws(() => P.importJson("{}"), /Not an Unbluffable progress file/);
  assert.throws(() => P.importJson("not json"));
  assert.throws(() => P.importJson(JSON.stringify({ ...p, answers: [{ s: "x", t: "ib", a: "DCF", v: 7 }] })), /answer/);
}

// --- Storage: works normally, and in memory only when storage is blocked ---
{
  const data = new Map();
  const local = { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) };
  const s = P.store(local);
  assert.equal(s.ok, true);
  const p = s.load();
  p.roles = ["quant"];
  assert.equal(s.save(p), true);
  assert.deepEqual(P.store(local).load().roles, ["quant"], "kept for the next visit");
  s.clear();
  assert.deepEqual(P.store(local).load(), P.empty());
  data.set(P.KEY, "{broken");
  assert.deepEqual(P.store(local).load(), P.empty(), "a broken saved profile starts fresh");

  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
  const b = P.store(blocked);
  assert.equal(b.ok, false);
  const q = b.load();
  q.roles = ["software"];
  assert.equal(b.save(q), false);
  assert.deepEqual(b.load().roles, ["software"], "this visit only");
  b.clear();
}
console.log("profile ok");
