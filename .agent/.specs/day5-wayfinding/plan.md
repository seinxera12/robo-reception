Reiteration of Understanding Before Day 5
What's Done So Far
Day 1: Infrastructure foundation. Docker Compose, SQLAlchemy 2.0 async models, Alembic with pg_trgm, pydantic-settings, idempotent seed data, /health endpoint with real checks.
Day 2: Full voice pipeline. Lazy ML imports inside load functions. asyncio.to_thread for CPU-bound loading. HF_HUB_OFFLINE=1 for Kokoro. VADProcessor per-connection stateful class with reset_states(). Sentence-by-sentence TTS streaming. AudioWorklet at 16kHz. Session manager in Redis.
Day 3: PydanticAI agent replacing hardcoded response. @agent.tool with lazy module registration via _register_tools(). RunContext[RoboDeps] for dependency injection into tools. AsyncSessionLocal() opened directly in tools. Three read tools working: lookup_appointment (pg_trgm, 0.3 SQL / 0.45 Python threshold), check_availability, get_info (faq.json, zero DB).
Day 4: Write tools and notification round-trip. update_checkin_status writing to PostgreSQL. notify_host via direct httpx POST to ntfy with action buttons. list_hosts with LEFT JOIN on availability slots. /acknowledge/{appointment_id} endpoint writing to DB and publishing Redis pub/sub event. Two concurrent async tasks in WebSocket handler — audio_loop as main task, redis_listener as background create_task cancelled on disconnect. Redis added to RoboDeps for tool-level event publishing. ngrok for public acknowledge URL.
What Day 4 Left Incomplete

get_directions tool not yet implemented — wayfinding module empty
building_graph.json not yet written
SVG floor plans not yet created
Frontend still plain HTML from Day 2 — no React, no state machine, no wayfinding UI
Status badges wired with JS class toggling but no proper state machine driving them
The wayfinding UI state exists in spec but has no implementation

What Day 5 Must Deliver
Day 5 is the biggest visual day. Two parallel tracks: the last tool (get_directions with NetworkX), and the complete React frontend replacing the Day 2 plain HTML test page. By end of day the kiosk should look and feel like a real product — all 5 UI states rendering correctly, SVG floor plan with animated route highlighting, and status badges updating in real time from WebSocket events. This is the day a non-technical person would watch a demo and believe in it.

Day 5 — Frontend State Machine + Wayfinding UI
What You're Actually Proving Today

Does the React state machine correctly transition through all 5 states driven purely by WebSocket frames — no manual intervention?
Does the SVG floor plan highlight the correct route path when get_directions runs?
Do the three status badges (Checked In, Host Notified, Host On Their Way) light up in sequence driven by real events?
Does the UI feel like a kiosk — touch-optimised, full screen, no browser chrome artifacts?


Mental Model: State Machine Architecture
The entire frontend is a single state machine. Every WebSocket frame is an event that drives a transition. No component manages its own state independently — everything flows through one reducer:
WebSocket Frame → dispatch(action) → reducer → new state → UI re-renders

States:
  idle        → avatar, tap/speak prompt
  listening   → waveform animation, VAD level meter
  thinking    → processing spinner, contextual message
  speaking    → response text, word highlight, audio playing
  wayfinding  → SVG floor plan, animated route highlight

Transitions driven by frame type:
  {type: "state", state: "listening"}   → SET_STATE listening
  {type: "state", state: "thinking"}    → SET_STATE thinking
  {type: "state", state: "speaking"}    → SET_STATE speaking
  {type: "transcript", text: "..."}     → SET_TRANSCRIPT
  {type: "response", text: "..."}       → SET_RESPONSE
  {type: "audio_end"}                   → audio queue drains → back to idle
  {type: "ui_update", event: "..."}     → SET_BADGE / SET_STATE wayfinding
  {type: "wayfinding", route: [...]}    → SET_ROUTE + SET_STATE wayfinding
One reducer, one useReducer, all state in one place. This is intentional — on a kiosk with a single user session, shared global state is simpler and more reliable than component-local state scattered across the tree.

New Dependencies for Day 5
bash# Frontend — initialise React project inside frontend/
cd frontend
npm create vite@latest . -- --template react
npm install
npm install lucide-react
Vite is the build tool — it gives you hot module replacement during development and a fast production build. No need for Create React App or Next.js for a kiosk frontend.
Add a dev proxy in vite.config.js so React dev server forwards WebSocket and API calls to FastAPI:
javascript// frontend/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      '/health': 'http://localhost:8000',
      '/acknowledge': 'http://localhost:8000',
    }
  },
  build: {
    outDir: '../static',      // build output goes to /static, served by FastAPI
    emptyOutDir: true,
  }
})
This means during development you run npm run dev (port 3000) with hot reload. For production/demo you run npm run build which outputs to ../static/ and FastAPI serves it at localhost:8000/static/.

