Live Testing Guide
Before you start
Reset the database if you've run tests before — APT001's status becomes checked_in after scenario S1 and the seed is idempotent (it skips if data exists). Drop and re-seed:

docker exec -it reception-postgres psql -U reception -c "TRUNCATE hosts, appointments, availability_slots RESTART IDENTITY CASCADE;"
uv run python seed.py
# Expected: Seeded: 5 active hosts (1 inactive), 8 appointments, 16 availability slots
Confirm the server is fully ready before running any scenario:

curl -s http://localhost:8000/health | python -m json.tool
# All fields must be "ok" and all_ready: true
Open the kiosk UI: http://localhost:8000/static/index.html

Click Connect & Start and wait for "Connected — tap to speak" before each scenario. The PTT button will be green.

The data at a glance
Code	Visitor	Host	Room/Floor	Status	Purpose
APT001	Sarah Chen	Marcus Webb	204 / F2	scheduled	S1 — full happy path
APT002	Liam Park	Sarah Lim	Lab-B / F2	scheduled	S2 — code lookup
APT003	John Smith	Priya Nair	HR-01 / F1	scheduled	S3 — fuzzy name match
APT004	Emma Torres	David Chen	301 / F3	scheduled	S4 — low confidence clarification
APT005	James Okafor	Priya Nair	HR-02 / F1	scheduled	S5 — second full cycle
APT006	Anne-Marie Dupont	Marcus Webb	204 / F2	scheduled	S6 — hyphenated name
APT007	Nina Osei	Marcus Webb	204 / F2	cancelled	S7 — cancelled edge case
APT008	Tom Bradley	Marcus Webb	204 / F2	scheduled	S8 — tomorrow (availability)
Hosts: Marcus Webb (Engineering), Sarah Lim (Engineering), Priya Nair (HR), David Chen (Management), Alex Turner (Engineering, inactive).

S1 — Full happy path: check-in + notify + acknowledge
This is the primary demo scenario. Tests the complete round-trip.

Speak: "Hi, I'm Sarah Chen, I have an appointment with Marcus"

Expected log sequence:

┌ user  : 'hi i'm sarah chen i have an appointment with marcus'
▶ lookup_appointment({"visitor_name": "sarah chen"})
  lookup: matched 'Sarah Chen' conf=0.9x host=Marcus Webb room=204
◀ lookup_appointment → {"found": true, "visitor_name": "Sarah Chen", ...}
▶ update_checkin_status({"appointment_id": "..."})
  checkin: ✓ appointment ... → checked_in
◀ update_checkin_status → {"success": true, ...}
▶ notify_host({"host_id": "...", "visitor_name": "Sarah Chen", ...})
  notify_host: → Marcus Webb via ntfy/marcus-webb
◀ notify_host → {"sent": true, "channel": "marcus-webb"}
└ robo  : 'Welcome Sarah! You're checked in...' (2.xs)
Expected UI:

☐ Checked In badge turns green immediately after update_checkin_status
☐ Host Notified badge turns green after notify_host
Robo speaks a confirmation including room 204, floor 2
ntfy notification: Open http://localhost:8081 — a notification for topic marcus-webb should appear with an "I'm on my way ✓" button.

Acknowledge: Click the action button, or run:

# Get the appointment ID first
docker exec -it reception-postgres psql -U reception -c \
  "SELECT id FROM appointments WHERE appointment_code='APT001';"
curl http://localhost:8000/acknowledge/<uuid>
Expected within ~1 second:

☐ Host On Their Way badge turns green
Response display updates to: "Marcus Webb is on their way to meet you."
DB verification:

docker exec -it reception-postgres psql -U reception -c \
  "SELECT status, check_in_at IS NOT NULL, notification_sent, notification_acknowledged
   FROM appointments WHERE appointment_code='APT001';"
# Expected: checked_in | t | t | t
S2 — Code-based lookup (exact match)
Tests the appointment_code branch of lookup_appointment — bypasses fuzzy matching entirely.

Speak: "My appointment code is APT zero zero two"

The STT will likely transcribe "APT002" or "A P T 0 0 2". If it doesn't, say: "I have a code — it's A P T zero zero two"

Expected log:

▶ lookup_appointment({"appointment_code": "APT002"})
  lookup: matched 'Liam Park' conf=1.00 host=Sarah Lim room=Lab-B
