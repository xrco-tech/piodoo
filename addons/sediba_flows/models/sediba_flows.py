# -*- coding: utf-8 -*-
"""Server side of the Sediba Flows screen.

Sediba Flows is a builder on top of the channel-agnostic bot engine
(comm_chatbot): a flow is a comm.bot, a step is a comm.bot.step. Nothing here
talks to a channel; how a step comes out on each channel is asked of the
engine's own renderer, so the builder shows what the engine will send.
"""
from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.comm_chatbot.models.runtime.adapter_registry import get_adapter
from odoo.addons.comm_chatbot.models.runtime.renderer import (
    CapabilityMismatchError, RenderError)

# Steps that pick their next step from a list of answers, not from one "then".
BRANCHING = ('menu', 'condition')
# Steps that send nothing themselves.
SILENT = ('condition', 'action', 'jump', 'wait', 'end', 'set_variable')

STEP_FIELDS = {
    'name': 'name',
    'kind': 'kind',
    'body': 'body',
    'next_id': 'next_step_id',
    'input_type': 'input_type',
    'save_to': 'input_save_to',
    'condition': 'condition_expression',
    'condition_mode': 'condition_mode',
    'handoff_message': 'handoff_message',
    'jump_bot_id': 'jump_target_bot_id',
    'jump_step_id': 'jump_target_step_id',
    'jump_return': 'jump_return',
    'variable_name': 'set_variable_name',
    'variable_value': 'set_variable_value',
    'wait_seconds': 'wait_seconds',
    'end_outcome': 'end_outcome',
    'llm_prompt': 'llm_system_prompt',
    'llm_use_sediba': 'llm_use_sediba',
}