Step 1 — building_graph.json and NetworkX Tool
Before the frontend, wire up the last tool so wayfinding data actually exists to display.
Write data/building_graph.json — 20 nodes across 2 floors:
json{
  "nodes": [
    {"id": "reception",    "label": "Reception",        "floor": 1, "x": 100, "y": 300},
    {"id": "lobby-f1",     "label": "Lobby",            "floor": 1, "x": 200, "y": 300},
    {"id": "lift-f1",      "label": "Lift (Floor 1)",   "floor": 1, "x": 350, "y": 300},
    {"id": "stairs-f1",    "label": "Stairs (Floor 1)", "floor": 1, "x": 350, "y": 200},
    {"id": "toilet-f1",    "label": "Toilets",          "floor": 1, "x": 200, "y": 150},
    {"id": "cafeteria",    "label": "Cafeteria",        "floor": 1, "x": 500, "y": 350},
    {"id": "hr-01",        "label": "HR Office",        "floor": 1, "x": 550, "y": 200},
    {"id": "meeting-f1-a", "label": "Meeting Room A",   "floor": 1, "x": 450, "y": 150},
    {"id": "lift-f2",      "label": "Lift (Floor 2)",   "floor": 2, "x": 350, "y": 300},
    {"id": "stairs-f2",    "label": "Stairs (Floor 2)", "floor": 2, "x": 350, "y": 200},
    {"id": "lobby-f2",     "label": "Floor 2 Lobby",   "floor": 2, "x": 250, "y": 300},
    {"id": "room-204",     "label": "Room 204",         "floor": 2, "x": 150, "y": 200},
    {"id": "room-205",     "label": "Room 205",         "floor": 2, "x": 150, "y": 350},
    {"id": "lab-b",        "label": "Lab B",            "floor": 2, "x": 500, "y": 200},
    {"id": "meeting-f2-a", "label": "Meeting Room 2A",  "floor": 2, "x": 550, "y": 150},
    {"id": "meeting-f2-b", "label": "Meeting Room 2B",  "floor": 2, "x": 550, "y": 350},
    {"id": "room-301",     "label": "Room 301",         "floor": 2, "x": 450, "y": 150},
    {"id": "toilet-f2",    "label": "Toilets F2",       "floor": 2, "x": 200, "y": 150},
    {"id": "server-room",  "label": "Server Room",      "floor": 2, "x": 500, "y": 350},
    {"id": "kitchen-f2",   "label": "Kitchen F2",       "floor": 2, "x": 300, "y": 150}
  ],
  "edges": [
    {"from": "reception",    "to": "lobby-f1",     "weight": 10},
    {"from": "lobby-f1",     "to": "lift-f1",      "weight": 15},
    {"from": "lobby-f1",     "to": "stairs-f1",    "weight": 20},
    {"from": "lobby-f1",     "to": "toilet-f1",    "weight": 12},
    {"from": "lift-f1",      "to": "cafeteria",    "weight": 20},
    {"from": "lift-f1",      "to": "hr-01",        "weight": 25},
    {"from": "lift-f1",      "to": "meeting-f1-a", "weight": 18},
    {"from": "lift-f1",      "to": "lift-f2",      "weight": 30},
    {"from": "stairs-f1",    "to": "stairs-f2",    "weight": 35},
    {"from": "lift-f2",      "to": "lobby-f2",     "weight": 10},
    {"from": "stairs-f2",    "to": "lobby-f2",     "weight": 15},
    {"from": "lobby-f2",     "to": "room-204",     "weight": 20},
    {"from": "lobby-f2",     "to": "room-205",     "weight": 18},
    {"from": "lobby-f2",     "to": "kitchen-f2",   "weight": 12},
    {"from": "lobby-f2",     "to": "toilet-f2",    "weight": 15},
    {"from": "lift-f2",      "to": "lab-b",        "weight": 25},
    {"from": "lift-f2",      "to": "room-301",     "weight": 22},
    {"from": "lift-f2",      "to": "meeting-f2-a", "weight": 20},
    {"from": "lift-f2",      "to": "meeting-f2-b", "weight": 22},
    {"from": "lift-f2",      "to": "server-room",  "weight": 28}
  ],
  "room_aliases": {
    "204":    "room-204",
    "205":    "room-205",
    "301":    "room-301",
    "hr-01":  "hr-01",
    "lab b":  "lab-b",
    "lab-b":  "lab-b",
    "cafeteria": "cafeteria",
    "meeting a": "meeting-f1-a",
    "meeting 2a": "meeting-f2-a"
  }
}
Now write app/tools/wayfinding.py:
python# app/tools/wayfinding.py
import json
import logging
from pathlib import Path
from pydantic import BaseModel
from pydantic_ai import RunContext

