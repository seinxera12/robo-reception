# Day 4 Tasks — Full Check-In Round-Trip

## Status Legend
- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete

---

## Backend: New Files

---

### [x] T1 — Create `update_checkin_status` tool (extend appointments.py)

**File:** `app/tools/appointments.py`

**What:**
- Add `from datetime import datetime, timezone` import at top of file
- Add `CheckinResult(BaseModel)` class with fields: `success: bool`, `appointment_id: str | None = None`, `message: str = ""`
- Add `@agent.tool` async function `update_checkin_status(ctx: RunContext[RoboDeps], appointment_id: str) -> CheckinResult`
- Docstring: "Mark a visitor as checked in. Call this after lookup_appointment succeeds and the visitor has confirmed their details. Sets status to checked_in and records the check-in timestamp."
- Open `AsyncSessionLocal()`, query `Appointment` by `id == appointment_id`
- If not found: return `CheckinResult(success=False, message=f"Appointment {appointment_id} not found.")`
- If already `AppointmentStatus.checked_in`: return `CheckinResult(success=True, appointment_id=appointment_id, message="Visitor was already checked in.")`
- Otherwise: set `appt.status = AppointmentStatus.checked_in`, set `appt.check_in_at = datetime.now(timezone.utc)`, `await session.commit()`
- Log `f"✓ Checked in: appointment {appointment_id}"`
- After commit, if `ctx.deps.redis` is not None, publish to `"robo:events"` the JSON: `{"type": "checkin_complete", "appointment_id": appointment_id}`
- Return `CheckinResult(success=True, appointment_id=appointment_id, message="Visitor successfully checked in.")`

**Depends on:** none

**Done when:** `python -c "from app.tools.appointments import update_checkin_status; print('ok')"` runs without error and `CheckinResult` is importable

---

### [x] T2 — Create `app/tools/notifications.py` with `notify_host` tool

**File:** `app/tools/notifications.py` (new file)

**What:**
- Imports: `logging`, `json`, `httpx`, `pydantic.BaseModel`, `pydantic_ai.RunContext`, `sqlalchemy.select`, `app.agent.core.agent`, `app.agent.models.RoboDeps`, `app.config.settings`, `app.db.models.Appointment`, `app.db.models.Host`, `app.db.session.AsyncSessionLocal`
- Define `NotifyResult(BaseModel)` with fields: `sent: bool`, `channel: str | None = None`, `message: str = ""`
- Add `@agent.tool` async function `notify_host(ctx: RunContext[RoboDeps], host_id: str, visitor_name: str, appointment_id: str) -> NotifyResult`
- Docstring: "Send a push notification to the host via ntfy. The notification includes an acknowledgement link. Call this after update_checkin_status succeeds."
- Log `f"Tool: notify_host(host_id={host_id}, visitor={visitor_name})"`
- Open `AsyncSessionLocal()`, query `Host` by `id == host_id`; if not found return `NotifyResult(sent=False, message=f"Host {host_id} not found.")`
- Build `ack_url = f"{settings.base_url}/acknowledge/{appointment_id}"`
- Set `topic = host.notification_channel`
- Build `ntfy_url = f"{settings.ntfy_host}/{topic}"`
- Build JSON payload: `topic`, `title: f"Visitor arrived: {visitor_name}"`, `message: f"{visitor_name} is at reception for you."`, `actions: [{"action": "view", "label": "I'm on my way ✓", "url": ack_url, "clear": True}]`, `priority: "high"`, `tags: ["bell", "office"]`
- Send via `httpx.AsyncClient(timeout=5.0)` with `.post(ntfy_url, json=payload)` and `.raise_for_status()`
- On success: query `Appointment` by `id == appointment_id`, set `appt.notification_sent = True`, `await session.commit()`
- If `ctx.deps.redis` is not None, publish to `"robo:events"` the JSON: `{"type": "notification_sent", "appointment_id": appointment_id, "host_name": host.name}`
- Log `f"✓ Notification sent to {host.name} via {topic}"`
- Return `NotifyResult(sent=True, channel=topic, message=f"Notification sent to {host.name}.")`
- On `httpx.HTTPError` exception: log error, return `NotifyResult(sent=False, message=f"Failed to notify host: {e}")`

**Depends on:** none

**Done when:** `python -c "from app.tools.notifications import notify_host; print('ok')"` runs without error

---

### [x] T3 — Create `app/tools/hosts.py` with `list_hosts` tool

**File:** `app/tools/hosts.py` (new file)