class SedibaFlows(models.AbstractModel):
    _name = 'sediba.flows'
    _description = 'Sediba Flows screen'

    # ── Reading ──────────────────────────────────────────────────────────

    @api.model
    def _channels(self):
        return [{
            'id': c.id,
            'code': c.code,
            'name': c.name,
            'connected': bool(get_adapter(c.adapter_key)),
            'limit': c.max_body_length or 0,
        } for c in self.env['comm.channel'].search([])]

    @api.model
    def home(self):
        Bot = self.env['comm.bot']
        return {
            'can_edit': Bot.has_access('write'),
            'can_create': Bot.has_access('create'),
            'flows': [{
                'id': b.id,
                'name': b.name,
                'status': b.engine_mode,
                'steps': len(b.step_ids),
                'channels': b.channel_ids.mapped('name'),
            } for b in Bot.search([])],
            'channels': self._channels(),
        }

    @api.model
    def load(self, bot_id):
        bot = self.env['comm.bot'].browse(bot_id).exists()
        if not bot:
            raise UserError(_("This flow no longer exists."))
        steps = bot.step_ids
        return {
            'can_edit': bot.has_access('write'),
            'flow': {
                'id': bot.id,
                'name': bot.name,
                'status': bot.engine_mode,
                'entry_id': bot.entry_step_id.id or False,
                'channel_ids': bot.channel_ids.ids,
            },
            'channels': self._channels(),
            'flows': [{'id': b.id, 'name': b.name}
                      for b in self.env['comm.bot'].search([('id', '!=', bot.id)])],
            'steps': [self._step(s, bot) for s in steps],
        }

    def _step(self, step, bot):
        overrides = {o.channel_id.id: o for o in step.channel_override_ids}
        return {
            'id': step.id,
            'name': step.name,
            'kind': step.kind,
            'body': step.body or '',
            'next_id': step.next_step_id.id or False,
            'options': [{
                'id': o.id,
                'label': o.label,
                'next_id': o.next_step_id.id or False,
                'is_default': o.is_default,
            } for o in step.option_ids.sorted('sequence')],
            'input_type': step.input_type or 'text',
            'save_to': step.input_save_to or '',
            'condition': step.condition_expression or '',
            'condition_mode': step.condition_mode or 'truthy',
            'handoff_message': step.handoff_message or '',
            'jump_bot_id': step.jump_target_bot_id.id or False,
            'jump_step_id': step.jump_target_step_id.id or False,
            'jump_return': step.jump_return,
            'variable_name': step.set_variable_name or '',
            'variable_value': step.set_variable_value or '',
            'wait_seconds': step.wait_seconds or 0,
            'end_outcome': step.end_outcome or '',
            'llm_prompt': step.llm_system_prompt or '',
            'llm_use_sediba': step.llm_use_sediba,
            'overrides': [{
                'channel_id': c.id,
                'body': overrides[c.id].body_override or '' if c.id in overrides else '',
                'hide': overrides[c.id].hide if c.id in overrides else False,
            } for c in bot.channel_ids],
            'out': {c.code: self._out(step, c, bot) for c in bot.channel_ids},
        }

    def _out(self, step, channel, bot):
        """How this step comes out on one channel: what is said, in what form,
        and anything that will not fit. Asked of the engine's renderer."""
        res = {'state': 'ok', 'how': '', 'body': '', 'options': [],
               'chars': 0, 'limit': channel.max_body_length or 0, 'note': ''}
        override = step.channel_override_ids.filtered(
            lambda o: o.channel_id == channel)
        if override.hide:
            return dict(res, state='skip', how=_("Skipped on this channel"))
        if step.kind in SILENT:
            return dict(res, state='none', how=_("Says nothing"))
        if step.kind == 'llm':
            return dict(res, how=_("The AI writes the reply"))
        if step.kind == 'handoff':
            body = step.handoff_message or ''
            return dict(res, how=_("Plain message"), body=body, chars=len(body))
        if step.kind == 'channel_switch':
            body = step.channel_switch_message or ''
            return dict(res, how=_("Plain message"), body=body, chars=len(body))

        renderer = self.env['comm.chatbot.renderer']
        conversation = self.env['comm.conversation'].new({
            'partner_id': self.env.user.partner_id.id,
            'bot_id': bot.id,
            'primary_channel_id': channel.id,
            'state': {},
        })
        try:
            body = renderer._resolve_body(step, channel, conversation)
            options = renderer._resolve_options(step, conversation)
            media = renderer._resolve_media(step, channel)
            renderer._check_capabilities(step, channel)
            body, options, media = renderer._degrade(
                step, channel, body, options, media)
        except CapabilityMismatchError as e:
            reason = str(e)
            if reason == 'menu_no_options':
                note = _("Add at least one choice.")
            elif reason == 'input_media_unsupported':
                note = _("This channel cannot receive files.")
            else:
                note = _("This channel cannot show this step.")
            return dict(res, state='warn', how=_("Cannot be shown"), note=note)
        except RenderError as e:
            return dict(res, state='warn', how=_("Cannot be shown"),
                        note=_("A placeholder has no value: %s", str(e)))

        res.update(body=body, chars=len(body))
        if options:
            numbered = any(o.get('numeric_key') for o in options)
            count = len(options)
            if numbered:
                res['how'] = (_("Read out as a numbered list")
                              if channel.code == 'voice'
                              else _("Numbered list, reply with a number"))
            elif channel.supports_buttons and count <= (channel.max_buttons or 3):
                res['how'] = _("%s reply buttons", count)
                res['options'] = [o['label'] for o in options]
            else:
                res['how'] = _("List to pick from")
                res['options'] = [o['label'] for o in options]
            if count < len(step.option_ids):
                res['state'] = 'warn'
                res['note'] = _("Only the first %s choices fit here.", count)
        else:
            res['how'] = (_("Read out") if channel.code == 'voice'
                          else _("Plain message"))
        if res['limit'] and res['chars'] > res['limit']:
            res['state'] = 'warn'
            res['note'] = _("Too long: %(chars)s of %(limit)s characters. It will be cut.",
                            chars=res['chars'], limit=res['limit'])
        return res

    # ── Writing ──────────────────────────────────────────────────────────

    @api.model
    def create_flow(self, name=None):
        bot = self.env['comm.bot'].create({'name': name or _("New flow")})
        step = self.env['comm.bot.step'].create({
            'bot_id': bot.id,
            'name': _("Welcome"),
            'kind': 'message',
            'body': _("Hi {{contact.first_name}}, welcome."),
        })
        bot.entry_step_id = step
        return bot.id

    @api.model
    def save_flow(self, bot_id, vals):
        bot = self.env['comm.bot'].browse(bot_id)
        write = {}
        if 'name' in vals:
            if not (vals['name'] or '').strip():
                raise UserError(_("A flow needs a name."))
            write['name'] = vals['name'].strip()
        if 'entry_id' in vals:
            write['entry_step_id'] = vals['entry_id'] or False
        if 'channel_ids' in vals:
            write['channel_ids'] = [(6, 0, vals['channel_ids'])]
        if 'status' in vals:
            if vals['status'] == 'live' and not bot.channel_ids \
                    and not vals.get('channel_ids'):
                raise UserError(_("Choose at least one channel before going live."))
            write['engine_mode'] = vals['status']
        bot.write(write)
        return self.load(bot.id)

    def _free_name(self, bot, base):
        names = set(bot.step_ids.mapped('name'))
        if base not in names:
            return base
        n = 2
        while '%s %s' % (base, n) in names:
            n += 1
        return '%s %s' % (base, n)

    @api.model
    def add_step(self, bot_id, after_id=False, option_id=False):
        """Add a message step. After a step that has one "then", the new step
        is put between it and what followed; for one answer of a menu or a
        condition, that answer leads to the new step."""
        bot = self.env['comm.bot'].browse(bot_id)
        Step = self.env['comm.bot.step']
        step = Step.create({
            'bot_id': bot.id,
            'name': self._free_name(bot, _("New step")),
            'kind': 'message',
        })
        if option_id:
            option = self.env['comm.bot.step.option'].browse(option_id)
            step.next_step_id = option.next_step_id
            option.next_step_id = step
        elif after_id:
            after = Step.browse(after_id)
            if after.kind not in BRANCHING:
                step.next_step_id = after.next_step_id
                after.next_step_id = step
        if not bot.entry_step_id:
            bot.entry_step_id = step
        res = self.load(bot.id)
        res['new_id'] = step.id
        return res

    @api.model
    def save_step(self, step_id, vals):
        step = self.env['comm.bot.step'].browse(step_id)
        write = {}
        for key, field in STEP_FIELDS.items():
            if key in vals:
                write[field] = vals[key]
        if 'name' in write and not (write['name'] or '').strip():
            raise UserError(_("A step needs a name."))
        if write:
            step.write(write)

        if 'options' in vals:
            Option = self.env['comm.bot.step.option']
            keep = Option
            for seq, row in enumerate(vals['options']):
                label = (row.get('label') or '').strip()
                if not label:
                    continue
                data = {
                    'label': label,
                    'sequence': (seq + 1) * 10,
                    'next_step_id': row.get('next_id') or False,
                    'is_default': bool(row.get('is_default')),
                }
                option = Option.browse(row.get('id') or []).exists()
                if option and option.step_id == step:
                    if option.value == option.label:
                        data['value'] = label
                    option.write(data)
                else:
                    option = Option.create(dict(data, step_id=step.id, value=label))
                keep |= option
            (step.option_ids - keep).unlink()

        if 'overrides' in vals:
            Override = self.env['comm.bot.step.channel.override']
            for row in vals['overrides']:
                existing = step.channel_override_ids.filtered(
                    lambda o: o.channel_id.id == row['channel_id'])
                body = (row.get('body') or '').strip()
                hide = bool(row.get('hide'))
                if not body and not hide:
                    existing.unlink()
                elif existing:
                    existing.write({'body_override': body, 'hide': hide})
                else:
                    Override.create({
                        'step_id': step.id,
                        'channel_id': row['channel_id'],
                        'body_override': body,
                        'hide': hide,
                    })
        return self.load(step.bot_id.id)

    @api.model
    def delete_step(self, step_id):
        """Remove a step. Whatever led to it now leads to the step after it,
        so deleting one step from the middle does not cut the flow in two."""
        step = self.env['comm.bot.step'].browse(step_id)
        bot = step.bot_id
        after = step.next_step_id if step.kind not in BRANCHING else step.browse()
        if after == step:
            after = step.browse()
        self.env['comm.bot.step'].search(
            [('next_step_id', '=', step.id)]).write({'next_step_id': after.id})
        self.env['comm.bot.step.option'].search(
            [('next_step_id', '=', step.id)]).write({'next_step_id': after.id})
        if bot.entry_step_id == step:
            if bot.engine_mode == 'live' and not after:
                raise UserError(_(
                    "A live flow must have a first step. Pause the flow, or "
                    "choose another first step, before deleting this one."))
            bot.entry_step_id = after
        step.unlink()
        return self.load(bot.id)
