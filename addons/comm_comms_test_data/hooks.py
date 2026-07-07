# -*- coding: utf-8 -*-
"""Populate historical activity so the dashboards, graphs, and pivots have
realistic data to render right after install."""
import logging
import random
from datetime import datetime, timedelta

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def generate_historical_activity(env, registry=None):
    """Called post-install by the module manifest.

    Creates:
    - ~15 conversations across the seeded bots and partners
    - ~50 interactions inside those conversations
    - ~30 campaign sends attached to the running / completed campaigns
    - ~40 billing events spanning WA / SMS / USSD / voice / LLM over the
      last 30 days (so the graph in Comm Billing → Dashboard has range)
    """
    # Odoo 18 post_init hooks receive `env` (or (cr, registry) in older
    # versions). Handle both signatures.
    if registry is not None and not hasattr(env, 'user'):
        env = api.Environment(env, SUPERUSER_ID, {})

    Ref = env.ref
    Convo = env['comm.conversation']
    Leg = env['comm.conversation.leg']
    Interaction = env['comm.interaction']
    Send = env['comm.campaign.send']
    Event = env['comm.billing.event']
    Snapshot = env['comm.campaign.audience.snapshot']

    def _r(xmlid):
        try:
            return Ref(f'comm_comms_test_data.{xmlid}')
        except Exception:
            _logger.warning('test data ref missing: %s', xmlid)
            return None

    now = datetime.now()
    channel_wa = env.ref('comm_chatbot.channel_whatsapp')
    channel_sms = env.ref('comm_chatbot.channel_sms')

    partners = [
        _r('partner_thabo'), _r('partner_naledi'), _r('partner_lerato'),
        _r('partner_kagiso'), _r('partner_zanele'), _r('partner_bongani'),
        _r('partner_palesa'), _r('partner_james'),
    ]
    partners = [p for p in partners if p]

    bots = {
        'booking': _r('bot_booking'),
        'service': _r('bot_service'),
        'onboarding_a': _r('bot_onboarding_a'),
        'onboarding_b': _r('bot_onboarding_b'),
    }

    campaigns = {
        'ab': _r('campaign_onboarding_ab'),
        'service': _r('campaign_service_check'),
    }
    variants = {
        'a': _r('variant_onboarding_a'),
        'b': _r('variant_onboarding_b'),
    }

    # ------------------------------------------------------------------
    # 1. Audience snapshot for the running A/B campaign
    # ------------------------------------------------------------------
    if campaigns['ab']:
        Snapshot.search([('campaign_id', '=', campaigns['ab'].id)]).unlink()
        for p in partners[:5]:
            Snapshot.create({
                'campaign_id': campaigns['ab'].id,
                'partner_id': p.id,
            })

    # ------------------------------------------------------------------
    # 2. Historical conversations + interactions
    # ------------------------------------------------------------------
    scenarios = [
        # (partner, bot_key, channel, days_ago, outcome, closed)
        (partners[0], 'booking',       channel_wa,  1, 'completed', True),
        (partners[1], 'booking',       channel_wa,  2, 'declined',  True),
        (partners[2], 'booking',       channel_sms, 3, 'completed', True),
        (partners[3], 'service',       channel_wa,  4, 'completed', True),
        (partners[4], 'service',       channel_wa,  5, 'error',     True),
        (partners[0], 'onboarding_a',  channel_wa,  7, 'completed', True),
        (partners[1], 'onboarding_b',  channel_wa,  8, 'completed', True),
        (partners[2], 'onboarding_a',  channel_wa,  9, 'completed', True),
        (partners[3], 'onboarding_a',  channel_wa, 10, None,        False),  # open
        (partners[4], 'onboarding_b',  channel_wa, 12, None,        False),  # open
    ]

    for scenario in scenarios:
        partner, bot_key, channel, days_ago, outcome, closed = scenario
        bot = bots.get(bot_key)
        if not (partner and bot and bot.entry_step_id):
            continue
        opened_at = now - timedelta(days=days_ago)
        convo = Convo.create({
            'partner_id': partner.id,
            'bot_id': bot.id,
            'primary_channel_id': channel.id,
            'current_step_id': bot.entry_step_id.id,
            'lifecycle_state': 'closed' if closed else 'waiting',
            'outcome': outcome,
            'opened_at': opened_at,
            'last_activity_at': opened_at + timedelta(minutes=15),
            'closed_at': opened_at + timedelta(minutes=15) if closed else False,
        })
        leg = Leg.create({
            'conversation_id': convo.id,
            'channel_id': channel.id,
            'external_session_id': f'test-{convo.id}',
            'opened_at': opened_at,
            'closed_at': opened_at + timedelta(minutes=15) if closed else False,
        })
        # 3-6 interactions per conversation
        n = random.randint(3, 6)
        for i in range(n):
            direction = 'outbound' if i % 2 == 0 else 'inbound'
            Interaction.create({
                'conversation_id': convo.id,
                'leg_id': leg.id,
                'channel_id': channel.id,
                'direction': direction,
                'at': opened_at + timedelta(minutes=i * 2),
                'rendered_body': _sample_body(bot_key, direction, i),
                'status': 'sent' if direction == 'outbound' else 'received',
            })

    # ------------------------------------------------------------------
    # 3. Campaign sends for the A/B and completed campaigns
    # ------------------------------------------------------------------
    if campaigns['ab']:
        for i, partner in enumerate(partners[:5]):
            variant = variants['a'] if i % 2 == 0 else variants['b']
            sent_at = now - timedelta(hours=6 + i * 2)
            Send.create({
                'campaign_id': campaigns['ab'].id,
                'partner_id': partner.id,
                'variant_id': variant.id if variant else False,
                'chosen_channel_id': channel_wa.id,
                'status': random.choice(['sent', 'delivered']),
                'sent_at': sent_at,
                'conversion_registered': (i < 2),
                'billed_usd': 0.0379,
                'billed_local': 0.0379 * 18.5,
            })

    if campaigns['service']:
        for i, partner in enumerate(partners[:6]):
            sent_at = now - timedelta(days=3 + i)
            Send.create({
                'campaign_id': campaigns['service'].id,
                'partner_id': partner.id,
                'chosen_channel_id': channel_wa.id,
                'status': 'delivered',
                'sent_at': sent_at,
                'conversion_registered': True,
                'billed_usd': 0.0076,
                'billed_local': 0.0076 * 18.5,
            })

    # ------------------------------------------------------------------
    # 4. Billing events across channels + models over 30 days
    # ------------------------------------------------------------------
    za_country = env.ref('base.za', raise_if_not_found=False)
    _create_billing_events(env, za_country, channel_wa, channel_sms,
                           partners, now)

    _logger.info('Comms test data: historical activity generated.')


