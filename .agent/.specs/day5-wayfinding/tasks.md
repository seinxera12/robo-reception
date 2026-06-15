# Day 5 — Wayfinding + React Frontend
## Implementation Task List

### Summary
Day 5 delivers two parallel tracks: the final backend tool (`get_directions` via NetworkX) and a full React frontend replacing the plain HTML test page. By the end of this sprint the kiosk has a proper state machine UI, animated SVG floor plan route highlighting, and all 5 states driven purely by WebSocket frames.

**Total tasks: 24**
**Estimated order of operations:**
1. Backend first (T01–T06) — wayfinding tool, graph data, SVG assets, dependency wiring
2. Frontend scaffold (T07–T09) — Vite init, config, entry point
3. State machine (T10) — useRoboState reducer
4. Root App component (T11) — WebSocket + audio wiring
5. State components (T12–T16) — one per UI state
6. Shared components (T17–T19) — FloorPlan, StatusBadges, WaveformMeter
7. Integration & wiring (T20–T22) — Makefile, static serving, ws_handler wayfinding event
8. Verification (T23–T24) — backend smoke test, full end-to-end

---

> ⚠️ **Decision required before starting:** The existing `frontend/index.html` (Day 2 plain HTML test page) will be superseded by the React build output. The React build writes to `../static/` (i.e., the `/static` directory that FastAPI mounts). The old `index.html` lives at `frontend/index.html` — it is NOT at `/static/index.html`, so it will NOT be overwritten. You can keep it as a fallback during development. If you want to retire it, delete it manually after verifying the React build works. **Do not delete it as part of this sprint unless explicitly decided.**

---

## Section A — Backend: Wayfinding Tool

### T01 — Add networkx to project dependencies
- **Status:** [ ]
- **File(s):** `pyproject.toml`, `requirements.txt`
- **Depends on:** none
- **What to do:**
  Run `uv add networkx` from the project root. This adds `networkx` to `pyproject.toml` under `[project] dependencies` and regenerates `uv.lock`. Then export requirements:
  ```
  uv add networkx
  uv export --no-dev --format requirements-txt > requirements.txt
  ```
  Verify networkx appears in both files.
- **Done when:**
  `uv run python -c "import networkx; print(networkx.__version__)"` prints a version number without error.

---

### T02 — Create data/building_graph.json
- **Status:** [ ]
- **File(s):** `data/building_graph.json`
- **Depends on:** none
- **What to do:**
  Create the file with exactly 20 nodes across 2 floors and 20 weighted undirected edges, plus a `room_aliases` map for fuzzy name resolution. Copy the full JSON structure from the plan verbatim:
  - Nodes: `reception`, `lobby-f1`, `lift-f1`, `stairs-f1`, `toilet-f1`, `cafeteria`, `hr-01`, `meeting-f1-a` (Floor 1); `lift-f2`, `stairs-f2`, `lobby-f2`, `room-204`, `room-205`, `lab-b`, `meeting-f2-a`, `meeting-f2-b`, `room-301`, `toilet-f2`, `server-room`, `kitchen-f2` (Floor 2).
  - Each node has: `id`, `label`, `floor` (int), `x` (int), `y` (int).
  - Edges connect the nodes with `from`, `to`, `weight` (walking seconds). The graph is undirected — `_load_graph()` will add both directions.
  - `room_aliases` maps common spoken names to canonical node IDs (e.g. `"204": "room-204"`, `"lab b": "lab-b"`, `"cafeteria": "cafeteria"`, `"meeting a": "meeting-f1-a"`, `"meeting 2a": "meeting-f2-a"`).
  Use the exact node IDs and coordinates from the plan — they must match the SVG element IDs in T04 and T05.
- **Done when:**
  `uv run python -c "import json; d=json.load(open('data/building_graph.json')); print(len(d['nodes']), 'nodes,', len(d['edges']), 'edges')"` prints `20 nodes, 20 edges`.

---