**What:**
- Imports: `logging`, `datetime` (`datetime`, `timezone`, `timedelta`), `pydantic.BaseModel`, `pydantic_ai.RunContext`, `sqlalchemy.text`, `app.agent.core.agent`, `app.agent.models.RoboDeps`, `app.db.session.AsyncSessionLocal`
- Define `HostInfo(BaseModel)` with fields: `host_id: str`, `name: str`, `department: str`, `next_available_slot: str | None = None`
- Define `HostListResult(BaseModel)` with fields: `found: bool`, `hosts: list[HostInfo] = []`, `message: str = ""`
- Add `@agent.tool` async function `list_hosts(ctx: RunContext[RoboDeps], department: str | None = None) -> HostListResult`
- Docstring: "List active staff members, optionally filtered by department. Returns each host with their next available slot today or tomorrow. Use this for walk-in visitors who don't have an appointment."
- Log `f"Tool: list_hosts(department={department})"`
- Compute `now = datetime.now(timezone.utc)` and `lookahead = now + timedelta(hours=48)`
- If `department` provided: run SQL with `similarity(h.department, :dept) > 0.4` WHERE clause, params `{"dept": department, "now": now, "lookahead": lookahead}`
- If no `department`: run SQL without similarity filter, params `{"now": now, "lookahead": lookahead}`
- Both queries: `SELECT h.id, h.name, h.department, MIN(s.slot_start) as next_slot FROM hosts h LEFT JOIN availability_slots s ON s.host_id = h.id AND s.slot_start >= :now AND s.slot_start <= :lookahead AND s.is_booked = false WHERE h.is_active = true GROUP BY h.id, h.name, h.department ORDER BY h.name`
- If no rows: return `HostListResult(found=False, message=f"No active hosts found{' in ' + department if department else ''}.")`
- Map rows to `HostInfo` list: `host_id=str(row.id)`, `name=row.name`, `department=row.department`, `next_available_slot=row.next_slot.isoformat() if row.next_slot else None`
- Log `f"list_hosts: {len(hosts)} hosts found"`
- Return `HostListResult(found=True, hosts=hosts)`

**Depends on:** none

**Done when:** `python -c "from app.tools.hosts import list_hosts; print('ok')"` runs without error

---

### [x] T4 — Create `app/api/acknowledge.py` endpoint

**File:** `app/api/acknowledge.py` (new file)

**What:**
- Imports: `logging`, `json`, `fastapi.APIRouter`, `fastapi.Request`, `fastapi.responses.HTMLResponse`, `sqlalchemy.select`, `app.db.models.Appointment`, `app.db.models.Host`, `app.db.session.AsyncSessionLocal`
- Define `router = APIRouter()`
- Add `@router.get("/acknowledge/{appointment_id}", response_class=HTMLResponse)` async function `acknowledge(appointment_id: str, request: Request)`
- Log `f"Acknowledge request: appointment_id={appointment_id}"`
- Open `AsyncSessionLocal()`, execute `select(Appointment, Host).join(Host, Appointment.host_id == Host.id).where(Appointment.id == appointment_id)`
- If no row: return `HTMLResponse(content="<h2>Appointment not found.</h2>", status_code=404)`
- Unpack `appt, host = row`
- If `not appt.notification_acknowledged`: set `appt.notification_acknowledged = True`, `await session.commit()`, log `f"✓ Acknowledged: {appt.visitor_name} → {host.name}"`
- Get redis from `request.app.state.redis`
- Publish to `"robo:events"` the JSON: `{"type": "host_acknowledged", "appointment_id": appointment_id, "visitor_name": appt.visitor_name, "host_name": host.name}`
- Log `f"Redis event published: host_acknowledged for {appointment_id}"`
- Return `HTMLResponse` with green "On my way!" HTML page containing: full `<!DOCTYPE html>` document, viewport meta tag, flexbox centering (`min-height: 100vh`), green card with `border-radius: 1rem`, large `✓` check in a `div.check` element at `font-size: 4rem`, `<h2>On my way!</h2>` in `#16a34a` green, paragraph `f"{host.name} is heading to reception to meet {appt.visitor_name}."` in `#6b7280` gray, background `#f0fdf4`

**Depends on:** none

**Done when:** `curl -s localhost:8000/acknowledge/<valid-id>` returns HTML with "On my way!" and Redis log shows `host_acknowledged` published

---

## Backend: Modifications

---

### [x] T5 — Register new tools in `app/agent/core.py`

**File:** `app/agent/core.py`

