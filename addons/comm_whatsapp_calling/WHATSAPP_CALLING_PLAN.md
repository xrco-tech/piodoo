# WhatsApp Calling with comm_whatsapp and contact_centre

## Meta API requirements (WhatsApp Cloud API Calling)

Based on [Meta's Calling API](https://developers.facebook.com/docs/whatsapp/cloud-api/calling/):

### 1. Prerequisites

- **Business number** on WhatsApp Cloud API (same as for messaging).
- **Webhook** subscribed to the `calls` field (in addition to `messages`).
- **App permissions**: `whatsapp_business_messaging` (and any calling-specific permissions Meta requires).
- **Calling enabled** on the phone number in Meta Business Manager (Phone Numbers → Your number → Call settings).

### 2. Webhook payload (incoming call)

When a user calls your business, Meta sends a webhook with:

- `object`: `"whatsapp_business_account"`
- `entry[].changes[].field`: `"calls"`
- `entry[].changes[].value.calls[]`: list of call objects with:
  - `id`: call ID
  - `from`: caller WhatsApp ID (phone)
  - `to`: your phone number ID
  - `event`: e.g. `"connect"` (incoming with SDP), `"terminate"` (ended)
  - `timestamp`: Unix timestamp
  - `session.sdp`: **SDP offer** (only in connect event) – required to generate the SDP answer

### 3. Call flow (Meta side)

1. **Incoming call** → Webhook with `event: "connect"` and `session.sdp` (offer).
2. **Pre-accept (recommended)** → Your server POSTs to Graph API with an **SDP answer** so the media path is set up before the agent answers (faster connect, less clipping).
3. **Accept** → When the agent answers, POST again with `action: "accept"` and the same (or updated) SDP answer. Media starts.
4. **End/Decline** → POST `action: "decline"` or handle `event: "terminate"` from webhook.

### 4. Graph API endpoints (your server → Meta)

All use the same base URL and token from your messaging setup:

- **Pre-accept**:  
  `POST https://graph.facebook.com/v21.0/{phone_number_id}/calls`  
  Body: `{ "messaging_product": "whatsapp", "call_id": "<id>", "action": "pre_accept", "session": { "sdp_type": "answer", "sdp": "<your SDP answer>" } }`

- **Accept**:  
  Same URL, body: `{ "messaging_product": "whatsapp", "call_id": "<id>", "action": "accept", "session": { "sdp_type": "answer", "sdp": "<your SDP answer>" } }`

- **Decline**:  
  Same URL, body: `{ "messaging_product": "whatsapp", "call_id": "<id>", "action": "decline" }`

Use the same **access token** and **phone_number_id** as for messaging (e.g. from `comm_whatsapp` config).

### 5. SDP answer requirements (Meta)

- Use **SHA-256** for DTLS fingerprint: `a=fingerprint:sha-256 ...` (Meta may require capitalisation `SHA-256` in some versions; if you get fingerprint errors, try that).
- Only one fingerprint line (e.g. remove sha-384/sha-512 if present).
- SDP must be a valid answer to the offer (same codecs/transport as in the offer).

---

## WebRTC and media (your side)

Meta sends an **SDP offer** and expects an **SDP answer**. Who generates the answer and where does media go?

### Option A: Server-side SDP only (no real audio yet)

- Your backend generates a **minimal SDP answer** from the offer (e.g. same codecs, dummy/placeholder addresses).
- You send this in **pre_accept** and **accept** so Meta thinks the call is answered.
- **Use case**: Log calls, show “incoming call” in Odoo, but **no real audio** until you add a media path (Option B or C).

### Option B: Browser (agent) WebRTC

- **Flow**:  
  1. Webhook receives call + SDP offer.  
  2. Backend stores call and SDP offer, notifies the agent (e.g. via bus or polling).  
  3. Agent opens a “call” screen in the browser.  
  4. Browser creates an `RTCPeerConnection`, sets `setRemoteDescription(offer)`, creates answer with `createAnswer()`, sends the SDP answer to your backend.  
  5. Backend sends that SDP answer to Meta via **pre_accept** and/or **accept**.  
  6. Meta sends media to the browser; browser sends agent’s media to Meta (via Meta’s servers).
- **Requirements**: HTTPS, and (for NAT) a **TURN server** so the browser can receive/send media reliably. No media server in the middle if you keep it simple.

### Option C: Media server (Janus / custom Node, etc.)

- A **media server** (e.g. Janus, or a custom WebRTC server) receives the SDP offer from Meta (your backend forwards it) and generates an SDP answer.
- The server bridges **Meta ↔ media server** and **media server ↔ browser** (agent).
- **Use case**: More control, recording, IVR, etc. Your existing `whatsapp_custom` + `webrtc.media.server` is in this family.

For **Odoo Community** with **comm_whatsapp** and **contact_centre**, a practical path is:

1. **Phase 1**: Use **comm_whatsapp_calling** to handle webhook, create call log, generate a **server-side SDP answer** (Option A), and call Meta **pre_accept** / **accept**. Result: calls are “answered” on Meta’s side and logged in Odoo; no real audio yet.
2. **Phase 2**: Add a **browser WebRTC client** (Option B): agent UI in Odoo that gets the SDP offer from the backend, creates an answer in the browser, sends it back so the backend can pre_accept/accept with that real SDP. Then add a TURN server if needed.
3. **Optional**: Later, add a media server (Option C) if you need recording, IVR, or more complex flows.

---

## What this module does (comm_whatsapp_calling)

- **Depends on**: `comm_whatsapp` (and optionally `contact_centre`).
- **Extends** `comm_whatsapp` webhook so that when `field == 'calls'`, it processes call events and does **not** run the normal message handling for that change.
- **Call log model**: Stores `call_id`, `from`, `to`, `status`, `sdp_offer`, `sdp_answer`, timestamps; links to `res.partner` (and optionally `contact.centre.contact`).
- **Meta API**: Uses `comm_whatsapp` config (access token, phone number ID) to:
  - **Pre-accept** with a server-generated SDP answer (Phase 1).
  - **Accept** with the same or browser-provided SDP (when agent answers).
  - **Decline** when the agent declines.
- **Controllers**: Endpoints for the Odoo front end to answer/decline/end and (Phase 2) to submit a browser-generated SDP answer.
- **Contact Centre**: If installed, show WhatsApp calls in contact centre (e.g. call history on contact, or a “Calls” view) and link call log to `contact.centre.contact` by phone.

---

## Meta docs references

- [WhatsApp Cloud API – Calling](https://developers.facebook.com/docs/whatsapp/cloud-api/calling/)
- [Calling – SIP (alternative to webhook)](https://developers.facebook.com/docs/whatsapp/cloud-api/calling/sip/)
- [Call settings](https://developers.facebook.com/docs/whatsapp/cloud-api/calling/call-settings) (business hours, etc.)

---

## Enabling calling in Meta

1. In [Meta for Developers](https://developers.facebook.com/): your App → WhatsApp → Configuration.
2. Webhook: subscribe to **calls** (and keep **messages**).
3. In **Meta Business Suite** (or Business Manager): Phone numbers → select number → **Call settings** → enable calling for that number.