### T03 — Create app/tools/wayfinding.py with get_directions tool
- **Status:** [ ]
- **File(s):** `app/tools/wayfinding.py`
- **Depends on:** T01, T02
- **What to do:**
  Create the file. Key implementation requirements:

  **Module-level lazy graph cache:**
  ```python
  _GRAPH_PATH = Path(__file__).parent.parent.parent / "data" / "building_graph.json"
  _graph_data: dict = {}
  _nx_graph = None  # loaded on first call
  ```

  **`_load_graph()` function:** imports `networkx` inside the function body (lazy), reads JSON, adds nodes with all attributes (`G.add_node(node["id"], **node)`), adds edges in both directions (undirected — call `G.add_edge` twice per edge entry, `from→to` and `to→from`).

  **Pydantic models:**
  - `DirectionStep(BaseModel)` — fields: `step: int`, `node_id: str`, `instruction: str`, `floor: int`
  - `DirectionsResult(BaseModel)` — fields: `found: bool`, `destination: str`, `steps: list[DirectionStep] = []`, `floor_changes: list[int] = []`, `total_seconds: int = 0`, `message: str = ""`

  **`@agent.tool` decorated `async def get_directions(ctx: RunContext[RoboDeps], destination_room: str) -> DirectionsResult:`**
  - Docstring: `"Get step-by-step walking directions from reception to a room. Use after check-in to guide the visitor to their host."`
  - Call `_load_graph()` if `_nx_graph is None`
  - Resolve alias: `aliases.get(destination_room.lower().strip(), destination_room.lower().strip())`
  - If node not in graph: try partial match against `node["label"].lower()` and `node["id"]`; if still not found, return `DirectionsResult(found=False, ...)`
  - Compute path: `nx.shortest_path(_nx_graph, source="reception", target=node_id, weight="weight")` — catch `nx.NetworkXNoPath`
  - Compute total weight: `nx.shortest_path_length(...)` same args
  - Build `steps: list[DirectionStep]` iterating `enumerate(path)`:
    - i == 0: `"Start at {label}"`
    - i == last: `"Arrive at {label} — your destination"`
    - `"lift"` in node_id + next floor differs: `"Take the lift to Floor {next_floor}"`
    - `"stairs"` in node_id: `"Take the stairs"`
    - else: `"Continue to {label}"`
  - Collect `floors_visited` list (deduplicated ordered)
  - **Publish Redis event** (after building steps):
    ```python
    if ctx.deps.redis is not None:
        await ctx.deps.redis.publish("robo:events", json.dumps({
            "type": "wayfinding",
            "route": [s.model_dump() for s in steps],
            "floor_changes": floors_visited,
            "destination": destination_room,
        }))
    ```
    Note: use `s.model_dump()` (Pydantic v2), not `s.dict()` (Pydantic v1).
  - Return `DirectionsResult(found=True, destination=..., steps=steps, floor_changes=floors_visited, total_seconds=int(total_weight), message=f"About {total_weight // 60} min {total_weight % 60} sec walk.")`

  **Imports needed:** `json`, `logging`, `from pathlib import Path`, `from pydantic import BaseModel`, `from pydantic_ai import RunContext`, `from app.agent.core import agent`, `from app.agent.models import RoboDeps`
- **Done when:**
  File is importable without error: `uv run python -c "from app.tools.wayfinding import get_directions; print('ok')"`. The `@agent.tool` decorator registers at import time.

---

### T04 — Create data/floor_plan_f1.svg
- **Status:** [ ]
- **File(s):** `data/floor_plan_f1.svg`
- **Depends on:** T02
- **What to do:**
  Create a valid SVG file with `viewBox="0 0 700 500"`. Include:
  - A background rect for the building outline
  - `<path>` elements for corridors. Each path must have an `id` of the form `corridor-{nodeA}-{nodeB}` using the exact node IDs from `building_graph.json` (e.g. `id="corridor-reception-lobby-f1"`, `id="corridor-lobby-f1-lift-f1"`, etc.). Stroke should be `#334155`, `stroke-width="12"`.
  - `<g>` elements for rooms, each with `id="node-{node_id}"` (e.g. `id="node-reception"`, `id="node-lobby-f1"`, `id="node-lift-f1"`, etc.). Inside each group: a `<rect>` and a `<text>` label.
  - Room coordinates must match the `x`/`y` values from `building_graph.json` (offset as needed so rects are centered on those coordinates).
  - Floor 1 nodes only: `reception`, `lobby-f1`, `lift-f1`, `stairs-f1`, `toilet-f1`, `cafeteria`, `hr-01`, `meeting-f1-a`.
  - A `<text>` label "Floor 1" in the top-left corner.

  **Critical:** `id` values for `<g>` elements must be exactly `node-{node_id}` and for `<path>` corridors exactly `corridor-{from}-{to}`, because `FloorPlan.jsx` uses `querySelector('#node-...')` and `querySelector('#corridor-...')` to apply route highlighting. A mismatch means no highlights render.
