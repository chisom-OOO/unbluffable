// Natural voice (beta), decision logs 43-44: Kokoro runs in this worker on WebGPU, never on the
// page's main thread (synthesis there would freeze the interview while a sentence is made). The page
// sends the pins and then one sentence at a time; this sends back the samples, or an error.
// No text leaves the browser: the only network use is the pinned library and model downloads.
let pin = null, tts = null;

const b64 = (buffer) => btoa(String.fromCharCode(...new Uint8Array(buffer)));
const hex = (buffer) => [...new Uint8Array(buffer)].map((x) => x.toString(16).padStart(2, "0")).join("");

// Kokoro's own files only: fetched from the pinned commit, and the model and voice checked
// against their SHA-256 before kokoro-js (or its cache) gets them. Everything else is untouched.
function pinFetch() {
  const original = self.fetch.bind(self);
  const main = `https://huggingface.co/${pin.model}/resolve/main/`;
  const pinned = `https://huggingface.co/${pin.model}/resolve/${pin.revision}/`;
  self.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input?.url;
    if (typeof url !== "string" || !url.startsWith(main)) return original(input, init);
    const file = url.slice(main.length);
    const response = await original(pinned + file, { credentials: "omit" });
    const want = pin.sha256[file];
    if (!response.ok || !want) return response;
    const bytes = await response.arrayBuffer();
    if (hex(await crypto.subtle.digest("SHA-256", bytes)) !== want) throw new Error("Natural voice failed its integrity check.");
    return new Response(bytes, { status: 200, headers: { "Content-Type": response.headers.get("Content-Type") || "application/octet-stream",
                                                        "Content-Length": String(bytes.byteLength) } });
  };
}

async function load() {
  pinFetch();
  const response = await fetch(pin.bundle, { credentials: "omit" });
  if (!response.ok) throw new Error("The natural voice could not be downloaded.");
  const bytes = await response.arrayBuffer();
  if (b64(await crypto.subtle.digest("SHA-384", bytes)) !== pin.bundleSha384) throw new Error("Natural voice failed its integrity check.");
  const url = URL.createObjectURL(new Blob([bytes], { type: "text/javascript" }));
  let kokoro;
  try { kokoro = await import(url); } finally { URL.revokeObjectURL(url); }
  tts = await kokoro.KokoroTTS.from_pretrained(pin.model, { dtype: pin.dtype, device: pin.device });
  const first = await tts.generate("Ready.", { voice: pin.voice });  // compiles the model now
  if (!first?.audio?.length || first.audio.some((x) => !Number.isFinite(x))) throw new Error("The natural voice produced no sound.");
}

self.onmessage = async ({ data }) => {
  if (data.type === "load") {
    pin = data.pin;
    try { await load(); self.postMessage({ type: "ready", device: pin.device }); }
    catch (error) { self.postMessage({ type: "failed", message: String(error?.message || error).slice(0, 200) }); }
    return;
  }
  if (data.type === "synth") {
    try {
      const clip = await tts.generate(data.text, { voice: pin.voice });
      const samples = clip.audio instanceof Float32Array ? clip.audio : Float32Array.from(clip.audio);
      if (!samples.length || samples.some((x) => !Number.isFinite(x))) throw new Error("no sound");
      self.postMessage({ type: "clip", id: data.id, audio: samples, rate: clip.sampling_rate }, [samples.buffer]);
    } catch {
      self.postMessage({ type: "clip_failed", id: data.id });
    }
  }
};
