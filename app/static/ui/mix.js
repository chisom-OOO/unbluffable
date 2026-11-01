// Setup chips (decision log 37): every chip combines with every other. A special format chosen
// alone still runs on its own; chosen with others, the interview runs as segments in the order
// of the track's "mix" (the server's defaults table, app/mixed.py), and the topics note says so.
(function () {
  // A chip's kind -> its segment format ("topic" chips are forge questions, or a coding round).
  const FORMAT = { market: "market", behavioural: "behavioural", conversational: "conversational", design: "design", cases: "cases" };

  // Add or remove one chip; nothing else changes.
  function toggle(chosen, id) {
    const list = [...chosen];
    return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
  }

  const byId = (chips, ids) => ids.map((id) => chips.find((c) => c.id === id)).filter(Boolean);

  // A mix: at least one special format, and more than one chip.
  function isMix(chips, ids) {
    const picked = byId(chips, ids);
    return picked.length > 1 && picked.some((c) => c.kind !== "topic");
  }

  // "Probability, Mental math, then a market-making game." or null when this isn't a mix.
  function note(chips, ids, mix) {
    if (!isMix(chips, ids)) return null;
    const picked = byId(chips, ids);
    const topics = picked.filter((c) => c.kind === "topic").map((c) => c.name);
    const formats = new Set(picked.filter((c) => c.kind !== "topic").map((c) => FORMAT[c.kind]));
    const parts = [];
    for (const step of mix || []) {
      if (step.format === "forge" && topics.length) parts.push(topics.join(", "));
      else if (step.format === "coding" && topics.length) parts.push(`a coding round on ${topics.join(", ")}`);
      else if (formats.has(step.format) && step.note) parts.push(step.note);
    }
    if (!parts.length) return null;
    const text = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")}, then ${parts[parts.length - 1]}`;
    return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
  }

  const api = { toggle, isMix, note };
  if (typeof module !== "undefined") module.exports = api;
  else window.UBMix = api;
})();
