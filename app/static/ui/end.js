// Report. /ui/end?session=ID renders that session's report from /api/interview/ID/report;
// without a session there is nothing to show. The four labels below are the only verdict
// vocabulary (spec/01).
document.addEventListener("DOMContentLoaded", () => {
  if (window.UB.desktopOnly()) return;  // decision log 26: laptop or desktop only
  const { escapeHtml, receiptHtml } = window.UB;
  const $ = (id) => document.getElementById(id);
  const sessionId = new URLSearchParams(location.search).get("session");

  function unavailable(text) {
    $("end-sub").textContent = text;
    $("result-tag").hidden = true;
    document.querySelectorAll(".section, .end-verdict, #stats").forEach((el) => { el.hidden = true; });
  }
  if (!sessionId) { unavailable("No report to show yet. A report appears here at the end of an interview."); return; }
  // With accounts, a guest's result is kept only after signing in (the page then reloads).
  const account = window.UBAccount;
  document.addEventListener("ub-account", (e) => { if (e.detail.user && keepPending) location.reload(); });
  let keepPending = false;
  Promise.all([fetch(`/api/interview/${encodeURIComponent(sessionId)}/report`)
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status))), account.whenReady])
    .then(([e]) => render(e))
    .catch(() => unavailable("This report is no longer available. Reports are kept in memory for the session only."));

  // Decision log 23: add this interview to the profile once, then show what changed.
  function showProgress(e) {
    const P = window.UBProfile, S = window.UB.profile();
    if (!P || !S || !e.track || !Array.isArray(e.rating_items)) return null;
    if (account.guest) {
      keepPending = true;
      $("progress-body").innerHTML = `<div class="keep-result"><p>Your profile, rating and history are kept only after you sign in.</p>`
        + `<button class="btn" type="button" id="keep-result">Sign in to keep this result</button></div>`;
      $("keep-result").addEventListener("click", () => account.openSignIn("Sign in to keep this result in your profile."));
      $("progress").hidden = false;
      return null;
    }
    const profile = S.load();
    const entry = P.applyReport(profile, e, sessionId, new Date().toISOString().slice(0, 10), null);
    if (!entry) return null;
    S.save(profile);
    const n = (x) => (x === null ? null : P.shown(x));
    const changes = entry.areas.map((a) => {
      const text = a.after === null ? "Not assessed yet" : a.before === null ? `${n(a.after)} (first estimate)` : `${n(a.before)} → ${n(a.after)}`;
      return `<li><span>${escapeHtml(a.area)}</span><span class="mono">${escapeHtml(text)}</span></li>`;
    }).join("");
    const head = entry.after === null ? "<p>No rating estimate yet: an area is assessed after two answers.</p>"
      : entry.placement ? `<p><strong>Starting rating estimate: <span class="mono">${n(entry.after)}</span></strong> · ${P.band(entry.after)}. Interviews on this track now start at ${P.startLevel(entry.after)}.</p>`
      : `<p>Overall estimate: <span class="mono">${entry.before === null ? n(entry.after) : `${n(entry.before)} → ${n(entry.after)}`}</span> · ${P.band(entry.after)}</p>`;
    let radar = "";
    if (entry.placement && profile.placement[e.track]) {
      const areas = Object.keys(profile.placement[e.track].scores);
      if (areas.length) {
        const chart = P.radar(areas, [{ key: "placement", name: "Placement", values: profile.placement[e.track].scores }],
          "Placement estimates by strength area, 0 to 100");
        radar = chart.svg ? `<figure class="radar-figure">${chart.svg}<ul class="legend"><li><span class="swatch swatch-placement" aria-hidden="true"></span>Placement</li></ul></figure>`
          : `<p class="muted">Answer a few more questions to see your shape.</p>`;
      }
    }
    $("progress-body").innerHTML = head + (changes ? `<ul class="change-list">${changes}</ul>` : "") + radar
      + (S.ok ? "" : `<p class="storage-note">Your browser is blocking storage, so this lasts only for this visit.</p>`)
      + `<p class="fine">Estimates from your scored answers. <a href="/ui/profile?track=${encodeURIComponent(e.track)}">See your profile</a></p>`
      + (account.enabled && account.firstTime ? `<a class="btn btn-small" href="/ui/welcome?first=1">Make it yours →</a>` : "");
    $("progress").hidden = false;
    // The header link shows the new rating.
    const link = document.querySelector("#profile-link .profile-rating");
    const o = P.overall(P.areaScores(profile, window.UB.headlineTrack(profile)));
    if (link && o) { link.hidden = false; link.textContent = String(P.shown(o.rating)); }
    return entry;
  }

  // Decision log 24: behavioural answers, model-judged and not exact. No label, stats or rating.
  function renderBehavioural(e) {
    $("end-eyebrow").textContent = "Behavioural report";
    $("end-title").textContent = "How you told it";
    $("end-sub").textContent = `${e.questions} question${e.questions === 1 ? "" : "s"}, each with one follow-up.`;
    $("result-tag").textContent = "Model-judged";
    $("conditions").hidden = !e.conditions;
    $("conditions").textContent = e.conditions || "";
    $("conditions").classList.toggle("warn", !!e.conditions && !/^Exam/.test(e.conditions));
    $("topics-line").hidden = false;
    $("topics-line").textContent = `Topics: ${e.topics}`;
    document.querySelectorAll(".section, .end-verdict, #stats").forEach((el) => { el.hidden = true; });
    const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    const quote = (q) => `<blockquote class="evidence"><p>“${escapeHtml(q)}”</p></blockquote>`;
    const check = (ok, text) => `<li class="${ok ? "ok" : "miss"}"><span aria-hidden="true">${ok ? "✓" : "–"}</span> ${text}</li>`;
    $("behavioural").innerHTML = e.behavioural.map((b) => {
      const s = b.specificity;
      const steps = b.steps.map((st) => `<li class="funnel-step${st.quote ? "" : " empty"}"><strong>${escapeHtml(st.step)}</strong>`
        + (st.quote ? quote(st.quote) : `<p class="fine">Not covered in your answer.</p>`) + `</li>`).join("");
      const quotes = (list, empty) => (list.length ? list.map(quote).join("") : `<p class="fine">${empty}</p>`);
      const details = s.details.length ? `<ul class="detail-list">${s.details.map((d) => `<li><span class="chip">${escapeHtml(d.detail)}</span> “${escapeHtml(d.quote)}”</li>`).join("")}</ul>` : "";
      const flags = b.consistency.length
        ? b.consistency.map((c) => `<div class="contradiction"><p class="qcard-when">First you said</p>${quote(c.first)}<p class="qcard-when">Then you said</p>${quote(c.probe)}</div>`).join("")
        : `<p class="fine">No contradiction found between your first answer and the follow-up.</p>`;
      return `<article class="qcard bq"><header><h3>${escapeHtml(b.q)}</h3><span class="tag">${b.type === "situational" ? "What would you do" : "Tell me about a time"}</span></header>`
        + `<p class="qcard-time">Time <span class="mono">${clock(b.seconds)}</span> · guide <span class="mono">${clock(b.guide)}</span></p>`
        + `<p class="bq-question">${escapeHtml(b.question)}</p>`
        + `<h4>${b.type === "situational" ? "Situation, action, reasoning, expected outcome" : "Situation, task, action, result"}</h4><ol class="funnel">${steps}</ol>`
        + `<h4>Relevance</h4><p class="qcard-when">Answers the question</p>${quotes(b.relevant, "No quote was marked as answering the question.")}`
        + (b.drift.length ? `<p class="qcard-when">Drifts away from it</p>${quotes(b.drift, "")}` : "")
        + `<h4>Specificity</h4><ul class="checklist">`
        + check(s.outcome_has_number, `${escapeHtml(s.outcome_step)} has a number${s.outcome_numbers.length ? `: <span class="mono">${s.outcome_numbers.map(escapeHtml).join(", ")}</span>` : ""}`)
        + check(s.action_owned, `Action says “I” at least as often as “we” (I ${s.action_i}, we ${s.action_we})`)
        + check(s.details.length > 0, `Concrete details quoted: ${s.details.length}`) + `</ul>${details}`
        + `<h4>Follow-up</h4><p class="fine">Asked about the ${escapeHtml(b.weakest.toLowerCase())}: “${escapeHtml(b.probe)}”</p>`
        + `<h4>Consistency</h4>${flags}`
        + `<div class="tip-line"><strong>One thing to practise:</strong> ${escapeHtml(b.tip)}</div>`
        + (b.dropped_quotes ? `<p class="fine">${b.dropped_quotes} quote${b.dropped_quotes === 1 ? "" : "s"} from the model didn't match your words and ${b.dropped_quotes === 1 ? "was" : "were"} left out.</p>` : "")
        + (b.model_error ? `<p class="fine">The model couldn't judge one answer, so some steps are empty.</p>` : "")
        + `</article>`;
    }).join("");
    $("behavioural-section").hidden = false;
    const again = document.querySelector(".end-actions .btn:not(.secondary)");
    if (again) {
      again.textContent = "More behavioural questions →";
      again.href = `/ui/interview?track=${encodeURIComponent(e.track)}`;
    }
  }

  // Decision log 26: the coding round. Tests are exact; the discussion is model-judged.
  function renderCoding(e) {
    const problems = e.problems && e.problems.length ? e.problems : [e.coding];
    const c = problems[0];
    $("end-eyebrow").textContent = "Coding interview report";
    $("end-title").textContent = problems.length > 1 ? `How your code did on ${problems.length} problems` : "How your code did";
    const reached = problems.map((p) => p.reached).join(" · ");
    $("result-tag").textContent = c.outcome === "correct" ? `Reached ${reached}` : c.tests ? "Part 1 not passed" : "Not submitted";
    $("end-sub").textContent = c.tests ? `Problem 1: ${c.tests.passed}/${c.tests.total} tests passed on your final Part 1 submit, compared exactly with the stored answers.`
      : "No code was submitted.";
    $("conditions").hidden = !e.conditions;
    $("conditions").textContent = e.conditions || "";
    $("conditions").classList.toggle("warn", !!e.conditions && !/^Exam/.test(e.conditions));
    $("topics-line").hidden = false;
    $("topics-line").textContent = e.topics;
    document.querySelectorAll(".section:not(#progress), .end-verdict, #stats").forEach((el) => { el.hidden = true; });
    const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    const quote = (q) => `<blockquote class="evidence"><p>“${escapeHtml(q)}”</p></blockquote>`;
    const partLine = (x) => {
      const tests = x.tests ? `${x.tests.passed}/${x.tests.total} tests` : "not submitted";
      const what = x.part === 2 ? `${escapeHtml(x.verdict_text)}${x.n ? ` at n = ${x.n.toLocaleString("en-GB")}` : ""}`
          + (x.max_ms != null ? ` · slowest ${x.max_ms.toLocaleString("en-GB")} ms (limit ${x.limit_ms.toLocaleString("en-GB")} ms)` : "")
        : x.outcome === "correct" ? (x.challenged ? "Correct after the challenge" : "Correct")
        : x.named ? `Named mistake: ${escapeHtml(x.named)}` : x.tests ? "Wrong" : "Not submitted";
      const help = x.hints.length ? ` · ${x.hints.length} hint${x.hints.length === 1 ? "" : "s"} (H ${escapeHtml(x.help_load)})` : "";
      return `<li><strong>${escapeHtml(x.label)}</strong>${x.part === 3 ? ` <span class="tag">only raises your rating · hints cost half</span>` : ""}: `
        + `${what} · ${tests}${help}${x.statement ? `<br><span class="fine">${escapeHtml(x.statement)}</span>` : ""}</li>`;
    };
    const card = (c) => {
      const outcome = c.outcome === "correct" ? (c.challenged ? "Correct after the challenge" : "Correct")
        : c.named ? `Named mistake: ${escapeHtml(c.named)}` : c.tests ? "Wrong" : "Not submitted";
      const p = c.provenance;
      return `<div class="qcard"><header><h3>${problems.length > 1 ? `Problem ${c.number}: ` : ""}${escapeHtml(outcome)}</h3>`
        + `<span class="tag">${c.tests ? `${c.tests.passed}/${c.tests.total} tests` : "no submit"}</span></header>`
        + `<p class="qcard-time">Reached <strong>${escapeHtml(c.reached || "Part 1")}</strong> · time <span class="mono">${clock(c.seconds)}</span>`
        + ` · ${c.submits.length} Part 1 submit${c.submits.length === 1 ? "" : "s"}${c.submits.length > 1 ? `: ${c.submits.map((s) => `${s.passed}/${s.total}`).join(", ")}` : ""}</p>`
        + `<p class="bq-question">${escapeHtml(c.statement)}</p>`
        + (c.parts && c.parts.length ? `<h4>How far it got</h4><ul class="see-list parts-list">${c.parts.map(partLine).join("")}</ul>` : "")
        + (c.receipt ? receiptHtml(c.receipt, { words: false }) : "")
        + `<div class="code-side"><div><h4>Your approach</h4>`
        + (c.plan_quotes.length ? c.plan_quotes.map(quote).join("") : `<p class="fine">No plan was quoted from your words.</p>`)
        + `<h4>Complexity claim</h4>${c.complexity_claim ? quote(c.complexity_claim) : `<p class="fine">None stated.</p>`}</div>`
        + `<div><h4>Your final code</h4><pre class="code-block mono">${escapeHtml(c.code || "")}</pre></div></div>`
        + `<h4>Questions about your code <span class="tag">model-chosen</span></h4>`
        + (c.questions.length ? `<ul class="see-list">${c.questions.map((q) => `<li>${escapeHtml(q)}</li>`).join("")}</ul>` : `<p class="fine">None asked.</p>`)
        + (c.follow_up ? `<h4>Follow-up <span class="tag">model-judged, not exact</span></h4><p class="fine">${escapeHtml(c.follow_up.question)}</p>`
          + quote(c.follow_up.answer) + (c.follow_up.verdict ? `<p class="check-line">Judged ${escapeHtml(c.follow_up.verdict)}${c.follow_up.quote ? `, from “${escapeHtml(c.follow_up.quote)}”` : ""}. Not scored.</p>` : "") : "")
        + `<details class="receipt provenance"><summary>Where this problem came from</summary><div class="receipt-body solo"><div><dl>`
        + `<div><dt>Solver</dt><dd>Written by ${escapeHtml(p.author)}; reproduced the verified answer on ${p.solver_reproduced}/${p.variants} variants through this signature.</dd></div>`
        + `<div><dt>Wrong methods</dt><dd>${p.wrong_methods.length ? `${p.wrong_methods.length} verified in code: ${escapeHtml(p.wrong_methods.join(", "))}.` : "None verified."}</dd></div>`
        + (p.solver_source ? `<div><dt>Solver code</dt><dd><pre class="code-block mono">${escapeHtml(p.solver_source)}</pre></dd></div>` : "")
        + `</dl></div></div></details></div>`;
    };
    // Quant development: the spoken opener's card first.
    const opener = (e.opener?.cards || []).map((o) => `<div class="qcard"><header><h3>Spoken opener: ${escapeHtml(o.outcome)}</h3>`
      + `<span class="tag">graded exactly</span></header>`
      + o.words.map((w) => `<h4>${escapeHtml(w.when)}</h4>${quote(w.text)}`).join("")
      + (o.said ? `<p class="check-line">You said <span class="mono">${escapeHtml(o.said)}</span>; exact <span class="mono">${escapeHtml(o.exact || "")}</span>.</p>` : "")
      + (o.receipt ? receiptHtml(o.receipt) : "") + `</div>`).join("");
    $("coding-report").innerHTML = opener + problems.map(card).join("");
    if (e.quant_dev) {
      $("coding-report-title").textContent = "Quant development: spoken opener + coding round";
      const again = document.querySelector(".end-actions .btn:not(.secondary)");
      if (again) { again.textContent = "Another quant development interview →"; again.href = "/ui/interview?track=quant_dev"; }
    }
    $("coding-section").hidden = false;
    const again = document.querySelector(".end-actions .btn:not(.secondary)");
    if (again && !e.quant_dev) { again.textContent = "Another coding interview →"; again.href = "/ui/interview?track=software"; }
  }

  // Decision log 28: market making, one card per game.
  function renderMarket(e) {
    $("end-eyebrow").textContent = "Market making report";
    $("end-title").textContent = "How your markets did";
    const scores = e.market.map((r) => r.scorecard.score_float);
    $("result-tag").textContent = e.market.length ? `Score ${Math.round(100 * scores.reduce((a, b) => a + b, 0) / scores.length)}/100` : "No market quoted";
    $("end-sub").textContent = "Scored in code from your quotes: fair value inside your market, width against the spread, and the direction of each update.";
    $("conditions").hidden = !e.conditions;
    $("conditions").textContent = e.conditions || "";
    $("conditions").classList.toggle("warn", !!e.conditions && !/^Exam/.test(e.conditions));
    $("topics-line").hidden = false;
    $("topics-line").textContent = e.topics;
    document.querySelectorAll(".section:not(#progress), .end-verdict, #stats").forEach((el) => { el.hidden = true; });
    const signed = (x) => (String(x).startsWith("-") ? `−${String(x).slice(1)}` : `+${x}`);
    const pct = (f) => `${Math.round(100 * Number(fractionValue(f)))}%`;
    $("market").innerHTML = e.market.map((r) => {
      const quotes = r.quotes.map((q, i) => `<tr><td>${i > 0 && r.quotes[i - 1].stage === q.stage ? "Tightened" : q.stage === 0 ? "Opening" : `After reveal ${q.stage}`}</td>`
        + `<td class="mono">${escapeHtml(q.bid)} at ${escapeHtml(q.ask)}</td><td class="mono">${escapeHtml(q.ev)}</td>`
        + `<td class="mono">${q.sd}</td><td>${q.contains ? "Inside" : "Outside"}${q.wide ? " · wide" : ""}</td></tr>`).join("");
      const updates = r.updates.map((u) => `<li>Reveal ${u.stage}: fair value moved <span class="mono">${signed(u.ev_change)}</span>,`
        + ` your mid <span class="mono">${signed(u.mid_change)}</span> · ${u.direction_right ? "right direction" : "wrong direction"}`
        + `${u.size_ratio == null ? "" : ` · ${u.size_ratio}× the change`}</li>`).join("");
      const trades = r.trades.map((t) => `<li>${t.side > 0 ? "Bought" : "Sold"} at <span class="mono">${escapeHtml(t.price)}</span>`
        + ` (fair <span class="mono">${escapeHtml(t.ev)}</span>${Number(fractionValue(t.edge_given)) > 0 ? `; gave away <span class="mono">${escapeHtml(t.edge_given)}</span>` : ""})</li>`).join("");
      return `<article class="qcard"><header><h3>Market ${r.n}</h3><span class="tag">${escapeHtml(r.difficulty)} · score ${Math.round(100 * r.scorecard.score_float)}/100</span></header>`
        + `<p class="bq-question">${escapeHtml(r.game)}</p>`
        + (r.reveals.length ? `<p class="fine">${r.reveals.map(escapeHtml).join(" ")}</p>` : "")
        + `<table class="market-quotes"><thead><tr><th scope="col">When</th><th scope="col">Your market</th><th scope="col">Fair value</th>`
        + `<th scope="col">SD</th><th scope="col">Check</th></tr></thead><tbody>${quotes}</tbody></table>`
        + `<p class="check-line">Fair value inside ${pct(r.scorecard.contains)} of your markets · not wider than 1.5 SD ${pct(r.scorecard.tight)}`
        + ` · updates in the right direction ${pct(r.scorecard.direction)}</p>`
        + (updates ? `<h4>Updates</h4><ul class="see-list">${updates}</ul>` : "")
        + `<h4>Trades</h4>${trades ? `<ul class="see-list">${trades}</ul>` : `<p class="fine">No trades.</p>`}`
        + `<dl class="market-book"><div><dt>Edge given away</dt><dd class="mono">${escapeHtml(r.edge_given)}</dd></div>`
        + `<div><dt>Position</dt><dd>${r.position === 0 ? "Flat" : `${r.position > 0 ? "Long" : "Short"} ${Math.abs(r.position)}`}</dd></div>`
        + `<div><dt>Settlement</dt><dd class="mono">${escapeHtml(r.settlement.payoff)}</dd></div>`
        + `<div><dt>P&amp;L</dt><dd class="mono">${signed(r.realised_pnl)} realised · ${signed(r.expected_pnl)} expected</dd></div></dl>`
        + (r.question ? `<h4>${escapeHtml(r.question.question)} <span class="tag">quoted, not scored</span></h4>`
          + `<blockquote class="evidence"><p>“${escapeHtml(r.question.answer)}”</p></blockquote>` : "")
        + `</article>`;
    }).join("") || `<p class="fine">No market was quoted.</p>`;
    $("market-section").hidden = false;
    const again = document.querySelector(".end-actions .btn:not(.secondary)");
    if (again) { again.textContent = "Make more markets →"; again.href = "/ui/interview?track=quant"; }
  }
  // "3/4" or "1" as a number (the scorecard's exact fractions).
  function fractionValue(f) { const [a, b] = String(f).split("/"); return Number(a) / (b ? Number(b) : 1); }

  function render(e) {
    if (e.coding) { showProgress(e); renderCoding(e); return; }
    if (e.market) { showProgress(e); renderMarket(e); return; }
    if (e.behavioural) { showProgress(e); renderBehavioural(e); return; }

    const ICON = {
      check: '<path d="M20 6 9 17l-5-5"/>',
      cross: '<path d="M18 6 6 18M6 6l12 12"/>',
      dash: '<path d="M5 12h14"/>',
      more: '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>',
    };
    const LABELS = {
      supports: { text: "Evidence supports understanding", cls: "verdict-supports", icon: "check" },
      misconception: { text: "Misconception detected", cls: "verdict-misconception", icon: "cross" },
      "not-shown": { text: "Understanding not shown", cls: "verdict-not-shown", icon: "dash" },
      "more-evidence": { text: "More evidence needed", cls: "verdict-more-evidence", icon: "more" },
    };
    const svg = (k) => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;

    if (e.drill) {
      // Drill mode (decision log 16): the check's result, not an interview label.
      const cleared = e.drill.result === "Cleared";
      $("end-title").textContent = "How the drill went";
      $("end-eyebrow").textContent = "Drill report";
      $("result-tag").textContent = "Drill complete";
      $("verdict").innerHTML =
        `<p class="verdict ${cleared ? "verdict-supports" : "verdict-misconception"}">${svg(cleared ? "check" : "cross")}<span>${escapeHtml(e.drill.result || "Not finished")}</span></p>` +
        `<p class="misconception-name">Drilled: ${escapeHtml(e.drill.misconception)}. ${escapeHtml(e.drill.note)}</p>`;
      $("end-sub").textContent = `${e.questions} question${e.questions === 1 ? "" : "s"}, including the check.`;
    } else {
      const L = LABELS[e.label];
      $("verdict").innerHTML =
        `<p class="verdict ${L.cls}">${svg(L.icon)}<span>${L.text}</span></p>` +
        (e.label === "misconception" && e.misconception
          ? `<p class="misconception-name">${escapeHtml(e.misconception)}: ${escapeHtml(e.misconception_note || "a known wrong method for this question.")}</p>` : "");
      $("end-sub").textContent = `${e.questions} question${e.questions === 1 ? "" : "s"}. Scored on where you end up, discounted by the help it took.`;
    }

    $("topics-line").hidden = !e.topics;
    $("topics-line").textContent = e.topics ? `Topics: ${e.topics}` : "";

    // Decision log 20: which mode was used.
    $("conditions").hidden = !e.conditions;
    $("conditions").textContent = e.conditions || "";
    $("conditions").classList.toggle("warn", !!e.conditions && !/^Exam/.test(e.conditions));

    if (sessionId && e.drills && e.drills.length) {
      $("drills").hidden = false;
      $("drill-list").innerHTML = e.drills.map((d) =>
        `<div class="drill-row"><p>${escapeHtml(d.misconception)}</p>` +
        `<a class="btn btn-small" href="/ui/interview?drill=${encodeURIComponent(sessionId)}&m=${d.index}">Drill this mistake</a></div>`).join("");
    }
    $("tip-section").hidden = !e.tip;
    $("estimate-section").hidden = !(e.estimate && e.estimate.length);

    // Each question's time against its guide, on its evidence card.
    function timeLine(q) {
      const t = (e.times || []).find((x) => x.q === q);
      if (!t) return "";
      const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
      const over = t.seconds > t.guide;
      return `<p class="qcard-time${over ? " over" : ""}">Time <span class="mono">${clock(t.seconds)}</span> · guide <span class="mono">${clock(t.guide)}</span>${over ? " · over" : ""}</p>`;
    }

    // Evidence you can check: one card per question. Each answer is quoted here and only here,
    // beside the exact value and the receipt (its words are not repeated inside the receipt).
    // The receipt's span (the number you committed to) is marked where it was said.
    const mark = (text, span) => {
      const safe = escapeHtml(text), needle = span ? escapeHtml(span) : "";
      const at = needle ? safe.lastIndexOf(needle) : -1;
      return at < 0 ? safe : `${safe.slice(0, at)}<mark>${needle}</mark>${safe.slice(at + needle.length)}`;
    };
    const quote = (text, receipt) =>
      `<blockquote class="evidence"><p>“${receipt && receipt.words === text ? mark(text, receipt.span) : escapeHtml(text)}”</p></blockquote>`;
    const numberLine = (said, exact) => said
      ? `<p class="check-line">You said <span class="mono">${escapeHtml(said)}</span>; the exact value is <span class="mono">${escapeHtml(exact)}</span>.</p>`
      : `<p class="check-line">No committed number; the exact value is <span class="mono">${escapeHtml(exact)}</span>.</p>`;
    $("evidence").innerHTML = (e.cards || []).map((c) =>
      `<article class="qcard" id="${escapeHtml(c.anchor)}" tabindex="-1"><header><h3>${escapeHtml(c.q)}</h3><span class="tag">${escapeHtml(c.outcome)}</span></header>` +
      timeLine(c.q) +
      c.words.map((w) => `<p class="qcard-when">${escapeHtml(w.when)}</p>${quote(w.text, c.receipt)}`).join("") +
      numberLine(c.said, c.exact) + receiptHtml(c.receipt, { words: false }) +
      (c.part2 ? `<div class="qcard-extra"><p class="qcard-when">Part 2 · not scored</p><p class="fine">${escapeHtml(c.part2.question)}</p>` +
        quote(c.part2.words, c.part2.receipt) + (c.part2.said ? numberLine(c.part2.said, c.part2.exact) : "") +
        receiptHtml(c.part2.receipt, { words: false }) + `</div>` : "") +
      (c.follow_up ? `<div class="qcard-extra"><p class="qcard-when">Follow-up · model-matched, not scored</p><p class="fine">${escapeHtml(c.follow_up.question)}</p>` +
        quote(c.follow_up.words, c.follow_up.receipt) + `<p class="check-line">${escapeHtml(c.follow_up.verdict)}</p>` +
        receiptHtml(c.follow_up.receipt, { words: false }) + `</div>` : "") +
      window.UB.provenanceHtml(c.provenance_rows) +
      `</article>`).join("");

    // Numbers only: each question's outcome and words are on its evidence card.
    // Numbers only, one row. Each question's time is on its evidence card.
    const entry = showProgress(e);
    const P = window.UBProfile;
    const stat = (dt, dd, small) => `<div class="stat"><dt>${dt}</dt><dd>${dd}${small ? `<small>${small}</small>` : ""}</dd></div>`;
    $("stats").innerHTML = (e.placement
      ? [
          stat("Questions", e.questions),
          stat("Areas covered", new Set((e.rating_items || []).map((i) => i.area).filter(Boolean)).size),
          stat("Starting rating", entry && entry.after !== null ? P.shown(entry.after) : "Not yet", "estimate"),
          stat("Start level", entry && entry.after !== null ? P.startLevel(entry.after) : "Easy", "next interviews"),
        ]
      : [
          stat("Questions", e.questions),
          stat("Challenges", e.challenges),
          stat("Nudges", e.nudges),
          stat("Hints used", e.hints.length),
          ...(e.level == null ? [] : [stat("Level reached", `${e.level} of ${e.levels}`, "Shown apart from the label")]),
        ]).join("");

    $("hints").innerHTML = e.hints.length
      ? e.hints.map((h) => `<li><span class="tag tag-hint">Hint</span><p class="says">${escapeHtml(h.text)}</p></li>`).join("")
      : `<li>No hints used.</li>`;

    $("tip").textContent = e.tip || "";

    // ---- Report (decision log 8): summary, doing well / improve, one tab per question ----
    // Breakdown items keep timings, help and the follow-up, without quoting your words again.
    const r = e.report;
    const item = (it) =>
      `<article class="report-item"><h3>${escapeHtml(it.title)}</h3>` +
      `<p>${escapeHtml(it.text)}</p>` +
      (it.question ? `<p class="fine">${escapeHtml(it.question)}</p>` : "") +
      (it.number
        ? `<p class="check-line">You said <span class="mono">${escapeHtml(it.number.said)}</span>; exact maths: <span class="mono">${escapeHtml(it.number.exact)}</span>.</p>`
        : it.verdict ? `<p class="check-line">${escapeHtml(it.verdict)}</p>` : "") +
      receiptHtml(it.receipt, { words: false }) + `</article>`;
    // Doing well / to improve: one line each, pointing at the question's evidence card.
    const pointer = (it) => `<li><span>${escapeHtml(it.title)}</span>` +
      (it.anchor ? ` <a href="#${escapeHtml(it.anchor)}">See ${escapeHtml(it.see)}</a>` : "") + `</li>`;
    $("overall").textContent = r.overall;
    $("well").innerHTML = r.well.length ? r.well.map(pointer).join("") : "<li>Nothing to single out yet.</li>";
    $("improve").innerHTML = r.improve.length ? r.improve.map(pointer).join("") : "<li>Nothing to single out yet.</li>";

    $("breakdown-tabs").innerHTML = r.breakdown.map((b, i) =>
      `<button type="button" role="tab" class="tab" id="tab-${i}" aria-controls="panel-${i}" aria-selected="${i === 0}" tabindex="${i === 0 ? 0 : -1}">${escapeHtml(b.tab)}</button>`).join("");
    $("breakdown-panels").innerHTML = r.breakdown.map((b, i) =>
      `<div role="tabpanel" class="tab-panel" id="panel-${i}" aria-labelledby="tab-${i}" tabindex="0"${i === 0 ? "" : " hidden"}>` +
      `<p class="tab-sub">${escapeHtml(b.sub)}</p>${b.items.map(item).join("")}</div>`).join("");

    const tabs = [...document.querySelectorAll('#breakdown-tabs [role="tab"]')];
    function select(i, focus) {
      tabs.forEach((t, j) => {
        t.setAttribute("aria-selected", String(j === i));
        t.tabIndex = j === i ? 0 : -1;
        $(`panel-${j}`).hidden = j !== i;
      });
      if (focus) tabs[i].focus();
    }
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(i, false));
      t.addEventListener("keydown", (ev) => {
        const last = tabs.length - 1;
        const to = { ArrowRight: i === last ? 0 : i + 1, ArrowLeft: i === 0 ? last : i - 1, Home: 0, End: last }[ev.key];
        if (to === undefined) return;
        ev.preventDefault();
        select(to, true);
      });
    });

    $("estimate").innerHTML = e.estimate.map((r) =>
      `<tr><td>${escapeHtml(r.label)}</td><td class="mono num-col">${escapeHtml(r.p)}</td></tr>`).join("");
  }
});
