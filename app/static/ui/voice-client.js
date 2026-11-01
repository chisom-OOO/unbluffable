// Minimal realtime microphone client for the Exam Room, copied from app/static/voice.js
// (which belongs to the voice lane and is not modified). It captures 16 kHz PCM with the
// shared /voice-static/mic-worklet.js and sends frames over the interview socket only while
// a capture is open. Audio is never stored; nothing is sent outside a capture.
(() => {
  let stream = null, context = null, worklet = null, analyser = null;
  let socket = null, capturing = false, pending = [], wanted = "";

  // iPad Safari runs audio only once a context was created or resumed inside a tap: call
  // unlock() from the tap itself (Start, Test microphone), before any await. Any later tap
  // resumes a context iOS suspended (a call, Siri, another app's audio).
  function unlock() {
    if (!window.AudioContext && !window.webkitAudioContext) return;
    context ||= new (window.AudioContext || window.webkitAudioContext)();
    if (context.state !== "running") context.resume().catch(() => {});
  }
  document.addEventListener("pointerdown", () => {
    if (context && context.state !== "running" && context.state !== "closed") context.resume().catch(() => {});
  }, { capture: true, passive: true });

  // `deviceId` (optional) picks an input; a different one closes the open stream first.
  // A track that ends (unplugged, revoked) fires "ub-mic-ended" on the document.
  async function open({ deviceId } = {}) {
    if (deviceId !== undefined && deviceId !== wanted) { close(); wanted = deviceId; }
    if (stream) return;
    context ||= new (window.AudioContext || window.webkitAudioContext)();
    // Outside a tap iOS may leave resume() pending: wait at most a second; the next tap resumes it.
    const resumed = Promise.race([context.resume().catch(() => {}), new Promise((r) => setTimeout(r, 1000))]);
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true,
               ...(wanted ? { deviceId: { exact: wanted } } : {}) },
    });
    const opened = stream;
    stream.getAudioTracks().forEach((t) => t.addEventListener("ended", () => {
      if (stream === opened) document.dispatchEvent(new CustomEvent("ub-mic-ended"));
    }));
    await resumed;
    await context.audioWorklet.addModule("/voice-static/mic-worklet.js");
    worklet = new AudioWorkletNode(context, "mic-pcm");
    worklet.port.onmessage = ({ data }) => {
      if (data.type === "pcm" && socket?.readyState === WebSocket.OPEN) {
        if (capturing) socket.send(data.buffer);
        else { pending.push(data.buffer); if (pending.length > 25) pending.shift(); }
      }
      if (data.type === "flushed" && socket?.readyState === WebSocket.OPEN && capturing) {
        socket.send(JSON.stringify({ type: "done" }));
        capturing = false;
      }
    };
    const source = context.createMediaStreamSource(stream);
    const silent = context.createGain();
    silent.gain.value = 0;
    source.connect(worklet).connect(silent).connect(context.destination);
    analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
  }

  // The interview socket; frames captured before "ready" are buffered briefly.
  function attach(ws) { socket = ws; pending = []; }

  // Called on the server's "ready": stream buffered and live frames until capture_stopped.
  function startStreaming(ws) {
    socket = ws;
    capturing = true;
    for (const frame of pending) ws.send(frame);
    pending = [];
  }

  function stopStreaming() { capturing = false; pending = []; }

  // Without headphones the mic is muted while the interviewer speaks (no echo).
  function mute(value) {
    worklet?.port.postMessage({ type: "mute", value });
    stream?.getAudioTracks().forEach((t) => { t.enabled = !value; });
  }

  function flush() { worklet?.port.postMessage({ type: "flush" }); }

  // Local input level 0..1 for the device check (RMS x 4, read as floats so a quiet
  // microphone still registers); nothing is sent.
  function level() {
    if (!analyser) return 0;
    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);
    let sum = 0;
    for (const x of data) sum += x * x;
    return Math.min(1, Math.sqrt(sum / data.length) * 4);
  }

  // The input in use: { id, label } (the label is empty until the browser allows the microphone).
  function device() {
    const track = stream?.getAudioTracks()[0];
    return track ? { id: track.getSettings?.().deviceId || wanted, label: track.label } : null;
  }

  function close() {
    capturing = false; pending = [];
    worklet?.disconnect(); worklet = null; analyser = null;
    if (context) context.close().catch(() => {});
    context = null;
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  window.UBVoice = {
    open, unlock, attach, startStreaming, stopStreaming, mute, flush, level, device, close,
    get isOpen() { return !!stream; },
    get capturing() { return capturing; },
  };
})();
