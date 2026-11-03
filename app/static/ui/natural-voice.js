// Natural voice (beta), decision logs 43-44: Kokoro-82M via kokoro-js, run only in this browser,
// on WebGPU (fp16). Off by default; off means the browser voice, unchanged. Without WebGPU the
// switch is hidden and nothing is downloaded.
// No text is sent to any server for speech: the only network use is downloading the pinned
// library (jsDelivr) and the pinned model and voice (Hugging Face), which the browser caches.
//
// The page (interview.js) keeps one speaking path: a natural line reports the same start and
// end as a browser utterance, so "Speaking", the mic mute, barge-in and the silence timer are
// unchanged. If anything fails, the browser voice takes over for the rest of the session.
(function () {
  const PIN = {
    kokoro: "1.2.1",
    bundle: "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/dist/kokoro.web.js",
    bundleSha384: "suR1TeKe6Fe8fT0n/uTWoohnPJrp1zu3z0bj4VH2anmmq739wlmFSnMFJyMYszAC",
    model: "onnx-community/Kokoro-82M-v1.0-ONNX",
    revision: "1939ad2a8e416c0acfeecc08a694d14ef25f2231",
    // Decision log 44: the 163 MB fp16 model on WebGPU, never the 326 MB fp32. Measured 3 Nov in
    // Edge on an Intel Iris Xe laptop: 3.9 s to make an 8 s sentence (8-bit took 22-26 s).
    dtype: "fp16",
    device: "webgpu",
    voice: "af_heart",
    // Hugging Face's LFS SHA-256 at that revision; checked before the files are used.
    sha256: {
      "onnx/model_fp16.onnx": "ba4527a874b42b21e35f468c10d326fdff3c7fc8cac1f85e9eb6c0dfc35c334a",
      "voices/af_heart.bin": "d583ccff3cdca2f7fae535cb998ac07e9fcb90f09737b9a41fa2734ec44a8f0b",
    },
  };
  const STORE_KEY = "ub-natural-voice";
  const START_TIMEOUT_MS = 20000;    // the model must be ready 20 s after Start
  const SENTENCE_TIMEOUT_MS = 8000;  // a sentence not ready by then counts as failing to play
  const PROGRESS_LINE = "Downloading natural voice (first time only)…";
  const FALLBACK_LINE = "Natural voice didn't load, so the interviewer is using your browser's voice.";
  const READY_LINE = "Natural voice ready. It runs in this browser.";

  const HF = "https://huggingface.co/";
  const MAIN = `${HF}${PIN.model}/resolve/main/`;
  const PINNED = `${HF}${PIN.model}/resolve/${PIN.revision}/`;
  // kokoro-js asks for Kokoro's files at "main"; they are fetched from the pinned commit instead.
  const pinnedUrl = (url) => (typeof url === "string" && url.startsWith(MAIN) ? PINNED + url.slice(MAIN.length) : null);

  // ---------- The switch and the fallback (pure: engine, storage and timers are injected) ----------
  function createController({ loadEngine, store, setTimer = setTimeout, clearTimer = clearTimeout, onNotice = () => {} }) {
    const remembered = store.get(STORE_KEY) === "on";
    let enabled = remembered;
    let available = null;        // WebGPU: null until checked, then true or false (decision log 44)
    let state = "off";           // off | loading | ready | failed
    let engine = null, fellBack = false, startTimer = null;

    const fallBack = () => {
      if (fellBack) return;
      fellBack = true;
      clearTimer(startTimer);
      onNotice("fallback", FALLBACK_LINE);
    };
    const load = () => {
      if (state !== "off" || available !== true) return;
      state = "loading";
      onNotice("progress", PROGRESS_LINE);
      let loading;
      try { loading = Promise.resolve(loadEngine()); } catch (error) { loading = Promise.reject(error); }
      loading.then((e) => {
        engine = e; state = "ready";
        if (!fellBack) onNotice("ready", READY_LINE);
      }, () => {
        state = "failed";
        if (enabled) fallBack();
      });
    };
    return {
      enabled: () => enabled,
      available: () => available,
      // Without WebGPU the page hides the switch; a remembered "on" is kept but does nothing here.
      setAvailable(yes) {
        available = !!yes;
        if (!available) { enabled = false; onNotice("unavailable", ""); return; }
        enabled = remembered || enabled;
        onNotice("available", "");
        if (enabled) load();
      },
      state: () => state,
      engine: () => engine,
      usable: () => enabled && state === "ready" && !fellBack,
      setEnabled(on) {
        if (available !== true) return;
        enabled = !!on;
        store.set(STORE_KEY, enabled ? "on" : "off");
        if (!enabled) { onNotice("off", ""); return; }
        if (state === "failed" || fellBack) { onNotice("fallback", FALLBACK_LINE); return; }
        if (state === "ready") onNotice("ready", READY_LINE);
        load();
      },
      // Start was pressed: the model has 20 s to be ready; the download itself is never cut off.
      started() {
        if (!enabled || available !== true || state === "ready" || fellBack || startTimer) return;
        if (state === "failed") { fallBack(); return; }
        startTimer = setTimer(() => { if (state !== "ready") fallBack(); }, START_TIMEOUT_MS);
      },
      lineFailed: fallBack,
    };
  }

  // ---------- One spoken line, sentence by sentence ----------
  let active = 0;  // natural lines in progress: speech is pending even before the first audio
  const busy = () => active;

  // `engine.synth(text)` resolves to a clip; `engine.play(clip)` returns { started, done, stop }.
  // onStart once, when the first sentence plays; onDone("end") after the last, or ("cancel");
  // onFail(i) instead when sentence i can't be made in time or fails to play.
  function speakLine(engine, parts, { pauseMs = 0, setTimer = setTimeout, clearTimer = clearTimeout, onStart, onDone, onFail }) {
    let over = false, current = null, pause = null, startedOnce = false;
    active++;
    const close = () => { if (over) return false; over = true; active = Math.max(0, active - 1); clearTimer(pause); return true; };
    const synth = (i) => {
      let timer = null;
      const made = new Promise((resolve, reject) => {
        timer = setTimer(() => reject(new Error("sentence timed out")), SENTENCE_TIMEOUT_MS);
        Promise.resolve().then(() => engine.synth(parts[i])).then(resolve, reject);
      });
      made.then(() => clearTimer(timer), () => clearTimer(timer));
      made.catch(() => {});  // handled where it is awaited
      return made;
    };
    const fail = (i) => { if (close()) onFail(i); };

    (async () => {
      let pending = parts.length ? synth(0) : null;
      for (let i = 0; i < parts.length; i++) {
        let clip;
        try { clip = await pending; } catch { fail(i); return; }
        if (over) return;
        pending = i + 1 < parts.length ? synth(i + 1) : null;  // the next sentence is made while this one plays
        try {
          current = engine.play(clip);
          await current.started;
          if (over) return;
          if (!startedOnce) { startedOnce = true; onStart(); }
          await current.done;
        } catch { fail(i); return; }
        current = null;
        if (over) return;
        if (i + 1 < parts.length && pauseMs > 0) await new Promise((r) => { pause = setTimer(r, pauseMs); });
        if (over) return;
      }
      if (close()) onDone("end");
    })();

    return {
      cancel() {
        if (!close()) return;
        try { current?.stop(); } catch { /* already stopped */ }
        onDone("cancel");
      },
    };
  }

  const exported = { PIN, STORE_KEY, START_TIMEOUT_MS, SENTENCE_TIMEOUT_MS, PROGRESS_LINE, FALLBACK_LINE, READY_LINE,
                     pinnedUrl, createController, speakLine, busy };
  if (typeof module !== "undefined") {
    module.exports = exported;
    return;
  }

  // ---------- The browser: a worker downloads, checks and runs Kokoro; the page only plays ----------
  // The worker's URL carries this script's ?v= (app.pages), so a deploy never pairs old and new.
  const WORKER = "/ui-static/natural-voice-worker.js" + (document.currentScript?.src.match(/\?v=[^&#]+/)?.[0] || "");

  let audio = null;  // one AudioContext, resumed inside the Start tap
  const context = () => (audio = audio || new (window.AudioContext || window.webkitAudioContext)());

  function play(clip) {
    const ctx = context();
    if (ctx.state !== "running") throw new Error("Audio is not running.");
    const samples = clip.audio, rate = clip.sampling_rate;
    const buffer = ctx.createBuffer(1, samples.length, rate);
    buffer.copyToChannel(samples, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    let guard = null, stop = () => {};
    const done = new Promise((resolve) => {
      source.onended = () => { clearTimeout(guard); resolve(); };
      // Like the browser voice's guard: never hold the mic muted past the clip's length plus 2 s.
      guard = setTimeout(resolve, (samples.length / rate) * 1000 + 2000);
      stop = () => { clearTimeout(guard); try { source.stop(); } catch { /* not started */ } resolve(); };
    });
    source.start();
    return { started: Promise.resolve(), done, stop: () => stop() };
  }

  function loadEngine() {
    return new Promise((resolve, reject) => {
      const worker = new Worker(WORKER, { type: "module" });
      const waiting = new Map();
      let id = 0;
      const synth = (text) => new Promise((ok, fail) => {
        const n = ++id;
        waiting.set(n, { ok, fail });
        worker.postMessage({ type: "synth", id: n, text });
      });
      worker.onmessage = ({ data }) => {
        if (data.type === "ready") resolve({ synth, play, device: data.device });
        else if (data.type === "failed") { reject(new Error(data.message)); worker.terminate(); }
        else if (data.type === "clip" || data.type === "clip_failed") {
          const w = waiting.get(data.id);
          waiting.delete(data.id);
          if (data.type === "clip") w?.ok({ audio: data.audio, sampling_rate: data.rate });
          else w?.fail(new Error("Natural voice could not make that sentence."));
        }
      };
      worker.onerror = () => {
        reject(new Error("The natural voice worker stopped."));
        for (const w of waiting.values()) w.fail(new Error("stopped"));
        waiting.clear();
      };
      worker.postMessage({ type: "load", pin: PIN });
    });
  }

  const listeners = new Set();
  let last = null;  // a remembered "on" starts loading before the page listens: replay the latest notice
  const controller = createController({
    loadEngine,
    store: window.UB?.store || { get: () => null, set: () => {} },
    onNotice: (kind, text) => { last = [kind, text]; for (const fn of listeners) fn(kind, text); },
  });

  // Decision log 44: offered only with a WebGPU adapter (and a worker, audio and crypto to run it).
  (async () => {
    const basics = !!(window.Worker && window.crypto?.subtle && (window.AudioContext || window.webkitAudioContext));
    let adapter = null;
    try { adapter = basics && navigator.gpu ? await navigator.gpu.requestAdapter() : null; } catch { adapter = null; }
    controller.setAvailable(!!adapter);
  })();

  window.UBNatural = {
    ...exported,
    controller,
    onNotice: (fn) => { listeners.add(fn); if (last) fn(...last); },
    available: controller.available,
    enabled: controller.enabled,
    usable: controller.usable,
    setEnabled: controller.setEnabled,
    lineFailed: controller.lineFailed,
    // Inside the Start tap: resume audio (a user gesture), then the 20 s count.
    started() {
      if (controller.enabled()) { try { context().resume(); } catch { /* fallback handles it */ } }
      controller.started();
    },
    speakLine: (parts, options) => speakLine(controller.engine(), parts, options),
    device: () => controller.engine()?.device || null,
  };
})();
