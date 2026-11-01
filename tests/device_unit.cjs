// Decision log 35: tablets run, phones are gated; iPad Safari specifics. Pure checks in Node:
// no browser, microphone, network or model calls.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "..");
const D = require(path.join(root, "app/static/ui/device.js"));

// --- The gate: the smaller screen side, or a narrow window, under 700 px is a phone ---
{
  const at = (w, h, inner = w) => D.phoneSized({ screenWidth: w, screenHeight: h, innerWidth: inner });
  // iPhones, either orientation (Playwright's iPhone 13/15 and SE sizes).
  assert.equal(at(390, 844), true, "iPhone portrait");
  assert.equal(at(844, 390), true, "iPhone landscape: the smaller side still decides");
  assert.equal(at(430, 932), true, "iPhone Pro Max");
  assert.equal(at(375, 667), true, "iPhone SE");
  // iPads, either orientation, touch-only or not: iPad mini (744) and up run.
  assert.equal(at(744, 1133), false, "iPad mini portrait");
  assert.equal(at(1133, 744), false, "iPad mini landscape");
  assert.equal(at(810, 1080), false, "iPad portrait");
  assert.equal(at(820, 1180), false, "iPad Air portrait");
  assert.equal(at(1024, 1366), false, "iPad Pro 12.9 portrait");
  assert.equal(at(1366, 1024), false, "iPad Pro landscape");
  // iPadOS Safari reports the portrait screen size in landscape too; the window is wide.
  assert.equal(at(820, 1180, 1180), false);
  // Laptops; a laptop window narrowed under 700 px is gated, as is Split View that narrow.
  assert.equal(at(1440, 900), false, "laptop");
  assert.equal(at(1280, 800, 1280), false);
  assert.equal(at(1440, 900, 699), true, "narrow window");
  assert.equal(at(820, 1180, 507), true, "iPad Split View at a third");
  assert.equal(at(700, 1000), false, "700 px exactly runs");
  assert.equal(D.PHONE_MAX, 700);
}

