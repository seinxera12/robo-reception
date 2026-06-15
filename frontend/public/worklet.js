// frontend/worklet.js
//
// Captures microphone audio, resamples to 16kHz, and sends 30ms Int16 PCM
// chunks to the main thread regardless of the AudioContext's native sample rate.
//
// Most browsers honour AudioContext({ sampleRate: 16000 }) only as a hint and
// will run at their native rate (44100 or 48000 Hz). Without explicit resampling
// here, the VAD and STT on the backend receive audio at the wrong rate and fail
// silently — VAD never fires because the spectral content is wrong.

const TARGET_RATE   = 16000;
const CHUNK_SAMPLES = 480;          // 30ms at 16kHz  (matches VAD CHUNK_SAMPLES)
const CHUNK_BYTES   = CHUNK_SAMPLES * 2;  // Int16 = 2 bytes/sample

class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    // Resampler state
    this._ratio        = 1.0;        // updated on first process()
    this._inputBuffer  = new Float32Array(0);
    this._resampPos    = 0.0;        // fractional read position into inputBuffer

    // Output accumulator — filled with resampled 16kHz float32 samples
    this._outBuffer  = new Float32Array(CHUNK_SAMPLES);
    this._outOffset  = 0;
  }

  process(inputs) {
    const input = inputs[0][0];   // mono channel, float32
    if (!input || input.length === 0) return true;

    // Determine resample ratio on first real frame
    // sampleRate is a global provided by the AudioWorkletGlobalScope
    if (this._ratio === 1.0 && sampleRate !== TARGET_RATE) {
      this._ratio = sampleRate / TARGET_RATE;  // e.g. 44100/16000 = 2.75625
    } else if (this._ratio === 1.0) {
      this._ratio = 1.0;  // already 16kHz — no resampling needed
    }

    // Append incoming frame to input ring buffer
    const combined = new Float32Array(this._inputBuffer.length + input.length);
    combined.set(this._inputBuffer);
    combined.set(input, this._inputBuffer.length);
    this._inputBuffer = combined;

    // Consume input samples, produce TARGET_RATE output via linear interpolation
    while (this._resampPos + 1 < this._inputBuffer.length) {
      const i0  = Math.floor(this._resampPos);
      const i1  = i0 + 1;
      const frac = this._resampPos - i0;

      // Linear interpolation between adjacent samples
      const sample = this._inputBuffer[i0] * (1 - frac) + this._inputBuffer[i1] * frac;

      this._outBuffer[this._outOffset++] = sample;

      if (this._outOffset === CHUNK_SAMPLES) {
        // 30ms chunk ready — convert float32 → int16 and post
        const int16 = new Int16Array(CHUNK_SAMPLES);
        for (let i = 0; i < CHUNK_SAMPLES; i++) {
          const s = Math.max(-1, Math.min(1, this._outBuffer[i]));
          int16[i] = s < 0 ? s * 32768 : s * 32767;
        }
        this.port.postMessage(int16.buffer.slice(0));
        this._outOffset = 0;
      }

      this._resampPos += this._ratio;
    }

    // Keep only the unconsumed tail of the input buffer
    const consumed = Math.floor(this._resampPos);
    this._inputBuffer = this._inputBuffer.slice(consumed);
    this._resampPos  -= consumed;

    return true;
  }
}

registerProcessor("pcm-capture", PCMCapture);
