// Landing: show the puzzle; if the visitor hasn't started within 3 s, play the labelled recorded run.
document.addEventListener("DOMContentLoaded", () => {
  const data = window.UB_FAKE;
  const { highlight, escapeHtml, reducedMotion } = window.UB;

  document.getElementById("landing-puzzle").textContent = data.puzzle.text;
  document.getElementById("replay-note").textContent = `Recorded on ${data.replay.recordedOn}. Replay works without a live model.`;

  const body = document.getElementById("replay-body");
  const bar = document.getElementById("replay-bar");
  const toggle = document.getElementById("replay-toggle");
  const toggleLabel = toggle.querySelector("span");

  // Build lines up front (hidden) so layout doesn't jump when they appear.
  const nodes = data.replay.lines.map((line, i) => {
    const el = document.createElement("div");
    el.className = `utterance ${line.who}` + (line.kind === "challenge" ? " is-challenge" : "");
    el.hidden = true;
    const who = line.who === "interviewer" ? "Interviewer" : "Candidate";
    const tag = line.kind === "challenge" ? `<span class="tag tag-challenge">Challenge</span>` : "";
    el.innerHTML = `<div class="speaker"><span>${who}</span>${tag}</div><p class="says">${escapeHtml(line.text)}</p>`;
    el.dataset.index = i;
    body.appendChild(el);
    return el;
  });

  let timers = [];
  let playing = false;
  const clear = () => { timers.forEach(clearTimeout); timers = []; };

  function setButton(state) {
    toggleLabel.textContent = state === "playing" ? "Stop" : state === "done" ? "Play again" : "Play recorded run";
  }

  function play() {
    clear();
    playing = true;
    setButton("playing");
    document.getElementById("replay-placeholder")?.remove();
    nodes.forEach((n) => { n.hidden = true; });
    nodes[0].querySelector(".says").textContent = data.replay.lines[0].text;
    bar.style.width = "0%";

    const step = reducedMotion() ? 900 : 2600;
    nodes.forEach((n, i) => {
      timers.push(setTimeout(() => {
        n.hidden = false;
        bar.style.width = `${((i + 1) / nodes.length) * 100}%`;
        // Once the challenge lands, mark the number it challenged in the candidate's line.
        if (data.replay.lines[i].kind === "challenge") {
          const c = data.replay.lines[0];
          nodes[0].querySelector(".says").innerHTML = highlight(c.text, c.challenge);
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
