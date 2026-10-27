// Pure JavaScript unit checks: no browser, microphone, network, or model calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');

async function checkController() {
  const elements = new Map();
  const element = () => ({disabled: false, checked: false, hidden: false, textContent: '', value: '',
    children: [], append(child) { this.children.push(child); }, replaceChildren() { this.children = []; }});
  global.document = {getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }, createElement: element};
  const $ = id => document.getElementById(id);
  $('consent').checked = true;
  const spoken = [];
  let cancellations = 0;
  global.speechSynthesis = {getVoices: () => [{lang: 'en-GB', name: 'Test voice'}], speak: value => spoken.push(value.text), cancel() { cancellations++; }};
  global.window = {speechSynthesis};
  global.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
  global.location = {protocol: 'http:', host: 'localhost'};
  global.fetch = async () => ({ok: true, json: async () => ({mode: 'replay', silence_s: 1.8, replays: [], question: 'Synthetic question'})});
  const sockets = [];
  global.WebSocket = class {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 1; this.sent = []; sockets.push(this); }
    send(value) { this.sent.push(value); }
    close() { this.onclose?.(); }
  };
  const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
  await new AsyncFunction(fs.readFileSync(path.join(root, 'app/static/voice.js'), 'utf8'))();
  $('transcript').value = 'Synthetic candidate answer';
  $('confirm').onclick();
  const old = sockets.at(-1);
  old.onopen();
  assert.equal(JSON.parse(old.sent[0]).transcript, 'Synthetic candidate answer');
  const deliver = value => old.onmessage({data: JSON.stringify(value)});
  await deliver({type: 'answer_complete', transcript: 'Synthetic candidate answer', acknowledgement: 'Okay, let me check your working'});
  assert.deepEqual(spoken, ['Okay, let me check your working']);
  assert.equal(cancellations, 1, 'The acknowledgement must not queue behind stale interviewer speech');
  const model = {model: 'muse-spark-1.3', job: 'minimal', effort: 'minimal', latency_s: 0.9, estimated_cost_usd: null, mode: 'replay'};
  await deliver({type: 'challenge_result', should_challenge: true, message: 'Synthetic challenge', model});
  assert.deepEqual(spoken, ['Okay, let me check your working', 'Synthetic challenge']);
  await deliver({type: 'analysis_complete'});
  assert.equal($('confirm').disabled, false);
  assert.equal($('fallback').disabled, true);
  $('confirm').onclick();
  assert.equal($('confirm').disabled, true);
  old.onclose();
  assert.equal($('confirm').disabled, true, 'An older socket must not reset a new recording');
}

function checkPCM() {
  const output = [];
  let Processor;
  vm.runInNewContext(fs.readFileSync(path.join(root, 'app/static/mic-worklet.js'), 'utf8'), {
    sampleRate: 48000, ArrayBuffer, DataView,
    AudioWorkletProcessor: class { constructor() { this.port = {postMessage: data => output.push(data)}; } },
    registerProcessor(name, value) { assert.equal(name, 'mic-pcm'); Processor = value; },
  });
  const active = new Processor();
  for (let block = 0; block < 30; block++) active.process([[new Float32Array(128).fill(0.5)]]);
  const frame = output.find(item => item.type === 'pcm');
  assert.equal(frame.buffer.byteLength, 2560, 'One PCM frame must contain 80 ms at 16 kHz');
  assert.equal(new DataView(frame.buffer).getInt16(0, true), 16384);
  output.length = 0;
  const muted = new Processor();
  muted.port.onmessage({data: {type: 'mute', value: true}});
  for (let block = 0; block < 30; block++) muted.process([[new Float32Array(128).fill(0.8)]]);
  assert(output.filter(item => item.type === 'pcm').every(item => new Uint8Array(item.buffer).every(value => value === 0)));
  muted.port.onmessage({data: {type: 'flush'}});
  assert.equal(output.at(-1).type, 'flushed');
  output.length = 0;
  for (let block = 0; block < 30; block++) muted.process([[new Float32Array(128).fill(0.8)]]);
  assert(output.some(item => item.type === 'pcm'), 'Done must leave the worklet running for the next answer');
}

