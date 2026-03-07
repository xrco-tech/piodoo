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

## Installation

1. Install **comm_whatsapp** and configure Meta (token, webhook, phone number ID).
2. Install **comm_whatsapp_calling**.
3. In Meta, subscribe the webhook to **calls** and enable calling on the number.
4. Restart Odoo and trigger a test call to your business number.

## Files

- `controllers/whatsapp_webhook.py`: extends comm_whatsapp webhook, handles `field == 'calls'`.
- `controllers/whatsapp_call_routes.py`: `/whatsapp/call/answer/<id>`, `/whatsapp/call/decline/<id>`.
- `models/whatsapp_call_log.py`: call log model and Meta pre_accept/accept/decline.
