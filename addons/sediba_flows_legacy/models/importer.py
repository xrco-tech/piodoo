# -*- coding: utf-8 -*-
"""Copy a bot of the older engine (whatsapp.chatbot) into the newer one
(comm.bot), as a draft.

The older engine keeps steps as a tree: a step's children are what can follow
it, and a child may name the answers, or the variable rules, that lead to it.
The newer engine keeps a graph: each step names its next step, and a menu or
a condition names one next step per answer. How the older engine walks its
tree (see whatsapp.chatbot.message._sim_walk) decides the translation:

- message, one child or none      -> message, then that child
- message, several children       -> menu, one choice per child
- question                        -> question (or a menu, as above)
- children picked by variable     -> a chain of conditions
- set variable / end / transfer   -> set variable / end / hand-over
- jump                            -> go to flow, coming back if it did
- run code                        -> an empty action, and a note

Nothing of the older bot is changed. Whatever has no equivalent is written
down in the new flow's notes.
"""
import re

from odoo import _, api, models

OLD_PLACEHOLDER = re.compile(r'\{\{\s*variables\.(\w+)\s*\}\}')

INPUT_TYPES = {
    'question_text': 'text',
    'question_numeric': 'number',
    'question_phone': 'phone',
    'question_email': 'email',
    'question_date': 'date',
    'question_document': 'media',
    'question_image': 'media',
    'question_video': 'media',
    'question_audio': 'media',
    'question_interactive': 'text',
}

VARIABLE_TYPES = {
    'text': 'string', 'integer': 'int', 'float': 'float', 'date': 'date',
    'boolean': 'bool', 'json': 'json',
}


def _slug(text):
    return re.sub(r'[^a-z0-9]+', '_', (text or '').lower()).strip('_') or 'x'


