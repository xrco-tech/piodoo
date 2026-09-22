# The `asterisk-test` box — agent softphone + the live Vox trunk

Originally a trunk-less rig for validating the WebRTC softphone. **It is now the
box that carries the live Vox trunk too** — the trunk config was bolted on here
rather than on `docker-compose.asterisk.yml`, because this was the Asterisk whose
WebRTC path was already proven. Treat it as the running telephony node.

Endpoints: `1001` (the Odoo agent softphone) and `1002` (the standalone
`dialer.html` test client). **Secrets are hard-coded in `pjsip.conf`** — fine for
this single-tenant box, not something to copy into a multi-tenant deployment.

## Bring up
```bash
cd /home/ubuntu/odoo-stack
docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml up -d asterisk-test
```
The entrypoint renders `${VOX_*}`, `${TURN_*}`, `${EXTERNAL_IP}`, `${LOCAL_NET}`
from `.env` into `/etc/asterisk/*.conf`, so a **restart is how you apply config
changes**.

## How the softphone reaches it

Two working paths — the Odoo VoIP account record decides which
(`comm.voip.account.sip_ws_url` + `sip_domain`):

| Path | URL | Notes |
|---|---|---|
| **Cloudflare tunnel** (remote agents) | `wss://pbx.xrco.tech/ws` | Edge terminates TLS → Asterisk gets **plain ws on :8088**. Needs `[transport-ws]` and endpoints with **no** `transport=` pin. |
| **Tailscale direct** (tailnet agents) | `wss://ubuntu.taild8679b.ts.net:8089/ws` | Real WSS on :8089 using the Tailscale cert (CN `ubuntu.taild8679b.ts.net`). Bypasses the tunnel — steadier, but only for tailnet machines. |

Agent side: `res.users.dialer_sip_ext` = `1001`, `dialer_sip_secret` =
`test1001secret`, and set `dialer_manual_answer = True` so inbound calls present
an **Accept/Decline** bar. Reload Odoo → systray headphones dot goes **green**.

```bash
A="docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml exec -T asterisk-test"
$A asterisk -rx "pjsip show contacts"        # 1001 registered
$A asterisk -rx "pjsip show registrations"   # vox_reg → Registered
```

## Audio tests

**Echo to the softphone** (rings 1001; with manual answer you now click Accept):
```bash
$A asterisk -rx "channel originate PJSIP/1001 application Echo"
```

**Outbound down the live trunk** — rings a real phone and bills a real call:
```bash
$A asterisk -rx "channel originate PJSIP/0XXXXXXXXX@vox extension 600@from-agents"
```

**Inbound** — call the DID `27108221225`; `[from-vox]` rings `PJSIP/1001`.

Confirm media either way:
```bash
$A asterisk -rx "pjsip show channelstats"   # balanced rx/tx counts = two-way audio
```

**Two-endpoint test (optional):** open `dialer.html` in a second browser (edit the
WSS URL/domain; pre-filled for `1002` / `test1002secret`), register, then **Call
1001**. Dial `600` for a standalone echo.

## Debugging

- **Browser DevTools ▸ Network ▸ WS** — the socket must reach **101 Switching
  Protocols**. If not, it's cert/reachability; fix that before anything else.
- **Console, `[softphone]` lines** (enable **Verbose** — they're `console.debug`).
- **`chrome://webrtc-internals`** — live ICE + audio stats.
- Asterisk: `pjsip set logger on` (full SIP trace into `docker compose logs`),
  `pjsip show channelstats`, `pjsip show transports`.

### The trap that will cost you a day

**Inbound rings, then dies at exactly 30s with `cause=Canceled`, and the
softphone never sends a `200 OK`.**

JsSIP is **non-trickle**: it withholds the SIP answer until ICE gathering reports
**complete**. If the agent machine has interfaces that can't reach the TURN
server (Tailscale v4/v6 are the usual culprits), Chrome waits on those
allocations, gathering never finishes, the answer never goes out — and therefore
**Asterisk never receives the browser's candidates at all**, so ICE cannot
possibly connect. Every "ICE failed / disconnected" you see is a *symptom*, not
the cause.

- Tell-tale: `localCand: GATHERING COMPLETE` **never appears** in the console.
- The 30s cancel comes from **Vox/the mobile network** (`CANCEL sip:<DID>@…`
  arrives first) — raising `Dial(...,30→90)` does nothing.
- `iceGatheringTimeout` on `session.answer()` is **ignored** by this JsSIP build.
- **Fix:** `comm.turn.disable=1` → no ICE servers → host-only gathering completes
  instantly → the 200 goes out. Only valid when agent and Asterisk can reach each
  other directly (same LAN/tailnet). Other knobs: `comm.turn.url_filter`
  (default `transport=udp,:443`), `comm.turn.drop_stun`.

Also worth knowing: **ICE stuck at `checking` across NAT** means no reachable
candidate pair — check the SDP for `typ srflx`/`typ relay`, not just `typ host`.
Asterisk gets its relay from Cloudflare TURN via `rtp.conf` (`turnaddr`); those
creds expire after 48h.

## Teardown
```bash
docker compose -f docker-compose.yml -f docker-compose.asterisk-test.yml down
```
⚠️ This now takes the **live trunk** down with it.
