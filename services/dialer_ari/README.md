# Dialer ARI bridge service

Turns queued `comm.voip.call` rows (created by the Odoo dialer pacer for
`provider=asterisk` accounts) into real calls via Asterisk ARI: originate →
AMD → bridge to a Ready agent, then write the outcome back to Odoo.

## Run (with the Asterisk overlay)
    cp ../../asterisk/env.sample ../../.env    # then fill in Vox + host + ARI + Odoo
    docker compose -f docker-compose.yml -f docker-compose.asterisk.yml up -d asterisk dialer_ari

## Needs before it works end-to-end
- A live Asterisk with the Vox trunk registered (../../asterisk).
- An Odoo user (ODOO_USER) + API key with access to comm.voip.call and
  comm.dialer.contact.
- A comm.voip.account (provider=asterisk) filled in: ARI URL/user/pass, trunk.
- Each agent needs a **SIP endpoint** set (res.users.dialer_sip_ext, editable on
  the Dialer Console / agent session as "SIP Endpoint") matching a pjsip.conf
  endpoint. The service bridges to PJSIP/<ext>; Ready agents without an ext are
  skipped. Progressive pre-assigns the agent at dial time; predictive binds a
  Ready agent on answer.
- Remaining TODO in bridge.py: play a compliance message on abandoned/machine
  calls before hangup.
