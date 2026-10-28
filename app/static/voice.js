const $ = id => document.getElementById(id);
let config, socket, stream, context, worklet, recorder, fallbackChunks = [], busy = false;
let speechCount = 0, speechGeneration = 0;
let handsFree = false, captureReady = false, pendingAudio = [];
let candidateActive = false;
const status = message => { $('status').textContent = message; };
const interviewer = message => {
  $('interviewer-section').hidden = false;
  $('interviewer').textContent = message;
};
function muteMic(value) {
  worklet?.port.postMessage({type: 'mute', value});
  stream?.getAudioTracks().forEach(track => { track.enabled = !value; });
}
function speechState() {
  muteMic(speechCount > 0 && !$('headphones').checked);
  if (socket?.readyState === WebSocket.OPEN && handsFree) socket.send(JSON.stringify({
    type: 'interviewer_speaking', value: speechCount > 0, headphones: $('headphones').checked,
  }));
}
function cancelSpeech() {
  speechGeneration++; speechCount = 0;
  window.speechSynthesis?.cancel(); speechState();
}
function speak(text) {
  interviewer(text);
  if ($('mute').checked || !window.speechSynthesis) return;
  const utterance = new SpeechSynthesisUtterance(text);
  const voices = speechSynthesis.getVoices().filter(voice => voice.lang.startsWith('en'))
    .sort((a, b) => a.name.localeCompare(b.name));
  utterance.voice = voices.find(voice => /Natural|Online/i.test(voice.name)) ||
    voices.find(voice => voice.lang === 'en-GB') || voices.find(voice => voice.lang === 'en-US') || voices[0] || null;
  const generation = speechGeneration;
  speechCount++; speechState();
  let ended = false;
  const finished = () => {
    if (ended || generation !== speechGeneration) return;
    ended = true;
    speechCount = Math.max(0, speechCount - 1); speechState();
  };
  utterance.onend = finished; utterance.onerror = finished;
  speechSynthesis.speak(utterance);
}
function controls(value) {
  busy = value;
  for (const id of ['record', 'fallback', 'confirm', 'transcribe']) $(id).disabled = value;
  if (config?.mode === 'replay') $('fallback').disabled = true;
}
function consent() {
  if (!$('consent').checked) { status('Please agree to submit your answer before continuing.'); return false; }
  return true;
}
function stopCapture() {
  captureReady = false; pendingAudio = [];
  worklet?.disconnect(); worklet = null;
  if (context) context.close().catch(() => {}); context = null;
  stream?.getTracks().forEach(track => track.stop()); stream = null;
  $('done').disabled = true;
  $('stop').disabled = true;
}
function showModel(model) {
  const row = document.createElement('p');
  const elapsed = model.latency_s == null ? '' : ` · ${model.latency_s.toFixed(2)} s`;
  const cost = model.estimated_cost_usd == null ? 'cost not reported' : `estimated $${model.estimated_cost_usd.toFixed(6)}`;
  row.textContent = `${model.model} · ${model.job}${model.effort ? ` (${model.effort})` : ''}${elapsed} · ${cost}`;
  if (model.mode === 'replay') row.textContent += ` · RECORDED RUN ${model.run_id} · ${model.recorded_at}`;
  $('models').append(row);
}
function openSocket(path, start) {
  const connection = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${path}`);
  socket = connection;
  connection.onopen = () => connection.send(JSON.stringify(start));
  connection.onmessage = async ({data}) => {
    if (socket !== connection) return;
    const event = JSON.parse(data);
    if (event.type === 'ready') {
      if (event.model.mode === 'replay') {
        status(`Recorded run · ${event.model.run_id} · ${event.model.recorded_at}`);
      } else {
        try {
          await startPCM();
          if (socket !== connection) return;
          captureReady = true;
          for (const frame of pendingAudio) connection.send(frame);
          pendingAudio = []; speechState();
          $('done').disabled = false;
          status('Listening. Keep thinking out loud; I’ll respond when you finish.');
        } catch {
          handsFree = false; stopCapture(); controls(false); connection.close();
          status('Live microphone capture is unavailable. Record then transcribe, upload audio, or type an answer.');
        }
      }
    }
    if (event.type === 'transcript') $('transcript').value = event.transcript;
    if (event.type === 'candidate_speech') {
      candidateActive = true;
      if ($('headphones').checked && speechCount) cancelSpeech();
    }
    if (event.type === 'listening_prompt') { cancelSpeech(); speak(event.message); }
    if (event.type === 'capture_stopped') {
      captureReady = false; $('done').disabled = true;
      if (!handsFree) stopCapture();
    }
    if (event.type === 'transcription_model') showModel(event.model);
    if (event.type === 'endpoint_decision' && event.model) showModel(event.model);
    if (event.type === 'answer_complete') {
      candidateActive = false;
      if (!handsFree) stopCapture();
      $('transcript').value = event.transcript;
      // Synchronous speech enqueue happens before handling any model-result frame.
      cancelSpeech();
      speak(event.acknowledgement);
      status('Checking your working…');
    }
    if (event.type === 'challenge_result') {
      showModel(event.model);
      if (event.message) {
        if (candidateActive) interviewer(event.message);
        else { cancelSpeech(); speak(event.message); }
      }
      else status(event.number_found ? 'The stated number matches the exact check. Reasoning review may still be running.' : 'No committed probability was found. You can edit your answer.');
    }
    if (event.type === 'scoring_result') {
      showModel(event.model); $('evidence').textContent = JSON.stringify(event.extraction, null, 2);
    }
    if (event.type === 'model_error') status(event.message);
    if (event.type === 'analysis_complete' && !handsFree) controls(false);
    if (event.type === 'error') { handsFree = false; stopCapture(); controls(false); status(event.message); }
  };
  connection.onerror = () => { if (socket !== connection) return; handsFree = false; stopCapture(); controls(false); status('Connection failed. Try recording then transcribing, or type an answer.'); };
  connection.onclose = () => { if (socket !== connection) return; handsFree = false; stopCapture(); if (busy) controls(false); };
}
async function microphone() {
  stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}});
  speechState();
}
async function startPCM() {
  if (worklet) return;
  context ||= new AudioContext();
  await context.audioWorklet.addModule('/voice-static/mic-worklet.js');
  worklet = new AudioWorkletNode(context, 'mic-pcm');
  worklet.port.onmessage = ({data}) => {
    if (data.type === 'pcm' && socket?.readyState === WebSocket.OPEN) {
      if (captureReady) socket.send(data.buffer);
      else if (handsFree) { pendingAudio.push(data.buffer); if (pendingAudio.length > 25) pendingAudio.shift(); }
    }
    if (data.type === 'flushed' && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({type: 'done'})); captureReady = false;
      if (!handsFree) stopCapture();
      status('Finishing transcription…');
    }
  };
  const source = context.createMediaStreamSource(stream), silent = context.createGain();
  silent.gain.value = 0; source.connect(worklet).connect(silent).connect(context.destination);
  speechState();
  await context.resume();
}
$('hear').onclick = () => { cancelSpeech(); speak($('question').textContent); };
$('mute').onchange = () => {
  if ($('mute').checked) cancelSpeech();
};
$('headphones').onchange = speechState;
$('record').onclick = async () => {
  if (!consent()) return;
  controls(true); $('models').replaceChildren(); $('evidence').textContent = ''; $('transcript').value = '';
  try {
    handsFree = config.mode !== 'replay';
    candidateActive = false;
    if (handsFree) {
      context = new AudioContext();
      const resumed = context.resume();
      speak($('question').textContent);
      await microphone(); await resumed;
    }
    $('stop').disabled = false;
    openSocket('/api/voice/realtime', {type: 'start', sample_rate: 16000, replay_id: $('replay').value,
      hands_free: handsFree, headphones: $('headphones').checked, interviewer_speaking: speechCount > 0});
    status('Connecting…');
  } catch { handsFree = false; cancelSpeech(); stopCapture(); controls(false); status('Microphone unavailable. You can upload audio or type an answer.'); }
};
$('stop').onclick = () => {
  handsFree = false; cancelSpeech(); socket?.close(); stopCapture(); controls(false);
  status('Interview stopped. Your transcript remains editable.');
};
$('done').onclick = () => {
  $('done').disabled = true;
  if (recorder?.state === 'recording') recorder.stop();
  else worklet?.port.postMessage({type: 'flush'});
};
async function transcribe(blob) {
  status('Transcribing your recording…');
  const response = await fetch('/api/voice/transcribe', {method: 'POST', headers: {'Content-Type': blob.type || 'application/octet-stream'}, body: blob});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Transcription failed.');
  $('transcript').value = data.transcript; showModel(data.model);
  status('Review or edit the transcript, then tap Check this answer.');
}
$('fallback').onclick = async () => {
  if (!consent()) return;
  controls(true);
  try {
    await microphone(); fallbackChunks = [];
    const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(type => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, mimeType ? {mimeType} : {});
    recorder.ondataavailable = ({data}) => { if (data.size) fallbackChunks.push(data); };
    recorder.onstop = async () => {
      const blob = new Blob(fallbackChunks, {type: recorder.mimeType}); stopCapture();
      try { await transcribe(blob); } catch (error) { status(error.message); } finally { controls(false); }
    };
    recorder.start(); $('done').disabled = false; status('Recording locally. Tap Done to transcribe.');
  } catch { stopCapture(); controls(false); status('Recording is unavailable. Upload an audio file or type your answer.'); }
};
$('transcribe').onclick = async () => {
  if (!consent()) return;
  const file = $('file').files[0];
  if (!file) { status('Choose an audio file.'); return; }
  controls(true);
  try { await transcribe(file); } catch (error) { status(error.message); } finally { controls(false); }
};
$('confirm').onclick = () => {
  if (!consent()) return;
  const transcript = $('transcript').value.trim();
  if (!transcript) { status('Enter an answer to check.'); return; }
  controls(true); $('models').replaceChildren();
  openSocket('/api/voice/answer', {transcript});
};
try {
  const response = await fetch('/api/voice/config'); config = await response.json();
  if (!response.ok) throw new Error();
  $('question').textContent = config.question;
  $('silence').textContent = 'Keep thinking out loud. Done is an optional fallback if I miss the end of your answer.';
  $('mode').textContent = config.mode === 'replay' ? 'Recorded replay · no live model calls' : 'Live mode';
  $('replay-controls').hidden = config.mode !== 'replay';
  for (const run of config.replays) {
    const option = document.createElement('option'); option.value = run.run_id; option.textContent = `${run.recorded_at} · ${run.run_id}`; $('replay').append(option);
  }
  if (config.mode === 'replay') $('fallback').disabled = true;
} catch { controls(true); status('Voice configuration is unavailable.'); }