// --- iPadOS Safari reports itself as a Mac: maxTouchPoints tells them apart ---
{
  const MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
  assert.equal(D.appleTouch({ userAgent: MAC_UA, platform: "MacIntel", maxTouchPoints: 5 }), true, "iPadOS desktop-class Safari");
  assert.equal(D.appleTouch({ userAgent: MAC_UA, platform: "MacIntel", maxTouchPoints: 0 }), false, "a real Mac");
  assert.equal(D.appleTouch({ userAgent: MAC_UA, platform: "MacIntel", maxTouchPoints: 1 }), false, "one touch point is not an iPad");
  assert.equal(D.appleTouch({ userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", platform: "iPhone", maxTouchPoints: 5 }), true);
  assert.equal(D.appleTouch({ userAgent: "Mozilla/5.0 (iPad; CPU OS 12_0 like Mac OS X)", platform: "iPad", maxTouchPoints: 5 }), true, "older iPad UA");
  assert.equal(D.appleTouch({ userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", platform: "Win32", maxTouchPoints: 10 }), false, "Windows touch laptop");
  assert.equal(D.appleTouch({ userAgent: "Mozilla/5.0 (Linux; Android 14)", platform: "Linux armv8l", maxTouchPoints: 5 }), false);
  assert.equal(D.appleTouch(), false);
}

// --- Touch-only: coarse pointer, no fine one ---
assert.equal(D.touchOnly({ coarse: true, anyFine: false }), true, "iPad on its own");
assert.equal(D.touchOnly({ coarse: true, anyFine: true }), false, "iPad with a trackpad keyboard");
assert.equal(D.touchOnly({ coarse: false, anyFine: true }), false, "laptop");

// --- The on-screen keyboard: the visible area above it ---
assert.deepEqual(D.viewportFrame(null, 900), { height: 900, top: 0, keyboard: false });
assert.deepEqual(D.viewportFrame({ height: 820, offsetTop: 0 }, 820), { height: 820, top: 0, keyboard: false });
assert.deepEqual(D.viewportFrame({ height: 418.6, offsetTop: 12.2 }, 820), { height: 419, top: 12, keyboard: true }, "keyboard open");
assert.equal(D.viewportFrame({ height: 760, offsetTop: 0 }, 820).keyboard, false, "a toolbar is not a keyboard");
assert.equal(D.viewportFrame({ height: 700, offsetTop: -3 }, 820).top, 0);
console.log("device rules ok");

// --- The mic worklet: any input rate to 16 kHz ---
{
  const { Resampler16k } = require(path.join(root, "app/static/mic-worklet.js"));
  const tone = (rate, hz, seconds, amp = 0.5) => Float32Array.from({ length: Math.round(rate * seconds) }, (_, i) => amp * Math.sin(2 * Math.PI * hz * i / rate));
  // Fed in 128-sample render quanta, as the audio thread does.
  const run = (rate, input, quantum = 128) => {
    const r = new Resampler16k(rate), out = [];
    for (let i = 0; i < input.length; i += quantum) r.push(input.subarray(i, i + quantum), out);
    return out;
  };
  const amplitude = (s) => Math.sqrt(2 * s.reduce((a, x) => a + (x / 32767) ** 2, 0) / s.length);
  const crossings = (s) => s.slice(1).filter((x, i) => (s[i] < 0) !== (x < 0)).length;
  for (const rate of [48000, 44100, 24000, 16000]) {
    const out = run(rate, tone(rate, 440, 1));
    assert.ok(Math.abs(out.length - 16000) <= 1, `${rate} Hz: one second gives 16000 samples (${out.length})`);
    assert.ok(Math.abs(crossings(out) - 880) <= 2, `${rate} Hz: 440 Hz stays 440 Hz`);
    assert.ok(Math.abs(amplitude(out.slice(100)) - 0.5) < 0.02, `${rate} Hz: speech-band level kept`);
  }
  // 16 kHz in: unchanged. A constant stays constant at any rate; chunking never matters.
  const same = tone(16000, 300, 0.1);
  assert.deepEqual(run(16000, same), Array.from(same, (x) => Math.round(x * 32767)));
  assert.ok(run(48000, new Float32Array(4800).fill(0.25)).every((x) => x === Math.round(0.25 * 32767)));
  const t = tone(44100, 1000, 0.2);
  assert.deepEqual(run(44100, t, 128), run(44100, t, 37), "same result whatever the quantum");
  // Above 8 kHz cannot be held at 16 kHz: a 15 kHz tone at 48 kHz is mostly filtered, not aliased at full level.
  assert.ok(amplitude(run(48000, tone(48000, 15000, 0.5))) < 0.25, "anti-aliased");
  // Clipped to 16-bit.
  assert.deepEqual(run(16000, Float32Array.from([2, -2])), [32767, -32767]);
}
console.log("mic resampling ok");

// --- Echo safety stays on tablets: mic muted while the interviewer speaks, unless headphones ---
{
  const T = require(path.join(root, "app/static/ui/turn-logic.js"));
  assert.equal(T.micShouldMute({ headphones: false, mutingLines: 1 }), true);
  assert.equal(T.micShouldMute({ headphones: true, mutingLines: 2 }), false, "headphones: barge-in allowed");
  assert.equal(T.micShouldMute({ headphones: false, mutingLines: 0 }), false);

  // iPad Safari's voices: no Edge Natural voice, so the best English voice; novelty voices last.
  const v = (name, lang, voiceURI = `com.apple.voice.compact.${lang}.${name}`) => ({ name, lang, voiceURI });
  const ipad = [v("Albert", "en-US", "com.apple.speech.synthesis.voice.Albert"), v("Bad News", "en-US"), v("Eddy (English (UK))", "en-GB", "com.apple.eloquence.en-GB.Eddy"),
                v("Grandma", "en-GB", "com.apple.eloquence.en-GB.Grandma"), v("Arthur", "en-GB"), v("Daniel", "en-GB"), v("Samantha", "en-US"),
                v("Zarvox", "en-US"), v("Amélie", "fr-CA"), v("Karen", "en-AU")];
  const ranked = T.rankVoices(ipad).map((x) => x.name);
  assert.deepEqual(ranked.slice(0, 4), ["Arthur", "Daniel", "Samantha", "Karen"], "real voices first, British first");
  assert.deepEqual(new Set(ranked.slice(4)), new Set(["Albert", "Bad News", "Eddy (English (UK))", "Grandma", "Zarvox"]), "novelty last");
  assert.equal(T.onlyRobotic(ipad), false);
  // A downloaded Enhanced voice beats the compact ones.
  assert.equal(T.rankVoices([...ipad, v("Serena (Enhanced)", "en-GB", "com.apple.voice.enhanced.en-GB.Serena")])[0].name, "Serena (Enhanced)");
  // Still Edge Natural first where it exists, and a Mac's own voices stay ordinary.
  assert.equal(T.voiceTier({ name: "Alex", voiceURI: "com.apple.speech.synthesis.voice.Alex" }), 2);
  assert.equal(T.voiceTier({ name: "Freddie", voiceURI: "Freddie" }), 2, "only the exact novelty names");
}
console.log("tablet voice ok");

// --- ui.js in a fake page: the gate, and the speech unlock inside a tap ---
function page({ screen, innerWidth, coarse = false, anyFine = true, desktopOnly = "true", navigator = {} }) {
  const listeners = {}, spoken = [];
  const body = { dataset: { desktopOnly } };
  const header = { after(el) { body.gate = el; } };
  const document = {
    body, documentElement: { classList: { add(c) { body.gated = c; } }, getAttribute: () => null, setAttribute() {} },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    querySelector: (sel) => (sel === ".shell > header" ? header : null), querySelectorAll: () => [],
    getElementById: () => ({ addEventListener() {} }), createElement: () => ({}),
  };
  const matchMedia = (q) => ({ matches: q === "(pointer: coarse)" ? coarse : q === "(any-pointer: fine)" ? anyFine : false });
  class SpeechSynthesisUtterance { constructor(text) { this.text = text; this.volume = 1; } }
  const window = { innerWidth, UBDevice: D, speechSynthesis: { speak: (u) => spoken.push(u), getVoices: () => [] }, SpeechSynthesisUtterance };
  const context = { window, document, screen, navigator, matchMedia, location: { href: "https://x/ui/interview", reload() {} },
                    localStorage: { getItem: () => null, setItem() {} }, addEventListener() {}, CustomEvent: class {}, speechSynthesis: window.speechSynthesis,
                    SpeechSynthesisUtterance };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, "app/static/ui/ui.js"), "utf8"), context);
  (listeners.DOMContentLoaded || []).forEach((fn) => { try { fn(); } catch { /* the rest of the page is not faked */ } });
  return { UB: window.UB, body, spoken };
}
{
  const iPad = page({ screen: { width: 820, height: 1180 }, innerWidth: 820, coarse: true, anyFine: false,
                      navigator: { userAgent: "Macintosh", platform: "MacIntel", maxTouchPoints: 5 } });
  assert.equal(iPad.UB.desktopOnly(), false, "a touch-only iPad runs");
  assert.equal(iPad.body.gate, undefined, "no gate screen");
  assert.equal(iPad.UB.appleTouch(), true);
  assert.equal(iPad.UB.touchOnly(), true);
  const phone = page({ screen: { width: 390, height: 844 }, innerWidth: 390, coarse: true, anyFine: false });
  assert.equal(phone.UB.desktopOnly(), true, "a phone is gated");
  assert.match(phone.body.gate.innerHTML, /Open this on a laptop or tablet/);
  assert.doesNotMatch(phone.body.gate.innerHTML, /desktop/i);
  const sideways = page({ screen: { width: 390, height: 844 }, innerWidth: 844, coarse: true, anyFine: false });
  assert.equal(sideways.UB.desktopOnly(), true, "a phone on its side is still gated");
  assert.equal(page({ screen: { width: 1440, height: 900 }, innerWidth: 1440 }).UB.desktopOnly(), false, "laptop");
  assert.equal(page({ screen: { width: 390, height: 844 }, innerWidth: 390, desktopOnly: "false" }).UB.desktopOnly(), false, "the landing page is never gated");

  // The first utterance, started inside the Start tap: silent, and only once.
  iPad.UB.unlockSpeech(); iPad.UB.unlockSpeech();
  assert.equal(iPad.spoken.length, 1);
  assert.equal(iPad.spoken[0].volume, 0);
  assert.equal(iPad.spoken[0].text.trim(), "");
}
console.log("tablet gate ok");