The confidence is always 1.0 for code lookup. Robo should confirm Liam Park's appointment with Sarah Lim in Lab-B, Floor 2. Then proceed through check-in as normal. notification_channel is sarah-lim.

Pass criteria: conf=1.00 in logs, correct visitor/host/room in response.

S3 — Fuzzy name match: slight misspelling
Tests pg_trgm tolerance for common mishearing.

Speak: "Hi I'm Jon Smith" (no 'h' in Jon)

"Jon Smith" vs "John Smith" → similarity ≈ 0.67, well above the 0.45 threshold.

Expected log:

▶ lookup_appointment({"visitor_name": "jon smith"})
  lookup: matched 'John Smith' conf=0.6x host=Priya Nair room=HR-01
Robo should respond confirming John Smith's appointment with Priya Nair. It should NOT ask for clarification — the confidence is high enough.

Pass criteria: Match found without clarification prompt, conf > 0.45 in logs.

S4 — Low confidence → clarification → no match
Tests two things: the agent asking for spelling when confidence is low, and graceful handling of a genuinely absent visitor.

Turn 1 — Speak: "Hi, I'm Li"

"Li" against all visitor names will score below 0.3 — no results returned. The agent should ask you to spell or confirm your full name.

Expected: Robo says something like "I couldn't find an appointment for Li. Could you spell your full name or provide your appointment code?"

Turn 2 — Speak: "My name is Zara Khan"

"Zara Khan" has no match in the DB. The agent should respond gracefully: "I don't have an appointment for Zara Khan. Please check your confirmation email or speak with the front desk."

Pass criteria: Two-turn conversation, no crash, no tool error in logs. lookup: low confidence on first turn, No appointment found on second.

S5 — Second full cycle: different host, different department
Ensures the full pipeline isn't brittle to a single fixture. Also tests priya-nair ntfy channel.

Speak: "I'm James Okafor, I'm here to see Priya"

"James Okafor" → confident match (conf > 0.8). Host is Priya Nair, HR department, room HR-02, floor 1.

Expected: Same badge sequence as S1. ntfy/priya-nair notification fires. Acknowledge via curl or ntfy UI.

docker exec -it reception-postgres psql -U reception -c \
  "SELECT status, notification_sent, notification_acknowledged
   FROM appointments WHERE appointment_code='APT005';"
S6 — Hyphenated name (fuzzy stress test)
Tests that pg_trgm handles names with hyphens correctly.

Speak: "I'm Anne-Marie Dupont"

Hyphenated names can have lower trigram overlap. "Anne-Marie Dupont" → confidence should still be above 0.45. If STT drops the hyphen to "Anne Marie Dupont", the similarity should still hold.

Pass criteria: Match found, conf > 0.45. If it fails, it surfaces a real edge case worth noting.

S7 — Cancelled appointment (should not be found)
The lookup_appointment query filters status = 'scheduled' only. Nina Osei's appointment is cancelled.

Speak: "Hi, I'm Nina Osei"

Expected: Robo says the appointment wasn't found and suggests contacting the front desk. No tool error.

Pass criteria: No appointment found in logs. Status badge does NOT light up.

S8 — Availability check for a future date
Tests check_availability. Does not trigger check-in.

Speak: "Is Marcus available tomorrow?"

The agent needs to figure out tomorrow's date. The system prompt includes the current time, so the LLM can compute it.

Expected log:

▶ check_availability({"host_name": "marcus", "date": "YYYY-MM-DD"})
  availability: 'Marcus Webb' → 3 open slot(s) on YYYY-MM-DD