**What:**
- In `_register_tools()`, replace the commented-out Day 4 lines with active imports:
  - Keep `import app.tools.appointments` (comment update: `# registers: lookup_appointment, check_availability, update_checkin_status`)
  - Keep `import app.tools.info`
  - Add `import app.tools.notifications  # registers: notify_host`
  - Add `import app.tools.hosts          # registers: list_hosts`
- Remove the old `# Day 4:` comment lines

**Depends on:** T1, T2, T3

**Done when:** `python -c "from app.agent.core import agent; print(list(agent._function_toolset.tools.keys()))"` outputs all 6 tools: `lookup_appointment`, `check_availability`, `get_info`, `update_checkin_status`, `notify_host`, `list_hosts`

---

### [x] T6 — Update system prompt in `app/agent/prompts.py`

**File:** `app/agent/prompts.py`

**What:**
- In the `TOOLS AVAILABLE:` section, add 3 new tool entries after `get_info`:
  - `- update_checkin_status: mark visitor as checked in after confirming their appointment details`
  - `- notify_host: send push notification to the host after check-in is recorded`
  - `- list_hosts: list active staff members, optionally by department, for walk-in visitors`
- In the `RULES:` section, add a check-in sequence rule: `- Check-in sequence: always call lookup_appointment first, then update_checkin_status, then notify_host — never skip steps`
- Update the final confirmation rule to read: `- After successful check-in: confirm check-in, say host has been notified, offer directions`

**Depends on:** none

**Done when:** `build_system_prompt` output contains all 6 tool names and the check-in sequence rule

---

### [x] T7 — Pass Redis to `RoboDeps` and add Redis pub/sub listener in `app/voice/ws_handler.py`

**File:** `app/voice/ws_handler.py`

**What:**
- In `voice_endpoint`, after `redis = websocket.app.state.redis`, verify it is passed to `RoboDeps` (see below)
- When constructing `deps = RoboDeps(...)` inside the utterance loop, add `redis=redis` as a keyword argument
- Add `async def redis_listener()` coroutine nested inside `voice_endpoint` (before the audio loop):
  - Create `pubsub = redis.pubsub()`
  - `await pubsub.subscribe("robo:events")`
  - Log `"Redis pub/sub subscribed: robo:events"`
  - `async for message in pubsub.listen():` — skip if `message["type"] != "message"`
  - Parse `event = json.loads(message["data"])`
  - Log `f"Redis event received: {event['type']}"`
  - Handle `event["type"] == "host_acknowledged"`: call `await send_json({"type": "ui_update", "event": "host_acknowledged", "host_name": event["host_name"], "visitor_name": event["visitor_name"], "appointment_id": event["appointment_id"]})`, log `"✓ Host acknowledged event sent to browser"`
  - Handle `event["type"] == "checkin_complete"`: call `await send_json({"type": "ui_update", "event": "checkin_complete", "appointment_id": event["appointment_id"]})`
  - Handle `event["type"] == "notification_sent"`: call `await send_json({"type": "ui_update", "event": "notification_sent", "appointment_id": event["appointment_id"], "host_name": event["host_name"]})`
  - On `asyncio.CancelledError`: `await pubsub.unsubscribe("robo:events")`, log `"Redis pub/sub unsubscribed"`, then re-raise
- After defining `redis_listener`, before the `try` block that wraps the audio loop, launch: `listener_task = asyncio.create_task(redis_listener())`
- In the `finally` block: add `listener_task.cancel()` followed by `await asyncio.gather(listener_task, return_exceptions=True)` (before `session_manager.delete`)
- In the utterance loop, after `response_text = await run_agent(...)`, replace `await session_manager.update(kiosk_id, session_uuid, {})` with `await session_manager.update(kiosk_id, session_uuid, {"conversation_history": result.all_messages_json()})` — note: `run_agent` must return both `response_text` and `result`; update `run_agent` call or unpack accordingly so `result.all_messages_json()` is accessible

**Depends on:** T1, T2, T3

**Done when:** Server logs show `"Redis pub/sub subscribed: robo:events"` on WebSocket connect, and tapping `/acknowledge/<id>` causes `ui_update` message logged in browser console within 3 seconds

---

### [x] T8 — Update `run_agent` in `app/agent/core.py` to return the result object for history persistence

**File:** `app/agent/core.py`

**What:**
- Change `run_agent` return type annotation from `str` to `tuple[str, object]` (or keep as `str` and add a separate return)
- After `result = await agent.run(...)`, return both `result.output` and `result` so the caller can call `result.all_messages_json()`
- Update the return statement: `return result.output, result`
- Update the `except` block to return a sentinel: `return "I'm sorry, I ran into a problem. Could you please repeat that?", None`
- In `ws_handler.py`, update the call site to unpack: `response_text, agent_result = await run_agent(transcript, deps, conversation_history)`
- Update the session persist call to: `await session_manager.update(kiosk_id, session_uuid, {"conversation_history": agent_result.all_messages_json() if agent_result else []})`

