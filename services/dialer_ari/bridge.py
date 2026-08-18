#!/usr/bin/env python3
"""ARI bridge service for comm_dialer.

The Odoo pacer (comm.dialer.campaign._pace_once) creates queued comm.voip.call
rows for Asterisk accounts. This service:

  1. polls Odoo for those queued rows and ORIGINATES the customer leg via ARI,
  2. on answer, reads AMD and — if HUMAN and an agent is Ready — BRIDGES the
     call to that agent's WebRTC endpoint (else plays a message and drops it =
     an "abandoned" call, the predictive trade-off the governor bounds),
  3. on hangup, writes the final state back to Odoo and calls
     comm.dialer.contact.register_result() to drive retry logic.

This is the telephony half of the dialer. It needs a live Asterisk (see
../../asterisk) and a Vox trunk to validate end-to-end. Sections marked TODO
depend on your dialplan/AMD tuning and how you map agents → SIP endpoints.
"""
import asyncio
import json
import logging
import os
import xmlrpc.client

import aiohttp

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
_log = logging.getLogger('dialer_ari')

# ── Config (from env / .env) ────────────────────────────────────────────────
ARI_URL = os.environ.get('ARI_URL', 'http://127.0.0.1:8088')
ARI_USER = os.environ.get('ARI_USERNAME', 'odoo')
ARI_PASS = os.environ.get('ARI_PASSWORD', '')
ARI_APP = os.environ.get('ARI_APP', 'comm_dialer')
TRUNK = os.environ.get('VOX_TRUNK', 'vox')
CALLER_ID = os.environ.get('VOX_DID', '')
POLL_INTERVAL = float(os.environ.get('POLL_INTERVAL', '2'))

ODOO_URL = os.environ.get('ODOO_URL', 'http://odoo:8069')
ODOO_DB = os.environ.get('ODOO_DB', 'odoo')
ODOO_USER = os.environ.get('ODOO_USER', 'dialer@bot')
ODOO_PASS = os.environ.get('ODOO_PASSWORD', '')


# ── Odoo (XML-RPC) ──────────────────────────────────────────────────────────
class Odoo:
    """Thin blocking XML-RPC client; calls are run in a thread executor."""

    def __init__(self):
        common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
        self.uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASS, {})
        if not self.uid:
            raise SystemExit('Odoo auth failed — check ODOO_USER / API key')
        self.models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')
        self._asterisk_accounts = self._call(
            'comm.voip.account', 'search',
            [[['provider', '=', 'asterisk'], ['active', '=', True]]])
        _log.info('Odoo connected (uid=%s), asterisk accounts=%s',
                  self.uid, self._asterisk_accounts)

    def _call(self, model, method, args, kw=None):
        return self.models.execute_kw(ODOO_DB, self.uid, ODOO_PASS, model, method, args, kw or {})

    def pending_calls(self, limit=20):
        """Queued outgoing calls on Asterisk accounts, not yet originated.

        Carries the pre-assigned agent (progressive) as agent_sip_ext +
        dialer_agent_session_id, and the campaign (for predictive pick-on-answer).
        """
        if not self._asterisk_accounts:
            return []
        return self._call('comm.voip.call', 'search_read', [[
            ['state', '=', 'queued'],
            ['external_id', 'in', [False, '']],
            ['dialer_contact_id', '!=', False],
            ['account_id', 'in', self._asterisk_accounts],
        ]], {'fields': ['id', 'to_number', 'dialer_contact_id',
                        'dialer_agent_session_id', 'agent_sip_ext',
                        'dialer_campaign_id'], 'limit': limit})

    def set_call(self, call_id, vals):
        self._call('comm.voip.call', 'write', [[call_id], vals])

    def ready_agent(self, campaign_id):
        """Pick one Ready agent (with an endpoint) for the campaign. Returns
        {'session_id', 'ext'} or None. Used by predictive, which binds an agent
        only once a human answers."""
        if not campaign_id:
            return None
        rows = self._call('comm.dialer.agent.session', 'search_read', [[
            ['state', '=', 'ready'], ['campaign_id', '=', campaign_id],
            ['sip_ext', 'not in', [False, '']],
        ]], {'fields': ['sip_ext'], 'limit': 1})
        return {'session_id': rows[0]['id'], 'ext': rows[0]['sip_ext']} if rows else None

    def set_agent(self, session_id, vals):
        if session_id:
            self._call('comm.dialer.agent.session', 'write', [[session_id], vals])

    def register_result(self, contact_id, outcome):
        self._call('comm.dialer.contact', 'register_result', [[contact_id], outcome])


