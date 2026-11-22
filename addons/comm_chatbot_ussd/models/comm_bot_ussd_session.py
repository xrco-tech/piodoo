# -*- coding: utf-8 -*-
"""One USSD session that runs a flow of the bot engine.

USSD is one screen a turn: the gateway sends what the caller typed and must
get the next screen back at once, as 'CON …' (keep the session open) or
'END …' (close it). Each session is its own conversation: a dial never picks
up a conversation the same contact left open on another channel.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

SCREEN_MAX = 182
WAITS = ('menu', 'input')


class CommBotUssdSession(models.Model):
    _name = 'comm.bot.ussd.session'
    _description = 'USSD session run by a flow'
    _order = 'id desc'
    _rec_name = 'session_id'

    session_id = fields.Char(required=True, index=True,
        help="The gateway's own number for the session.")
    service_code = fields.Char(index=True)
    phone_number = fields.Char(index=True)
    account_id = fields.Many2one('comm.ussd.account', ondelete='set null')
    bot_id = fields.Many2one('comm.bot', ondelete='set null', index=True)
    conversation_id = fields.Many2one('comm.conversation', ondelete='set null')
    breadcrumb = fields.Char(default='', help='Everything typed so far, joined by *.')
    last_response = fields.Text(help='The last screen sent.')
    outcome = fields.Selection([
        ('open', 'Open'),
        ('completed', 'Completed'),
        ('timeout', 'Timed out'),
        ('hangup', 'Ended by the caller'),
        ('error', 'Error'),
    ], default='open', required=True, index=True)

    # ── One turn ─────────────────────────────────────────────────────────

    @api.model
    def ussd_handle(self, session_id, service_code, phone_number, text, latest_input):
        """The next screen for this session, as 'CON …' or 'END …'."""
        try:
            session = self.search([('session_id', '=', session_id),
                                   ('outcome', '=', 'open')], limit=1)
            if session:
                session.breadcrumb = text or ''
                return session._turn(latest_input)
            account = self.env['comm.ussd.account'].sudo().find_for_service_code(service_code)
            bot = account.flow_bot_id
            if not bot or not bot.entry_step_id:
                _logger.warning('USSD %r: no flow, or a flow with no first step', service_code)
                return 'END Service unavailable.'
            return self._open(session_id, account, bot, phone_number, text)._turn(None)
        except Exception:
            _logger.exception('USSD session %r on %r failed', session_id, service_code)
            return 'END Service error.'

    @api.model
    def _open(self, session_id, account, bot, phone_number, text):
        Exec = self.env['comm.chatbot.executor']
        channel = self.env['comm.channel'].get_by_code('ussd')
        partner = Exec._resolve_partner(phone_number, channel)
        conversation = self.env['comm.conversation'].create({
            'partner_id': partner.id,
            'bot_id': bot.id,
            'primary_channel_id': channel.id,
            'current_step_id': bot.entry_step_id.id,
            'lifecycle_state': 'open',
        })
        self.env['comm.conversation.leg'].create({
            'conversation_id': conversation.id,
            'channel_id': channel.id,
            'external_session_id': session_id,
        })
        return self.create({
            'session_id': session_id,
            'service_code': account.service_code,
            'phone_number': phone_number,
            'account_id': account.id,
            'bot_id': bot.id,
            'conversation_id': conversation.id,
            'breadcrumb': text or '',
        })

    def _turn(self, typed):
        """Run the flow as far as it goes on what the caller typed, and
        return the screen. `typed` is None on the first turn."""
        self.ensure_one()
        conversation = self.conversation_id
        if not conversation:
            self.outcome = 'error'
            return 'END Service unavailable.'
        leg = conversation.leg_ids.filtered(lambda l: not l.closed_at)[:1]
        seen = conversation.interaction_ids.ids
        # A gateway allows a few seconds for the answer: AI steps are not run.
        Exec = self.env['comm.chatbot.executor'].with_context(comm_chatbot_skip_llm=True)
        step = conversation.current_step_id
        if typed is not None:
            self.env['comm.interaction'].create({
                'conversation_id': conversation.id,
                'leg_id': leg.id,
                'channel_id': conversation.primary_channel_id.id,
                'direction': 'inbound',
                'raw_body': typed,
                'status': 'received',
                'step_id': step.id,
            })
            seen = conversation.interaction_ids.ids
        if typed is not None and step.kind in WAITS:
            Exec._handle_input(conversation, leg, typed)
        else:
            Exec.advance(conversation, leg)

        said = conversation.interaction_ids.filtered(
            lambda i: i.id not in seen and i.direction == 'outbound').sorted('id')
        screen = '\n'.join(filter(None, (self._plain(i.rendered_body) for i in said)))
        step = conversation.current_step_id
        waiting = (conversation.lifecycle_state not in ('closed', 'timeout', 'handoff')
                   and step.kind in WAITS)
        if len(screen) > SCREEN_MAX:
            screen = screen[:SCREEN_MAX - 3] + '...'
        if not waiting:
            if conversation.lifecycle_state not in ('closed', 'timeout'):
                conversation.close(outcome=conversation.outcome or 'ended')
            self.write({'last_response': screen, 'outcome': 'completed'})
            return 'END ' + (screen or 'Thank you.')
        self.last_response = screen
        return 'CON ' + (screen or 'Please reply.')

    @staticmethod
    def _plain(body):
        """The USSD adapter writes CON or END before what it records."""
        body = body or ''
        return body[4:] if body[:4] in ('CON ', 'END ') else body

    # ── The gateway says the session is over ─────────────────────────────

    @api.model
    def ussd_closed(self, session_id, status, seconds=None):
        session = self.search([('session_id', '=', session_id)], limit=1)
        if not session:
            return False
        if session.conversation_id.lifecycle_state not in ('closed', 'timeout'):
            session.conversation_id.close(outcome=status or 'ended')
        if session.outcome == 'open':
            session = session.with_context(ussd_seconds=seconds) if seconds else session
            session.outcome = status if status in ('timeout', 'hangup', 'completed') else 'completed'
        elif seconds:
            # Already charged at its last screen, by our own clock. The
            # gateway's figure for the length is the one it bills on, so the
            # session is charged again from that.
            session._billing_events().unlink()
            session.with_context(ussd_seconds=seconds)._charge()
        return True

    # ── Charging ─────────────────────────────────────────────────────────

    def _billing_events(self):
        return self.env['comm.billing.event'].sudo().search([
            ('source_model', '=', self._name), ('source_id', 'in', self.ids)])

    def write(self, vals):
        res = super().write(vals)
        if 'outcome' in vals and vals['outcome'] != 'open':
            for session in self:
                try:
                    session._charge()
                except Exception:
                    _logger.exception('USSD billing failed for session %s', session.id)
        return res

    def _charge(self):
        """One billing event a session, by its length, like any USSD session."""
        self.ensure_one()
        if self._billing_events():
            return
        account = self.account_id
        providers = dict(self.env['comm.ussd.account']._fields['provider'].selection)
        seconds = self.env.context.get('ussd_seconds')
        if not seconds and self.create_date:
            seconds = (fields.Datetime.now() - self.create_date).total_seconds()
        self.env['comm.billing.event'].sudo().create({
            'event_date': fields.Datetime.now(),
            'channel': 'ussd',
            'provider': providers.get(account.provider) if account else False,
            'account_ref': account.name or self.service_code,
            'wa_id': self.phone_number,
            'category': 'ussd_session',
            'unit': 'block',
            'unit_qty': 1.0,
            'duration_seconds': seconds or 0.0,
            'service_code': self.service_code,
            'source_model': self._name,
            'source_id': self.id,
        })