**Depends on:** none

**Done when:** After an agent exchange, `session_manager.get(kiosk_id, session_uuid)` returns a dict with a non-empty `conversation_history` key

---

### [x] T9 — Register acknowledge router in `app/main.py`

**File:** `app/main.py`

**What:**
- Add import: `from app.api.acknowledge import router as acknowledge_router`
- Add after the existing `app.include_router(ws_router)` line: `app.include_router(acknowledge_router)`

**Depends on:** T4

**Done when:** `GET /acknowledge/<id>` returns HTTP 200 or 404 (not 404 "route not found") when the server is running

---

## Frontend: Modifications

---

### [x] T10 — Add badge elements, CSS, and `ui_update` handler to `frontend/index.html`

**File:** `frontend/index.html`

**What:**
- Add 3 badge `<span>` elements as a `<div id="badges">` block placed after the `#response` div and before the `#debug` div:
  ```html
  <div id="badges" style="margin-top: 1rem;">
      <span id="badge-checkin"  class="badge">☐ Checked In</span>
      <span id="badge-notified" class="badge">☐ Host Notified</span>
      <span id="badge-ack"      class="badge">☐ Host On Their Way</span>
  </div>
  ```
- Add badge CSS inside the `<style>` block:
  ```css
  .badge {
      display: inline-block;
      padding: 0.3rem 0.8rem;
      margin: 0.2rem;
      border-radius: 1rem;
      background: #333;
      color: #888;
      font-size: 0.9rem;
      transition: all 0.3s;
  }
  .badge.active {
      background: #16a34a;
      color: white;
  }
  ```
- Add `function resetBadges()` to the `<script>` block: iterates `["badge-checkin", "badge-notified", "badge-ack"]` and removes `"active"` class from each
- Add `function setBadge(id, active)` to the `<script>` block: adds or removes `"active"` class on `document.getElementById(id)`
- In `handleControl(msg)`, add a new `else if` branch for `msg.type === "ui_update"`:
  - If `msg.event === "checkin_complete"`: call `setBadge("badge-checkin", true)`
  - If `msg.event === "notification_sent"`: call `setBadge("badge-notified", true)`
  - If `msg.event === "host_acknowledged"`: call `setBadge("badge-ack", true)`, set `responseEl.textContent = \`${msg.host_name} is on their way to meet you.\``, log `"Host acknowledged:" + JSON.stringify(msg)`
- Call `resetBadges()` inside `cleanup()` (WebSocket disconnect handler) to reset state on disconnect
- Call `resetBadges()` at the start of `connect()` to reset badges on reconnect

**Depends on:** none

**Done when:** Browser shows 3 dark badges on load; badge-ack turns green when acknowledge endpoint is hit and `ui_update` arrives over WebSocket

---

## Verification

---

### [ ] T11 — Verify all 6 tools registered

**File:** n/a (run in shell)

**What:**
- Run: `uv run python -c "from app.agent.core import agent; tools = list(agent._function_toolset.tools.keys()); print('Tools:', tools); assert 'update_checkin_status' in tools; assert 'notify_host' in tools; assert 'list_hosts' in tools; assert 'lookup_appointment' in tools; assert 'check_availability' in tools; assert 'get_info' in tools; print('All 6 tools registered ✓')"`
- All 6 assertions must pass without error

**Depends on:** T1, T2, T3, T5

**Done when:** Script prints `All 6 tools registered ✓` with no AssertionError

---

### [ ] T12 — Verify acknowledge endpoint returns HTML and publishes Redis event

**File:** n/a (run in shell)

**What:**
- Start the server
- Pick a valid appointment UUID from the database (e.g. via seed data)
- Run: `curl -s http://localhost:8000/acknowledge/<valid-uuid>` — response must contain `On my way!`
- Run: `curl -s http://localhost:8000/acknowledge/<nonexistent-uuid>` — response must return HTTP 404 with `Appointment not found.`
- Check server logs: confirm `Redis event published: host_acknowledged for <uuid>` appears

**Depends on:** T4, T9

**Done when:** HTML response contains `On my way!` and Redis publish log line appears

---

### [ ] T13 — Verify ntfy notification sends and action button is present

**File:** n/a (run in shell)

