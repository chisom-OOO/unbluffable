// Look "Trading floor", the default since its approval: <html data-look="floor"> in each
// template. /ui?look=default switches this browser back to the earlier look (remembered);
// /ui?look=floor returns. This file adds the look's favicon (the ≠ mark), swaps the landing
// screenshot, and draws the candidate's waveform on the mic indicator.
// Display only: the waveform reads the local input level (UBVoice.level(), never sent).
(() => {
  const look = document.documentElement.dataset.look;
  if (look !== "floor") return;

  // The favicon carries the same ?v= as this script, so a deploy never shows a stale one.
  const version = (document.currentScript?.src.match(/\?v=[^"#]*/) || [""])[0];
  for (const [rel, file, type] of [["icon", "favicon-floor.svg", "image/svg+xml"], ["apple-touch-icon", "apple-touch-icon-floor.png", ""]]) {
    const link = Object.assign(document.createElement("link"), { rel, href: `/ui-static/img/${file}${version}` });
    if (type) link.type = type;
    document.head.appendChild(link);
  }

  // The waveform: the candidate's real input level, a bar every ~70 ms, newest on the right.
  // Flat when the candidate is silent. Only while the candidate's microphone is open and the
  // room is listening; the interviewer's speaking state keeps its own muted bars. Reduced
  // motion keeps static bars (the stylesheet colours them).
  document.addEventListener("DOMContentLoaded", () => {
    // The landing's screenshot of the interview screen, taken in this look.
    for (const img of document.querySelectorAll(".shot img")) {
      img.src = img.getAttribute("src").replace(/interview-(light|dark)\.webp/, "interview-floor-$1.webp");
    }
    const mic = document.getElementById("mic");
    if (!mic) return;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const canvas = document.createElement("canvas");
    canvas.className = "wave";
    canvas.setAttribute("aria-hidden", "true");
    mic.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    const BARS = 7, history = new Array(BARS).fill(0);
    let frame = null, last = 0;

    function draw(now) {
      frame = requestAnimationFrame(draw);
      if (now - last < 70) return;
      last = now;
      const level = window.UBVoice?.level() || 0;
      history.push(level < 0.02 ? 0 : Math.min(1, Math.sqrt(level) * 1.5));
      history.shift();
      const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = getComputedStyle(canvas).color;
      const gap = w / BARS, bar = Math.max(2, gap * 0.55);
      history.forEach((v, i) => {
        const bh = Math.max(2, v * h);  // silence draws a flat 2 px line
        ctx.fillRect(i * gap + (gap - bar) / 2, (h - bh) / 2, bar, bh);
      });
    }
    function stop() { if (frame) cancelAnimationFrame(frame); frame = null; history.fill(0); mic.classList.remove("live"); }
    function sync() {
      const live = mic.dataset.state === "listening" && !!window.UBVoice?.isOpen && !reduced.matches;
      if (live && !frame) { mic.classList.add("live"); frame = requestAnimationFrame(draw); }
      else if (!live && frame) stop();
    }
    new MutationObserver(sync).observe(mic, { attributes: true, attributeFilter: ["data-state"] });
    reduced.addEventListener?.("change", sync);
    sync();
  });
})();
