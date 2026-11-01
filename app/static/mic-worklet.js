/* Resample microphone floats to paced 80 ms frames of 16 kHz little-endian PCM.
   The input rate is whatever the audio context runs at: 48 kHz on most iPads and Macs,
   44.1 kHz or 48 kHz elsewhere. Each output sample is the average of the input it covers
   (fractional edges weighted), which also filters out what 16 kHz cannot hold, instead of
   picking points and aliasing. State carries across render quanta, so chunk size never
   changes the result. */
class Resampler16k {
  constructor(inputRate, outputRate = 16000) {
    this.ratio = inputRate / outputRate;  // input samples per output sample
    this.sum = 0; this.filled = 0;
  }
  // Floats in; Int16 sample values out (an array of numbers).
  push(input, out = []) {
    const ratio = this.ratio;
    for (let i = 0; i < input.length; i++) {
      const x = input[i];
      let left = 1;  // this input sample's weight still to place
      while (left > 1e-9) {
        const take = Math.min(left, ratio - this.filled);
        this.sum += x * take; this.filled += take; left -= take;
        if (this.filled >= ratio - 1e-9) {
          const value = this.sum / ratio;
          out.push(Math.round(Math.max(-1, Math.min(1, value)) * 32767));
          this.sum = 0; this.filled = 0;
        }
      }
    }
    return out;
  }
}

if (typeof AudioWorkletProcessor !== 'undefined') {
  class MicPCM extends AudioWorkletProcessor {
    constructor() {
      super();
      this.resampler = new Resampler16k(sampleRate);
      this.pending = []; this.muted = false; this.running = true;
      this.port.onmessage = ({data}) => {
        if (data.type === 'mute') this.muted = data.value;
        if (data.type === 'flush') {
          this.emit(true);
          this.port.postMessage({type: 'flushed'});
        }
      };
    }
    emit(flush = false) {
      while (this.pending.length >= 1280 || (flush && this.pending.length)) {
        const count = Math.min(1280, this.pending.length);
        const buffer = new ArrayBuffer(count * 2);
        const view = new DataView(buffer);
        for (let i = 0; i < count; i++) view.setInt16(i * 2, this.pending[i], true);
        this.pending.splice(0, count);
        this.port.postMessage({type: 'pcm', buffer}, [buffer]);
      }
    }
    process(inputs) {
      if (!this.running) return true;
      const input = inputs[0]?.[0];
      if (!input) return true;
      this.resampler.push(this.muted ? new Float32Array(input.length) : input, this.pending);
      this.emit();
      return true;
    }
  }
  registerProcessor('mic-pcm', MicPCM);
}

if (typeof module !== 'undefined') module.exports = {Resampler16k};