from app.agent.core import agent
from app.agent.models import RoboDeps

logger = logging.getLogger(__name__)

_GRAPH_PATH = Path(__file__).parent.parent.parent / "data" / "building_graph.json"
_graph_data: dict = {}
_nx_graph = None


def _load_graph():
    global _graph_data, _nx_graph
    import networkx as nx

    with open(_GRAPH_PATH) as f:
        _graph_data = json.load(f)

    G = nx.Graph()
    for node in _graph_data["nodes"]:
        G.add_node(node["id"], **node)
    for edge in _graph_data["edges"]:
        G.add_edge(edge["from"], edge["to"], weight=edge["weight"])
        G.add_edge(edge["to"], edge["from"], weight=edge["weight"])  # undirected

    _nx_graph = G
    logger.info(f"Building graph loaded: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")


class DirectionStep(BaseModel):
    step: int
    node_id: str
    instruction: str
    floor: int


class DirectionsResult(BaseModel):
    found: bool
    destination: str
    steps: list[DirectionStep] = []
    floor_changes: list[int] = []   # floors the route passes through
    total_seconds: int = 0
    message: str = ""


@agent.tool
async def get_directions(
    ctx: RunContext[RoboDeps],
    destination_room: str,
) -> DirectionsResult:
    """
    Get step-by-step walking directions from reception to a room.
    Use after check-in to guide the visitor to their host.
    """
    import networkx as nx
    logger.info(f"Tool: get_directions(destination={destination_room})")

    if _nx_graph is None:
        _load_graph()

    # Resolve room alias
    aliases = _graph_data.get("room_aliases", {})
    dest_key = destination_room.lower().strip()
    node_id = aliases.get(dest_key, dest_key)

    if node_id not in _nx_graph:
        # Try partial match against node labels
        for node in _graph_data["nodes"]:
            if dest_key in node["label"].lower() or dest_key in node["id"]:
                node_id = node["id"]
                break
        else:
            return DirectionsResult(
                found=False,
                destination=destination_room,
                message=f"Could not find room '{destination_room}' in the building map."
            )

    try:
        path = nx.shortest_path(
            _nx_graph, source="reception", target=node_id, weight="weight"
        )
        total_weight = nx.shortest_path_length(
            _nx_graph, source="reception", target=node_id, weight="weight"
        )
    except nx.NetworkXNoPath:
        return DirectionsResult(
            found=False,
            destination=destination_room,
            message=f"No path found to '{destination_room}'."
        )

    # Build human-readable steps
    steps = []
    floors_visited = []

    for i, node_id in enumerate(path):
        node_data = _nx_graph.nodes[node_id]
        floor = node_data.get("floor", 1)
        label = node_data.get("label", node_id)

        if not floors_visited or floors_visited[-1] != floor:
            floors_visited.append(floor)

        # Generate instruction
        if i == 0:
            instruction = f"Start at {label}"
        elif i == len(path) - 1:
            instruction = f"Arrive at {label} — your destination"
        elif "lift" in node_id:
            next_node = _nx_graph.nodes[path[i + 1]]
            next_floor = next_node.get("floor", floor)
            if next_floor != floor:
                instruction = f"Take the lift to Floor {next_floor}"
            else:
                instruction = f"Pass through {label}"
        elif "stairs" in node_id:
            instruction = f"Take the stairs"
        else:
            instruction = f"Continue to {label}"

        steps.append(DirectionStep(
            step=i + 1,
            node_id=node_id,
            instruction=instruction,
            floor=floor,
        ))

    logger.info(f"Directions: {len(steps)} steps, {total_weight}s walk, floors {floors_visited}")

    return DirectionsResult(
        found=True,
        destination=destination_room,
        steps=steps,
        floor_changes=floors_visited,
        total_seconds=int(total_weight),
        message=f"About {total_weight // 60} min {total_weight % 60} sec walk."
    )
