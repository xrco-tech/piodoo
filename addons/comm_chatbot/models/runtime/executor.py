# -*- coding: utf-8 -*-
"""The executor — advances a conversation through its bot's step graph.

Public entry points:
  - `ExecutorService.on_inbound(env, channel_code, source_record, wa_id, body)`
      Called by channel adapters when an inbound message lands.
  - `ExecutorService.start(env, bot, partner, channel_code, campaign_id=None)`
      Called by campaign / scheduler to open a conversation and run entry step.
  - `ExecutorService.advance(env, conversation)`
      Internal — runs the current step and moves forward.
"""
import logging
from odoo import models, fields, api

from . import adapter_registry
from .renderer import RenderError

_logger = logging.getLogger(__name__)


class ExecutorService(models.AbstractModel):
    _name = 'comm.chatbot.executor'
    _description = 'Bot step executor / runtime state machine'

    # ---------- Public: inbound ----------
    @api.model
    def on_inbound(self, channel_code, source_model, source_id,
                   wa_id, body, at=None, external_session_id=None):
        """Handle an inbound message from a channel adapter."""
        channel = self.env['comm.channel'].get_by_code(channel_code)
        if not channel:
            _logger.info('No comm.channel for code=%s', channel_code)
            return

        partner = self._resolve_partner(wa_id, channel)
        conversation = self._find_open_conversation(partner, channel)
        if not conversation:
            trigger = self.env['comm.bot.trigger'].find_trigger(
                channel_code, body)
            if not trigger:
                _logger.info('No trigger matched for %s / %r', channel_code, body)
                return
            conversation = self.env['comm.conversation'].find_or_open(
                partner, trigger.bot_id, channel, external_session_id)

        # Ensure a leg exists for this channel
        leg = self._ensure_leg(conversation, channel, source_model, source_id,
                               external_session_id)
        conversation.primary_channel_id = channel

        # Log the inbound interaction
        self.env['comm.interaction'].create({
            'conversation_id': conversation.id,
            'leg_id': leg.id,
            'channel_id': channel.id,
            'direction': 'inbound',
            'at': at or fields.Datetime.now(),
            'raw_body': body or '',
            'source_model': source_model,
            'source_id': source_id,
            'status': 'received',
            'step_id': conversation.current_step_id.id,
        })
        conversation.touch()

        # If there's a current step waiting for input, handle it
        if conversation.current_step_id and conversation.current_step_id.kind in (
                'menu', 'input'):
            self._handle_input(conversation, leg, body)
        else:
            # No pending input — advance from entry or current step
            self.advance(conversation, leg)

    @api.model
    def start(self, bot, partner, channel_code, campaign_id=None):
        """Open a fresh conversation and run entry step (used by campaigns)."""
        channel = self.env['comm.channel'].get_by_code(channel_code)
        if not channel or not bot.entry_step_id:
            return self.env['comm.conversation']
        conversation = self.env['comm.conversation'].create({
            'partner_id': partner.id,
            'bot_id': bot.id,
            'primary_channel_id': channel.id,
            'current_step_id': bot.entry_step_id.id,
            'campaign_id': campaign_id,
        })
        leg = self._ensure_leg(conversation, channel, None, None, None)
        self.advance(conversation, leg)
        return conversation

    # ---------- Core advance loop ----------
    @api.model
    def advance(self, conversation, leg=None):
        """Execute steps until we hit a waiting state or end."""
        if not conversation.current_step_id:
            return
        # Bounded loop to prevent runaway
        for _ in range(50):
            step = conversation.current_step_id
            if not step:
                break
            try:
                next_step = self._execute_step(step, conversation, leg)
            except RenderError as e:
                self._handle_render_error(conversation, step, e)
                next_step = conversation.bot_id.on_error_step_id
            if next_step and next_step.id != step.id:
                conversation.current_step_id = next_step
                if next_step.kind in ('menu', 'input', 'wait'):
                    conversation.lifecycle_state = 'waiting'
                    break
                continue
            if step.kind in ('menu', 'input', 'wait'):
                conversation.lifecycle_state = 'waiting'
            break

    # ---------- Step dispatchers ----------
    def _execute_step(self, step, conversation, leg):
        conversation.touch()
        kind = step.kind
        handler = getattr(self, f'_execute_{kind}', None)
        if not handler:
            _logger.warning('No handler for step kind=%s', kind)
            return step.next_step_id
        return handler(step, conversation, leg)

    # message: render + send + advance
    def _execute_message(self, step, conversation, leg):
        self._render_and_send(step, conversation, leg)
        return step.next_step_id

    # menu: render + send + wait for input (caller handles)
    def _execute_menu(self, step, conversation, leg):
        self._render_and_send(step, conversation, leg)
        return step  # stay here, waiting

    # input: render prompt + send + wait
    def _execute_input(self, step, conversation, leg):
        self._render_and_send(step, conversation, leg)
        return step  # stay here, waiting

    # condition: no output; branch by evaluating expression
    def _execute_condition(self, step, conversation, leg):
        renderer = self.env['comm.chatbot.renderer']
        result = renderer._eval_condition(step.condition_expression or '',
                                          conversation)
        # Pick first option matching branch; is_default = else-branch
        options = step.option_ids.sorted('sequence')
        target = None
        for opt in options:
            if opt.is_default and not result:
                target = opt.next_step_id
                break
            if not opt.is_default and result:
                target = opt.next_step_id
                break
        return target or step.next_step_id

    # action: run executor, save result to state
    def _execute_action(self, step, conversation, leg):
        try:
            result = self._run_action(step, conversation)
            if step.action_save_to:
                state = dict(conversation.state or {})
                state[step.action_save_to] = result
                conversation.state = state
        except Exception as e:
            _logger.warning('Action step %s failed: %s', step.id, e)
            if step.on_unsupported_step_id:
                return step.on_unsupported_step_id
        return step.next_step_id

    def _run_action(self, step, conversation):
        cfg = step.action_config or {}
        if step.action_executor == 'http':
            import requests, json
            url = cfg.get('url')
            method = cfg.get('method', 'POST').upper()
            headers = cfg.get('headers') or {}
            payload = cfg.get('payload') or {}
            # Substitute Mustache in payload strings
            renderer = self.env['comm.chatbot.renderer']
            for k, v in list(payload.items()):
                if isinstance(v, str):
                    payload[k] = renderer._substitute(v, conversation,
                                                      conversation.bot_id)
            r = requests.request(method, url, json=payload, headers=headers,
                                 timeout=cfg.get('timeout_sec', 15))
            r.raise_for_status()
            try:
                return r.json()
            except ValueError:
                return r.text
        if step.action_executor == 'odoo':
            model = self.env[cfg['model']]
            method = getattr(model, cfg['method'])
            return method(**(cfg.get('kwargs') or {}))
        if step.action_executor == 'python':
            fn = adapter_registry.get_python_tool(cfg.get('callable_key'))
            if not fn:
                raise Exception(f'No python tool: {cfg.get("callable_key")}')
            return fn(self.env, conversation, cfg.get('args') or {})
        return None

    # handoff: mark conversation for agent, send handoff message
    def _execute_handoff(self, step, conversation, leg):
        conversation.lifecycle_state = 'handoff'
        conversation.assigned_team_code = (step.handoff_team_id
                                            or conversation.bot_id.handoff_team_id)
        # Send the handoff message text
        if step.handoff_message:
            self._send_body_only(conversation, leg, step.handoff_message, step)
        return None  # engine yields

    # llm: delegate to llm_client
    def _execute_llm(self, step, conversation, leg):
        return self.env['comm.chatbot.llm']._run_llm_step(step, conversation, leg)

    # jump: move to target step or bot
    def _execute_jump(self, step, conversation, leg):
        if step.jump_target_bot_id:
            # Start a fresh conversation on target bot; close this one
            self._start_child_bot(step.jump_target_bot_id, conversation)
            return None
        return step.jump_target_step_id or step.next_step_id

    # wait: schedule resumption
    def _execute_wait(self, step, conversation, leg):
        import datetime as dt
        if step.wait_seconds:
            resume_at = fields.Datetime.now() + dt.timedelta(seconds=step.wait_seconds)
        elif step.wait_until_variable:
            resume_iso = (conversation.state or {}).get(step.wait_until_variable)
            resume_at = fields.Datetime.from_string(resume_iso) if resume_iso else fields.Datetime.now()
        else:
            resume_at = fields.Datetime.now()
        conversation.timeout_at = max(resume_at, conversation.timeout_at or resume_at)
        return step  # engine yields

    # end: close conversation
    def _execute_end(self, step, conversation, leg):
        conversation.close(outcome=step.end_outcome or 'ended', state='closed')
        return None

    # channel_switch: send bridge message + wait for user on target channel
    def _execute_channel_switch(self, step, conversation, leg):
        target = step.channel_switch_target_id
        if not target:
            return step.next_step_id
        self._send_body_only(conversation, leg, step.channel_switch_message, step)
        conversation.primary_channel_id = target
        conversation.lifecycle_state = 'waiting'
        return step  # yield

    # ---------- Input handling ----------
    def _handle_input(self, conversation, leg, body):
        step = conversation.current_step_id
        state = dict(conversation.state or {})

        if step.kind == 'menu':
            option = self._match_option(step, body, conversation)
            if not option:
                # Retry: could bounce to input_retry_step_id; for now just re-send
                self.advance(conversation, leg)
                return
            if step.input_save_to:
                state[step.input_save_to] = option['value']
                conversation.state = state
            conversation.current_step_id = self.env['comm.bot.step'].browse(
                option['next_step_id']) if option.get('next_step_id') else step.next_step_id
            conversation.lifecycle_state = 'open'
            self.advance(conversation, leg)
            return

        if step.kind == 'input':
            value = self._parse_input(step, body)
            if value is None and step.input_retry_step_id:
                conversation.current_step_id = step.input_retry_step_id
                self.advance(conversation, leg)
                return
            if step.input_save_to:
                state[step.input_save_to] = value
                conversation.state = state
            conversation.current_step_id = step.next_step_id
            conversation.lifecycle_state = 'open'
            self.advance(conversation, leg)
            return

    def _match_option(self, step, body, conversation):
        renderer = self.env['comm.chatbot.renderer']
        options = renderer._resolve_options(step, conversation)
        b = (body or '').strip().lower()
        # Try numeric key first
        for i, o in enumerate(options):
            if b == str(i + 1) or b == o.get('numeric_key', ''):
                return o
        # Then value / label match
        for o in options:
            if o['value'].lower() == b or o['label'].lower() == b:
                return o
        # Fall back to default
        for o in options:
            if o.get('is_default'):
                return o
        return None

    def _parse_input(self, step, body):
        t = step.input_type or 'text'
        b = (body or '').strip()
        if not b:
            return None
        if step.input_validation_regex:
            import re
            if not re.search(step.input_validation_regex, b):
                return None
        if t == 'text':
            return b
        if t == 'number':
            try:
                return float(b) if '.' in b else int(b)
            except ValueError:
                return None
        if t == 'date':
            import datetime as dt
            for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
                try:
                    return dt.datetime.strptime(b, fmt).date().isoformat()
                except ValueError:
                    continue
            return None
        if t == 'email':
            import re
            return b if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', b) else None
        if t == 'phone':
            return b
        return b

    # ---------- Render + send ----------
    def _render_and_send(self, step, conversation, leg):
        adapter = self._get_adapter(leg.channel_id if leg else conversation.primary_channel_id)
        renderer = self.env['comm.chatbot.renderer']
        payload = renderer.render(step, conversation, leg)

        interaction = self.env['comm.interaction'].create({
            'conversation_id': conversation.id,
            'leg_id': leg.id if leg else False,
            'channel_id': (leg.channel_id if leg else conversation.primary_channel_id).id,
            'direction': 'outbound',
            'step_id': step.id,
            'raw_body': step.body or '',
            'rendered_body': payload.get('body', ''),
            'status': 'rendered',
        })

        # Shadow-mode: do not actually send. force_shadow via context is
        # used by the preview walker to advance a live bot without sending.
        force_shadow = self.env.context.get('comm_chatbot_force_shadow')
        if conversation.bot_id.engine_mode == 'shadow' or force_shadow:
            interaction.status = 'sent'
            return interaction

        if not adapter:
            interaction.write({'status': 'failed',
                               'error': 'no adapter registered'})
            return interaction

        try:
            result = adapter().send(self.env, interaction, payload)
            interaction.write({
                'status': result.get('status', 'sent'),
                'source_model': result.get('source_model'),
                'source_id': result.get('source_id'),
                'error': result.get('error'),
            })
        except Exception as e:
            _logger.warning('Adapter send failed for interaction %s: %s',
                            interaction.id, e)
            interaction.write({'status': 'failed', 'error': str(e)})
        return interaction

    def _send_body_only(self, conversation, leg, body, step):
        adapter = self._get_adapter(leg.channel_id if leg else conversation.primary_channel_id)
        renderer = self.env['comm.chatbot.renderer']
        substituted = renderer._substitute(body, conversation, conversation.bot_id)
        interaction = self.env['comm.interaction'].create({
            'conversation_id': conversation.id,
            'leg_id': leg.id if leg else False,
            'channel_id': (leg.channel_id if leg else conversation.primary_channel_id).id,
            'direction': 'outbound',
            'step_id': step.id if step else False,
            'raw_body': body,
            'rendered_body': substituted,
            'status': 'rendered',
        })
        force_shadow = self.env.context.get('comm_chatbot_force_shadow')
        if (conversation.bot_id.engine_mode == 'shadow' or force_shadow
                or not adapter):
            interaction.status = 'sent'
            return interaction
        try:
            result = adapter().send(self.env, interaction,
                                    {'body': substituted, 'options': [], 'media': []})
            interaction.write({'status': result.get('status', 'sent'),
                               'source_model': result.get('source_model'),
                               'source_id': result.get('source_id')})
        except Exception as e:
            interaction.write({'status': 'failed', 'error': str(e)})
        return interaction

    # ---------- Helpers ----------
    def _get_adapter(self, channel):
        return self.env['comm.chatbot.registry'].get_adapter_for_channel(channel)

    def _handle_render_error(self, conversation, step, error):
        _logger.warning('Render error on conversation %s step %s: %s',
                        conversation.id, step.id, error)
        self.env['comm.interaction'].create({
            'conversation_id': conversation.id,
            'channel_id': conversation.primary_channel_id.id,
            'direction': 'outbound',
            'step_id': step.id,
            'raw_body': step.body or '',
            'status': 'failed',
            'render_error_type': type(error).__name__,
            'error': str(error),
        })

    def _resolve_partner(self, wa_id, channel):
        Partner = self.env['res.partner'].sudo()
        # 1. Match on channel-specific identity
        if channel.code == 'whatsapp':
            partner = Partner.search([('whatsapp_id', '=', wa_id)], limit=1)
            if partner:
                return partner
        # 2. Match on MSISDN
        partner = Partner.search([('mobile', '=', wa_id)], limit=1)
        if partner:
            return partner
        partner = Partner.search([('phone', '=', wa_id)], limit=1)
        if partner:
            return partner
        # 3. Create new
        return Partner.create({
            'name': wa_id,
            'mobile': wa_id if wa_id.startswith('+') or wa_id[0:2] in ('27',) else False,
            'whatsapp_id': wa_id if channel.code == 'whatsapp' else False,
        })

    def _find_open_conversation(self, partner, channel):
        return self.env['comm.conversation'].search([
            ('partner_id', '=', partner.id),
            ('lifecycle_state', 'in', ('open', 'waiting')),
        ], limit=1, order='last_activity_at desc')

    def _ensure_leg(self, conversation, channel, source_model, source_id,
                    external_session_id):
        Leg = self.env['comm.conversation.leg']
        existing = Leg.search([
            ('conversation_id', '=', conversation.id),
            ('channel_id', '=', channel.id),
            ('closed_at', '=', False),
        ], limit=1)
        if existing:
            if external_session_id and not existing.external_session_id:
                existing.external_session_id = external_session_id
            return existing
        return Leg.create({
            'conversation_id': conversation.id,
            'channel_id': channel.id,
            'external_session_id': external_session_id,
            'source_model': source_model,
            'source_id': source_id,
        })

    def _start_child_bot(self, target_bot, parent_conversation):
        return self.env['comm.chatbot.executor'].start(
            target_bot, parent_conversation.partner_id,
            parent_conversation.primary_channel_id.code,
            campaign_id=parent_conversation.campaign_id)
