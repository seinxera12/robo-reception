import { useEffect, useRef, useCallback } from "react";
import { useRoboState } from "./useRoboState";
import IdleState from "./states/IdleState";
import ListeningState from "./states/ListeningState";
import ThinkingState from "./states/ThinkingState";
import SpeakingState from "./states/SpeakingState";
import WayfindingState from "./states/WayfindingState";
import StatusBadges from "./components/StatusBadges";

const KIOSK_ID = "kiosk-01";
const MIC_SAMPLE_RATE = 16000;
const TTS_SAMPLE_RATE = 24000;

export default function App() {
  const [state, dispatch] = useRoboState();
  const wsRef = useRef(null);
  const audioCtxRef = useRef(null);
  const playbackQueueRef = useRef([]);
  const isPlayingRef = useRef(false);
  
  // Refs for tracking state values inside event listeners
  const pttStateRef = useRef(state.pttState);
  const uiStateRef = useRef(state.uiState);
  
  useEffect(() => {
    pttStateRef.current = state.pttState;
    uiStateRef.current = state.uiState;
  }, [state.pttState, state.uiState]);

  // ── UI update from WebSocket frame ──────────────────────────────────────
  const handleUIUpdate = useCallback((msg) => {
    if (msg.event === "checkin_complete") {
      dispatch({ type: "SET_BADGE", badge: "checkedIn" });
    } else if (msg.event === "notification_sent") {
      dispatch({ type: "SET_BADGE", badge: "hostNotified" });
    } else if (msg.event === "host_acknowledged") {
      dispatch({ type: "SET_BADGE", badge: "hostAcknowledged" });
    }
  }, [dispatch]);

  // ── Play next audio buffer in queue ─────────────────────────────────────
  const playNext = useCallback(() => {
    if (playbackQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      return;
    }
    isPlayingRef.current = true;
    const arrayBuffer = playbackQueueRef.current.shift();

    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0;
    }

    const audioCtx = audioCtxRef.current;
    if (!audioCtx) return;
    
    // Create AudioBuffer at TTS sample rate (24kHz)
    const buffer = audioCtx.createBuffer(1, float32.length, TTS_SAMPLE_RATE);
    buffer.copyToChannel(float32, 0);

    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(audioCtx.destination);
    source.onended = playNext;
    source.start();
  }, []);

  // ── WebSocket message handler ──────────────────────────────────────────
  const handleMessage = useCallback((event) => {
    if (typeof event.data === "string") {
      const msg = JSON.parse(event.data);

      switch (msg.type) {
        case "state":
          dispatch({ type: "SET_STATE", state: msg.state });
          break;
        case "transcript":
          dispatch({ type: "SET_TRANSCRIPT", text: msg.text });
          break;
        case "response":
          dispatch({ type: "SET_RESPONSE", text: msg.text });
          break;
        case "ui_update":
          handleUIUpdate(msg);
          break;
        case "wayfinding":
          dispatch({
            type: "SET_ROUTE",
            route: msg.route,
            floor_changes: msg.floor_changes,
          });
          break;
        case "audio_end":
          // Queue drains naturally, state changes are handled by the 'state' frame
          break;
      }
    } else {
      // Binary audio chunk (synthesised TTS from Kokoro)
      playbackQueueRef.current.push(event.data);
      if (!isPlayingRef.current) playNext();
    }
  }, [dispatch, handleUIUpdate, playNext]);

  // ── Connect & initialize audio on mount ──────────────────────────────────
  useEffect(() => {
    let active = true;
    let ws = null;
    let worklet = null;
    let mediaStream = null;

    const connect = async () => {
      // Create session via POST request to align sessionUuid
      let sessionUuid = null;
      try {
        const sessionRes = await fetch(`/chat/${KIOSK_ID}/session`, { method: "POST" });
        if (sessionRes.ok) {
          const sessionData = await sessionRes.json();
          sessionUuid = sessionData.session_uuid;
        }
      } catch (err) {
        console.warn("Could not pre-initialize session UUID, falling back to server-generated session", err);
      }

      if (!active) return;

      // ── 1. Connect WebSocket FIRST (independent of audio) ──────────────
      const wsUrl = sessionUuid
        ? `ws://${window.location.host}/ws/voice/${KIOSK_ID}?session_uuid=${encodeURIComponent(sessionUuid)}`
        : `ws://${window.location.host}/ws/voice/${KIOSK_ID}`;
      
      ws = new WebSocket(wsUrl);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onmessage = handleMessage;
      
      ws.onclose = () => {
        if (active) {
          dispatch({ type: "SET_STATE", state: "idle" });
        }
      };

      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
      };

      // Wait for WebSocket to open before wiring audio
      await new Promise((resolve, reject) => {
        ws.addEventListener("open", resolve, { once: true });
        ws.addEventListener("error", reject, { once: true });
      });

      if (!active) return;

      // ── 2. Initialize AudioContext + mic ────────────────────────────────
      const audioCtx = new AudioContext({ sampleRate: MIC_SAMPLE_RATE });
      audioCtxRef.current = audioCtx;
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      // Initialize microphone stream
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: MIC_SAMPLE_RATE,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        }
      });

      if (!active) return;

      const source = audioCtx.createMediaStreamSource(mediaStream);

      // Resolve worklet path: Vite dev serves public/ at root, production uses /static/
      const workletPath = import.meta.env.DEV ? "/worklet.js" : "/static/worklet.js";
      await audioCtx.audioWorklet.addModule(workletPath);
      if (!active) return;

      worklet = new AudioWorkletNode(audioCtx, "pcm-capture");
      source.connect(worklet);

      // Worklet forwards audio chunks only when pttState === "recording"
      worklet.port.onmessage = (e) => {
        if (ws && ws.readyState === WebSocket.OPEN && pttStateRef.current === "recording") {
          ws.send(e.data);

          // Calculate RMS level for UI waveform feedback
          const int16 = new Int16Array(e.data);
          const rms = Math.sqrt(
            int16.reduce((sum, s) => sum + (s / 32768) ** 2, 0) / int16.length
          );
          dispatch({ type: "SET_AUDIO_LEVEL", level: Math.min(rms * 5, 1) });
        }
      };
    };

    connect().catch((err) => {
      console.error("Connection setup failed:", err);
    });

    return () => {
      active = false;
      if (ws) ws.close();
      if (worklet) worklet.disconnect();
      if (audioCtxRef.current) audioCtxRef.current.close();
      if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());
    };
  }, [handleMessage, dispatch]);

  // ── PTT Interaction Toggles ───────────────────────────────────────────────
  const handlePttToggle = () => {
    if (state.pttState === "idle") {
      dispatch({ type: "START_RECORDING" });
    } else if (state.pttState === "recording") {
      dispatch({ type: "CANCEL_RECORDING" });
    }
  };

  // ── Render current state component ────────────────────────────────────────
  const stateComponents = {
    idle: (
      <IdleState 
        onPttToggle={handlePttToggle} 
        pttState={state.pttState} 
      />
    ),
    listening: (
      <ListeningState 
        onPttToggle={handlePttToggle} 
        audioLevel={state.audioLevel} 
      />
    ),
    thinking: (
      <ThinkingState 
        response={state.response} 
      />
    ),
    speaking: (
      <SpeakingState 
        response={state.response} 
        transcript={state.transcript} 
      />
    ),
    wayfinding: (
      <WayfindingState
        route={state.route}
        currentFloor={state.currentFloor}
        onFloorChange={(f) => dispatch({ type: "SET_FLOOR", floor: f })}
        onClose={() => dispatch({ type: "SET_STATE", state: "idle" })}
        onPttToggle={handlePttToggle}
        pttState={state.pttState}
      />
    ),
  };

  return (
    <div style={{
      width: "100vw", height: "100vh",
      background: "radial-gradient(circle at center, #0f172a 0%, #020617 100%)", 
      color: "white",
      display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center",
      fontFamily: "'Outfit', 'Inter', sans-serif",
      overflow: "hidden",
      position: "relative",
    }}>
      {stateComponents[state.uiState] ?? stateComponents.idle}
      <StatusBadges badges={state.badges} />
    </div>
  );
}