Add to _register_tools() in core.py:
pythonimport app.tools.wayfinding   # registers get_directions
Add networkx dependency:
bashuv add networkx
uv export --no-dev --format requirements-txt > requirements.txt
Also update ws_handler.py to send a wayfinding frame when the agent's response includes directions — the agent will call get_directions and the tool result flows back through the agent response. Send the route data explicitly so the frontend can render it:
python# In ws_handler.py — after agent response, check if route data exists in session
# The cleanest approach: publish a wayfinding event from the get_directions tool itself
# Add to get_directions tool after building steps:
if ctx.deps.redis:
    import json
    await ctx.deps.redis.publish("robo:events", json.dumps({
        "type": "wayfinding",
        "route": [s.dict() for s in steps],
        "floor_changes": floors_visited,
        "destination": destination_room,
    }))
The Redis listener in the WebSocket handler already forwards all events to the browser — the wayfinding event type just needs handling in the frontend.

Step 2 — React App Structure
frontend/src/
├── main.jsx                 ← Vite entry point
├── App.jsx                  ← Root: state machine + WebSocket + AudioClient
├── AudioClient.js           ← WebSocket + AudioWorklet (moved from plain JS)
├── useRoboState.js          ← useReducer hook — all state logic
├── components/
│   ├── StatusBadges.jsx     ← Checked In / Host Notified / Host On Their Way
│   ├── FloorPlan.jsx        ← SVG inline render + route highlight
│   └── WaveformMeter.jsx    ← VAD level visualisation
└── states/
    ├── IdleState.jsx        ← Avatar, tap to speak
    ├── ListeningState.jsx   ← Waveform, recording indicator
    ├── ThinkingState.jsx    ← Spinner, contextual message
    ├── SpeakingState.jsx    ← Response text
    └── WayfindingState.jsx  ← Floor plan + route

Step 3 — State Reducer (src/useRoboState.js)
javascript// src/useRoboState.js
import { useReducer } from "react";

const initialState = {
  uiState: "idle",           // idle | listening | thinking | speaking | wayfinding
  transcript: "",            // last visitor utterance
  response: "",              // last agent response
  route: null,               // wayfinding route [{step, node_id, instruction, floor}]
  currentFloor: 1,           // which floor SVG is showing
  badges: {
    checkedIn: false,
    hostNotified: false,
    hostAcknowledged: false,
  },
  audioLevel: 0,             // 0-1, for waveform meter
};

function reducer(state, action) {
  switch (action.type) {

    case "SET_STATE":
      return { ...state, uiState: action.state };

    case "SET_TRANSCRIPT":
      return { ...state, transcript: action.text };

    case "SET_RESPONSE":
      return { ...state, response: action.text };

    case "SET_AUDIO_LEVEL":
      return { ...state, audioLevel: action.level };

    case "SET_ROUTE":
      return {
        ...state,
        uiState: "wayfinding",
        route: action.route,
        currentFloor: action.floor_changes?.[0] ?? 1,
      };

    case "SET_FLOOR":
      return { ...state, currentFloor: action.floor };

    case "SET_BADGE":
      return {
        ...state,
        badges: { ...state.badges, [action.badge]: true },
      };

    case "RESET_SESSION":
      return {
        ...initialState,
        // keep badges visible until explicit reset
      };

    case "RESET_BADGES":
      return { ...state, badges: initialState.badges };

    default:
      return state;
  }
}

export function useRoboState() {
  return useReducer(reducer, initialState);
}

Step 4 — Root App (src/App.jsx)
jsx// src/App.jsx
import { useEffect, useRef, useCallback } from "react";
import { useRoboState } from "./useRoboState";
import IdleState from "./states/IdleState";
import ListeningState from "./states/ListeningState";
import ThinkingState from "./states/ThinkingState";
import SpeakingState from "./states/SpeakingState";
import WayfindingState from "./states/WayfindingState";
import StatusBadges from "./components/StatusBadges";

const KIOSK_ID = "kiosk-01";
const WS_URL = `ws://${window.location.hostname}:8000/ws/voice/${KIOSK_ID}`;