# ── ARI (REST + WebSocket) ──────────────────────────────────────────────────
class Ari:
    def __init__(self, session):
        self.s = session
        self.auth = aiohttp.BasicAuth(ARI_USER, ARI_PASS)
        self.base = f'{ARI_URL}/ari'

    async def originate(self, endpoint, app_args, caller_id, variables=None):
        params = {
            'endpoint': endpoint, 'app': ARI_APP, 'appArgs': app_args,
            'callerId': caller_id, 'timeout': 30,
        }
        payload = {'variables': variables or {}}
        async with self.s.post(f'{self.base}/channels', params=params,
                               json=payload, auth=self.auth) as r:
            r.raise_for_status()
            return await r.json()

    async def create_bridge(self):
        async with self.s.post(f'{self.base}/bridges', params={'type': 'mixing'},
                               auth=self.auth) as r:
            r.raise_for_status()
            return await r.json()

    async def add_to_bridge(self, bridge_id, channel_id):
        async with self.s.post(f'{self.base}/bridges/{bridge_id}/addChannel',
                               params={'channel': channel_id}, auth=self.auth) as r:
            r.raise_for_status()

    async def get_var(self, channel_id, var):
        async with self.s.get(f'{self.base}/channels/{channel_id}/variable',
                              params={'variable': var}, auth=self.auth) as r:
            if r.status != 200:
                return None
            return (await r.json()).get('value')

    async def hangup(self, channel_id):
        async with self.s.delete(f'{self.base}/channels/{channel_id}', auth=self.auth) as r:
            return r.status


# In-memory map of live customer channels → their Odoo call/contact/campaign.
LIVE = {}  # channel_id -> {'call_id', 'contact_id', 'campaign_id', 'bridge_id'}


# ── The two loops ───────────────────────────────────────────────────────────
async def poll_odoo(odoo, ari, loop):
    """Every tick: turn queued Odoo calls into ARI originations."""
    while True:
        try:
            pending = await loop.run_in_executor(None, odoo.pending_calls)
            for c in pending:
                to = c['to_number']
                endpoint = f'PJSIP/{to}@{TRUNK}'
                try:
                    ch = await ari.originate(endpoint, 'outbound', CALLER_ID,
                                             {'CALL_ID': str(c['id'])})
                    sess = c.get('dialer_agent_session_id')
                    camp = c.get('dialer_campaign_id')
                    LIVE[ch['id']] = {
                        'call_id': c['id'],
                        'contact_id': c['dialer_contact_id'][0],
                        'campaign_id': camp[0] if camp else None,
                        # Pre-assigned agent (progressive); empty for predictive.
                        'session_id': sess[0] if sess else None,
                        'pre_ext': c.get('agent_sip_ext') or None,
                    }
                    await loop.run_in_executor(
                        None, odoo.set_call, c['id'],
                        {'external_id': ch['id'], 'state': 'ringing'})
                    _log.info('originated call %s -> %s (%s)', c['id'], to, ch['id'])
                except Exception:
                    _log.exception('originate failed for call %s', c['id'])
                    await loop.run_in_executor(None, odoo.set_call, c['id'], {'state': 'failed'})
        except Exception:
            _log.exception('poll loop error')
        await asyncio.sleep(POLL_INTERVAL)


