// Camera (decision log 20, amending 7): checked before Start, then kept on as a local
// self-view during the interview. The stream goes to the <video> elements and nowhere else:
// it is never recorded, uploaded, stored or sent to any model. No permission prompt until
// the candidate turns it on. "ub-camera" events tell the page whether a picture is showing.
document.addEventListener("DOMContentLoaded", () => {
  const $ = (id) => document.getElementById(id);
  const toggle = $("camera-toggle"), state = $("camera-state"), video = $("camera-video"),
    off = $("camera-off"), self = $("camera-self");
  let stream = null, ok = false;

  function report(value, label, cls) {
    ok = value;
    state.textContent = label;
    state.className = `check-state${cls ? ` ${cls}` : ""}`;
    document.dispatchEvent(new CustomEvent("ub-camera", { detail: { ok } }));
  }

  function show(on, note) {
    toggle.setAttribute("aria-pressed", String(on));
    toggle.textContent = on ? "Turn off camera" : "Turn on camera";
    video.hidden = !on;
    off.hidden = on;
    off.textContent = note || "Camera off";
  }

  function stop(note, bad) {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    video.srcObject = null;
    if (self) self.srcObject = null;
    show(false, note);
    report(false, bad ? "Not working" : "Not checked", bad ? "bad" : "");
  }

  // A picture counts once the video has real frames.
  video.addEventListener("playing", () => {
    if (stream && video.videoWidth > 0) report(true, "Picture showing", "ok");
  });

  async function start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      stop("This browser can't show a camera here.", true);
      return;
    }
    toggle.disabled = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 360 }, aspectRatio: { ideal: 16 / 9 } },
        audio: false,
      });
      stream.getVideoTracks().forEach((t) => t.addEventListener("ended", () => stop("The camera stopped.", true)));
      video.srcObject = stream;
      if (self) self.srcObject = stream;
      show(true);
      report(false, "Waiting for a picture", "");
    } catch {
      stop("The camera is blocked or missing.", true);
    } finally {
      toggle.disabled = false;
    }
  }

  toggle.addEventListener("click", () => (stream ? stop() : start()));
  window.addEventListener("pagehide", () => stop());
  show(false);

  window.UBCamera = {
    get ok() { return ok; },
    get on() { return !!stream; },
    // The room's self-view: keep showing the same local stream.
    attachSelf() { if (self && stream) { self.srcObject = stream; self.play?.().catch(() => {}); } return !!stream; },
  };
});