export default function App() {
  const [state, dispatch] = useRoboState();
  const wsRef = useRef(null);
  const audioCtxRef = useRef(null);
  const playbackQueueRef = useRef([]);
  const isPlayingRef = useRef(false);

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
          // queue drains naturally
          break;
      }
    } else {
      // Binary audio chunk
      playbackQueueRef.current.push(event.data);
      if (!isPlayingRef.current) playNext();
    }
  }, []);

  function handleUIUpdate(msg) {
    if (msg.event === "checkin_complete") {
      dispatch({ type: "SET_BADGE", badge: "checkedIn" });
    } else if (msg.event === "notification_sent") {
      dispatch({ type: "SET_BADGE", badge: "hostNotified" });
    } else if (msg.event === "host_acknowledged") {
      dispatch({ type: "SET_BADGE", badge: "hostAcknowledged" });
    }
  }

  // ── Audio playback ─────────────────────────────────────────────────────
  function playNext() {
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
    const buffer = audioCtx.createBuffer(1, float32.length, 24000);
    buffer.copyToChannel(float32, 0);

    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(audioCtx.destination);
    source.onended = playNext;
    source.start();
  }

  // ── Connect on mount ───────────────────────────────────────────────────
  useEffect(() => {
    const connect = async () => {
      audioCtxRef.current = new AudioContext({ sampleRate: 16000 });

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const source = audioCtxRef.current.createMediaStreamSource(stream);

      await audioCtxRef.current.audioWorklet.addModule("/worklet.js");
      const worklet = new AudioWorkletNode(audioCtxRef.current, "pcm-capture");
      source.connect(worklet);

      const ws = new WebSocket(WS_URL);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onmessage = handleMessage;

      worklet.port.onmessage = (e) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(e.data);

          // Audio level for waveform meter
          const int16 = new Int16Array(e.data);
          const rms = Math.sqrt(
            int16.reduce((sum, s) => sum + (s / 32768) ** 2, 0) / int16.length
          );
          dispatch({ type: "SET_AUDIO_LEVEL", level: Math.min(rms * 5, 1) });
        }
      };

      ws.onclose = () => dispatch({ type: "SET_STATE", state: "idle" });
    };

    connect().catch(console.error);
  }, []);

  // ── Render current state ───────────────────────────────────────────────
  const stateComponents = {
    idle:       <IdleState />,
    listening:  <ListeningState audioLevel={state.audioLevel} />,
    thinking:   <ThinkingState response={state.response} />,
    speaking:   <SpeakingState response={state.response} transcript={state.transcript} />,
    wayfinding: <WayfindingState
                  route={state.route}
                  currentFloor={state.currentFloor}
                  onFloorChange={(f) => dispatch({ type: "SET_FLOOR", floor: f })}
                />,
  };

  return (
    <div style={{
      width: "100vw", height: "100vh",
      background: "#0f172a", color: "white",
      display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center",
      fontFamily: "-apple-system, sans-serif",
      overflow: "hidden",
    }}>
      {stateComponents[state.uiState] ?? stateComponents.idle}
      <StatusBadges badges={state.badges} />
    </div>
  );
}

Step 5 — State Components
states/IdleState.jsx
jsxexport default function IdleState() {
  return (
    <div style={{ textAlign: "center" }}>
      {/* Robo avatar — pulsing circle for now, replace with SVG/Lottie */}
      <div style={{
        width: 160, height: 160, borderRadius: "50%",
        background: "radial-gradient(circle, #3b82f6, #1d4ed8)",
        margin: "0 auto 2rem",
        animation: "pulse 2s ease-in-out infinite",
        boxShadow: "0 0 40px rgba(59,130,246,0.4)",
      }} />
      <h1 style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>Welcome</h1>
      <p style={{ color: "#94a3b8", fontSize: "1.1rem" }}>
        Tap or speak to begin
      </p>
      <style>{`
        @keyframes pulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.08); opacity: 0.85; }
        }
      `}</style>
    </div>
  );
}
states/ListeningState.jsx
jsxexport default function ListeningState({ audioLevel }) {
  const bars = 12;
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{
        display: "flex", alignItems: "center",
        justifyContent: "center", gap: 4,
        height: 80, marginBottom: "2rem",
      }}>
        {Array.from({ length: bars }).map((_, i) => {
          const phase = (i / bars) * Math.PI;
          const height = 8 + audioLevel * 60 * Math.abs(Math.sin(phase + Date.now() / 200));
          return (
            <div key={i} style={{
              width: 6, borderRadius: 3,
              height: Math.max(8, height),
              background: "#3b82f6",
              transition: "height 0.05s ease",
            }} />
          );
        })}
      </div>
      <p style={{ color: "#94a3b8", fontSize: "1.2rem" }}>Listening...</p>
    </div>
  );
}
states/ThinkingState.jsx
jsxexport default function ThinkingState({ response }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{
        width: 60, height: 60,
        border: "4px solid #1e293b",
        borderTop: "4px solid #3b82f6",
        borderRadius: "50%",
        margin: "0 auto 2rem",
        animation: "spin 0.8s linear infinite",
      }} />
      <p style={{ color: "#94a3b8" }}>One moment...</p>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