(Marcus has 2 tomorrow slots: +1h and +3h from base_tomorrow. One today slot is pre-booked but that doesn't affect tomorrow.)

Robo should respond with something like "Marcus Webb has slots open tomorrow at [times]."

Pass criteria: check_availability tool fires, not lookup_appointment. At least 2 slots returned.

S9 — Walk-in by department: Engineering
Tests list_hosts with department filter.

Speak: "I don't have an appointment. I'd like to speak with someone in Engineering."

Expected log:

▶ list_hosts({"department": "Engineering"})
  list_hosts: 2 host(s) found in 'Engineering'
Result should contain Marcus Webb and Sarah Lim — not Alex Turner (inactive). Both should have a next_available_slot.

Pass criteria: Exactly 2 hosts returned, Alex Turner absent, Robo names both in response.

S10 — Walk-in, all staff (no department filter)
Speak: "I just walked in and I'd like to meet someone. Who's available?"

Expected log:

▶ list_hosts({"department": null})
  list_hosts: 4 host(s) found
All 4 active hosts returned (Marcus, Sarah Lim, Priya, David). Alex Turner must not appear.

Pass criteria: 4 results, no inactive host.

S11 — Walk-in, non-existent department
Speak: "I'd like to see someone in Finance."

"Finance" has no similarity match > 0.4 against any department name.

Expected log:

▶ list_hosts({"department": "Finance"})
  list_hosts: 0 host(s) found in 'Finance'
Robo should apologise and suggest checking with the front desk.

Pass criteria: HostListResult(found=False) returned, graceful agent response.

S12 — FAQ: building info
Tests get_info across different topics. No DB call, near-instant.

Speak: "What are the building hours?" → get_info(query_type="hours")

Speak: "Where can I park?" → get_info(query_type="parking")

Speak: "What's the WiFi password?" → get_info(query_type="wifi")

Speak: "Is there wheelchair access?" → get_info(query_type="accessibility")

Expected log format: get_info: 'hours' → exact match or get_info: 'parking' → fuzzy match 'parking'

Pass criteria: Robo answers each from the FAQ. No DB query logged. Response is short and speakable.

S13 — Multi-turn conversation (context carries)
Tests that conversation_history is persisted across utterances in the same session.

Turn 1 — Speak: "I'm looking for my appointment"

Robo should ask for your name.

Turn 2 — Speak: "It's Sarah Chen"

Robo should now call lookup_appointment with the name from turn 2, and the context from turn 1 should be present.

Turn 3 — Speak: "Yes, please check me in"

Robo should proceed to update_checkin_status without asking for the name again — the context from the previous turns is in conversation_history.

Pass criteria: Three-turn flow works without re-introducing name. Check server logs — conversation_history grows across turns.

S14 — Health endpoint
curl -s http://localhost:8000/health | python -m json.tool
Expected:

{
  "db": "ok",
  "redis": "ok",
  "llm": "ok",
  "stt": "ok",
  "tts": "ok",
  "all_ready": true
}
S15 — Idempotent acknowledge (tap link twice)
The /acknowledge endpoint is idempotent — hitting it a second time should not error or double-publish a meaningful state change.

# Get APT001's id (after S1 run)
ID=$(docker exec -it reception-postgres psql -U reception -t -c \
  "SELECT id FROM appointments WHERE appointment_code='APT001';" | tr -d ' \n\r')
curl -s http://localhost:8000/acknowledge/$ID   # first tap
curl -s http://localhost:8000/acknowledge/$ID   # second tap — must not crash
Both should return the green HTML page. The second tap should NOT re-publish host_acknowledged in a way that causes problems (it still publishes, but the DB field is already true — idempotent).

Pass criteria: Both curls return 200 with "On my way!" HTML. No 500 in server logs.

Quick DB state reference
After running S1 through S5, check overall state:

docker exec -it reception-postgres psql -U reception -c \
  "SELECT appointment_code, visitor_name, status, 
          check_in_at IS NOT NULL as checked_in,
          notification_sent, notification_acknowledged
   FROM appointments ORDER BY appointment_code;"
Code	Visitor	status	checked_in	notified	acknowledged
APT001	Sarah Chen	checked_in	t	t	t (after S1 ack)
APT002	Liam Park	checked_in	t	t	depends
APT003	John Smith	checked_in	t	t	depends
APT004	Emma Torres	scheduled	f	f	f
APT005	James Okafor	checked_in	t	t	t (after S5 ack)
APT006	Anne-Marie Dupont	scheduled → checked_in	varies	varies	varies
APT007	Nina Osei	cancelled	f	f	f (never touched)
APT008	Tom Bradley	scheduled	f	f	f (availability only)
What to look for if something fails
Wrong tool called — check ▶ tool_name(...) in logs. If list_hosts fires for a named visitor, the system prompt needs adjustment.
Badge doesn't light up — Redis pub/sub not delivering. Check Redis event received: log line appears after tool call. If missing, Redis connection issue.
Agent loops on clarification — conf logged below 0.45. The visitor name the STT produced doesn't match well enough. Check STT (xs): '...' to see what was transcribed.
ntfy POST fails — notify_host: ntfy POST failed in logs. Most common cause is NTFY_HOST=http://localhost:8080 instead of 8081.
History not carrying — look for conversation_history growth in Redis. Run docker exec -it reception-redis redis-cli KEYS "session:*" then GET the key to inspect the stored JSON string.