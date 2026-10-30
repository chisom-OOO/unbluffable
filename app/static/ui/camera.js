// Camera (decision log 20, amending 7): checked before Start, then kept on as a local
// self-view during the interview. The stream goes to the <video> elements and nowhere else:
// it is never recorded, uploaded, stored or sent to any model. No permission prompt until
// the candidate turns it on. "ub-camera" events tell the page whether a picture is showing
// and, if not, why: off | waiting | blocked | none | busy.
document.addEventListener("DOMContentLoaded", () => {
  const $ = (id) => document.getElementById(id);
  const toggle = $("camera-toggle"), state = $("camera-state"), video = $("camera-video"),
    off = $("camera-off"), self = $("camera-self");
  const note = $("camera-note");
  const NOTE = "Shown only on this screen. Never recorded, uploaded or sent.";
  let stream = null, ok = false, reason = "off";

  function report(value, why, label, cls, text) {
    ok = value; reason = why;
    state.textContent = label;
    state.className = `check-state${cls ? ` ${cls}` : ""}`;
    note.textContent = text || NOTE;
    note.className = `device-note${cls === "bad" ? " bad" : ""}`;
    document.dispatchEvent(new CustomEvent("ub-camera", { detail: { ok, reason } }));
  }

  function show(on, note) {
    toggle.setAttribute("aria-pressed", String(on));
    toggle.textContent = on ? "Turn off camera" : "Turn on camera";
    video.hidden = !on;
    off.hidden = on;
    off.textContent = note || "Camera off";
  }

  const PROBLEM = {
    blocked: ["Blocked", "The browser is blocking the camera. Allow it from the camera icon in the address bar, then reload."],
    none: ["No camera", "No camera found. Connect one or use typed practice."],
    busy: ["Not responding", "The camera is in use by another app or not responding. Close other apps using it, then try again."],
  };
  function stop(why = "off") {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    video.srcObject = null;
    if (self) self.srcObject = null;
    show(false, why === "off" ? "Camera off" : PROBLEM[why][0]);
    if (why === "off") report(false, "off", "Not checked", "");
    else report(false, why, PROBLEM[why][0], "bad", PROBLEM[why][1]);
  }
  const why = (error) => ({ NotAllowedError: "blocked", SecurityError: "blocked", NotFoundError: "none",
                            OverconstrainedError: "none", NotReadableError: "busy", AbortError: "busy" }[error?.name] || "busy");

  // A picture counts once the video has real frames. "playing" can arrive before the frame
  // size is known, so the size change and first data are checked too.
  const framed = () => { if (stream && !ok && video.videoWidth > 0) report(true, "ok", "Picture showing", "ok"); };
  ["playing", "loadeddata", "resize"].forEach((type) => video.addEventListener(type, framed));

  async function start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      stop("none");
      return;
    }
    toggle.disabled = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 360 }, aspectRatio: { ideal: 16 / 9 } },
        audio: false,
      });
      stream.getVideoTracks().forEach((t) => t.addEventListener("ended", () => stop("none")));
      video.srcObject = stream;
      if (self) self.srcObject = stream;
      show(true);
      report(false, "waiting", "Waiting for a picture", "");
    } catch (error) {
      stop(why(error));
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
    get reason() { return reason; },
    // Turn the camera on (again): the device check's dialog uses this.
    start() { if (stream) stop(); return start(); },
    // The room's self-view: keep showing the same local stream.
    attachSelf() { if (self && stream) { self.srcObject = stream; self.play?.().catch(() => {}); } return !!stream; },
  };
});
