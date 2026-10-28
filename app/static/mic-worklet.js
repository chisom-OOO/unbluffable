/* Downsample microphone floats to paced 80 ms frames of 16 kHz little-endian PCM. */
class MicPCM extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples = []; this.position = 0; this.pending = []; this.muted = false; this.running = true;
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
    for (const value of input) this.samples.push(this.muted ? 0 : value);
    const ratio = sampleRate / 16000;
    while (this.position + 1 < this.samples.length) {
      const index = Math.floor(this.position), mix = this.position - index;
      const value = this.samples[index] * (1 - mix) + this.samples[index + 1] * mix;
      this.pending.push(Math.round(Math.max(-1, Math.min(1, value)) * 32767));
      this.position += ratio;
    }
    const consumed = Math.floor(this.position);
    this.samples.splice(0, consumed); this.position -= consumed;
    this.emit();
    return true;
  }
}
registerProcessor('mic-pcm', MicPCM);
