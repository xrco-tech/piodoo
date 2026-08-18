# Tier-1 test — softphone registration + audio, without Vox

Validates the agent WebRTC softphone end-to-end (register → auto-answer → two-way
audio) using a trunk-less Asterisk. Do this before the Vox trunk to de-risk the
whole WebRTC/media path independently.

## Prerequisites (unavoidable)
- Asterisk reachable at `wss://<host>:8089` with a **valid TLS cert** for `<host>`
  (browsers refuse WSS to untrusted certs — self-signed won't work). Put the cert at
  `asterisk/keys/fullchain.pem` + `privkey.pem`.
- Set `EXTERNAL_IP` in `.env` to the box's reachable IP (LAN IP is fine for a LAN test).
- Browser + box on a network where media can flow (same LAN needs no TURN).

## 1. Bring up the test Asterisk
```bash
cd /home/ubuntu/odoo-stack
docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml up -d asterisk-test
```

## 2. Point the Odoo softphone at it (endpoint 1001)
- UCX ▸ Configuration ▸ **VoIP Accounts** → the Asterisk account:
  - WebSocket URL `wss://<host>:8089/ws`, SIP Domain `<host>`
- Your user's **SIP Endpoint** = `1001`, **SIP Secret** = `test1001secret`
- Reload Odoo → the systray **headphones dot goes green (registered)**.

Confirm from Asterisk:
```bash
docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml \
  exec asterisk-test asterisk -rx "pjsip show contacts"   # 1001 should have a contact
```

## 3a. Quickest audio test — originate an echo call (no 2nd client)
This mimics exactly what the dialer bridge does: rings 1001 and connects Echo.
```bash
docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml \
  exec asterisk-test asterisk -rx "channel originate PJSIP/1001 application Echo"
```
Your Odoo softphone **auto-answers** → you hear your own voice echoed back. ✅ proves
registration + auto-answer + two-way audio.

## 3b. Full two-endpoint test (optional)
Open `asterisk/webrtc-test/dialer.html` in a **second browser** (edit the WSS URL /
domain to your host — it's pre-filled for 1002 / `test1002secret`). Register, then
**Call 1001**. The Odoo softphone auto-answers → talk between the two tabs.
(Dial `600` from the test dialer for a standalone echo test.)

## Debugging
- Browser **DevTools ▸ Network ▸ WS**: the `wss://…:8089/ws` socket must reach **101
  Switching Protocols**. If not, it's cert/reachability — fix that first.
- **`chrome://webrtc-internals`**: live ICE + audio stats. ICE stuck at `checking`
  across NAT = you need coturn/TURN (see `docker-compose.asterisk.yml`).
- Asterisk: `asterisk -rx "pjsip set logger on"`, `pjsip show contacts`.

## Teardown
```bash
docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml down
```
This is a **test** config with hard-coded secrets — don't run it in production. The
real trunk-backed setup is `docker-compose.asterisk.yml` + `RUNBOOK.md`.
