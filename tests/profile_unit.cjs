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
// --- Radar: only areas assessed in at least one series; fewer than 3, no shape ---
{
  const areas = ["Probability", "Expectations", "Combinatorics", "Statistics", "Stochastic processes"];
  const r = P.radar(areas, [
    { key: "placement", name: "Placement", values: { Probability: 60, Expectations: 80, Statistics: 40 } },
    { key: "now", name: "Now", values: { Probability: 60, Expectations: 85, Statistics: null, "Stochastic processes": 50 } },
  ], "t");
  assert.deepEqual(r.drawn, ["Probability", "Expectations", "Statistics", "Stochastic processes"]);
  assert.deepEqual(r.missing, ["Combinatorics"]);
  assert.equal((r.svg.match(/<line class="axis"/g) || []).length, 4, "no axis for an area assessed nowhere");
  assert.ok(!/Combinatorics/.test(r.svg));
  assert.ok(r.svg.indexOf("series-now") < r.svg.indexOf("series-placement"), "placement drawn on top of now");
  assert.equal((r.svg.match(/class="dot dot-now"/g) || []).length, 3);
  assert.equal((r.svg.match(/class="dot dot-placement"/g) || []).length, 3);
  // Ring labels sit between the first two axes, never on one.
  const labels = [...r.svg.matchAll(/class="ring-label" x="([-\d.]+)" y="([-\d.]+)"/g)].map((m) => [+m[1], +m[2]]);
  assert.equal(labels.length, 4);
  assert.ok(labels.every(([x]) => Math.abs(x) > 1), "off the top axis");
  const few = P.radar(areas, [{ key: "now", name: "Now", values: { Probability: 50, Statistics: 70 } }], "t");
  assert.deepEqual([few.svg, few.drawn.length, few.missing.length], ["", 2, 3]);
}
// --- Display name and photo: validated, exported, imported and cleared with the rest ---
{
  const photo = "data:image/jpeg;base64," + "A".repeat(4000);
  const p = { ...P.empty(), name: "  Ada Lovelace  ", photo };
  const back = P.importJson(P.exportJson(P.normalise(p)));
  assert.deepEqual([back.name, back.photo], ["Ada Lovelace", photo], "round trip keeps both");
  assert.equal(P.normalise({ ...p, name: "x".repeat(200) }).name.length, P.NAME_MAX);
  for (const bad of ["data:image/png;base64,AAAA", "javascript:alert(1)", "data:image/jpeg;base64,<svg>",
                     "data:image/jpeg;base64," + "A".repeat(140000), 42]) {
    assert.equal(P.normalise({ ...p, photo: bad }).photo, null, `refuses ${String(bad).slice(0, 30)}`);
  }
  assert.ok(P.validPhoto("data:image/jpeg;base64," + "A".repeat(136000)), "just under 100 KB");
  assert.deepEqual([P.initials("Ada Lovelace"), P.initials("cher"), P.initials(" "), P.initials("Émile Zola Jr")], ["AL", "C", "", "ÉZ"]);
  // Clear my data removes them.
  const data = new Map();
  const local = { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) };
  const s = P.store(local);
  s.save(P.normalise(p));
  s.clear();
  assert.deepEqual([s.load().name, s.load().photo], ["", null]);
}
console.log("profile ok");

// --- Decision log 29: a bonus part only ever raises its area ---
{
  const p = P.empty();
  const item = (v, bonus) => ({ area: "Dynamic programming", value_float: v, ...(bonus ? { bonus: true } : {}) });
  P.applyReport(p, { track: "software", rating_items: [item(0.85), item(0.85)] }, "a", "2026-10-31", null);
  const before = P.areaScores(p, "software", ["Dynamic programming"])[0].score;
  P.applyReport(p, { track: "software", rating_items: [item(0.5, true)] }, "b", "2026-10-31", null);
  assert.equal(P.areaScores(p, "software", ["Dynamic programming"])[0].score, before, "a lower bonus is left out");
  P.applyReport(p, { track: "software", rating_items: [item(1, true)] }, "c", "2026-10-31", null);
  assert.ok(P.areaScores(p, "software", ["Dynamic programming"])[0].score > before, "a higher bonus counts");
  const fresh = P.empty();
  P.applyReport(fresh, { track: "software", rating_items: [item(1, true)] }, "d", "2026-10-31", null);
  assert.equal(fresh.answers.length, 1, "an unassessed area keeps it (it cannot lower anything)");
}
console.log("bonus parts ok");

// --- Setup redesign: the radar follows the role's Core chips, matching answers by topic ---
{
  const p = P.empty();
  P.applyReport(p, { track: "quant", placement: true, rating_items: [
    { area: "Probability", topic: "Discrete probability", value_float: 0.8 },
    { area: "Expectations", topic: "Expectations", value_float: 0.6 }] }, "pl", "2026-11-01", null);
  assert.equal(p.answers[0].tp, "Discrete probability", "an answer keeps its topic");
  const scores = P.areaScores(p, "quant", ["Probability", "Expected value"],
    { Probability: ["Discrete probability", "Continuous probability"], "Expected value": ["Expectations"] });
  assert.deepEqual(scores.map((s) => [s.area, Math.round(s.score)]), [["Probability", 80], ["Expected value", 60]]);
  assert.equal(P.normalise(JSON.parse(JSON.stringify(p))).answers[1].tp, "Expectations", "kept through export and import");
}
console.log("role radar ok");
