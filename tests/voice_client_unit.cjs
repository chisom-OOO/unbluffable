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
}

checkController().then(() => { checkPCM(); console.log('Voice client controller and PCM unit checks passed.'); })
  .catch(error => { console.error(error); process.exitCode = 1; });
