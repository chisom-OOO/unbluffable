// Camera preview tile (decision log 7): local preview only, off by default, first item in the cut order.
// The stream goes to the <video> element and nowhere else: it is never recorded, uploaded, stored or sent.
// No permission prompt until the candidate turns it on; denial is handled quietly.
document.addEventListener("DOMContentLoaded", () => {
  const $ = (id) => document.getElementById(id);
  const toggle = $("camera-toggle"), state = $("camera-state"), video = $("camera-video"), off = $("camera-off");
  let stream = null;

  function show(on, note) {
    toggle.setAttribute("aria-pressed", String(on));
    state.textContent = on ? "On" : "Off";
    video.hidden = !on;
    off.hidden = on;
    off.textContent = note || "Camera off";
  }

  function stop(note) {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    video.srcObject = null;
    show(false, note);
  }

  async function start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      show(false, "Camera preview isn't available here");
      return;
    }
    toggle.disabled = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 360 }, aspectRatio: { ideal: 16 / 9 } },
        audio: false,
      });
      video.srcObject = stream;
      show(true);
    } catch {
      stop("Camera off. You can carry on without it.");
    } finally {
      toggle.disabled = false;
    }
  }

  toggle.addEventListener("click", () => (stream ? stop() : start()));
  window.addEventListener("pagehide", () => stop());
  show(false);
});