class SedibaFlowsImporter(models.AbstractModel):
    _name = 'sediba.flows.importer'
    _description = 'Brings an older bot into Sediba Flows'

    @api.model
    def import_bot(self, chatbot, _done=None):
        """Return the flow for this older bot, copying it first if needed.
        `_done` carries the bots already copied in this run, so two bots that
        jump to each other do not copy each other for ever."""
        done = {} if _done is None else _done
        if chatbot.id in done:
            return done[chatbot.id]
        Bot = self.env['comm.bot']
        existing = Bot.search([('legacy_chatbot_id', '=', chatbot.id)],
                              order='id desc', limit=1)
        if existing:
            done[chatbot.id] = existing
            return existing

        notes = []
        channel = self.env['comm.channel'].search(
            [('code', '=', chatbot.channel)], limit=1)
        if not channel:
            notes.append(_("The channel “%s” is not installed for Sediba Flows; "
                           "choose a channel before going live.", chatbot.channel))
        bot = Bot.create({
            'name': chatbot.name,
            'description': chatbot.description,
            'engine_mode': 'draft',
            'channel_ids': [(6, 0, channel.ids)],
            'legacy_chatbot_id': chatbot.id,
        })
        done[chatbot.id] = bot

        names = self._copy_variables(chatbot, bot)
        new, save_to = self._copy_steps(chatbot, bot, names, notes)
        self._link_steps(chatbot, bot, new, save_to, names, notes, done)
        self._copy_keywords(chatbot, bot, channel, notes)
        self._note_the_rest(chatbot, notes)

        roots = chatbot.step_ids.filtered(lambda s: not s.parent_id).sorted(
            lambda s: (s.sequence, s.id))
        if roots:
            bot.entry_step_id = new[roots[0].id]
        bot.import_notes = '\n'.join(
            [_("Brought over from the older bot “%(name)s”: %(count)s steps.",
               name=chatbot.name, count=len(chatbot.step_ids))]
            + list(dict.fromkeys(notes)))
        return bot

    # ── Variables and wording ────────────────────────────────────────────

    def _copy_variables(self, chatbot, bot):
        """Declare the older bot's variables; return {older name: new name}."""
        names, used = {}, set()
        for var in chatbot.bot_variable_ids:
            name = re.sub(r'\W+', '_', var.name or '').strip('_') or 'value'
            base, n = name, 2
            while name in used:
                name, n = '%s_%s' % (base, n), n + 1
            used.add(name)
            names[var.name] = name
            self.env['comm.bot.variable'].create({
                'bot_id': bot.id,
                'name': name,
                'type': VARIABLE_TYPES.get(var.data_type, 'string'),
            })
        return names

    def _wording(self, text, names):
        """{{variables.x}} of the older engine is {{state.x}} in the newer."""
        return OLD_PLACEHOLDER.sub(
            lambda m: '{{state.%s}}' % names.get(m.group(1), m.group(1)),
            text or '')

    def _body(self, step, names, notes):
        if step.header_type and step.header_type != 'text':
            notes.append(_("“%(step)s”: its %(kind)s header was not carried over.",
                           step=step.name, kind=step.header_type))
        if step.attachment_id:
            notes.append(_("“%s”: its attachment was not carried over.", step.name))
        return self._wording(step.body_plain, names)

    def _frame(self, step, names):
        """The older step's header line and footer, as the new step's own."""
        header = step.header_text if step.header_type == 'text' else ''
        return {'header': self._wording(header, names) or False,
                'footer': self._wording(step.footer, names) or False}

    # ── Steps ────────────────────────────────────────────────────────────

    def _children(self, step):
        return step.child_ids.sorted(lambda s: (s.sequence, s.id))

    def _by_variable(self, step):
        """True when what follows this step is picked by variable rules: it
        has several children, some with a variable rule and none with an
        answer."""
        kids = self._children(step)
        return (len(kids) > 1
                and any(k.trigger_variable_ids for k in kids)
                and not any(k.trigger_answer_ids for k in kids))

    def _is_menu(self, step):
        if step.step_type != 'message' and not step.step_type.startswith('question_'):
            return False
        if step.button_ids or step.list_row_ids:
            return True
        return len(self._children(step)) > 1 and not self._by_variable(step)

    def _copy_steps(self, chatbot, bot, names, notes):
        """Create one new step per older step, not yet joined up. Returns
        {older step id: new step} and {older step id: name its answer is
        kept under}."""
        Step = self.env['comm.bot.step']
        new, save_to, used = {}, {}, set()
        for old in chatbot.step_ids.sorted(lambda s: (s.parent_path or '', s.sequence, s.id)):
            name, n = old.name, 2
            while name in used:
                name, n = '%s (%s)' % (old.name, n), n + 1
            used.add(name)
            vals = {'bot_id': bot.id, 'name': name, 'sequence': len(new) * 10 + 10}
            kind = old.step_type
            if kind == 'message' or kind.startswith('question_'):
                vals['body'] = self._body(old, names, notes)
                vals.update(self._frame(old, names))
                is_question = kind != 'message'
                if self._is_menu(old):
                    vals['kind'] = 'menu'
                elif is_question:
                    vals.update(kind='input', input_type=INPUT_TYPES[kind])
                else:
                    vals['kind'] = 'message'
                if is_question:
                    key = 'answer_%s' % _slug(old.name)
                    while key in save_to.values():
                        key += '_2'
                    save_to[old.id] = vals['input_save_to'] = key
                if old.wa_message_type == 'interactive_flow':
                    notes.append(_("“%s” opened a WhatsApp form. Forms are not "
                                   "carried over; it is now a plain question.", old.name))
            elif kind == 'set_variable':
                vals.update(kind='set_variable',
                            set_variable_name=names.get(old.variable_id.name, ''))
                if not old.variable_id:
                    notes.append(_("“%s” sets no variable; it now does nothing.", old.name))
            elif kind == 'execute_code':
                vals['kind'] = 'action'
                notes.append(_("“%s” ran code. Code is not carried over: the step "
                               "is now an empty action and needs rewriting.", old.name))
            elif kind == 'transfer_to_agent':
                vals.update(kind='handoff',
                            handoff_message=self._body(old, names, notes)
                            or _("Connecting you to an agent..."))
            elif kind == 'jump_to_flow':
                vals['kind'] = 'jump'
            elif kind == 'end_flow':
                vals['kind'] = 'end'
            else:
                vals['kind'] = 'message'
                notes.append(_("“%(step)s” is of a kind (%(kind)s) that is not known; "
                               "it is now a message.", step=old.name, kind=kind))
            if old.fallback_step_id:
                notes.append(_("“%s”: its step for too many wrong answers was "
                               "not carried over.", old.name))
            new[old.id] = Step.create(vals)
        return new, save_to

    def _link_steps(self, chatbot, bot, new, save_to, names, notes, done):
        Option = self.env['comm.bot.step.option']
        for old in chatbot.step_ids:
            step = new[old.id]
            kind = old.step_type
            if step.kind == 'menu':
                for seq, choice in enumerate(self._choices(old, notes)):
                    label, target = choice[0], choice[1]
                    Option.create({
                        'step_id': step.id,
                        'sequence': (seq + 1) * 10,
                        'label': label,
                        'value': choice[2] if len(choice) > 2 else label,
                        'next_step_id': new[target.id].id if target else False,
                    })
                continue
            if kind == 'set_variable' and old.variable_id:
                step.set_variable_value = self._value_of(old, save_to, names, notes)
            if kind == 'jump_to_flow':
                self._link_jump(old, step, chatbot, new, names, notes, done)
            if step.kind != 'end':
                step.next_step_id = self._after(old, bot, new, names, notes)

    def _after(self, old, bot, new, names, notes):
        """The new step that follows this older step, or an empty record."""
        kids = self._children(old)
        if not kids:
            return self.env['comm.bot.step']
        if self._by_variable(old):
            return self._conditions(old, bot, new, names, notes)
        return new[kids[0].id]

    def _conditions(self, old, bot, new, names, notes):
        """Children picked by variable rules become a chain of conditions,
        checked in the older order; when none holds, the first child follows,
        as the older engine did."""
        Step = self.env['comm.bot.step']
        Option = self.env['comm.bot.step.option']
        kids = self._children(old)
        following = new[kids[0].id]
        used = set(bot.step_ids.mapped('name'))
        for kid in reversed(kids):
            rule = kid.trigger_variable_ids.sorted(lambda t: (t.sequence, t.id))[:1]
            if not rule:
                continue
            if len(kid.trigger_variable_ids) > 1:
                notes.append(_("“%s” had several variable rules; only the first "
                               "was carried over.", kid.name))
            by_value = rule.operator in ('is_equal_to', 'is_not_equal_to')
            if not by_value and rule.operator not in ('is_set', 'is_not_set'):
                notes.append(_(
                    "“%(step)s” was reached when %(rule)s. Only “is set”, “is "
                    "not set”, “is equal to” and “is not equal to” can be "
                    "carried over; check what leads to it.",
                    step=kid.name, rule=rule.display_name))
                continue
            variable = names.get(rule.variable_id.name, rule.variable_id.name)
            name, n = _("Check %s", variable), 2
            while name in used:
                name, n = _("Check %s", variable) + ' (%s)' % n, n + 1
            used.add(name)
            check = Step.create({
                'bot_id': bot.id,
                'name': name,
                'kind': 'condition',
                'condition_expression': '{{state.%s}}' % variable,
                'condition_mode': 'equals' if by_value else 'truthy',
            })
            is_set = rule.operator in ('is_set', 'is_equal_to')
            Option.create({
                'step_id': check.id, 'sequence': 10,
                'label': rule.value if by_value else _("If so"),
                'value': rule.value if by_value else 'yes',
                'next_step_id': (new[kid.id] if is_set else following).id,
            })
            Option.create({
                'step_id': check.id, 'sequence': 20, 'label': _("Otherwise"),
                'value': 'no', 'is_default': True,
                'next_step_id': (following if is_set else new[kid.id]).id,
            })
            following = check
        return following

    def _choices(self, old, notes):
        """The choices of a menu, as (label, older step it leads to)."""
        kids = self._children(old)
        first = kids[:1]
        rows = [(b.title, b.button_id) for b in old.button_ids.sorted('sequence')] \
            or [(r.title, r.row_id) for r in old.list_row_ids.sorted('sequence')]
        if rows:
            choices = []
            for title, key in rows:
                wanted = {(title or '').strip().casefold(), (key or '').strip().casefold()}
                target = next((k for k in kids if any(
                    (a.value or '').strip().casefold() in wanted
                    for a in k.trigger_answer_ids)), first)
                choices.append((title, target))
            return choices
        choices = []
        for kid in kids:
            answers = kid.trigger_answer_ids.sorted(lambda a: (a.sequence, a.id))
            if len(answers) > 1:
                notes.append(_("“%s” was reached by several answers; only the "
                               "first is offered as a choice.", kid.name))
            if kid.trigger_variable_ids:
                notes.append(_("“%s” also had a variable rule, which was not "
                               "carried over.", kid.name))
            answer = (answers[0].value or '').strip() if answers else ''
            if answer.isdigit():
                # A numbered menu: the older engine shows "<number>. <step
                # name>", so the choice is the step's name and the number is
                # what it is stored as (typing it still picks the choice).
                choices.append((kid.name, kid, answer))
                if answer != str(len(choices)):
                    notes.append(_(
                        "“%(menu)s”: “%(choice)s” was number %(old)s and now "
                        "shows as number %(new)s. Typing %(old)s still works.",
                        menu=old.name, choice=kid.name, old=answer,
                        new=len(choices)))
            else:
                choices.append((answer or kid.name, kid))
        return choices

    def _value_of(self, old, save_to, names, notes):
        source = old.variable_data_source
        if source == 'answer':
            key = save_to.get(old.source_step_id.id)
            if not key:
                notes.append(_("“%s” kept the answer of a step that is not a "
                               "question; its value is now empty.", old.name))
                return ''
            return '{{state.%s}}' % key
        if source == 'variable':
            name = old.source_variable_id.name
            return '{{state.%s}}' % names.get(name, name) if name else ''
        return self._wording(old.variable_value, names)

    def _link_jump(self, old, step, chatbot, new, names, notes, done):
        target = old.target_chatbot_id
        if not target:
            notes.append(_("“%s” jumped to no bot; it now does nothing.", old.name))
            return
        if target == chatbot:
            roots = chatbot.step_ids.filtered(lambda s: not s.parent_id).sorted(
                lambda s: (s.sequence, s.id))
            entry = old.target_step_id or roots[:1]
            step.jump_target_step_id = new[entry.id] if entry else False
            return
        flow = self.import_bot(target, done)
        vals = {
            'jump_target_bot_id': flow.id,
            'jump_return': old.jump_mode == 'subroutine',
        }
        if old.jump_mode == 'subroutine':
            theirs = {v.name: re.sub(r'\W+', '_', v.name or '').strip('_')
                      for v in target.bot_variable_ids}
            vals['jump_mapping'] = [{
                'from': names.get(m.source_variable_id.name, m.source_variable_id.name),
                'to': theirs.get(m.target_variable_id.name, m.target_variable_id.name),
                'direction': m.direction,
            } for m in old.variable_mapping_ids]
        elif old.variable_mapping_ids:
            notes.append(_("“%s” passed variables on a one-way jump; they were "
                           "not carried over.", old.name))
        if old.target_step_id and old.target_step_id.parent_id:
            notes.append(_("“%s” jumped into the middle of the other bot; it now "
                           "starts at that flow's first step.", old.name))
        step.write(vals)
        notes.append(_("“%(step)s” goes to “%(flow)s”, which was brought over "
                       "too (or already was).", step=old.name, flow=flow.name))

    # ── Around the steps ─────────────────────────────────────────────────

    def _copy_keywords(self, chatbot, bot, channel, notes):
        if not channel:
            return
        words = [t.name for t in chatbot.bot_trigger_ids if t.name]
        for word in words:
            self.env['comm.bot.trigger'].create({
                'bot_id': bot.id,
                'channel_id': channel.id,
                'kind': 'keyword',
                'value': word,
                'match_mode': 'exact',
            })
        if words:
            notes.append(_(
                "Keywords carried over: %s. They do nothing while this flow is "
                "a draft. Once it is live, a message with one of them starts "
                "this flow and no longer the older bot.", ', '.join(words)))

    def _note_the_rest(self, chatbot, notes):
        if chatbot.global_interrupt_ids:
            notes.append(_(
                "The older bot had %s “at any time” keyword rules (for example "
                "typing MENU mid-way). Sediba Flows has no such rules yet.",
                len(chatbot.global_interrupt_ids)))
        if chatbot.ai_agent_prompt_text or chatbot.context_data or chatbot.context_url:
            notes.append(_("The older bot's AI instructions and context were not "
                           "carried over; add an AI reply step if you need them."))
        if chatbot.channel in ('ussd', 'voice'):
            notes.append(_("Walk this flow in Try it before going live: the older "
                           "engine has its own handling for %s that may differ.",
                           chatbot.channel.upper()))
