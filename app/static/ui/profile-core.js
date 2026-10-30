// Candidate profile (decision log 23): saved progress in this browser only, no accounts.
// Pure functions, shared by the pages and the Node unit test. The rating is built from the
// engine's own outcomes (each report's rating_items), never from a model's opinion.
(() => {
  const KEY = "ub-profile-v1";
  const WINDOW = 10;  // an area's score uses its last 10 scored answers
  const ROLES = [
    { id: "quant", name: "Quant trading/research", track: "quant" },
    { id: "ib", name: "Investment banking", track: "ib" },
    { id: "consulting", name: "Consulting", track: "consulting" },
    { id: "software", name: "Software engineering", track: "software" },
    { id: "other", name: "Other", track: null },
  ];

  const empty = () => ({ version: 1, onboarded: null, roles: [], other_text: "", default_track: null,
                         answers: [], history: [], placement: {} });

  // Accepts only a well-formed version 1 profile; anything else throws.
  function normalise(p) {
    if (!p || typeof p !== "object" || p.version !== 1) throw new Error("Not an Unbluffable progress file.");
    const str = (x) => typeof x === "string";
    const answers = Array.isArray(p.answers) ? p.answers : [];
    if (!answers.every((a) => a && str(a.s) && str(a.t) && str(a.a) && typeof a.v === "number" && a.v >= 0 && a.v <= 1)) {
      throw new Error("The progress file has an answer it can't read.");
    }
    const history = Array.isArray(p.history) ? p.history.filter((h) => h && str(h.session) && str(h.track)) : [];
    return {
      version: 1,
      onboarded: ["done", "skipped"].includes(p.onboarded) ? p.onboarded : null,
      roles: Array.isArray(p.roles) ? p.roles.filter((r) => ROLES.some((x) => x.id === r)) : [],
      other_text: str(p.other_text) ? p.other_text.slice(0, 200) : "",
      default_track: str(p.default_track) ? p.default_track : null,
      answers: answers.map((a) => ({ s: a.s, t: a.t, a: a.a, v: a.v, p: !!a.p, d: str(a.d) ? a.d : "" })),
      history,
      placement: p.placement && typeof p.placement === "object" ? p.placement : {},
    };
  }

  // Storage wrapper: every read and write in try/catch. Blocked storage keeps the profile in
  // memory for this visit (`ok` is false so the page can say so).
  function store(storage) {
    let ok = true, memory = null;
    try { storage.setItem("ub-probe", "1"); storage.removeItem("ub-probe"); } catch { ok = false; }
    return {
      get ok() { return ok; },
      load() {
        if (!ok) return memory || (memory = empty());
        try { const raw = storage.getItem(KEY); return raw ? normalise(JSON.parse(raw)) : empty(); } catch { return empty(); }
      },
      save(p) {
        memory = p;
        if (!ok) return false;
        try { storage.setItem(KEY, JSON.stringify(p)); return true; } catch { ok = false; return false; }
      },
      clear() { memory = null; try { storage.removeItem(KEY); } catch { /* blocked */ } },
    };
  }

  const exportJson = (p) => JSON.stringify(p, null, 2);
  const importJson = (text) => normalise(JSON.parse(text));

  // Area scores for a track: 100 x the mean of the last 10 answers. An area is assessed
  // once it has 2+ answers, or its placement answer (placement asks one per area).
  function areaScores(p, track, areas) {
    const mine = p.answers.filter((a) => a.t === track);
    const names = areas && areas.length ? areas : [...new Set(mine.map((a) => a.a))];
    return names.map((area) => {
      const all = mine.filter((a) => a.a === area);
      const recent = all.slice(-WINDOW);
      const assessed = all.length >= 2 || all.some((a) => a.p);
      const score = assessed ? (100 * recent.reduce((s, a) => s + a.v, 0)) / recent.length : null;
      return { area, score, n: recent.length, total: all.length };
    });
  }

  // Overall rating: the mean of assessed area scores, with how many answers and areas it rests on.
  function overall(scores) {
    const assessed = scores.filter((s) => s.score !== null);
    if (!assessed.length) return null;
    return { rating: assessed.reduce((s, x) => s + x.score, 0) / assessed.length,
             answers: assessed.reduce((s, x) => s + x.n, 0), areas: assessed.length };
  }

  const shown = (x) => (x === null || x === undefined ? null : Math.round(x));
  function band(rating) {
    const r = shown(rating);
    if (r === null) return null;
    return r < 40 ? "Starting" : r < 60 ? "Developing" : r < 80 ? "Interview-ready" : "Strong";
  }
  function startLevel(rating) {
    const r = shown(rating);
    if (r === null) return null;
    return r < 40 ? "Easy" : r < 70 ? "Medium" : "Hard";
  }

  function defaultTrack(roles) {
    const first = ROLES.find((r) => roles.includes(r.id) && r.track);
    return first ? first.track : null;
  }

  // Adds a finished interview's report to the profile once (by session id) and returns its
  // history entry: overall and per-area estimates before and after.
  function applyReport(p, report, session, date, areas) {
    const known = p.history.find((h) => h.session === session);
    if (known || !report || !report.track || !Array.isArray(report.rating_items)) return known || null;
    const track = report.track;
    const before = areaScores(p, track, areas);
    const items = report.rating_items.filter((i) => i.area);
    for (const i of items) p.answers.push({ s: session, t: track, a: i.area, v: Number(i.value_float), p: !!report.placement, d: date });
    const after = areaScores(p, track, areas);
    const touched = [...new Set(items.map((i) => i.area))];
    const entry = {
      session, date, track, topics: report.topics || null, label: report.label || null, placement: !!report.placement,
      before: overall(before)?.rating ?? null, after: overall(after)?.rating ?? null,
      areas: touched.map((area) => ({ area, before: before.find((s) => s.area === area)?.score ?? null,
                                      after: after.find((s) => s.area === area)?.score ?? null })),
    };
    p.history.push(entry);
    if (report.placement) {
      p.placement[track] = { date, scores: Object.fromEntries(after.filter((s) => s.score !== null).map((s) => [s.area, s.score])) };
    }
    return entry;
  }

  // Radar chart as an SVG string: 0-100 rings, one axis per area, and one filled shape per
  // series ({ key: "now" | "placement", name, values: { area: score | null } }). Unassessed
  // areas are left out of a shape rather than drawn as zero; the table carries every number.
  const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const shortName = (area) => area.split(/, | & /)[0];
  function radarSvg(areas, series, title) {
    const n = areas.length, R = 100;
    const at = (i, r) => {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
      return [+(r * Math.cos(a)).toFixed(2), +(r * Math.sin(a)).toFixed(2)];
    };
    const ring = (v) => (n >= 3 ? `<polygon class="ring" points="${areas.map((_, i) => at(i, (R * v) / 100).join(",")).join(" ")}"/>`
      : `<circle class="ring" r="${(R * v) / 100}"/>`);
    const parts = [`<title>${esc(title)}</title>`];
    [25, 50, 75, 100].forEach((v) => parts.push(ring(v)));
    areas.forEach((area, i) => {
      const [x, y] = at(i, R), [lx, ly] = at(i, R + 14);
      const anchor = Math.abs(lx) < 4 ? "middle" : lx > 0 ? "start" : "end";
      parts.push(`<line class="axis" x1="0" y1="0" x2="${x}" y2="${y}"/>`);
      parts.push(`<text class="axis-label" x="${lx}" y="${(ly + (ly > 4 ? 9 : ly < -4 ? -2 : 4)).toFixed(2)}" text-anchor="${anchor}">${esc(shortName(area))}</text>`);
    });
    [25, 50, 75, 100].forEach((v) => parts.push(`<text class="ring-label" x="3" y="${-(R * v) / 100 + 9}">${v}</text>`));
    for (const s of series) {
      const pts = areas.map((area, i) => [area, s.values[area]]).map(([area, v], i) => (v === null || v === undefined ? null : { area, v, xy: at(i, (R * v) / 100) }))
        .filter(Boolean);
      if (pts.length >= 3) parts.push(`<polygon class="series series-${s.key}" points="${pts.map((p) => p.xy.join(",")).join(" ")}"/>`);
      else if (pts.length === 2) parts.push(`<polyline class="series series-${s.key}" fill="none" points="${pts.map((p) => p.xy.join(",")).join(" ")}"/>`);
      pts.forEach((p) => parts.push(`<circle class="dot dot-${s.key}" cx="${p.xy[0]}" cy="${p.xy[1]}" r="4"><title>${esc(p.area)}: ${esc(s.name)} ${Math.round(p.v)}</title></circle>`));
    }
    return `<svg class="radar" viewBox="-180 -135 360 270" role="img" aria-label="${esc(title)}">${parts.join("")}</svg>`;
  }

  const api = { KEY, WINDOW, ROLES, empty, normalise, store, exportJson, importJson, areaScores, overall,
                shown, band, startLevel, defaultTrack, applyReport, radarSvg, shortName };
  if (typeof module !== "undefined") module.exports = api;
  else window.UBProfile = api;
})();