- **Done when:**
  File opens in a browser and all 8 Floor 1 rooms are visible as labelled rectangles. `grep 'id="node-' data/floor_plan_f1.svg` returns 8 matches.

---

### T05 — Create data/floor_plan_f2.svg
- **Status:** [ ]
- **File(s):** `data/floor_plan_f2.svg`
- **Depends on:** T02
- **What to do:**
  Create the Floor 2 SVG following the same structure as T04. Floor 2 nodes: `lift-f2`, `stairs-f2`, `lobby-f2`, `room-204`, `room-205`, `lab-b`, `meeting-f2-a`, `meeting-f2-b`, `room-301`, `toilet-f2`, `server-room`, `kitchen-f2` (12 nodes). Corridor paths connecting them using the edges defined in `building_graph.json` for Floor 2 nodes. Label "Floor 2" in top-left. Same `id` naming convention as T04.
- **Done when:**
  File opens in a browser and all 12 Floor 2 rooms are visible. `grep 'id="node-' data/floor_plan_f2.svg` returns 12 matches.

---

### T06 — Register wayfinding tool and update system prompt
- **Status:** [ ]
- **File(s):** `app/agent/core.py`, `app/agent/prompts.py`
- **Depends on:** T03
- **What to do:**
  **In `app/agent/core.py`**, add the wayfinding import to `_register_tools()`:
  ```python
  def _register_tools() -> None:
      import app.tools.appointments   # lookup_appointment, check_availability, update_checkin_status
      import app.tools.info           # get_info
      import app.tools.notifications  # notify_host
      import app.tools.hosts          # list_hosts
      import app.tools.wayfinding     # get_directions  ← ADD THIS LINE
  ```

  **In `app/agent/prompts.py`**, add `get_directions` to the `TOOLS AVAILABLE:` section of the system prompt string inside `build_system_prompt()`:
  ```
  - get_directions: get step-by-step walking directions from reception to a destination room
  ```
  Also update the `After successful check-in:` rule to read:
  ```
  - After successful check-in: confirm check-in, say host has been notified, offer directions by calling get_directions with the host's room/office
  ```
- **Done when:**
  `uv run python -c "from app.agent.core import agent; tools = [t.name for t in agent._function_tools.values()]; print(tools)"` — the printed list includes `"get_directions"`.

---

## Section B — Frontend: Vite React Scaffold

### T07 — Initialise Vite React project in frontend/
- **Status:** [ ]
- **File(s):** `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`, `frontend/src/main.jsx`
- **Depends on:** none
- **What to do:**
  Run inside the `frontend/` directory:
  ```bash
  cd frontend
  npm create vite@latest . -- --template react
  npm install
  npm install lucide-react
  ```
  The `npm create vite@latest . -- --template react` command scaffolds into the existing directory. It will warn that the directory is not empty and ask whether to overwrite — choose to **ignore files and continue** (do not overwrite `index.html` or `worklet.js` at this stage; the scaffold puts its own `index.html` in place which is fine — the original is kept as `frontend/index.html` for reference but the build uses the new scaffold).

  ⚠️ **Note:** Vite scaffold creates its own `frontend/index.html`. This will replace the Day 2 test page in that location. The Day 2 test page content is preserved in this repo via git history; no backup needed unless the developer prefers otherwise.

  After scaffold + install, verify `node_modules/` is present and `package.json` has `"vite"` and `"@vitejs/plugin-react"` as devDependencies.
- **Done when:**
  `cd frontend && npm run dev` starts the Vite dev server on port 5173 (default) without errors, and a default React app is visible in the browser.

---

### T08 — Configure vite.config.js
- **Status:** [ ]
- **File(s):** `frontend/vite.config.js`
- **Depends on:** T07
- **What to do:**
  Replace the scaffold-generated `vite.config.js` with:
  ```js
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
      outDir: '../static',
      emptyOutDir: true,
    }
  })
  ```
  Key points:
  - Dev server on port 3000 (not 5173)
  - `/ws` proxied as WebSocket to FastAPI on 8000
  - `/health` and `/acknowledge` HTTP-proxied to FastAPI
  - Build output goes to `../static/` (the `/static` directory FastAPI already mounts)
  - `emptyOutDir: true` clears stale build artifacts before each build
- **Done when:**
  `cd frontend && npm run dev` starts on `http://localhost:3000` (not 5173).

---

