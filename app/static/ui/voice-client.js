// Minimal realtime microphone client for the Exam Room, copied from app/static/voice.js
// (which belongs to the voice lane and is not modified). It captures 16 kHz PCM with the
// shared /voice-static/mic-worklet.js and sends frames over the interview socket only while
// a capture is open. Audio is never stored; nothing is sent outside a capture.
(() => {
  let stream = null, context = null, worklet = null, analyser = null;
  let socket = null, capturing = false, pending = [];

  async function open() {
    if (stream) return;
    context ||= new AudioContext();
    const resumed = context.resume();
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
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

  // Local input level 0..1 for the device check; nothing is sent.
  function level() {
    if (!analyser) return 0;
    const data = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const v of data) { const x = (v - 128) / 128; sum += x * x; }
    return Math.min(1, Math.sqrt(sum / data.length) * 4);
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
    open, attach, startStreaming, stopStreaming, mute, flush, level, close,
    get isOpen() { return !!stream; },
    get capturing() { return capturing; },
  };
})();
