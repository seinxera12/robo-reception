// frontend/worklet.js
class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Int16Array(480); // 30ms at 16kHz
    this._offset = 0;
  }

  process(inputs) {
    const input = inputs[0][0]; // mono channel, float32
    if (!input) return true;

    for (let i = 0; i < input.length; i++) {
      // float32 → int16
      const s = Math.max(-1, Math.min(1, input[i]));
      this._buffer[this._offset++] = s < 0 ? s * 32768 : s * 32767;

      if (this._offset === 480) {
        // Send 30ms chunk to main thread
        this.port.postMessage(this._buffer.buffer.slice(0));
        this._offset = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PCMCapture);