### T09 — Create frontend/src/main.jsx (entry point)
- **Status:** [ ]
- **File(s):** `frontend/src/main.jsx`
- **Depends on:** T07
- **What to do:**
  The Vite scaffold generates `main.jsx` importing `App.jsx`. Ensure it looks like:
  ```jsx
  import { StrictMode } from 'react'
  import { createRoot } from 'react-dom/client'
  import App from './App.jsx'

  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
  ```
  Delete the scaffold's `src/App.css`, `src/index.css`, `src/assets/` folder, and `public/vite.svg` if present — we're using inline styles throughout.
  Also update the scaffold's `index.html` to remove the default Vite title and favicon link if desired (optional cosmetic).
- **Done when:**
  `src/main.jsx` exists and imports `App` correctly. No import of `App.css` or `index.css` anywhere in the entry chain.

---

## Section C — Frontend: State Machine

### T10 — Create src/useRoboState.js (state reducer)
- **Status:** [ ]
- **File(s):** `frontend/src/useRoboState.js`
- **Depends on:** T09
- **What to do:**
  Create the file with `useReducer`-based state machine. Full structure:

  **`initialState`:**
  ```js
  {
    uiState: "idle",       // "idle" | "listening" | "thinking" | "speaking" | "wayfinding"
    transcript: "",
    response: "",
    route: null,           // array of DirectionStep objects or null
    currentFloor: 1,
    badges: {
      checkedIn: false,
      hostNotified: false,
      hostAcknowledged: false,
    },
    audioLevel: 0,         // 0–1, float
  }
  ```

  **`reducer(state, action)` handles these action types:**
  - `SET_STATE` → `{ ...state, uiState: action.state }`
  - `SET_TRANSCRIPT` → `{ ...state, transcript: action.text }`
  - `SET_RESPONSE` → `{ ...state, response: action.text }`
  - `SET_AUDIO_LEVEL` → `{ ...state, audioLevel: action.level }`
  - `SET_ROUTE` → `{ ...state, uiState: "wayfinding", route: action.route, currentFloor: action.floor_changes?.[0] ?? 1 }`
  - `SET_FLOOR` → `{ ...state, currentFloor: action.floor }`
  - `SET_BADGE` → `{ ...state, badges: { ...state.badges, [action.badge]: true } }`
  - `RESET_SESSION` → `{ ...initialState }` (full reset)
  - `RESET_BADGES` → `{ ...state, badges: initialState.badges }`
  - default: return `state` unchanged

  **Export:** `export function useRoboState() { return useReducer(reducer, initialState); }`
- **Done when:**
  File is importable in `App.jsx` with `import { useRoboState } from './useRoboState'` without any error at dev server startup.

---

## Section D — Frontend: Root App Component

### T11 — Create src/App.jsx (WebSocket + audio wiring)
- **Status:** [ ]
- **File(s):** `frontend/src/App.jsx`
- **Depends on:** T10
- **What to do:**
  Create the root component. Critical implementation notes:

  **Constants at top of file:**
  ```js
  const KIOSK_ID = "kiosk-01"
  const WS_URL = `ws://${window.location.hostname}:8000/ws/voice/${KIOSK_ID}`
  ```
  During Vite dev (port 3000) the proxy rewrites `/ws/...` — but the WS_URL is constructed with explicit port 8000, which bypasses the proxy. **Decision needed:** either construct the WS URL without hardcoded port (use `window.location.host` + rely on the Vite proxy, replacing `8000` with nothing), or keep port 8000 and accept dev requires FastAPI running. The plan uses `hostname:8000` directly — follow that for now.

  **State:** `const [state, dispatch] = useRoboState()`

  **Refs:** `wsRef`, `audioCtxRef`, `playbackQueueRef`, `isPlayingRef`

  **Audio playback rate:** TTS audio from FastAPI is 24kHz (Kokoro). The `AudioBuffer` must be created with `sampleRate: 24000`, NOT 16000. Mic capture uses 16000. This is an existing known issue in the Day 2 HTML page — replicate the correct two-sample-rate pattern from `frontend/index.html`.

  **`handleMessage(event)` callback (wrap in `useCallback`):**
  ```
  Binary frames → push to playbackQueue → call playNext() if not playing
  String frames → JSON.parse → switch on msg.type:
    "state"     → dispatch SET_STATE
    "transcript" → dispatch SET_TRANSCRIPT
    "response"  → dispatch SET_RESPONSE
    "ui_update" → handleUIUpdate(msg)
    "wayfinding" → dispatch SET_ROUTE (route: msg.route, floor_changes: msg.floor_changes)
    "audio_end" → no-op (idle state transition handled by "state" frame)
  ```

  **`handleUIUpdate(msg)`:**
  ```
  msg.event === "checkin_complete"    → dispatch SET_BADGE badge="checkedIn"
  msg.event === "notification_sent"   → dispatch SET_BADGE badge="hostNotified"
  msg.event === "host_acknowledged"   → dispatch SET_BADGE badge="hostAcknowledged"
  ```

  **`playNext()` function:** same PCM int16→float32 conversion as `frontend/index.html`. Create `AudioBuffer` at `sampleRate: 24000` (TTS rate).

  **`useEffect` on mount:** create `AudioContext({ sampleRate: 16000 })` for mic capture, get `getUserMedia`, add AudioWorklet from `/worklet.js`, connect worklet, open WebSocket, wire `ws.onmessage = handleMessage`, wire worklet port for PCM chunks + audio level dispatch. No PTT gating — the existing VAD handles silence detection on the backend. (The Day 2 HTML has PTT logic; the React version streams continuously like the original Day 2 design.)

  **Render:** `switch` or object lookup on `state.uiState` → renders matching state component. `<StatusBadges badges={state.badges} />` always rendered (it returns null when all badges are false). Wrapper div: full-screen dark background (`#0f172a`), flex column, centered.

  **Imports needed:** `useEffect`, `useRef`, `useCallback` from react; `useRoboState`; all 5 state components; `StatusBadges`.
