# Dialer / telephony runbook

Operating guide for the Asterisk telephony plane: the **live Vox SIP trunk**, the
agent WebRTC softphone, and the ARI dialer bridge.
Run on the ubuntu box (`ubuntu@100.88.7.93`, `/home/ubuntu/odoo-stack`).

> **Status (Sep 2026): the Vox trunk is LIVE.** Registration, outbound PSTN and
> inbound PSTN → agent softphone are all verified with two-way audio. What
> follows is the as-built configuration, not a bring-up plan.

---

## 0. Which overlay is actually running

⚠️ **Important:** the live trunk runs on the **`asterisk-test` overlay**, not
`docker-compose.asterisk.yml`. The trunk + dialplan were bolted onto the
already-validated WebRTC test box, so that is the one in production use:

```bash
docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml up -d asterisk-test
```

`docker-compose.asterisk.yml` (+ `asterisk/etc/`) is the older "production"
scaffold. It has **not** been updated with the `transport-ws` fix or the trunk
block — consolidate before ever switching to it.

## 1. Vox trunk (live)

| Item | Value |
|---|---|
| Registrar | `bdl1.vphone.co.za:5060` (PBX; `sf.vphone.co.za` is the standalone-phone one, unused) |
| Auth | Registration (username/secret) — NOT IP-based |
| Username | `27871640575` |
| Secret | `.env` → `VOX_SECRET` (never in git) |
| DID / CLI / alias | `27108221225` |
| Codecs | `alaw,ulaw` |

Config lives in `asterisk/webrtc-test/pjsip.conf`:
`[transport-udp]` (5060) + `[vox]` endpoint / `vox_auth` / `vox_aor` /
`vox_reg` / `vox_identify`. Dialplan in `asterisk/webrtc-test/extensions.conf`:
outbound patterns in `from-agents` (sets `CALLERID(num)=${VOX_DID}`), inbound
catch-all in `[from-vox]` → `Dial(PJSIP/1001)`.

**Trunk media works over the home NAT with NO router port-forward** —
`rtp_symmetric` + `force_rport` + Vox latching RTP to our source handles it.
Verified: outbound alaw, 0% packet loss both directions.

`.env` keys: `VOX_SIP_HOST`, `VOX_SIP_PORT`, `VOX_USERNAME`, `VOX_SECRET`,
`VOX_DID`, `VOX_CODECS`, `EXTERNAL_IP`, `LOCAL_NET`.
All are rendered into the configs by `asterisk/entrypoint.sh` (sed-based; it
escapes `\ & |` so secrets with special characters render literally).

## 2. Agent softphone path — signalling vs media

These now take **different routes**, which is the single most important thing to
understand here:

