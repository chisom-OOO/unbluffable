// Landing: track cards from the real template packs; the puzzle; if the visitor hasn't
// started within 3 s, play the labelled sample (to be swapped for a real recorded run).
document.addEventListener("DOMContentLoaded", () => {
  const data = window.UB_FAKE;
  const { highlight, escapeHtml, reducedMotion, trackCard } = window.UB;

  const tracks = document.getElementById("tracks");
  tracks.setAttribute("role", "list");
  fetch("/api/interview/topics").then((r) => (r.ok ? r.json() : Promise.reject())).then((t) => {
    tracks.innerHTML = t.tracks.map((track) =>
      trackCard(track, { href: `/ui/interview?track=${encodeURIComponent(track.id)}` })).join("");
  }).catch(() => { tracks.hidden = true; });

  document.getElementById("landing-puzzle").textContent = data.puzzle.text;

  const body = document.getElementById("replay-body");
  const bar = document.getElementById("replay-bar");
  const toggle = document.getElementById("replay-toggle");
  const toggleLabel = toggle.querySelector("span");

  // Build lines up front (hidden) so layout doesn't jump when they appear.
  const nodes = data.replay.lines.map((line, i) => {
    const el = document.createElement("div");
    el.className = "sampleline" + (line.kind === "challenge" ? " is-challenge" : "");
    el.hidden = true;
    const who = line.who === "interviewer" ? `Interviewer${line.kind === "challenge" ? " · Challenge" : ""}` : "Candidate";
    el.innerHTML = `<b>${who.toUpperCase()}</b><span class="says">“${escapeHtml(line.text)}”</span>`;
    el.dataset.index = i;
    body.appendChild(el);
    return el;
  });

  let timers = [];
  let playing = false;
  const clear = () => { timers.forEach(clearTimeout); timers = []; };

  function setButton(state) {
    toggleLabel.textContent = state === "playing" ? "Stop" : state === "done" ? "Play again" : "Play sample";
  }

  function play() {
    clear();
    playing = true;
    setButton("playing");
    nodes.forEach((n) => { n.hidden = true; });
    nodes[0].querySelector(".says").textContent = `“${data.replay.lines[0].text}”`;
    bar.style.width = "0%";

    const step = reducedMotion() ? 900 : 2600;
    nodes.forEach((n, i) => {
      timers.push(setTimeout(() => {
        n.hidden = false;
        bar.style.width = `${((i + 1) / nodes.length) * 100}%`;
        // Once the challenge lands, mark the number it challenged in the candidate's line.
        if (data.replay.lines[i].kind === "challenge") {
          const c = data.replay.lines[0];
          nodes[0].querySelector(".says").innerHTML = `“${highlight(c.text, c.challenge)}”`;
        }
      }, i * step + 300));
    });
    timers.push(setTimeout(() => { playing = false; setButton("done"); }, nodes.length * step));
  }

  function stop() {
    clear();
    playing = false;
    setButton("done");
  }

  toggle.addEventListener("click", () => (playing ? stop() : play()));

  // Auto-play after 3 s of no interaction (spec/01 Landing).
  let interacted = false;
  const mark = () => { interacted = true; };
  ["pointerdown", "keydown"].forEach((e) => addEventListener(e, mark, { once: true }));
  setTimeout(() => { if (!interacted) play(); }, 3000);
});
