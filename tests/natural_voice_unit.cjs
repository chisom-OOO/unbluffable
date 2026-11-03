// Decision log 43: the optional natural voice (Kokoro in the browser). Pure checks in Node with
// a fake engine and fake timers: no browser, audio, network or model.
const assert = require("node:assert/strict");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const N = require(path.join(root, "app/static/ui/natural-voice.js"));

const flush = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };

function clock() {
  let now = 0, id = 0;
  const timers = new Map();
  return {
    setTimer: (fn, ms) => { timers.set(++id, { fn, at: now + ms }); return id; },
    clearTimer: (t) => { timers.delete(t); },
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        await flush();
        const due = [...timers.entries()].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]); now = due[1].at; due[1].fn();
      }
      now = end; await flush();
    },
  };
}

function store(initial = {}) {
  const data = { ...initial };
  return { data, get: (k) => (k in data ? data[k] : null), set: (k, v) => { data[k] = v; } };
}

function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }

function controller({ saved, load, available = true } = {}) {
  const c = clock(), s = store(saved ? { [N.STORE_KEY]: saved } : {}), notices = [], loads = [];
  const ctl = N.createController({
    loadEngine: () => { const d = deferred(); loads.push(d); return load ? load() : d.promise; },
    store: s, setTimer: c.setTimer, clearTimer: c.clearTimer, onNotice: (kind, text) => notices.push([kind, text]),
  });
  if (available !== null) { ctl.setAvailable(available); notices.length = 0; }  // the page's availability signal
  return { ctl, c, s, notices, loads };
}

// --- The pinned facts and the copy ---
{
  assert.equal(N.OFFERED, false, "decision log 46: hidden for everyone until the glitching is fixed");
  assert.equal(N.PIN.kokoro, "1.2.1");
  assert.equal(N.PIN.bundle, "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/dist/kokoro.web.js");
  assert.equal(N.PIN.model, "onnx-community/Kokoro-82M-v1.0-ONNX");
  assert.equal(N.PIN.revision, "1939ad2a8e416c0acfeecc08a694d14ef25f2231");
  assert.equal(N.PIN.dtype, "fp16", "the 163 MB fp16 model (decision log 44), never the 326 MB fp32");
  assert.equal(N.PIN.device, "webgpu", "WebGPU only: no WASM path (decision log 44)");
  assert.equal(N.PIN.voice, "af_heart");
  assert.equal(N.START_TIMEOUT_MS, 20000);
  assert.equal(N.SENTENCE_TIMEOUT_MS, 8000);
  assert.equal(N.PROGRESS_LINE, "Downloading natural voice (first time only)…");
  assert.equal(N.FALLBACK_LINE, "Natural voice didn't load, so the interviewer is using your browser's voice.");
  // Only Kokoro's own files on Hugging Face are pinned; everything else passes through.
  assert.equal(N.pinnedUrl("https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/onnx/model_fp16.onnx"),
    "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/1939ad2a8e416c0acfeecc08a694d14ef25f2231/onnx/model_fp16.onnx");
  assert.equal(N.pinnedUrl("https://huggingface.co/other/model/resolve/main/x.onnx"), null);
  assert.equal(N.pinnedUrl("https://example.com/"), null);
  assert.equal(N.PIN.sha256["onnx/model_fp16.onnx"], "ba4527a874b42b21e35f468c10d326fdff3c7fc8cac1f85e9eb6c0dfc35c334a");
  assert.deepEqual(Object.keys(N.PIN.sha256).sort(), ["onnx/model_fp16.onnx", "voices/af_heart.bin"]);
  assert.equal(N.PIN.sha256["voices/af_heart.bin"], "d583ccff3cdca2f7fae535cb998ac07e9fcb90f09737b9a41fa2734ec44a8f0b");
}
console.log("pins ok");