- **Signalling (SIP over WebSocket): goes THROUGH the Cloudflare tunnel.**
  `wss://pbx.xrco.tech/ws` → tunnel `pi-odoo19` → HTTP `host.docker.internal:8088`
  → Asterisk. The edge terminates TLS, so Asterisk receives **plain ws** — which
  is why `[transport-ws]` (protocol=ws, bind 8088) must exist and endpoints must
  **not** pin `transport=`. (The older doc claim that Asterisk "cannot run behind
  the tunnel" is only true of media.)
  A direct `wss://ubuntu.taild8679b.ts.net:8089/ws` also works for tailnet agents.
- **Media (RTP/SRTP): never touches the tunnel.** It uses ICE, with relay
  candidates from **Cloudflare managed TURN**.

## 3. TURN — Cloudflare managed (not coturn)

Browser ICE credentials are minted server-side per call from a Cloudflare TURN
key; the long-lived token never reaches the browser. This replaced self-hosted
coturn and removed the router port-forward + dynamic-IP DDNS problem entirely.

Config params: `comm.turn.cf_key_id`, `comm.turn.cf_api_token`,
`comm.turn.ttl`. Consumed by `comm.voip.account.get_ice_servers()` (softphone)
and `/whatsapp/monitor/ice_servers` (WhatsApp call monitoring). coturn is still
deployed (`docker-compose.coturn.yml`) as a fallback but is not the active path.

**Asterisk itself also uses Cloudflare TURN** (`rtp.conf` →
`turnaddr`/`turnport`/`turnusername`/`turnpassword`, from `.env` `TURN_*`),
because behind NAT it otherwise advertises only private host candidates that a
remote browser can never reach. Those creds are **time-limited (48h)** — they
need a refresh job.
⚠️ `stunaddr` is deliberately **omitted**: `stun.cloudflare.com` is unreachable
from this site and its timeouts added ~15s to ICE gathering.

## 4. Provision an agent

Two halves must match:
1. **Odoo** — `res.users.dialer_sip_ext` (e.g. `1001`) + `dialer_sip_secret`.
   `get_softphone_config()` returns these verbatim.
2. **Asterisk** — an endpoint of the same name with the same password in
   `asterisk/webrtc-test/pjsip.conf` (the test box defines `1001` / `1002`).

The WebSocket URL + SIP domain come from the **VoIP account record**
(`comm.voip.account.sip_ws_url` / `sip_domain`), not a config param.
Set `res.users.dialer_manual_answer = True` so inbound calls ring with an
**Accept/Decline** bar instead of silently auto-answering.

## 5. Verify

```bash
A="docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml exec -T asterisk-test"
$A asterisk -rx "pjsip show registrations"   # vox_reg → Registered
$A asterisk -rx "pjsip show contacts"        # 1001 has a contact
$A asterisk -rx "pjsip show transports"      # transport-udp:5060, ws:8088, wss:8089
$A asterisk -rx "pjsip set logger on"        # full SIP trace into docker logs
$A asterisk -rx "pjsip show channelstats"    # live RTP counts both directions
```

Outbound smoke test straight down the trunk (rings a real phone, bills a real
call — connects it to the echo/demo extension on answer):
```bash
$A asterisk -rx "channel originate PJSIP/0XXXXXXXXX@vox extension 600@from-agents"
```

## 6. Known gotchas (hard-won)

**Inbound answer stalls — JsSIP non-trickle ICE.** The single worst trap.
JsSIP withholds the SIP `200 OK` until ICE gathering reports **complete**. If the
agent machine has interfaces that cannot reach the TURN server (e.g. Tailscale
v4/v6), Chrome waits on those allocations forever, gathering never completes, the
answer is never sent, and **Asterisk never receives the browser's candidates at
all** — so ICE can never connect. Symptom: the call rings, then dies at *exactly*
30s with `session failed: Canceled`.
- Tell-tale in the browser console: `GATHERING COMPLETE` never appears.
- The 30s cancel comes from **Vox/the mobile network**, not our `Dial()` timeout —
  raising `Dial(PJSIP/1001,30→90)` changes nothing.
- `iceGatheringTimeout` passed to `session.answer()` is **ignored** by this JsSIP build.
- **Fix / knob:** `comm.turn.disable=1` → `get_ice_servers()` returns `[]`, the
  browser gathers host candidates only (instant), the 200 goes out. Valid only
  when agent and Asterisk can reach each other directly (same LAN/tailnet).
  Related knobs: `comm.turn.url_filter` (default `transport=udp,:443`),
  `comm.turn.drop_stun`.

**Deploying `comm_dialer` silently rolls back.** The transcribe cron holds its
`ir_cron` row lock → `LockNotAvailable` → ParseError. Always:
```bash
docker compose stop odoo
docker compose run --rm odoo odoo -d odoo -u comm_dialer --stop-after-init --no-http
docker compose start odoo
```

**`EXTERNAL_IP` is a dynamic public IP.** If it changes, the SDP external address
goes stale. Symmetric RTP mostly masks this for the trunk, but a DDNS updater is
the durable fix.

**Asterisk restarts drop the SIP logger and the softphone registration** — re-arm
`pjsip set logger on` and hard-refresh the agent browser after any restart.

## 7. Troubleshooting

| Symptom | Look at |
|---|---|
| Inbound rings then dies at exactly 30s | The JsSIP gathering trap above — check for `GATHERING COMPLETE` in the console; try `comm.turn.disable=1` |
| Softphone dot never goes green | `pjsip show contacts`; is `sip_ws_url` reachable from that browser? tunnel hostname vs tailnet hostname |
| Softphone click does nothing | Fixed — the pad now always opens and shows connection status |
| Outbound sends no INVITE | Browser mic permission — JsSIP needs the mic to build the offer before it will send |
| Trunk won't register | `pjsip show registrations`; host/port, registration (not IP) auth, `VOX_SECRET` rendered (check length, not value) |
| Calls connect but no audio | ICE — check candidate types in the SDP (`typ host` only = no reachable candidate), and Cloudflare TURN creds |
| No calls placed by the dialer | `dialer_ari` logs; pacer cron active? campaign Running + in window? Ready agents with an endpoint? |

## Rollback / stop
```bash
docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml stop asterisk-test dialer_ari
```
Disabling the "Dialer: pace outbound campaigns" cron halts new originations
immediately; live calls finish on their own.
