# WhatsApp Calling (comm_whatsapp_calling)

Enables **receiving** WhatsApp voice calls in Odoo Community when using **comm_whatsapp**.  
Works with **contact_centre**: call logs are stored and can be linked to contacts.

## What it does

- Subscribes to webhook **`calls`** by extending `comm_whatsapp`’s webhook.
- Creates **whatsapp.call.log** records (call_id, from, to, status, SDP, timestamps).
- Sends **pre_accept** (and optionally **accept**) to Meta’s Graph API so the call is “answered” on Meta’s side.
- Uses **comm_whatsapp** config: same access token and phone number ID as messaging.
- Provides **Answer** / **Decline** JSON routes for the UI.

## Meta setup

1. **App**: In [Meta for Developers](https://developers.facebook.com/), in your WhatsApp app **Webhook**, subscribe to the **`calls`** field (in addition to `messages`).
2. **Phone number**: In Meta Business Suite, enable **Calling** for your WhatsApp Business number (Phone numbers → your number → Call settings).
3. **Same webhook URL** as for messages (e.g. `https://your-domain/whatsapp/webhook`).

## WebRTC / real audio

- This module can send a **server-generated SDP answer** so Meta stops ringing and the call is “connected” for logging. That does **not** by itself give the agent real audio.
- For **real voice**, you need either:
  - **Browser WebRTC**: agent UI that creates an `RTCPeerConnection`, gets the SDP offer from the backend, creates an answer, and sends it back so the backend can **accept** with that SDP; and a **TURN** server if needed.
  - **Media server**: e.g. Janus or a custom WebRTC server that bridges Meta ↔ agent (like in `whatsapp_custom` + `webrtc.media.server`).

See **WHATSAPP_CALLING_PLAN.md** for Meta API details and WebRTC options.

## Contact Centre

- **contact_centre** can list or link to **whatsapp.call.log** (e.g. “WhatsApp Calls” menu, or call history on a contact).  
- If you add a dependency from **contact_centre** to **comm_whatsapp_calling**, you can add a menu or a button “WhatsApp Calls” that opens `whatsapp.call.log`.

## Incoming call popup

- When an incoming call is **ringing**, the module can show a **popup** (Accept / Decline) in the browser.
- This uses Odoo’s **bus** for real-time notifications. The module does **not** depend on `bus`; if `bus` is available (e.g. from **mail**), it sends a notification and the frontend script shows the popup. If bus is not available or the real-time connection fails, use **WhatsApp Light → Calls** to see and answer/decline calls.

## Installation

1. Install **comm_whatsapp** and configure Meta (token, webhook, phone number ID).
2. Install **comm_whatsapp_calling**.
3. In Meta, subscribe the webhook to **calls** and enable calling on the number.
4. Restart Odoo and trigger a test call to your business number.

## Troubleshooting

### "Error validating access token: Session has expired"

Your Meta access token has expired. Re-authenticate via **comm_whatsapp**: open the WhatsApp configuration in Odoo (e.g. Settings → WhatsApp or the OAuth flow you used initially) and sign in again so a new token is stored. The same token is used for messaging and calling.

### “Couldn’t bind the websocket. Is the connection opened on the evented port (8072)?”

This comes from Odoo’s **bus** (real-time) layer, not from this module. The web client tries to use a **WebSocket** connection, but the server is not running the evented worker.

- **Option A – Use longpolling:** Run Odoo with **workers** and route longpolling to the evented port, e.g. start Odoo with `--gevent` (or your distro’s recommended way) and in nginx (or your proxy) proxy `/longpolling` (and websocket if needed) to `127.0.0.1:8072`. See [Odoo longpolling](https://www.odoo.com/documentation/current/administration/install.html#long-polling) and your Odoo version’s docs.
- **Option B – Ignore the error:** The popup will not appear, but **WhatsApp Light → Calls** still works: you can open the list and use Accept/Decline from the form or your own buttons that call the same JSON routes.

## Files

- `controllers/whatsapp_webhook.py`: extends comm_whatsapp webhook, handles `field == 'calls'`.
- `controllers/whatsapp_call_routes.py`: `/whatsapp/call/answer/<id>`, `/whatsapp/call/decline/<id>`.
- `models/whatsapp_call_log.py`: call log model and Meta pre_accept/accept/decline.