- **Done when:**
  Dev server starts without errors and the browser console shows no import errors. WebSocket connects to FastAPI and `{type: "state", state: "idle"}` causes the Idle state to render.

---

## Section E — Frontend: State Components

### T12 — Create src/states/IdleState.jsx
- **Status:** [ ]
- **File(s):** `frontend/src/states/IdleState.jsx`
- **Depends on:** T09
- **What to do:**
  Pulsing blue circle avatar (160×160px, `border-radius: 50%`, radial-gradient blue), "Welcome" heading (2rem), "Tap or speak to begin" subtext in muted color. CSS `@keyframes pulse` animating `scale` and `opacity` with 2s infinite loop. All styles are inline or via `<style>` tag inside the component. No props required.
- **Done when:**
  Component renders visually in the browser when `uiState === "idle"`.

---

### T13 — Create src/states/ListeningState.jsx
- **Status:** [ ]
- **File(s):** `frontend/src/states/ListeningState.jsx`
- **Depends on:** T09
- **What to do:**
  Props: `{ audioLevel }` (0–1 float).
  Renders 12 vertical bars in a row. Each bar's height is computed as:
  ```js
  const phase = (i / bars) * Math.PI
  const height = 8 + audioLevel * 60 * Math.abs(Math.sin(phase + Date.now() / 200))
  ```
  Bars are `6px` wide, `#3b82f6` blue, `border-radius: 3px`, `min-height: 8px`. `"Listening..."` label below.

  ⚠️ **Note:** The `Date.now() / 200` expression in the height calculation means bar heights change on every render, but React only re-renders when props change. The waveform will only animate when `audioLevel` prop changes (which it does each PCM chunk). For a smoother animation consider using `requestAnimationFrame` or `setInterval` to force re-renders, but the plan doesn't specify this — implement as specified and note the limitation.
- **Done when:**
  Component renders bars that visually respond to the `audioLevel` prop value.

---

### T14 — Create src/states/ThinkingState.jsx
- **Status:** [ ]
- **File(s):** `frontend/src/states/ThinkingState.jsx`
- **Depends on:** T09
- **What to do:**
  Spinning circle (60×60px, border-top blue, `animation: spin 0.8s linear infinite`). "One moment..." text below. `@keyframes spin { to { transform: rotate(360deg) } }`. Props: `{ response }` (unused in the spinner view — available if you want to show a contextual message once available).
- **Done when:**
  Spinner renders and rotates continuously when `uiState === "thinking"`.

---

### T15 — Create src/states/SpeakingState.jsx
- **Status:** [ ]
- **File(s):** `frontend/src/states/SpeakingState.jsx`
- **Depends on:** T09
- **What to do:**
  Props: `{ response, transcript }`.
  Layout: optional transcript display (small muted text: `You said: "{transcript}"`), agent response in a card (`background: #1e293b`, rounded, bordered), three bouncing dots below (`@keyframes bounce`, staggered 0, 0.2s, 0.4s delays). Max-width 600px, centered.
- **Done when:**
  Component renders response text in the card and dots animate when `uiState === "speaking"`.

---