**What:**
- With server running and ngrok active (`ngrok http 8000`), update `.env` `BASE_URL` to the ngrok HTTPS URL
- Send a test notification manually: `curl -X POST http://localhost:8080/<topic> -H "Content-Type: application/json" -d '{"title":"Test","message":"Sarah Chen is at reception","actions":[{"action":"view","label":"On my way","url":"<ngrok-url>/acknowledge/<uuid>"}]}'`
- Open ntfy web UI at `http://localhost:8080` and confirm notification appears with action button
- Tap the action button — confirm browser HTML page shows `On my way!`

**Depends on:** T4, T9

**Done when:** ntfy shows notification with tappable action button that opens the acknowledge HTML page

---

### [ ] T14 — Full Scenario 1 end-to-end voice test

**File:** n/a (manual test)

**What:**
- Connect browser to `http://localhost:8000/static/index.html`
- Tap "Connect & Start", then PTT button
- Speak: "Hi, I am Sarah Chen, I have a 2pm appointment with Marcus"
- Expected log sequence:
  1. `Tool: lookup_appointment(visitor_name='sarah chen')` → match with confidence ≥ 0.45
  2. `Tool: update_checkin_status(appointment_id='...')` → `✓ Checked in`
  3. `Tool: notify_host(host_id='...', visitor='Sarah Chen')` → `✓ Notification sent to Marcus Webb`
  4. Agent response confirms check-in and notifies host
- Expected UI: `badge-checkin` and `badge-notified` turn green
- Tap acknowledge link from ntfy notification (or curl it directly)
- Expected within 3 seconds: `badge-ack` turns green, response text updates to `"Marcus Webb is on their way to meet you."`
- Verify DB: `SELECT checked_in_at, notification_sent, notification_acknowledged FROM appointments WHERE visitor_name = 'Sarah Chen'` shows all three populated

**Depends on:** T1, T2, T4, T5, T6, T7, T8, T9, T10

**Done when:** All 4 expected log lines appear, all 3 badges turn green, DB row confirms state

---

### [ ] T15 — Full Scenario 2 walk-in voice test

**File:** n/a (manual test)

**What:**
- Connect browser, tap PTT
- Speak: "I don't have an appointment, I'd like to see someone in Engineering"
- Expected: `Tool: list_hosts(department='Engineering')` logged
- Expected: Agent response lists Engineering hosts by name with next available slot
- No badges should light up (no check-in or notification in this flow)

**Depends on:** T3, T5, T6

**Done when:** `list_hosts` tool call appears in logs and agent response names at least one Engineering staff member

---

## Dependency Graph

```
T1 (update_checkin_status) ──┐
T2 (notify_host)             ├──→ T5 (register tools in core.py) ──→ T11 (verify all tools)
T3 (list_hosts)              ┘                                   ──→ T14 (e2e scenario 1)
                                                                  ──→ T15 (e2e scenario 2)

T4 (acknowledge endpoint) ──→ T9 (register router) ──→ T12 (verify endpoint)
                          ──→ T13 (verify ntfy)

T6 (update prompts) ──→ T14, T15 (inform agent tool use)

T7 (ws_handler redis listener) ──→ T14 (browser receives ui_update)
T8 (run_agent returns result)  ──→ T7 (history persistence)

T10 (frontend badges) ──→ T14 (badges light up)

Execution order (safe serial):
T1 → T2 → T3 → T4 → T8 → T5 → T6 → T7 → T9 → T10 → T11 → T12 → T13 → T14 → T15

Parallel groups (tasks with no shared deps):
  Group A (independent, can run in parallel): T1, T2, T3, T4, T6, T8, T10
  Group B (depends on Group A): T5 (needs T1+T2+T3), T7 (needs T8), T9 (needs T4)
  Group C (verification, depends on Group B): T11, T12, T13
  Group D (end-to-end, depends on all): T14, T15
```

---

## Day 4 Done Criteria

- [ ] All 6 tools registered — confirmed via `agent._function_toolset.tools`
- [ ] Scenario 1: voice check-in → `checked_in` status written to DB → ntfy push received on host phone
- [ ] Acknowledge link in ntfy notification is publicly reachable (ngrok active, `BASE_URL` set in `.env`)
- [ ] Tapping acknowledge → browser `badge-ack` lights green within 3 seconds (no page refresh)
- [ ] Scenario 2: walk-in → `list_hosts` returns Engineering staff by name
- [ ] Redis pub/sub logs show both `publish` (from `/acknowledge`) and `receive` (in ws_handler) for the same event
- [ ] `GET /health` still returns `all_ready: true` with all services up
- [ ] DB row confirms `notification_sent=true` and `notification_acknowledged=true` after full loop