(async () => {
  // --- The switch: off by default, nothing loads ---
  {
    const { ctl, loads, notices } = controller();
    assert.equal(ctl.enabled(), false);
    assert.equal(ctl.usable(), false);
    ctl.started();
    assert.equal(loads.length, 0, "off: no download, no model");
    assert.deepEqual(notices, []);
  }
  // On: the download starts at once with the progress line, and is remembered.
  {
    const { ctl, loads, notices, s } = controller();
    ctl.setEnabled(true);
    assert.equal(loads.length, 1);
    assert.equal(s.data[N.STORE_KEY], "on");
    assert.deepEqual(notices[0], ["progress", N.PROGRESS_LINE]);
    assert.equal(ctl.usable(), false, "not ready yet: lines use the browser voice");
    loads[0].resolve({ synth: async () => ({}), play: () => ({}) });
    await flush();
    assert.equal(ctl.usable(), true);
    assert.equal(notices.at(-1)[0], "ready");
    ctl.setEnabled(false);
    assert.equal(ctl.usable(), false, "off again: the browser voice");
    assert.equal(s.data[N.STORE_KEY], "off");
    ctl.setEnabled(true);
    assert.equal(loads.length, 1, "turning it back on reuses the loaded model");
    assert.equal(ctl.usable(), true);
  }
  // A remembered "on" starts the download when the page opens.
  {
    const { ctl, loads } = controller({ saved: "on" });
    assert.equal(ctl.enabled(), true);
    assert.equal(loads.length, 1);
  }

  // --- No WebGPU: the switch is hidden and nothing loads, even if "on" was remembered (row 44) ---
  {
    const { ctl, loads, notices } = controller({ saved: "on", available: null });
    assert.equal(loads.length, 0, "nothing loads before WebGPU is confirmed");
    assert.equal(ctl.available(), null);
    ctl.setAvailable(false);
    assert.equal(loads.length, 0);
    assert.deepEqual(notices, [["unavailable", ""]], "the page hides the switch");
    assert.equal(ctl.enabled(), false);
    ctl.setEnabled(true); ctl.started();
    assert.equal(loads.length, 0, "a hidden switch can't start a download");
    assert.equal(ctl.usable(), false);
  }
  {
    const { ctl, loads } = controller({ saved: "on", available: null });
    ctl.setAvailable(true);
    assert.equal(loads.length, 1, "WebGPU confirmed: a remembered on starts the download");
    assert.equal(ctl.available(), true);
  }

  // --- Fallback: a failed load ---
  {
    const { ctl, loads, notices } = controller();
    ctl.setEnabled(true);
    loads[0].reject(new Error("integrity"));
    await flush();
    assert.equal(ctl.usable(), false);
    assert.deepEqual(notices.at(-1), ["fallback", N.FALLBACK_LINE]);
  }
  // Not ready 20 s after Start: the browser voice for the rest of the session; the download goes on.
  {
    const { ctl, c, loads, notices } = controller();
    ctl.setEnabled(true);
    ctl.started();
    await c.advance(19999);
    assert.equal(notices.filter(([k]) => k === "fallback").length, 0);
    await c.advance(1);
    assert.deepEqual(notices.at(-1), ["fallback", N.FALLBACK_LINE]);
    loads[0].resolve({ synth: async () => ({}), play: () => ({}) });
    await flush();
    assert.equal(ctl.usable(), false, "ready later: still the browser voice this session");
    assert.equal(ctl.state(), "ready", "the finished download is kept for next time");
  }
  // The 20 s count from Start, not from turning the switch on.
  {
    const { ctl, c, loads, notices } = controller();
    ctl.setEnabled(true);
    await c.advance(60000);  // a minute on the setup page: no limit yet
    assert.equal(notices.filter(([k]) => k === "fallback").length, 0);
    ctl.started();
    await c.advance(15000);
    loads[0].resolve({ synth: async () => ({}), play: () => ({}) });
    await c.advance(10000);
    assert.equal(ctl.usable(), true, "ready within 20 s of Start");
    assert.equal(notices.filter(([k]) => k === "fallback").length, 0);
  }
  // A line that fails to play: fallback once, one line.
  {
    const { ctl, loads, notices } = controller();
    ctl.setEnabled(true);
    loads[0].resolve({ synth: async () => ({}), play: () => ({}) });
    await flush();
    ctl.lineFailed(); ctl.lineFailed();
    assert.equal(ctl.usable(), false);
    assert.equal(notices.filter(([k]) => k === "fallback").length, 1);
  }

  // --- speakLine: the same start and end signals as the browser voice ---
  function engine({ synthMs = {}, failPlay = {}, failSynth = {} } = {}) {
    const log = [];
    const playing = [];
    return {
      log, playing,
      synth: (text) => { log.push(["synth", text]); return failSynth[text] ? Promise.reject(new Error("synth")) :
        new Promise((r) => (synthMs[text] ? setTimeout(() => r({ text }), synthMs[text]) : r({ text }))); },
      play: (clip) => {
        log.push(["play", clip.text]);
        const d = deferred();
        const p = { started: Promise.resolve(), done: d.promise, stop: () => { log.push(["stop", clip.text]); d.resolve(); }, finish: d.resolve,
                    fail: () => d.reject(new Error("audio")) };
        playing.push(p);
        if (failPlay[clip.text]) { p.fail(); }
        return p;
      },
    };
  }
  function line(eng, parts, c) {
    const events = [];
    const handle = N.speakLine(eng, parts, { pauseMs: 400, setTimer: c.setTimer, clearTimer: c.clearTimer,
      onStart: () => events.push("start"), onDone: (r) => events.push("done:" + r), onFail: (i) => events.push("fail:" + i) });
    return { events, handle };
  }
  {
    const c = clock(), eng = engine();
    const { events } = line(eng, ["One.", "Two.", "Three."], c);
    await flush();
    assert.deepEqual(events, ["start"], "start once, when the first sentence plays");
    assert.ok(eng.log.some(([k, t]) => k === "synth" && t === "Two."), "the next sentence is made while one plays");
    eng.playing[0].finish(); await c.advance(400);
    eng.playing[1].finish(); await c.advance(400);
    assert.deepEqual(events, ["start"], "Speaking holds through the pauses");
    eng.playing[2].finish(); await c.advance(0);
    assert.deepEqual(events, ["start", "done:end"], "end once, after the last sentence");
    assert.equal(N.busy(), 0);
  }
  // A sentence not ready within 8 s: that sentence fails, and the caller finishes the line.
  {
    const c = clock(), eng = engine();
    eng.synth = () => new Promise(() => {});  // never ready
    const { events } = line(eng, ["One.", "Two."], c);
    assert.equal(N.busy(), 1, "a line in progress counts as speech pending");
    await c.advance(7999);
    assert.deepEqual(events, []);
    await c.advance(1);
    assert.deepEqual(events, ["fail:0"]);
    assert.equal(N.busy(), 0);
  }
  // Playback failing on the second sentence: fail from that sentence, no end signal of its own.
  {
    const c = clock(), eng = engine({ failPlay: { "Two.": true } });
    const { events } = line(eng, ["One.", "Two.", "Three."], c);
    await flush();
    eng.playing[0].finish(); await c.advance(400);
    assert.deepEqual(events, ["start", "fail:1"]);
  }
  // Synthesis error on the first sentence: no start signal, fail at 0.
  {
    const c = clock(), eng = engine({ failSynth: { "One.": true } });
    const { events } = line(eng, ["One.", "Two."], c);
    await flush();
    assert.deepEqual(events, ["fail:0"]);
  }
  // Barge-in / cancel: the audio stops, one "cancel" end, nothing after.
  {
    const c = clock(), eng = engine();
    const { events, handle } = line(eng, ["One.", "Two."], c);
    await flush();
    handle.cancel();
    assert.ok(eng.log.some(([k]) => k === "stop"));
    eng.playing[0].finish(); await c.advance(1000);
    assert.deepEqual(events, ["start", "done:cancel"]);
    handle.cancel();
    assert.deepEqual(events, ["start", "done:cancel"], "cancel twice: one end");
    assert.equal(N.busy(), 0);
  }
  console.log("natural voice ok");
})().catch((e) => { console.error(e); process.exit(1); });