async function checkHandsFree() {
  const elements = new Map();
  const element = () => ({disabled: false, checked: false, hidden: false, textContent: '', value: '',
    children: [], append(child) { this.children.push(child); }, replaceChildren() { this.children = []; }});
  global.document = {getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }, createElement: element};
  const $ = id => document.getElementById(id);
  $('consent').checked = true;
  const spoken = [], sockets = [], ports = [];
  let cancellations = 0, micRequests = 0, trackStops = 0, contexts = 0;
  const track = {enabled: true, stop() { trackStops++; }};
  Object.defineProperty(global, 'navigator', {configurable: true, value: {mediaDevices: {
    async getUserMedia(options) {
      micRequests++;
      assert.equal(options.audio.echoCancellation, true);
      assert.equal(options.audio.noiseSuppression, true);
      assert.equal(spoken[0].text, 'Synthetic question', 'Start must unlock speech within the gesture');
      return {getAudioTracks: () => [track], getTracks: () => [track]};
    },
  }}});
  global.speechSynthesis = {getVoices: () => [{lang: 'en-GB', name: 'Natural voice'}], speak: utterance => spoken.push(utterance), cancel() { cancellations++; }};
  global.window = {speechSynthesis};
  global.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
  const chain = {connect() { return this; }};
  global.AudioContext = class {
    constructor() { contexts++; this.audioWorklet = {addModule: async () => {}}; }
    resume() { return Promise.resolve(); }
    close() { return Promise.resolve(); }
    createMediaStreamSource() { return chain; }
    createGain() { return {...chain, gain: {value: 1}}; }
  };
  global.AudioWorkletNode = class {
    constructor() { this.port = {sent: [], postMessage(value) { this.sent.push(value); }}; ports.push(this.port); }
    connect() { return chain; }
    disconnect() {}
  };
  global.location = {protocol: 'http:', host: 'localhost'};
  global.fetch = async () => ({ok: true, json: async () => ({mode: 'live', silence_s: .8, replays: [], question: 'Synthetic question'})});
  global.WebSocket = class {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 1; this.sent = []; sockets.push(this); }
    send(value) { this.sent.push(value); }
    close() { this.readyState = 3; this.onclose?.(); }
  };
  const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
  await new AsyncFunction(fs.readFileSync(path.join(root, 'app/static/voice.js'), 'utf8'))();
  await $('record').onclick();
  const socket = sockets[0]; socket.onopen();
  const start = JSON.parse(socket.sent[0]);
  assert(start.hands_free && start.interviewer_speaking && !start.headphones);
  const deliver = event => socket.onmessage({data: JSON.stringify(event)});
  await deliver({type: 'ready', model: {mode: 'live'}});
  assert.equal(track.enabled, false, 'Speaker playback must mute mic input');
  await deliver({type: 'candidate_speech'});
  assert.equal(cancellations, 0, 'Barge-in must be disabled without headphones');
  $('headphones').checked = true; $('headphones').onchange();
  assert.equal(track.enabled, true);
  await deliver({type: 'candidate_speech'});
  assert.equal(cancellations, 1, 'Headphone candidate speech must cancel browser speech');
  await deliver({type: 'listening_prompt', message: 'Want to talk me through where you are?'});
  assert.equal(spoken.at(-1).text, 'Want to talk me through where you are?');
  $('headphones').checked = false; $('headphones').onchange();
  assert.equal(track.enabled, false);
  spoken[0].onend();
  assert.equal(track.enabled, false, 'A cancelled utterance must not unmute a newer one');
  spoken.at(-1).onend();
  assert.equal(track.enabled, true);
  await deliver({type: 'capture_stopped'});
  await deliver({type: 'answer_complete', transcript: 'Synthetic answer', acknowledgement: 'Okay, let me check your working'});
  await deliver({type: 'ready', model: {mode: 'live'}});
  await deliver({type: 'analysis_complete'});
  assert.equal(micRequests, 1); assert.equal(contexts, 1); assert.equal(trackStops, 0);
  assert.equal($('record').disabled, true, 'Hands-free capture must continue after analysis');
  assert.equal($('done').disabled, false);
  $('done').onclick();
  assert.equal(ports[0].sent.at(-1).type, 'flush');
  ports[0].onmessage({data: {type: 'flushed'}});
  assert(socket.sent.some(value => typeof value === 'string' && JSON.parse(value).type === 'done'));
  assert.equal(trackStops, 0, 'Done must preserve mic access for the next answer');
  $('stop').onclick();
  assert.equal(trackStops, 1);
  assert.equal($('record').disabled, false);
}

checkController().then(checkHandsFree).then(() => { checkPCM(); console.log('Voice client controller, hands-free capture, headphones and PCM unit checks passed.'); })
  .catch(error => { console.error(error); process.exitCode = 1; });
