## Failed test scenarios

### Error 1

Turn 1 — Speak: "I'm looking for my appointment"

Robo should ask for your name.

Turn 2 — Speak: "It's Sarah Chen"

Robo should now call lookup_appointment with the name from turn 2, and the context from turn 1 should be present.

Turn 3 — Speak: "Yes, please check me in"

Robo should proceed to update_checkin_status without asking for the name again — the context from the previous turns is in conversation_history.

Pass criteria: Three-turn flow works without re-introducing name. Check server logs — conversation_history grows across turns.

**Error**: No appointment found for Sarah Chen even when its in the database.

### Error 2

After user confirms their name and agents confirms the check in of the user when the appointment is found, the notification is properly sent to ntfy topic, hosts and room info is properly given to the user. With this, the []Checked in and []Host Notified Badge should turn green upon status change.

When the host aknowledges the notification via the link thay get in their ntfy topic, the user's screen [] Host on their way badge should also be green to signal status update, which is also not happening.

terminal logs : 

```bash
[17:01:28] INFO     app.voice.stt : STT: (1.52s) → 'Hi, I am Tom Bradley and I am here for my appointment.'
[17:01:28] INFO     app.voice.ws_handler :   STT (1.52s): 'Hi, I am Tom Bradley and I am here for my appointment.'
[17:01:28] INFO     app.agent.core :   ┌ user  : 'Hi, I am Tom Bradley and I am here for my appointment.'
[17:01:29] INFO     app.tools.appointments : Tool: lookup_appointment(name='Tom Bradley', code=None)
[17:01:29] INFO     app.tools.appointments :   lookup: matched 'Tom Bradley' conf=1.00 host=Marcus Webb room=204
[17:01:29] INFO     app.tools.appointments : Tool: update_checkin_status(appointment_id=c2a6089e-de2e-4151-ae22-ccd46321e558)
[17:01:29] INFO     app.tools.appointments :   checkin: ✓ appointment c2a6089e… → checked_in
[17:01:31] INFO     app.tools.notifications : Tool: notify_host(host_id=457f52dd-d966-464a-83bb-b44cebff19dc, visitor=Tom Bradley)
[17:01:31] INFO     app.tools.notifications :   notify_host: → Marcus Webb via ntfy/marcus-webb
[17:01:32] INFO     app.agent.core :   ▶ lookup_appointment({"appointment_code":null,"visitor_name":"Tom Bradley"})
[17:01:32] INFO     app.agent.core :   ◀ lookup_appointment → found=True appointment_id='c2a6089e-de2e-4151-ae22-ccd46321e558' appointment_code='APT008' visitor_name='Tom Bradley' ho…
[17:01:32] INFO     app.agent.core :   ▶ update_checkin_status({"appointment_id":"c2a6089e-de2e-4151-ae22-ccd46321e558"})
[17:01:32] INFO     app.agent.core :   ◀ update_checkin_status → success=True appointment_id='c2a6089e-de2e-4151-ae22-ccd46321e558' message='Visitor successfully checked in.'
[17:01:32] INFO     app.agent.core :   ▶ notify_host({"appointment_id":"c2a6089e-de2e-4151-ae22-ccd46321e558","host_id":"457f52dd-d966-464a-83bb-b44cebff19dc","visitor_name"…)
[17:01:32] INFO     app.agent.core :   ◀ notify_host → sent=True channel='marcus-webb' message='Notification sent to Marcus Webb.'
[17:01:32] INFO     app.agent.core :   └ robo  : 'You've successfully checked in, Tom. Your host, Marcus Webb, has been notified. Room 204 on floor 2 is ready for you.' (4.32s)
[17:01:32] INFO     app.voice.tts : TTS: 3 sentence(s), 117 chars
[17:01:38] INFO     app.voice.ws_handler :   LATENCY  : STT 1.52s | agent 4.32s | TTS 6.58s | total 12.42s
[17:01:38] INFO     app.voice.ws_handler :   TTS: done
[17:07:20] INFO     app.api.acknowledge : Acknowledge request: appointment_id=c2a6089e-de2e-4151-ae22-ccd46321e558
[17:07:20] INFO     app.api.acknowledge : ✓ Acknowledged: Tom Bradley → Marcus Webb
[17:07:20] INFO     app.api.acknowledge : Redis event published: host_acknowledged for c2a6089e-de2e-4151-ae22-ccd46321e558

```