states/SpeakingState.jsx
jsxexport default function SpeakingState({ response, transcript }) {
  return (
    <div style={{ textAlign: "center", maxWidth: 600, padding: "0 2rem" }}>
      {transcript && (
        <p style={{ color: "#64748b", fontSize: "0.9rem", marginBottom: "1rem" }}>
          You said: "{transcript}"
        </p>
      )}
      <div style={{
        background: "#1e293b", borderRadius: "1rem",
        padding: "1.5rem 2rem",
        fontSize: "1.3rem", lineHeight: 1.6,
        border: "1px solid #334155",
      }}>
        {response}
      </div>
      <div style={{
        display: "flex", justifyContent: "center",
        gap: 6, marginTop: "1.5rem",
      }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            width: 8, height: 8, borderRadius: "50%",
            background: "#3b82f6",
            animation: `bounce 1s ease-in-out ${i * 0.2}s infinite`,
          }} />
        ))}
      </div>
      <style>{`
        @keyframes bounce {
          0%, 100% { transform: translateY(0); opacity: 0.4; }
          50% { transform: translateY(-8px); opacity: 1; }
        }
      `}</style>
    </div>
  );
}

Step 6 — SVG Floor Plans and FloorPlan.jsx
Write data/floor_plan_f1.svg — keep it simple, node IDs matching building_graph.json:
svg<svg viewBox="0 0 700 500" xmlns="http://www.w3.org/2000/svg"
     style="width:100%;height:100%">

  <!-- Building outline -->
  <rect x="50" y="50" width="600" height="400" fill="#1e293b" stroke="#334155" stroke-width="2" rx="8"/>

  <!-- Corridors -->
  <path id="corridor-reception-lobby"
        d="M 100 300 L 200 300"
        stroke="#334155" stroke-width="12" stroke-linecap="round" fill="none"/>
  <path id="corridor-lobby-lift"
        d="M 200 300 L 350 300"
        stroke="#334155" stroke-width="12" stroke-linecap="round" fill="none"/>
  <path id="corridor-lift-cafeteria"
        d="M 350 300 L 500 350"
        stroke="#334155" stroke-width="12" stroke-linecap="round" fill="none"/>
  <path id="corridor-lift-hr"
        d="M 350 300 L 550 200"
        stroke="#334155" stroke-width="12" stroke-linecap="round" fill="none"/>

  <!-- Rooms -->
  <g id="node-reception">
    <rect x="60" y="270" width="80" height="60" rx="6"
          fill="#1e3a5f" stroke="#3b82f6" stroke-width="2"/>
    <text x="100" y="305" text-anchor="middle" fill="#93c5fd" font-size="11">Reception</text>
  </g>

  <g id="node-lobby-f1">
    <rect x="160" y="270" width="80" height="60" rx="6"
          fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
    <text x="200" y="305" text-anchor="middle" fill="#94a3b8" font-size="11">Lobby</text>
  </g>

  <g id="node-lift-f1">
    <rect x="320" y="275" width="60" height="50" rx="6"
          fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
    <text x="350" y="305" text-anchor="middle" fill="#94a3b8" font-size="10">Lift</text>
  </g>

  <g id="node-cafeteria">
    <rect x="460" y="320" width="90" height="60" rx="6"
          fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
    <text x="505" y="355" text-anchor="middle" fill="#94a3b8" font-size="11">Cafeteria</text>
  </g>

  <g id="node-hr-01">
    <rect x="510" y="170" width="80" height="55" rx="6"
          fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
    <text x="550" y="202" text-anchor="middle" fill="#94a3b8" font-size="11">HR Office</text>
  </g>

  <g id="node-toilet-f1">
    <rect x="160" y="120" width="80" height="50" rx="6"
          fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
    <text x="200" y="150" text-anchor="middle" fill="#94a3b8" font-size="11">Toilets</text>
  </g>

  <!-- Floor label -->
  <text x="80" y="80" fill="#475569" font-size="13" font-weight="600">Floor 1</text>
</svg>
Create a similar floor_plan_f2.svg with Floor 2 rooms (room-204, room-205, lab-b, room-301, etc.) following the same pattern.
Now write src/components/FloorPlan.jsx:
jsx// src/components/FloorPlan.jsx
import { useEffect, useRef } from "react";

// Import SVGs as raw strings using Vite's ?raw import
import floorPlan1 from "../../data/floor_plan_f1.svg?raw";
import floorPlan2 from "../../data/floor_plan_f2.svg?raw";

const floorPlans = { 1: floorPlan1, 2: floorPlan2 };