def _sample_body(bot_key, direction, idx):
    """Rough sample text so transcripts don't look empty."""
    outbound_samples = {
        'booking': [
            'Hi! I can help you book an appointment.',
            'Would you like to proceed? Reply Yes or No.',
            'Great! What date would you like? (YYYY-MM-DD)',
            'Confirmed! See you then.',
        ],
        'service': [
            'Hi! What can I help you with?',
            'Type your question or request.',
            'Your current balance is R 2,450.00.',
        ],
        'onboarding_a': [
            'Welcome aboard! I\'m here to help you get set up. We offer three services...',
            'Which service would you like to explore first?',
            'Great choice — an advisor will reach out within 24 hours.',
        ],
        'onboarding_b': [
            'Welcome. What are you here for?',
            'Pick one: Personal / Business / Wealth',
            'Got it — advisor incoming.',
        ],
    }
    inbound_samples = ['Yes', 'No', '1', '2', '2026-08-15', 'Personal', 'Help me',
                       'What is my balance?']
    if direction == 'outbound':
        pool = outbound_samples.get(bot_key, ['(bot message)'])
        return pool[idx // 2 % len(pool)]
    return random.choice(inbound_samples)


def _create_billing_events(env, za, wa, sms, partners, now):
    Event = env['comm.billing.event']
    Card = env['comm.billing.rate.card']

    def _create(days_ago, channel_code, category, unit, qty,
                carrier=None, provider=None, partner=None,
                unit_price_usd=None):
        card = Card.active_on(channel_code, (now - timedelta(days=days_ago)).date())
        vals = {
            'event_date': now - timedelta(days=days_ago,
                                          hours=random.randint(0, 20)),
            'channel': channel_code,
            'category': category,
            'unit': unit,
            'unit_qty': qty,
            'wa_id': partner.mobile if partner else False,
            'partner_id': partner.id if partner else False,
            'country_id': za.id if za else False,
            'provider': provider,
        }
        if carrier:
            vals['carrier'] = carrier
        if unit_price_usd is not None:
            vals['price_usd'] = unit_price_usd * qty
        return Event.create(vals)

    # WA marketing (a burst 3 days ago) + trickle over last 30
    for i in range(15):
        _create(days_ago=random.randint(0, 30),
                channel_code='whatsapp', category='marketing',
                unit='message', qty=1, provider='Meta',
                partner=random.choice(partners))
    # WA authentication (steady state)
    for i in range(8):
        _create(days_ago=random.randint(0, 30),
                channel_code='whatsapp', category='authentication',
                unit='message', qty=1, provider='Meta',
                partner=random.choice(partners))
    # SMS outbound
    for i in range(10):
        _create(days_ago=random.randint(0, 30),
                channel_code='sms', category='sms_outbound_domestic',
                unit='segment', qty=random.randint(1, 3), provider='Infobip',
                partner=random.choice(partners))
    # LLM (Sonnet + a bit of Haiku)
    for i in range(6):
        _create(days_ago=random.randint(0, 20),
                channel_code='other', category='llm_input',
                unit='kilotoken', qty=round(random.uniform(0.5, 3.0), 2),
                carrier='claude-sonnet-4-6', provider='Anthropic',
                partner=random.choice(partners))
        _create(days_ago=random.randint(0, 20),
                channel_code='other', category='llm_output',
                unit='kilotoken', qty=round(random.uniform(0.1, 0.6), 2),
                carrier='claude-sonnet-4-6', provider='Anthropic',
                partner=random.choice(partners))
    for i in range(3):
        _create(days_ago=random.randint(0, 15),
                channel_code='other', category='llm_input',
                unit='kilotoken', qty=round(random.uniform(0.4, 1.5), 2),
                carrier='claude-haiku-4-5', provider='Anthropic',
                partner=random.choice(partners))
