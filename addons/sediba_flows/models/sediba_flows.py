# -*- coding: utf-8 -*-
"""Server side of the Interaction Flows screen.

Interaction Flows is a builder on top of the channel-agnostic bot engine
(comm_chatbot): a flow is a comm.bot, a step is a comm.bot.step. Nothing here
talks to a channel; how a step comes out on each channel is asked of the
engine's own renderer, so the builder shows what the engine will send.
"""
import base64
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.mimetypes import guess_mimetype

from odoo.addons.comm_chatbot.models.runtime.adapter_registry import get_adapter
from odoo.addons.comm_chatbot.models.runtime.renderer import (
    CapabilityMismatchError, RenderError)

# An uploaded picture: the kinds and the size WhatsApp takes.
IMAGE_TYPES = ('image/png', 'image/jpeg')
IMAGE_MAX_BYTES = 5 * 1024 * 1024

# Steps that pick their next step from a list of answers, not from one "then".
# The home cards: how far back the numbers look, and how many days the
# activity strip shows.
USAGE_DAYS = 30
STRIP_DAYS = 14

BRANCHING = ('menu', 'condition')
# Steps that send nothing themselves.
SILENT = ('condition', 'action', 'jump', 'wait', 'end', 'set_variable')

STEP_FIELDS = {
    'name': 'name',
    'kind': 'kind',
    'body': 'body',
    'header': 'header',
    'footer': 'footer',
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
    _description = 'Interaction Flows screen'

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
        bots = Bot.search([])
        return {
            'can_edit': Bot.has_access('write'),
            'can_create': Bot.has_access('create'),
            'flows': [self._card(b) for b in bots],
            'channels': self._channels(),
        }

    def _card(self, bot):
        """One flow as its card on the home screen: what it is, where it
        runs, how it is doing with real contacts, and what needs a look."""
        steps = bot.step_ids
        edited = max([bot.write_date] + [d for d in steps.mapped('write_date') if d])
        return {
            'id': bot.id,
            'name': bot.name,
            'description': bot.description or '',
            'status': bot.engine_mode,
            'steps': len(steps),
            'channels': bot.channel_ids.mapped('name'),
            'channel_codes': bot.channel_ids.mapped('code'),
            'runs': self._card_runs(bot),
            'usage': self._card_usage(bot),
            'attention': self._card_attention(bot),
            'edited': fields.Datetime.to_string(edited),
        }

    def _card_runs(self, bot):
        """Per channel, what the flow is connected to there, in one line."""
        names = {c.id: c.name for c in bot.channel_ids}
        res = []
        for connection in self._connections(bot):
            # Only what the flow is connected to: an account, a code, a site.
            links = [{
                'name': line['name'],
                'address': line.get('address') or '',
                'model': line.get('model') or False,
                'res_id': line.get('res_id') or False,
            } for line in connection['lines']
                if line.get('ok') and line.get('account')]
            res.append({
                'channel': names[connection['channel_id']],
                'ok': bool(links),
                'links': links,
            })
        return res

    def _card_usage(self, bot):
        """Real conversations in the last USAGE_DAYS days: how many, how many
        reached an end step, how many started on each of the last STRIP_DAYS
        days, and the step where most of the others stopped. False when
        there were none. Test walks are left out, as on the step cards."""
        now = fields.Datetime.now()
        Conversation = self.env['comm.conversation']
        domain = [
            ('bot_id', '=', bot.id),
            ('opened_at', '>=', now - timedelta(days=USAGE_DAYS)),
            # A conversation with no outcome yet must still count.
            '|', ('outcome', '=', False), ('outcome', '!=', '__preview_walker__'),
        ]
        tests = self._test_conversations(bot)
        if tests:
            domain.append(('id', 'not in', tests))
        talks = Conversation.search(domain)
        if not talks:
            return False
        finished = talks.filtered(lambda t: t.lifecycle_state == 'closed')
        today = fields.Date.context_today(self)
        days = [0] * STRIP_DAYS
        for talk in talks:
            age = (today - fields.Date.context_today(self, talk.opened_at)).days
            if 0 <= age < STRIP_DAYS:
                days[STRIP_DAYS - 1 - age] += 1
        stops = {}
        for talk in talks - finished:
            if talk.current_step_id:
                stops[talk.current_step_id] = stops.get(talk.current_step_id, 0) + 1
        stop = max(stops, key=lambda step: (stops[step], -step.id)) if stops else False
        return {
            'conversations': len(talks),
            'finished_pct': round(100 * len(finished) / len(talks)),
            'days': days,
            'stop': stop.name if stop else '',
        }

    def _card_attention(self, bot):
        """Short lines for what needs a look before the flow can be trusted."""
        res = []
        empty = len(bot.step_ids.filtered(
            lambda s: s.kind == 'action' and not s.action_config))
        if empty == 1:
            res.append(_("1 step runs an action that is empty"))
        elif empty:
            res.append(_("%s steps run an action that is empty", empty))
        return res

    @api.model
    def load(self, bot_id):
        bot = self.env['comm.bot'].browse(bot_id).exists()
        if not bot:
            raise UserError(_("This flow no longer exists."))
        steps = bot.step_ids
        reached = self._reached(bot)
        return {
            'can_edit': bot.has_access('write'),
            'can_create': self.env['comm.bot'].has_access('create'),
            'flow': {
                'id': bot.id,
                'name': bot.name,
                'description': bot.description or '',
                'status': bot.engine_mode,
                'entry_id': bot.entry_step_id.id or False,
                'channel_ids': bot.channel_ids.ids,
                # The most contacts any one step was reached by: what the
                # share on each card is a share of.
                'reached_most': max(reached.values(), default=0),
                'connections': self._connections(bot),
                'device_url': self._device_url(bot),
            },
            'channels': self._channels(),
            'flows': [{'id': b.id, 'name': b.name}
                      for b in self.env['comm.bot'].search([('id', '!=', bot.id)])],
            'steps': [dict(self._step(s, bot), reached=reached.get(s.id, 0))
                      for s in steps],
        }

    def _step(self, step, bot):
        overrides = {o.channel_id.id: o for o in step.channel_override_ids}
        return {
            'id': step.id,
            'name': step.name,
            'kind': step.kind,
            'body': step.body or '',
            'header': step.header or '',
            'footer': step.footer or '',
            'image_url': self._image(step).url or '',
            'image_alt': self._image(step).alt_text or '',
            # A picture that was uploaded, as opposed to one given by address.
            'image_file': self._image(step).attachment_id.name or '',
            'image_src': self._image_src(step),
            'placed': step.flow_placed,
            'x': step.flow_x,
            'y': step.flow_y,
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
               'header': '', 'footer': '', 'image': '',
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
            header, body, footer = renderer._frame(
                step, channel, body, conversation)
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

        res.update(
            body=body, chars=len(body), header=header, footer=footer,
            # The image, where the channel shows images; elsewhere its
            # description is already in the text.
            image=self._image_src(step) if any(
                m['kind'] == 'image' and m['url'] for m in media) else '')
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
            elif res['options'] and channel.code == 'whatsapp':
                most = 20 if count <= (channel.max_buttons or 3) else 24
                if any(len(label) > most for label in res['options']):
                    res['state'] = 'warn'
                    res['note'] = _(
                        "WhatsApp shows only the first %s characters of a "
                        "choice. Shorten the long ones.", most)
        else:
            res['how'] = (_("Read out") if channel.code == 'voice'
                          else _("Plain message"))
        if res['limit'] and res['chars'] > res['limit']:
            res['state'] = 'warn'
            res['note'] = _("Too long: %(chars)s of %(limit)s characters. It will be cut.",
                            chars=res['chars'], limit=res['limit'])
        return res

    def _image(self, step):
        """The step's picture: the first image among its attachments."""
        return step.media_ids.filtered(lambda m: m.kind == 'image')[:1]

    def _image_src(self, step):
        """The address this screen shows the step's picture from."""
        image = self._image(step)
        if image.url:
            return image.url
        return '/web/image/%s' % image.attachment_id.id if image.attachment_id else ''

    def _connections(self, bot):
        """For each channel the flow runs on, what it is connected to there:
        the number it sends from, what starts it, or that nothing is
        connected yet. Each channel's add-on says it for itself."""
        res = []
        for channel in bot.channel_ids:
            adapter = get_adapter(channel.adapter_key)
            if not adapter:
                lines = [{'ok': False, 'text': _(
                    "The add-on for this channel is not installed, so nothing "
                    "is connected.")}]
            elif hasattr(adapter, 'connections'):
                lines = adapter().connections(self.env, bot)
            else:
                lines = [{'ok': False, 'text': _(
                    "This channel does not say what it is connected to.")}]
            # What the flow could be connected to here, when the channel's
            # add-on offers a choice (USSD: the codes).
            options = adapter().connect_options(self.env, bot) \
                if adapter and hasattr(adapter, 'connect_options') else []
            res.append({'channel_id': channel.id,
                        'lines': [self._connection_line(line) for line in lines],
                        'options': options})
        return res

    def _connection_line(self, line):
        """A line as the screen shows it. A line that names an account says
        which record it is, so the screen can open it; that is left out for
        someone who may not read that kind of record."""
        line = dict(line)
        model = line.get('model')
        # An account, a code or a site, as against what starts the flow.
        line['account'] = bool(model and line.get('name'))
        if model and not (model in self.env and self.env[model].has_access('read')
                          and self.env[model].browse(line.get('res_id')).exists()):
            line.pop('model')
            line.pop('res_id', None)
        return line

    @api.model
    def connect_channel(self, bot_id, channel_id, option_id, on):
        """Connect the flow to one of a channel's options (a USSD code), or
        take it off. The channel's add-on does it."""
        bot = self.env['comm.bot'].browse(bot_id)
        bot.check_access('write')
        channel = self.env['comm.channel'].browse(channel_id)
        adapter = get_adapter(channel.adapter_key)
        if not adapter or not hasattr(adapter, 'connect'):
            raise UserError(_("This channel has nothing to connect."))
        adapter().connect(self.env, bot, option_id, bool(on))
        return self.load(bot.id)

    def _test_conversations(self, bot):
        """Ids of the flow's conversations that were tests, not contacts:
        walks in Try it, the engine's own simulator and the web widget's
        preview."""
        tests = self.env['comm.conversation.leg'].search([
            ('conversation_id.bot_id', '=', bot.id),
            '|', '|', ('external_session_id', '=like', 'sediba-flows-try-%'),
            ('external_session_id', '=like', 'bot-flow-%'),
            ('external_session_id', '=', 'dry-walk'),
        ]).conversation_id.ids
        if 'comm.bot.web.session' in self.env:
            tests += self.env['comm.bot.web.session'].sudo().search([
                ('is_preview', '=', True),
                ('conversation_id.bot_id', '=', bot.id),
            ]).conversation_id.ids
        return tests

    def _reached(self, bot):
        """{step id: how many real conversations the step spoke in}. Walks in
        Try it, the engine's own simulator and the web widget's preview are
        left out, so the numbers are contacts, not tests."""
        Interaction = self.env['comm.interaction']
        domain = [
            ('step_id', 'in', bot.step_ids.ids),
            ('direction', '=', 'outbound'),
            ('conversation_id.outcome', '!=', '__preview_walker__'),
        ]
        tests = self._test_conversations(bot)
        if tests:
            domain.append(('conversation_id', 'not in', tests))
        return {step.id: count for step, count in Interaction._read_group(
            domain, ['step_id'], ['conversation_id:count_distinct'])}

    def _device_url(self, bot):
        """The address of the web chat widget's preview of this flow, when
        the web chat add-on is installed. The preview sends nothing."""
        if 'comm.bot.web.session' not in self.env:
            return ''
        return '/comm_chatbot_web/embed/%s?preview=1' % bot.id

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
    def duplicate_flow(self, bot_id, name=None):
        """Copy a flow: its steps and how they join, wording per channel,
        pictures, variables, description and the channels it is meant for.
        The copy is a draft with nothing connected to it: no USSD code, no
        keyword that starts it, no conversations. The original is not
        touched."""
        bot = self.env['comm.bot'].browse(bot_id).exists()
        if not bot:
            raise UserError(_("This flow no longer exists."))
        bot.check_access('read')
        name = (name or '').strip() or _("%s (copy)", bot.name)
        new = bot.copy(self._duplicate_defaults(bot, name))

        Step = self.env['comm.bot.step']
        to_step = [f for f, field in Step._fields.items()
                   if field.comodel_name == 'comm.bot.step' and field.store
                   and field.type in ('many2one', 'many2many')]
        blank = {f: False for f in to_step}
        steps = {}
        for step in bot.step_ids:
            steps[step.id] = step.copy(dict(
                blank, bot_id=new.id, name=step.name,
                # Where the card was dragged to comes along too.
                flow_placed=step.flow_placed, flow_x=step.flow_x, flow_y=step.flow_y))

        def moved(old):
            """The copy of a step of this flow; a step of another flow stays."""
            return steps.get(old.id, old)

        for step in bot.step_ids:
            copy = steps[step.id]
            vals = {}
            for f in to_step:
                if not step[f]:
                    continue
                vals[f] = moved(step[f]).id if Step._fields[f].type == 'many2one' \
                    else [(6, 0, [moved(s).id for s in step[f]])]
            # A flow that jumps back into itself jumps into the copy.
            if step.jump_target_bot_id == bot:
                vals['jump_target_bot_id'] = new.id
            if vals:
                copy.write(vals)
            for option in step.option_ids:
                option.copy({'step_id': copy.id,
                             'next_step_id': moved(option.next_step_id).id or False})
            for media in step.media_ids:
                self._duplicate_media(media, {'step_id': copy.id})
            for override in step.channel_override_ids:
                over = override.copy({'step_id': copy.id})
                for media in override.media_override_ids:
                    self._duplicate_media(media, {'channel_override_id': over.id})
            for translation in step.body_translation_ids:
                translation.copy({'step_id': copy.id})
            for tool in step.llm_tool_ids:
                tool.copy({
                    'step_id': copy.id,
                    'executor_action_step_id': moved(tool.executor_action_step_id).id or False,
                    'executor_jump_step_id': moved(tool.executor_jump_step_id).id or False,
                })
        for variable in bot.variable_ids:
            variable.copy({'bot_id': new.id})
        new.write({
            'entry_step_id': moved(bot.entry_step_id).id or False,
            'on_error_step_id': moved(bot.on_error_step_id).id or False,
        })
        return new.id

    def _duplicate_defaults(self, bot, name):
        """What the copy of the flow itself starts with."""
        return {
            'name': name,
            'engine_mode': 'draft',
            'entry_step_id': False,
            'on_error_step_id': False,
        }

    def _duplicate_media(self, media, vals):
        """A picture uploaded for a step is copied with it, so taking it off
        one flow does not take it off the other."""
        if media.attachment_id:
            attachment = media.attachment_id.copy()
            if attachment.res_model == 'comm.bot.step' and vals.get('step_id'):
                attachment.res_id = vals['step_id']
            vals = dict(vals, attachment_id=attachment.id)
        return media.copy(vals)

    @api.model
    def save_flow(self, bot_id, vals):
        bot = self.env['comm.bot'].browse(bot_id)
        write = {}
        if 'name' in vals:
            if not (vals['name'] or '').strip():
                raise UserError(_("A flow needs a name."))
            write['name'] = vals['name'].strip()
        if 'description' in vals:
            write['description'] = (vals['description'] or '').strip() or False
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

    @api.model
    def move_step(self, step_id, x, y):
        """Keep where a card was dragged to."""
        self.env['comm.bot.step'].browse(step_id).write({
            'flow_placed': True,
            'flow_x': max(0, int(x)),
            'flow_y': max(0, int(y)),
        })
        return True

    @api.model
    def tidy(self, bot_id):
        """Forget every dragged position: the cards place themselves again."""
        bot = self.env['comm.bot'].browse(bot_id)
        bot.step_ids.filtered('flow_placed').write(
            {'flow_placed': False, 'flow_x': 0, 'flow_y': 0})
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

        if 'image_url' in vals or 'image_alt' in vals:
            # One image per step here: the first image among its attachments.
            image = self._image(step)
            url = (vals.get('image_url', image.url) or '').strip()
            alt = (vals.get('image_alt', image.alt_text) or '').strip()
            if image.attachment_id and not url:
                # An uploaded picture has no address; it goes only when
                # it is removed on purpose.
                image.alt_text = alt
            elif not url:
                image.unlink()
            elif image:
                image.attachment_id.unlink()
                image.write({'url': url, 'alt_text': alt})
            else:
                self.env['comm.bot.step.media'].create({
                    'step_id': step.id, 'kind': 'image', 'url': url, 'alt_text': alt})

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
    def set_image(self, step_id, filename, data):
        """Keep an uploaded picture as the step's image. `data` is the file,
        base64. The file is public, because WhatsApp fetches it by address."""
        step = self.env['comm.bot.step'].browse(step_id)
        raw = base64.b64decode(data or '')
        if guess_mimetype(raw) not in IMAGE_TYPES:
            raise UserError(_("Choose a PNG or JPEG picture."))
        if len(raw) > IMAGE_MAX_BYTES:
            raise UserError(_("That picture is over 5 MB. Choose a smaller one."))
        attachment = self.env['ir.attachment'].create({
            'name': filename or _("picture"),
            'raw': raw,
            'res_model': 'comm.bot.step',
            'res_id': step.id,
            'public': True,
        })
        image = self._image(step)
        if image:
            image.attachment_id.unlink()
            image.write({'attachment_id': attachment.id, 'url': False})
        else:
            self.env['comm.bot.step.media'].create({
                'step_id': step.id, 'kind': 'image', 'attachment_id': attachment.id})
        return self.load(step.bot_id.id)

    @api.model
    def remove_image(self, step_id):
        step = self.env['comm.bot.step'].browse(step_id)
        image = self._image(step)
        image.attachment_id.unlink()
        image.unlink()
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

    # ── Try it ───────────────────────────────────────────────────────────
    #
    # A walk of the flow as a test contact. Nothing is sent: the engine runs
    # with comm_chatbot_force_shadow, and AI steps are skipped.

    def _try_contact(self):
        """This user's own test contact. It is kept archived so that a real
        message from the same number is never matched to it."""
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        ref = 'sediba-flows-try-%s' % self.env.uid
        contact = Partner.search([('ref', '=', ref)], limit=1)
        if not contact:
            contact = Partner.create({
                'name': _("Test contact"), 'mobile': '+27600000001',
                'ref': ref, 'active': False,
            })
        return contact

    def _try_flows(self, bot):
        """The flow and every flow it can go into, the flow itself first."""
        flows, todo = bot, bot
        while todo:
            todo = todo.step_ids.jump_target_bot_id - flows
            flows |= todo
        return flows

    def _try_typed(self, kind, text):
        """A value typed in the panel, as the variable's declared type."""
        text = (text or '').strip() if isinstance(text, str) else text
        try:
            if kind == 'int':
                return int(text)
            if kind == 'float':
                return float(text)
        except (TypeError, ValueError):
            return text
        if kind == 'bool' and isinstance(text, str):
            return text.casefold() not in ('', '0', 'no', 'false')
        return text

    def _try_state(self, bot, variables):
        """{name: value} for the conversation, from what was typed. An empty
        box means "not set", so the variable is left out."""
        kinds = {v.name: v.type for v in self._try_flows(bot).variable_ids}
        return {name: self._try_typed(kinds.get(name), value)
                for name, value in (variables or {}).items()
                if value not in (None, False, '')}

    def _try_result(self, conversation):
        """The walk so far, for the panel: what was said each way, what the
        flow waits for now, and what each variable holds."""
        channel = conversation.primary_channel_id
        renderer = self.env['comm.chatbot.renderer']
        messages = []
        for i in conversation.interaction_ids.sorted('id'):
            entry = {
                'direction': i.direction,
                'body': i.rendered_body or i.raw_body or '',
                'step_name': i.step_id.name or '',
                'header': '', 'footer': '', 'image': '',
            }
            step = i.step_id
            if i.direction == 'outbound' and step.kind in ('message', 'menu', 'input'):
                # A channel with a header and a footer shows them apart from
                # the text; on the others they are already in the text.
                if channel.supports_header_footer:
                    entry['header'] = renderer._substitute(
                        step.header or '', conversation, conversation.bot_id)
                    entry['footer'] = renderer._substitute(
                        step.footer or '', conversation, conversation.bot_id)
                if channel.supports_media_image:
                    entry['image'] = self._image_src(step)
            messages.append(entry)

        step = conversation.current_step_id
        waiting, options = 'none', []
        if not step or conversation.lifecycle_state in ('closed', 'timeout'):
            waiting = 'done'
        elif step.kind == 'menu':
            waiting = 'menu'
            options = [{'label': o.label, 'value': o.value or o.label}
                       for o in step.option_ids.sorted('sequence')]
        elif step.kind == 'input':
            waiting = 'input'
        state = conversation.state or {}
        return {
            'session_id': str(conversation.id),
            'messages': messages,
            'waiting': waiting,
            'current_options': options,
            'variables': {k: ('' if v is None else str(v))
                          for k, v in state.items() if not k.startswith('__')},
        }

    @api.model
    def try_setup(self, bot_id):
        """What the panel asks before a walk: who the test contact is, and
        the variables of this flow and of the flows it goes into."""
        bot = self.env['comm.bot'].browse(bot_id)
        contact = self._try_contact()
        seen, groups = set(), []
        for flow in self._try_flows(bot):
            rows = []
            for var in flow.variable_ids.sorted('name'):
                if var.name in seen:
                    continue
                seen.add(var.name)
                rows.append({'name': var.name, 'type': var.type,
                             'value': var.default_value or ''})
            if rows:
                groups.append({'flow_id': flow.id, 'flow_name': flow.name,
                               'is_this_flow': flow == bot, 'variables': rows})
        return {'name': contact.name, 'mobile': contact.mobile or '',
                'groups': groups}

    @api.model
    def try_start(self, bot_id, channel_code, name=None, mobile=None, variables=None):
        bot = self.env['comm.bot'].browse(bot_id)
        channel = self.env['comm.channel'].get_by_code(channel_code)
        if not bot.entry_step_id:
            return {'error': _("This flow has no first step yet.")}
        if not channel:
            return {'error': _("That channel is not available.")}
        contact = self._try_contact()
        contact.write({'name': (name or '').strip() or _("Test contact"),
                       'mobile': (mobile or '').strip()})
        conversation = self.env['comm.conversation'].create({
            'partner_id': contact.id,
            'bot_id': bot.id,
            'primary_channel_id': channel.id,
            'current_step_id': bot.entry_step_id.id,
            'outcome': '__preview_walker__',
            'lifecycle_state': 'open',
            'state': self._try_state(bot, variables),
        })
        leg = self.env['comm.conversation.leg'].create({
            'conversation_id': conversation.id,
            'channel_id': channel.id,
            'external_session_id': 'sediba-flows-try-%s' % conversation.id,
        })
        self.env['comm.chatbot.executor'].with_context(
            comm_chatbot_force_shadow=True, comm_chatbot_skip_llm=True,
        ).advance(conversation, leg)
        return self._try_result(conversation)

    def _try_conversation(self, session_id):
        """The walk with this id, or nothing. Only walks started here count:
        a real contact's conversation is never replied to, changed or
        removed from this screen."""
        conversation = self.env['comm.conversation'].browse(int(session_id)).exists()
        if any((leg.external_session_id or '').startswith('sediba-flows-try-')
               for leg in conversation.leg_ids):
            return conversation
        return self.env['comm.conversation']

    @api.model
    def try_reply(self, session_id, text):
        conversation = self._try_conversation(session_id)
        if not conversation or conversation.lifecycle_state in ('closed', 'timeout'):
            return {'error': _("This walk has ended. Start again.")}
        leg = conversation.leg_ids.filtered(lambda l: not l.closed_at)[:1]
        step = conversation.current_step_id
        self.env['comm.interaction'].create({
            'conversation_id': conversation.id,
            'leg_id': leg.id,
            'channel_id': conversation.primary_channel_id.id,
            'direction': 'inbound',
            'raw_body': text or '',
            'status': 'received',
            'step_id': step.id,
        })
        Exec = self.env['comm.chatbot.executor'].with_context(
            comm_chatbot_force_shadow=True, comm_chatbot_skip_llm=True)
        if step.kind in ('menu', 'input'):
            Exec._handle_input(conversation, leg, text or '')
        else:
            Exec.advance(conversation, leg)
        return self._try_result(conversation)

    @api.model
    def try_apply(self, session_id, name=None, mobile=None, variables=None):
        """Change the test contact or the variables in the middle of a walk,
        without starting again."""
        conversation = self._try_conversation(session_id)
        if not conversation:
            return {'error': _("This walk has ended. Start again.")}
        contact = self._try_contact()
        if conversation.partner_id == contact:
            contact.write({'name': (name or '').strip() or contact.name,
                           'mobile': (mobile or '').strip()})
        state = {k: v for k, v in (conversation.state or {}).items()
                 if k.startswith('__')}
        root = self.env['comm.bot'].browse(
            ((conversation.state or {}).get('__stack') or [{}])[0].get('bot_id')
        ).exists() or conversation.bot_id
        state.update(self._try_state(root, variables))
        conversation.state = state
        return self._try_result(conversation)

    @api.model
    def try_stop(self, session_id):
        conversation = self._try_conversation(session_id)
        if conversation:
            conversation.sudo().unlink()
        return True
