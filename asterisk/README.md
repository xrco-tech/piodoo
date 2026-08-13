# Asterisk dialer engine (progressive + predictive)

This is the media engine behind `comm_dialer`. Asterisk originates the customer
leg over the **Vox** SIP trunk, runs **AMD** (answering-machine detection), and
bridges answered human calls to a Ready agent's **WebRTC** softphone — driven by
the **ARI bridge service** in `../services/dialer_ari`.

```
Odoo pacer ──creates queued comm.voip.call──▶ ARI bridge service
                                                    │  (ARI: originate / AMD / bridge)
                                                    ▼
   PSTN ◀── Vox SIP trunk ── Asterisk ── WSS ──▶ agent browser softphone (SIP.js)
```

## What you must supply before bring-up

1. **Vox SIP trunk details** (put in `.env`, see `env.sample`):
   - SIP server host/port, and whether auth is **registration** (user/secret) or **IP-based**
   - your **DID** (the caller-ID number Vox assigns)
   - allowed **codecs** (usually `alaw`/`ulaw`) and **concurrent channel** count
2. **A decision on agent audio (WebRTC media).** Your Cloudflare tunnel carries
   HTTP/WS only — it **cannot carry RTP media**. For agents' browser audio you need
   either a **public IP** on the box (open the RTP UDP range + 8089/tcp for WSS) or a
   **TURN server** (coturn). Trunk↔Asterisk media rides the Vox trunk and is fine;
   this only affects the browser softphone leg.
3. **TLS cert** for `wss://` (WebRTC). Reuse a Let's Encrypt cert or terminate at
   Asterisk's `http.conf` tls settings.

## Files
- `etc/pjsip.conf`   — transports, the Vox trunk, and a WebRTC agent template
- `etc/extensions.conf` — dialplan: customer leg → AMD → Stasis(comm_dialer); agent context
- `etc/ari.conf`     — enables ARI for the bridge service (`odoo` user)
- `etc/http.conf`    — HTTP/WS(S) server that ARI + WebRTC ride on
- `etc/rtp.conf`     — RTP media port range
- `env.sample`       — copy to `.env`, fill in Vox creds + host IP

Bring-up is via `../docker-compose.asterisk.yml` (an opt-in overlay on the
odoo-stack). Nothing here starts until you run that overlay.
