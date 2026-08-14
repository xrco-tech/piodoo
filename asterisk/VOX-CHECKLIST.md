# Vox SIP trunk — procurement checklist

Everything to request/decide so the Asterisk dialer can place calls. Each answer
maps to a field in `.env` / `pjsip.conf` (noted as → `VAR`).

---

## A. Ask Vox for these (the trunk spec)

1. **SIP trunk for an outbound contact-centre / dialer application.** Say up front
   it's an **automated (progressive & predictive) dialer** — see §D — so they put
   you on a trunk/AUP that permits it. This is the single most important question:
   some ITSPs restrict or ban predictive dialing, and getting cut mid-campaign is
   the worst outcome.
2. **Auth mode** — which do they support, and pick one:
   - **Registration** (username + secret): NAT-friendly, no static IP needed.
     → `VOX_USERNAME`, `VOX_SECRET`
   - **IP-based**: they whitelist your public IP (needs a static public IP our side).
   - **SIP server host + port** either way. → `VOX_SIP_HOST`, `VOX_SIP_PORT`
   - Transport: UDP/TCP on 5060, or **TLS** on 5061? (TLS preferred if offered.)
3. **DID** (a South African number) for caller-ID presentation + inbound. → `VOX_DID`
4. **Concurrent channels** (simultaneous calls) — how many, and price per channel.
   Size to peak (see §B sizing). Predictive over-dials, so you need more channels
   than agents.
5. **Outbound CLI / caller-ID presentation** — can you present your DID as the
   caller ID? Any **CLI verification** needed? (Under the CPA you must present a
   valid, reachable number — get this right.)
6. **Codecs** — confirm **alaw** (and ulaw) are available. → `VOX_CODECS`
7. **Per-minute rates** — mobile vs fixed-line, billing increment (per-second?),
   any setup / monthly channel fee.
8. **CPS (calls-per-second) cap** — the max origination rate on the trunk. (Our
   pacer opens lines once a minute, so CPS is low — but confirm there's headroom.)
9. **NAT** — confirm the trunk works with Asterisk **behind NAT** (registration +
   symmetric RTP). If IP-auth, they'll need our static public IP.

## B. Decisions on our side

- **Channel sizing** (rule of thumb): `channels ≈ peak_agents ÷ answer_rate × pacing_ratio`.
  e.g. **5 agents**, ~30% answer, ratio 1.0 → ~**17 channels** → order ~**20**.
  Start smaller for progressive (≈ agents + a few), grow for predictive.
- **Auth mode**: default to **registration** (works behind NAT, no static IP).
- **DID**: new number from Vox, or port an existing one (ask about porting if so).

## C. The media / networking reality (READ THIS)

Two separate audio (RTP) paths, and **neither can go through the Cloudflare tunnel**
(that carries HTTP/WS only):

1. **Trunk leg** (Asterisk ↔ Vox): with a **registration** trunk + `rtp_symmetric` +
   NAT keepalive, Asterisk behind NAT works **if** the router forwards the RTP UDP
   range (`10000–10200/udp`) + `5060/udp` to the box, and `EXTERNAL_IP` is the box's
   public WAN IP (use DDNS if it's dynamic).
2. **Agent leg** (browser ↔ Asterisk, WebRTC): browsers need a reachable media
   candidate — either the box on a **public IP** (open the RTP range + `8089/tcp`),
   or a **TURN server** (coturn) to relay when it isn't.

**Cleanest fix: a static public IP on the ubuntu box** + port-forwarding — it solves
both legs and lets agents connect without TURN. If this box is on residential
CGNAT (no inbound IP possible), the realistic options are:
   - **(recommended fallback)** run Asterisk on a **small cloud VM with a public IP**
     (contradicts "same box", but removes all NAT pain), **or**
   - keep it on-box with **registration trunk + port-forwarding + DDNS** for the
     trunk **and add coturn** for agents.

→ Action: ask your ISP whether a **static public IP** (and inbound ports) is
available for the box. That answer decides on-box-vs-cloud and TURN-or-not.

## D. Ready-to-send message to Vox

> Subject: SIP trunk for an outbound dialer (Asterisk) — quote & AUP
>
> Hi Vox team,
>
> I'm setting up an **Asterisk**-based outbound contact-centre that uses
> **progressive and predictive dialing**. Before ordering I'd like to confirm:
>
> 1. Do you offer a SIP trunk that **permits automated / predictive dialing**, and
>    are there any fair-use or CPS limits I should know about?
> 2. Auth options — **registration (user/secret)** vs **IP-based** — and your SIP
>    server host/port and supported transport (UDP/TLS)?
> 3. Pricing for **~20 concurrent channels** (I'll confirm the final count), and
>    **per-minute rates** to SA mobile and fixed lines (billing increment)?
> 4. A **DID** for caller-ID + inbound, and any **CLI presentation / verification**
>    requirements for outbound?
> 5. Supported **codecs** (I'll use alaw/ulaw)?
> 6. Any requirements for running Asterisk **behind NAT**?
>
> Thanks — happy to jump on a call.

## E. Where the answers land

| Vox answer | Goes in |
|---|---|
| SIP host / port | `.env` → `VOX_SIP_HOST`, `VOX_SIP_PORT` |
| Username / secret (registration) | `.env` → `VOX_USERNAME`, `VOX_SECRET` |
| DID (caller ID) | `.env` → `VOX_DID` (+ Odoo VoIP account Caller ID) |
| Codecs | `.env` → `VOX_CODECS` |
| IP-auth? | comment out `[vox_reg]` in `pjsip.conf`; give Vox the box's static IP |
| Public IP available? | `.env` → `EXTERNAL_IP`; decides coturn yes/no |

Once A–E are answered, follow `RUNBOOK.md` from step 1.