export default function FloorPlan({ route, currentFloor, onFloorChange }) {
  const containerRef = useRef(null);

  // Apply route highlighting whenever route or floor changes
  useEffect(() => {
    if (!containerRef.current || !route) return;

    // Clear all highlights first
    containerRef.current.querySelectorAll(".highlighted-route").forEach(el => {
      el.classList.remove("highlighted-route");
    });

    // Highlight nodes on the current floor
    const floorSteps = route.filter(step => step.floor === currentFloor);

    floorSteps.forEach((step, index) => {
      // Highlight room/node group
      const nodeEl = containerRef.current.querySelector(`#node-${step.node_id}`);
      if (nodeEl) {
        setTimeout(() => {
          nodeEl.classList.add("highlighted-route");
        }, index * 400);   // staggered animation
      }

      // Highlight corridor between this and next step
      if (index < floorSteps.length - 1) {
        const nextStep = floorSteps[index + 1];
        const corridorId = `corridor-${step.node_id}-${nextStep.node_id}`;
        const corridorEl = containerRef.current.querySelector(`#${corridorId}`);
        if (corridorEl) {
          setTimeout(() => {
            corridorEl.classList.add("highlighted-route");
          }, index * 400 + 200);
        }
      }
    });
  }, [route, currentFloor]);

  const svgContent = floorPlans[currentFloor] ?? floorPlans[1];
  const floors = route
    ? [...new Set(route.map(s => s.floor))].sort()
    : [1];

  return (
    <div style={{ width: "100%", height: "100%" }}>
      {/* Floor switcher — only show if route spans multiple floors */}
      {floors.length > 1 && (
        <div style={{
          display: "flex", gap: 8, justifyContent: "center", marginBottom: 12
        }}>
          {floors.map(floor => (
            <button
              key={floor}
              onClick={() => onFloorChange(floor)}
              style={{
                padding: "6px 16px", borderRadius: 20,
                border: "none", cursor: "pointer",
                background: currentFloor === floor ? "#3b82f6" : "#1e293b",
                color: currentFloor === floor ? "white" : "#94a3b8",
                fontWeight: 600,
              }}
            >
              Floor {floor}
            </button>
          ))}
        </div>
      )}

      {/* Inline SVG with route highlighting styles */}
      <div
        ref={containerRef}
        dangerouslySetInnerHTML={{ __html: svgContent }}
        style={{ width: "100%", height: "calc(100% - 50px)" }}
      />

      <style>{`
        .highlighted-route rect,
        .highlighted-route path {
          stroke: #22c55e !important;
          stroke-width: 3 !important;
          filter: drop-shadow(0 0 8px rgba(34, 197, 94, 0.6));
          transition: all 0.3s ease;
        }
        .highlighted-route text {
          fill: #86efac !important;
        }
        .highlighted-route[id^="corridor"] {
          stroke: #22c55e !important;
          stroke-width: 16 !important;
          opacity: 0.7;
        }
      `}</style>
    </div>
  );
}
states/WayfindingState.jsx
jsximport FloorPlan from "../components/FloorPlan";