async def handle_events(odoo, ari, loop):
    """Consume ARI WebSocket events: bridge answered humans to agents; finalize
    on hangup."""
    ws_url = f'{ARI_URL.replace("http", "ws")}/ari/events?app={ARI_APP}&subscribeAll=true'
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(ws_url, auth=aiohttp.BasicAuth(ARI_USER, ARI_PASS)) as ws:
            _log.info('ARI websocket connected')
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                ev = json.loads(msg.data)
                kind = ev.get('type')
                ch = ev.get('channel', {})
                cid = ch.get('id')

                if kind == 'StasisStart' and (ev.get('args') or [''])[0] == 'outbound':
                    # Customer answered. Read AMD, decide bridge vs abandon.
                    info = LIVE.get(cid)
                    if not info:
                        continue
                    amd = await ari.get_var(cid, 'AMDSTATUS')  # HUMAN / MACHINE / NOTSURE

                    # Progressive pre-assigned an agent; predictive picks one now.
                    ext = info.get('pre_ext')
                    session_id = info.get('session_id')
                    if not ext:
                        picked = await loop.run_in_executor(
                            None, odoo.ready_agent, info['campaign_id'])
                        if picked:
                            ext, session_id = picked['ext'], picked['session_id']

                    if amd == 'MACHINE' or not ext:
                        # Answering machine, or no agent free (predictive over-dial)
                        # => abandoned. TODO: play a short compliance message first.
                        await ari.hangup(cid)
                        await loop.run_in_executor(None, odoo.set_call, info['call_id'],
                                                   {'state': 'cancelled'})
                        # Release a pre-reserved agent back to Ready.
                        if info.get('session_id'):
                            await loop.run_in_executor(
                                None, odoo.set_agent, info['session_id'],
                                {'state': 'ready', 'current_call_id': False})
                    else:
                        bridge = await ari.create_bridge()
                        await ari.add_to_bridge(bridge['id'], cid)
                        agent_ep = f'PJSIP/{ext}'
                        # TODO (recording): to attach the agent's browser
                        # recording to this comm.voip.call, the agent INVITE must
                        # carry X-Voip-Call-Id. Originate via the dialplan instead
                        # of Stasis — Local/{ext}@from-dialer-agent with channel
                        # var __CALLID_HDR=info['call_id'] (see asterisk/etc/
                        # extensions.conf [from-dialer-agent]) — then add the
                        # Local channel to the bridge.
                        try:
                            ach = await ari.originate(agent_ep, 'agent', CALLER_ID)
                            await ari.add_to_bridge(bridge['id'], ach['id'])
                            info['bridge_id'] = bridge['id']
                            info['session_id'] = session_id  # bound agent (predictive)
                            await loop.run_in_executor(None, odoo.set_call, info['call_id'],
                                                       {'state': 'in_progress'})
                            await loop.run_in_executor(
                                None, odoo.set_agent, session_id,
                                {'state': 'on_call', 'current_call_id': info['call_id']})
                        except Exception:
                            _log.exception('agent bridge failed; dropping call')
                            await ari.hangup(cid)
                            await loop.run_in_executor(None, odoo.set_call, info['call_id'],
                                                       {'state': 'cancelled'})
                            if session_id:
                                await loop.run_in_executor(
                                    None, odoo.set_agent, session_id,
                                    {'state': 'ready', 'current_call_id': False})

                elif kind in ('StasisEnd', 'ChannelDestroyed'):
                    info = LIVE.pop(cid, None)
                    if not info:
                        continue
                    # Release the bound agent into wrap-up (they disposition, then
                    # go Ready again for the next call).
                    if info.get('session_id'):
                        await loop.run_in_executor(
                            None, odoo.set_agent, info['session_id'],
                            {'state': 'wrap', 'current_call_id': False})
                    cause = (ev.get('cause_txt') or '').lower()
                    # Map hangup cause -> our outcome.
                    if 'normal' in cause or ev.get('cause') == 16:
                        state, outcome = 'completed', 'completed'
                    elif 'busy' in cause:
                        state, outcome = 'busy', 'busy'
                    elif 'no answer' in cause or 'no user' in cause:
                        state, outcome = 'no_answer', 'no_answer'
                    else:
                        state, outcome = 'failed', 'failed'
                    await loop.run_in_executor(None, odoo.set_call, info['call_id'], {'state': state})
                    await loop.run_in_executor(None, odoo.register_result, info['contact_id'], outcome)


async def main():
    loop = asyncio.get_running_loop()
    odoo = await loop.run_in_executor(None, Odoo)
    async with aiohttp.ClientSession() as s:
        ari = Ari(s)
        await asyncio.gather(
            poll_odoo(odoo, ari, loop),
            handle_events(odoo, ari, loop),
        )


if __name__ == '__main__':
    asyncio.run(main())