### T16 — Create src/states/WayfindingState.jsx
- **Status:** [ ]
- **File(s):** `frontend/src/states/WayfindingState.jsx`
- **Depends on:** T17 (FloorPlan component)
- **What to do:**
  Props: `{ route, currentFloor, onFloorChange }`.
  Layout (full viewport, flex column, `padding: 1.5rem`):
  1. **Header:** destination name (extracted from last step's instruction — strip `"Arrive at "` and `" — your destination"`), subtitle "Follow the highlighted route"
  2. **FloorPlan component** in a `flex: 1` container (takes remaining height): `<FloorPlan route={route} currentFloor={currentFloor} onFloorChange={onFloorChange} />`
  3. **Step list** (max-height 140px, overflow-y auto): only steps for `currentFloor`. Each step: numbered circle (blue), instruction text. Filter: `route?.filter(s => s.floor === currentFloor) ?? []`.

  Handle `route === null` gracefully (render empty / loading state).
- **Done when:**
  Component renders when `uiState === "wayfinding"` with a route array. FloorPlan is visible, step list shows current-floor steps.

---

## Section F — Frontend: Shared Components

### T17 — Create src/components/FloorPlan.jsx
- **Status:** [ ]
- **File(s):** `frontend/src/components/FloorPlan.jsx`
- **Depends on:** T04, T05, T08
- **What to do:**
  Uses Vite's `?raw` import to load SVG as strings:
  ```js
  import floorPlan1 from "../../data/floor_plan_f1.svg?raw"
  import floorPlan2 from "../../data/floor_plan_f2.svg?raw"
  const floorPlans = { 1: floorPlan1, 2: floorPlan2 }
  ```
  Props: `{ route, currentFloor, onFloorChange }`.

  **`useEffect` for route highlighting** (deps: `[route, currentFloor]`):
  1. Clear all `.highlighted-route` classes from `containerRef.current`
  2. Filter `route` to steps where `step.floor === currentFloor`
  3. For each step (index `i`): `setTimeout(() => querySelector('#node-{step.node_id}').classList.add('highlighted-route'), i * 400)`
  4. For each adjacent pair of steps: try `querySelector('#corridor-{stepA.node_id}-{stepB.node_id}').classList.add('highlighted-route')` with offset `i * 400 + 200`

  **Floor switcher:** only render if `[...new Set(route.map(s => s.floor))].length > 1`. Renders floor buttons that call `onFloorChange(floor)`.

  **SVG injection:** `<div ref={containerRef} dangerouslySetInnerHTML={{ __html: svgContent }} />` — this is required to get queryable SVG DOM elements.

  **CSS for highlighted nodes/corridors** (via `<style>` tag):
  ```css
  .highlighted-route rect,
  .highlighted-route path {
    stroke: #22c55e !important;
    stroke-width: 3 !important;
    filter: drop-shadow(0 0 8px rgba(34, 197, 94, 0.6));
    transition: all 0.3s ease;
  }
  .highlighted-route text { fill: #86efac !important; }
  ```
- **Done when:**
  FloorPlan renders SVG content. Passing a mock route array with floor 1 steps causes those node groups to turn green with a staggered animation.

---

### T18 — Create src/components/StatusBadges.jsx
- **Status:** [ ]
- **File(s):** `frontend/src/components/StatusBadges.jsx`
- **Depends on:** T09
- **What to do:**
  Props: `{ badges }` where `badges = { checkedIn, hostNotified, hostAcknowledged }`.
  Returns `null` if all three badges are false (no empty container rendered).
  Renders fixed-position bar at `bottom: 2rem`, centered:
  Three badge pills, one per key:
  - Active (true): dark green background `#14532d`, green border `#22c55e`, green text `#86efac`, checkmark `✓`
  - Inactive (false): dark bg `#1e293b`, grey border `#334155`, grey text `#475569`, circle `○`
  Labels: `"Checked In"`, `"Host Notified"`, `"Host On Their Way"`.
  CSS `transition: all 0.4s ease` on each badge for smooth activation animation.
- **Done when:**
  Badges are invisible when all false. After `dispatch({ type: "SET_BADGE", badge: "checkedIn" })` the "Checked In" badge turns green.

---

### T19 — Create src/components/WaveformMeter.jsx (optional)
- **Status:** [ ]
- **File(s):** `frontend/src/components/WaveformMeter.jsx`
- **Depends on:** T09
- **What to do:**
  Simple compact audio level meter. Props: `{ level }` (0–1 float).
  Renders a horizontal bar: outer container 200×8px, inner fill bar width = `level * 100%`, color interpolates from `#3b82f6` (blue, low) to `#22c55e` (green, high) using inline style. Can be used in `ListeningState` as an alternative to the bar waveform, or as an additional indicator.
  This component is optional — implement if time permits. `ListeningState` works without it.
- **Done when:**
  Component renders and the fill bar width responds to the `level` prop.

---

## Section G — Integration & Wiring

### T20 — Add worklet.js to Vite public directory
- **Status:** [ ]
- **File(s):** `frontend/public/worklet.js`
- **Depends on:** T07
- **What to do:**
  The AudioWorklet processor (`pcm-capture`) must be served at `/worklet.js`. In the Vite setup, files in `frontend/public/` are served at the root URL as-is. Copy `frontend/worklet.js` to `frontend/public/worklet.js`:
  ```bash
  cp frontend/worklet.js frontend/public/worklet.js
  ```
  The `App.jsx` code does `audioCtxRef.current.audioWorklet.addModule("/worklet.js")`. In Vite dev, this resolves to the public directory. In production (FastAPI /static), the build copies `public/` contents to `../static/`, so `/static/worklet.js` is served by FastAPI.

  ⚠️ **Note:** The existing `frontend/index.html` (Day 2) references `/static/worklet.js`. The React app references `/worklet.js` (no `/static/` prefix). Ensure the React `App.jsx` uses `/worklet.js` (not `/static/worklet.js`) since Vite serves public files at root `/`.
- **Done when:**
  `http://localhost:3000/worklet.js` returns the AudioWorklet processor code when Vite dev server is running. After `npm run build`, `static/worklet.js` exists.

---

### T21 — Update Makefile with frontend targets
- **Status:** [ ]
- **File(s):** `Makefile`
- **Depends on:** T07, T08
- **What to do:**
  Add three new targets to the existing `Makefile`:
  ```makefile
  frontend-dev:
  	cd frontend && npm run dev

  frontend-build:
  	cd frontend && npm run build

  dev:
  	make frontend-build && uv run uvicorn app.main:app --reload --port 8000
  ```
  Add `frontend-dev`, `frontend-build`, `dev` to the `.PHONY` list at the top.

  ⚠️ **Note:** `make dev` builds the frontend then starts FastAPI. This is for demo/production. For active frontend development, run `cd frontend && npm run dev` and `uv run uvicorn app.main:app --reload` in separate terminals.
- **Done when:**
  `make frontend-build` runs without error and `static/index.html` is created.

---

### T22 — Verify FastAPI static file serving for React build
- **Status:** [ ]
- **File(s):** `app/main.py`
- **Depends on:** T21
- **What to do:**
  Read `app/main.py` and confirm it mounts `/static` from the `static/` directory at the project root. According to the inventory, it already does this. Confirm the mount path and that it's set up before routing.

  If the static mount is not present, add it:
  ```python
  from fastapi.staticfiles import StaticFiles
  app.mount("/static", StaticFiles(directory="static"), name="static")
  ```
  Also verify that the `static/` directory itself exists at the project root (it may not exist until the first `npm run build` runs). If not present, create an empty `static/.gitkeep` file so the directory is tracked in git.

  ⚠️ **Ambiguity:** The plan says FastAPI "already mounts /static". Verify this is true in `app/main.py` before making changes. Read the file first.
- **Done when:**
  After running `make frontend-build`, `curl http://localhost:8000/static/index.html` returns HTML (200 response), confirming FastAPI serves the React build.

---

## Section H — Verification

### T23 — Backend wayfinding smoke test
- **Status:** [ ]
- **File(s):** n/a (verification only)
- **Depends on:** T01, T02, T03, T06
- **What to do:**
  Run the following verification script:
  ```bash
  uv run python -c "
  import asyncio, json
  from app.tools.wayfinding import _load_graph, _nx_graph, _graph_data

  _load_graph()
  import networkx as nx
  path = nx.shortest_path(_nx_graph, source='reception', target='room-204', weight='weight')
  print('Path to Room 204:', path)
  weight = nx.shortest_path_length(_nx_graph, source='reception', target='room-204', weight='weight')
  print('Total weight:', weight, 'seconds')
  "
  ```
  Expected: path includes `reception → lobby-f1 → lift-f1 → lift-f2 → lobby-f2 → room-204` and weight is the sum of those edge weights (10+15+30+10+20 = 85).

  Then run the full agent smoke test:
  ```bash
  uv run python -c "
  import asyncio
  from unittest.mock import AsyncMock
  from app.agent.core import run_agent
  from app.agent.models import RoboDeps

  async def test():
      redis_mock = AsyncMock()
      redis_mock.publish = AsyncMock()
      deps = RoboDeps(kiosk_id='test', session_uuid='test-uuid', redis=redis_mock)
      text, result = await run_agent('How do I get to Room 204?', deps, [])
      print('Response:', text)
      print('Redis publish called:', redis_mock.publish.called)

  asyncio.run(test())
  "
  ```
  Expected: response text includes directions, `redis_mock.publish` called with a `wayfinding` type event.
- **Done when:**
  Both scripts run without exceptions. Path to room-204 is correct. Redis publish is called.

---

### T24 — Full end-to-end frontend verification
- **Status:** [ ]
- **File(s):** n/a (verification only)
- **Depends on:** T11–T22
- **What to do:**
  Run the complete verification sequence:

  **1. Dev server:**
  ```bash
  cd frontend && npm run dev
  # Open http://localhost:3000 — should see IdleState (pulsing blue circle + "Welcome")
  ```

  **2. All 5 states (browser console):**
  ```js
  // Open DevTools console on http://localhost:3000
  // These require a WebSocket connection to FastAPI first
  // Test each state frame manually:
  // ws.send(JSON.stringify({type:'state', state:'listening'}))
  // ws.send(JSON.stringify({type:'state', state:'thinking'}))
  // ws.send(JSON.stringify({type:'state', state:'speaking'}))
  // ws.send(JSON.stringify({type:'wayfinding', route:[...], floor_changes:[1,2]}))
  ```
  Each dispatch must transition the UI visually.

  **3. Production build:**
  ```bash
  cd frontend && npm run build
  # Should output to ../static/ without errors
  ls ../static/   # index.html, assets/, worklet.js should be present
  ```

  **4. FastAPI serves build:**
  ```bash
  uv run uvicorn app.main:app --reload --port 8000
  curl -s http://localhost:8000/static/index.html | head -5
  # Should return HTML starting with <!doctype html>
  ```

  **5. Full Scenario 1 (voice end-to-end):**
  - Connect to http://localhost:8000/static/index.html
  - Speak visitor name for a seeded appointment
  - Observe: listening → thinking → speaking states transition
  - Check in → badge 1 activates
  - Notify host → badge 2 activates
  - Acknowledge via ntfy → badge 3 activates
  - Ask "how do I get to [room]?" → wayfinding state shows floor plan with green route

  **6. Mobile viewport check:**
  - Chrome DevTools → device toolbar → 768px width
  - All 5 states must be readable, no horizontal scroll
- **Done when:**
  All 5 states render correctly. Production build serves from FastAPI. All 3 badges animate in sequence during a full check-in scenario. Wayfinding route highlighted green on SVG floor plan.

---

## Open Questions / Decisions for Developer

1. **Keep `frontend/index.html` (Day 2 test page)?** It lives at `frontend/index.html`, not `static/index.html`, so the React build doesn't overwrite it. You can keep it as a fallback or delete it. No action required in this sprint.

2. **WS_URL in App.jsx — proxy vs direct?** The plan hardcodes `ws://hostname:8000/ws/...`. During Vite dev on port 3000, the Vite proxy intercepts `/ws/...` on the same origin — but only if the URL uses the Vite origin (port 3000), not a hardcoded `:8000`. Consider constructing the URL as `ws://${window.location.host}/ws/voice/${KIOSK_ID}` and relying on the Vite proxy for dev, vs. `hostname:8000` for direct connection. Both work; pick one and commit.

3. **PTT vs continuous streaming?** The Day 2 HTML had PTT (push-to-talk). The plan's App.jsx streams continuously (no PTT gate) and relies on backend VAD. This is a regression in UX (no manual control). Decide whether to include a PTT toggle in the React app or ship without it.

4. **ListeningState animation smoothness:** The bar waveform uses `Date.now()` inline in render which only updates on re-render (PCM chunks). For smooth 60fps animation, wrap the bar rendering in `requestAnimationFrame` with a `useRef`-tracked RAF loop. Not in the plan spec — implement at discretion.

5. **`app/wayfinding/` and `app/notifications/` directories are empty.** The plan doesn't use them — wayfinding logic lives in `app/tools/wayfinding.py` and notification logic is already in `app/tools/notifications.py`. These directories can remain empty or be deleted. No action required.
