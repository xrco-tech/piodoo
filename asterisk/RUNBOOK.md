# Dialer bring-up runbook

Goes from "code deployed" to "placing progressive + predictive calls over Vox."
Run on the ubuntu box (`ubuntu@100.88.7.93`, `/home/ubuntu/odoo-stack`).

Prereqs already done: `comm_dialer` + `comm_chatbot_voip` installed; Asterisk
config + ARI bridge service scaffolded (`asterisk/`, `services/dialer_ari/`,
`docker-compose.asterisk.yml`).

---

## 0. Gather (from Vox + your host)
- Vox: SIP **host/port**, **auth mode** (registration user/secret, or IP-based),
  your **DID** (caller-ID), **codecs** (usually alaw/ulaw), **concurrent channels**.
- Host: a reachable **EXTERNAL_IP** for RTP media (public IP, or a TURN address).
  ⚠️ The Cloudflare tunnel carries HTTP/WS only — **not** call audio.
- A **TLS cert** for `wss://` (reuse Let's Encrypt) → `asterisk/keys/fullchain.pem`
  + `privkey.pem`.

## 1. Fill the environment
```bash
cd /home/ubuntu/odoo-stack
cp asterisk/env.sample .env
$EDITOR .env          # Vox creds, EXTERNAL_IP, ARI_PASSWORD, WSS cert paths
mkdir -p asterisk/keys && cp <your fullchain/privkey> asterisk/keys/
```

## 2. Open the firewall (host)
```bash
# SIP signalling + WebRTC WSS + RTP media range (match rtp.conf: 10000-10200)
sudo ufw allow 5060/udp
sudo ufw allow 8089/tcp
sudo ufw allow 10000:10200/udp
# TURN (coturn) — only if using it: signalling + TLS + relay range
sudo ufw allow 3478
sudo ufw allow 5349/tcp
sudo ufw allow 20000:20200/udp
```
If you're using TURN, also set `TURN_REALM` + `TURN_SECRET` in `.env`, and put the
same `TURN URL` + `TURN Secret` on the Odoo VoIP account so agent softphones get
ICE credentials.

## 3. Create the Odoo API user for the bridge service
In Odoo: Settings ▸ Users → new user `dialer@bot`, give it access to the CX/dialer
models, generate an **API key**. Put the key in `.env` as `ODOO_PASSWORD` (and set
`ODOO_USER=dialer@bot`).

## 4. Create the Asterisk VoIP account in Odoo
UCX ▸ Configuration ▸ **VoIP Accounts** → New:
- Provider **Asterisk (ARI + SIP/WebRTC)**, Usage **Automation** (or Both)
- Caller ID = your Vox DID
- ARI Base URL `http://<EXTERNAL_IP>:8088`, ARI user/pass = `.env` values
- Stasis App `comm_dialer`, SIP Trunk `vox`

## 5. Provision agent endpoints
For each agent, two halves must match:
1. **Odoo** — Voice ▸ My Dialer Console (or Dialer Agents) → set **SIP Endpoint**
   (e.g. `1001`) — this is `res.users.dialer_sip_ext`.
2. **Asterisk** — add a matching WebRTC endpoint in `asterisk/etc/pjsip.conf`
   (copy the `[1001]` template block, set the same name + a secret). The agent's
   browser softphone (SIP.js) registers with that name/secret over `wss://<host>:8089`.

## 6. Start the media engine + bridge service
```bash
cd /home/ubuntu/odoo-stack
# add `coturn` to the list if you're using TURN for agent audio
docker compose -f docker-compose.yml -f docker-compose.asterisk.yml up -d asterisk dialer_ari
# with TURN:
# docker compose -f docker-compose.yml -f docker-compose.asterisk.yml up -d asterisk coturn dialer_ari
```

## 7. Verify the trunk + ARI
```bash
# Vox trunk registered / reachable
docker compose -f docker-compose.yml -f docker-compose.asterisk.yml exec asterisk \
  asterisk -rx "pjsip show registrations"
docker compose -f docker-compose.yml -f docker-compose.asterisk.yml exec asterisk \
  asterisk -rx "pjsip show endpoint vox"
# Bridge service connected to Odoo + ARI (expect "Odoo connected" + "ARI websocket connected")
docker compose -f docker-compose.yml -f docker-compose.asterisk.yml logs --tail=30 dialer_ari
```

## 8. Test call (one agent, progressive)
1. Build a campaign: UCX ▸ Voice ▸ **Dialer Campaigns** → New, mode **Progressive**,
   pick the Asterisk account, add **one** contact = your own mobile. Start it.
2. Go **Ready** in My Dialer Console (endpoint set, softphone registered).
3. Enable the pacer for one run: Settings ▸ Technical ▸ Scheduled Actions →
   **"Dialer: pace outbound campaigns"** → set Active, or hit **Run Manually** once.
4. Your phone rings → answer → you're bridged to the agent softphone. Confirm a
   `comm.voip.call` row goes `queued → ringing → in_progress → completed`, and the
   contact lands on a disposition.

## 9. Flip to predictive
Once answer-rate data exists, set a campaign's mode to **Predictive**, tune
`pacing_ratio` (start 1.0) and `target_abandon_rate` (e.g. 3%). The pacer
over-dials by live answer-rate and the governor caps drops. Watch **abandon %**
on the campaign; lower `target_abandon_rate` to be more conservative.

---

## Rollback / stop
```bash
docker compose -f docker-compose.yml -f docker-compose.asterisk.yml stop dialer_ari asterisk
# and disable the "Dialer: pace outbound campaigns" scheduled action in Odoo
```
Stopping the pacer (disable the cron) halts new originations immediately; live
calls finish on their own.

## Quick troubleshooting
| Symptom | Look at |
|---|---|
| No calls placed | `dialer_ari` logs; is the pacer cron active? is the campaign Running + in its calling window? are there Ready agents with an endpoint? |
| Calls ring but no agent audio | RTP/WebRTC media path — EXTERNAL_IP wrong, RTP UDP range closed, or needs TURN |
| Trunk won't register | `pjsip show registrations`; Vox host/port, auth mode (reg vs IP), credentials |
| Agent never bridged | agent's `dialer_sip_ext` must equal a pjsip.conf endpoint name; softphone registered? |
| Too many abandoned calls | lower `pacing_ratio` / `target_abandon_rate`; check AMD is classifying machines |