export default function WayfindingState({ route, currentFloor, onFloorChange }) {
  const currentSteps = route?.filter(s => s.floor === currentFloor) ?? [];
  const destination = route?.[route.length - 1];

  return (
    <div style={{
      width: "100vw", height: "100vh",
      display: "flex", flexDirection: "column",
      padding: "1.5rem",
      boxSizing: "border-box",
    }}>
      {/* Header */}
      <div style={{ marginBottom: "1rem" }}>
        <h2 style={{ margin: 0, fontSize: "1.4rem" }}>
          Directions to {destination?.instruction?.replace("Arrive at ", "").replace(" — your destination", "")}
        </h2>
        <p style={{ color: "#64748b", margin: "0.25rem 0 0" }}>
          Follow the highlighted route
        </p>
      </div>

      {/* Floor plan */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <FloorPlan
          route={route}
          currentFloor={currentFloor}
          onFloorChange={onFloorChange}
        />
      </div>

      {/* Step list */}
      <div style={{
        marginTop: "1rem",
        display: "flex", flexDirection: "column", gap: 6,
        maxHeight: 140, overflowY: "auto",
      }}>
        {currentSteps.map(step => (
          <div key={step.step} style={{
            display: "flex", gap: 12, alignItems: "center",
            background: "#1e293b", borderRadius: 8, padding: "8px 12px",
          }}>
            <span style={{
              background: "#3b82f6", color: "white",
              borderRadius: "50%", width: 24, height: 24,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: "0.8rem", fontWeight: 700, flexShrink: 0,
            }}>{step.step}</span>
            <span style={{ color: "#e2e8f0", fontSize: "0.95rem" }}>
              {step.instruction}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

Step 7 — Status Badges Component
jsx// src/components/StatusBadges.jsx
export default function StatusBadges({ badges }) {
  const items = [
    { key: "checkedIn",       label: "Checked In" },
    { key: "hostNotified",    label: "Host Notified" },
    { key: "hostAcknowledged", label: "Host On Their Way" },
  ];

  // Don't render if nothing is active
  if (!Object.values(badges).some(Boolean)) return null;

  return (
    <div style={{
      position: "fixed", bottom: "2rem",
      display: "flex", gap: 12,
      flexWrap: "wrap", justifyContent: "center",
      padding: "0 1rem",
    }}>
      {items.map(({ key, label }) => (
        <div key={key} style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 16px", borderRadius: 24,
          background: badges[key] ? "#14532d" : "#1e293b",
          border: `1px solid ${badges[key] ? "#22c55e" : "#334155"}`,
          color: badges[key] ? "#86efac" : "#475569",
          fontSize: "0.9rem", fontWeight: 500,
          transition: "all 0.4s ease",
        }}>
          <span>{badges[key] ? "✓" : "○"}</span>
          <span>{label}</span>
        </div>
      ))}
    </div>
  );
}

Step 8 — Build and Serve
During development:
bashcd frontend
npm run dev
# Access at http://localhost:3000
# WebSocket proxied to FastAPI at localhost:8000
For demo day (FastAPI serves everything):
bashcd frontend
npm run build
# Outputs to ../static/
# Access at http://localhost:8000/static/index.html
Add to Makefile:
makefilefrontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

dev:
	make frontend-build && uv run uvicorn app.main:app --reload --port 8000

Verification Sequence
bash# 1. NetworkX graph loads correctly
uv run python -c "
import asyncio
from app.agent.models import RoboDeps
from app.agent.core import run_agent

deps = RoboDeps(kiosk_id='test', session_uuid='test')
async def test():
    result = await run_agent('How do I get to Room 204?', deps, [])
    print(result)
asyncio.run(test())
"
# Expected: step-by-step directions spoken + wayfinding Redis event published

# 2. All 5 UI states render — test each manually
# Open browser → states transition on WebSocket frames
# Use browser console to send mock frames:
# ws.send(JSON.stringify({type:'state', state:'wayfinding'}))

# 3. SVG route highlight works
# Trigger get_directions tool → check browser for green highlighted path

# 4. Status badges animate correctly
# Trigger full Scenario 1 → watch badges light up in sequence

# 5. Production build works
cd frontend && npm run build
curl localhost:8000/static/index.html  # should return HTML

# 6. All 5 states on mobile viewport
# Chrome DevTools → toggle device toolbar → 768px width
# All states must be readable without horizontal scroll

What You're Learning Today
React useReducer over useState for complex state — when state has multiple interdependent fields and transitions driven by external events (WebSocket), a reducer is cleaner than a dozen useState calls. Every state change is an explicit, named action — debuggable and predictable.
dangerouslySetInnerHTML for inline SVG — the only way to get SVG elements queryable via getElementById inside React. External <img src="file.svg"> renders SVG as an image — you can't query or style individual elements. Inline SVG gives you full DOM access for the route highlighting.
Vite ?raw imports — import a file as a raw string rather than a URL. Perfect for SVG content you want to inject as HTML. No extra loader configuration needed.
CSS class toggling for animation — adding/removing a CSS class with setTimeout stagger creates the sequential route highlight animation without any animation library. Simple, performant, and works inside SVG.
Vite dev proxy — proxying /ws and /health from the Vite dev server to FastAPI means you develop with hot module replacement while still hitting real backend endpoints. No CORS issues, no switching ports.
NetworkX shortest path — Dijkstra on a weighted graph. Weights are walking seconds. The graph is undirected (you can walk either direction), which is why edges are added in both directions. shortest_path returns the node list; shortest_path_length returns total weight.

Day 5 Done Criteria
✓ npm run dev starts without errors, React app loads at localhost:3000
✓ All 5 UI states render correctly driven by WebSocket frames
✓ Idle state: avatar pulsing, "tap or speak" visible
✓ Listening state: waveform bars animate with audio level
✓ Thinking state: spinner visible during agent processing
✓ Speaking state: response text displayed, audio plays
✓ Wayfinding state: SVG floor plan renders, route highlighted green sequentially
✓ Floor switcher appears when route spans 2 floors
✓ Status badges animate from grey → green in correct sequence
✓ npm run build outputs to /static/, FastAPI serves it at /static/index.html
✓ get_directions tool works: "How do I get to Room 204?" returns steps + Redis event
✓ Full Scenario 1 end-to-end: voice → check-in → notify → acknowledge → wayfinding