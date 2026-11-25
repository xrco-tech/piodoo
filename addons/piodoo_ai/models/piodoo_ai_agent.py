# -*- coding: utf-8 -*-
"""AI Agents: one record for each assistant that works inside piodoo.

The assistants stay in their own add-ons, with their tools, checks and limits
in code. What this app holds is the wording an admin may have changed. An
assistant asks for it with `_instructions_for(key, default)`, so it runs the
same when this app is not installed, and the screen reads the built-in
wording straight from the assistant's own module (FEATURES below).
"""
import importlib
import logging
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import formatLang

_logger = logging.getLogger(__name__)

DAYS = 30
CHAT_LIMIT = 60
TITLE_CHARS = 60
QUESTION_CHARS = 4000

# key -> where the assistant lives. `prompt` and `llm` are names in the module
# at `path`; `llm_param` is the setting that overrides the model, if any;
# `usage` is how its calls are tagged in billing; `chat` says whose chats the
# middle of the screen shows.
FEATURES = {
    'cc_sidekick': {
        'addon': 'contact_centre_ai_ops',
        'path': 'odoo.addons.contact_centre_ai_ops.models.contact_centre_ai_chat',
        'prompt': 'SYSTEM_PROMPT', 'llm': 'ANTHROPIC_MODEL', 'llm_param': False,
        'usage': ('contact_centre', 'ai_ops'), 'chat': 'cc',
    },
    'c2w_sidekick': {
        'addon': 'chat2work_workspace',
        'path': 'odoo.addons.chat2work_workspace.models.chat2work_sidekick',
        'prompt': 'SIDEKICK_SYSTEM', 'llm': 'DEFAULT_MODEL', 'llm_param': 'chat2work.occupation_model',
        'usage': ('chat2work', 'sidekick'), 'chat': 'c2w',
    },
    'reply_helper': {
        'addon': 'contact_centre_ai_copilot',
        'path': 'odoo.addons.contact_centre_ai_copilot.models.contact_centre_contact',
        'prompt': 'COPILOT_SYSTEM', 'llm': 'ANTHROPIC_MODEL', 'llm_param': False,
        'usage': ('contact_centre', 'copilot'), 'chat': False,
    },
    'call_notes': {
        'addon': 'comm_dialer',
        'path': 'odoo.addons.comm_dialer.models.transcription_mixin',
        'prompt': 'INSIGHT_PROMPT', 'llm': 'INSIGHT_MODEL', 'llm_param': 'comm_dialer.insight_model',
        'usage': ('other', 'call_notes'), 'chat': False,
    },
    'cv_reader': {
        'addon': 'chat2work',
        'path': 'odoo.addons.chat2work.models.chat2work_cv_rebuild',
        'prompt': 'SYSTEM', 'llm': 'DEFAULT_MODEL', 'llm_param': 'chat2work.cv_rebuild_model',
        'usage': ('chat2work', 'cv_rebuild'), 'chat': False,
    },
    'job_sorter': {
        'addon': 'chat2work_jobs',
        'path': 'odoo.addons.chat2work_jobs.models.chat2work_occupation',
        'prompt': 'SYSTEM', 'llm': 'DEFAULT_MODEL', 'llm_param': 'chat2work.occupation_model',
        'usage': ('chat2work', 'occupation'), 'chat': False,
    },
}

STATUSES = [('draft', 'Draft'), ('test', 'Test only'), ('live', 'Live')]


def model_label(name):
    """'claude-haiku-4-5-20251001' -> 'Haiku 4.5'. Anything else comes back as it is."""
    match = re.match(r'^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$', name or '')
    if not match:
        return name or ''
    family, major, minor = match.groups()
    return '%s %s' % (family.capitalize(), major + ('.' + minor if minor else ''))


class PiodooAiAgent(models.Model):
    _name = 'piodoo.ai.agent'
    _description = 'AI Agent'
    _order = 'sequence, id'

    key = fields.Char(required=True, readonly=True, index=True,
                      help='The name the assistant asks for its wording by.')
    name = fields.Char(required=True)
    sequence = fields.Integer(default=100)
    description = fields.Text()
    color = fields.Char(default='#374151')
    works_in = fields.Char(help='Where people meet this agent, separated by commas.')
    runs_note = fields.Char(help='When it runs, for an agent nobody chats with.')
    fixed_note = fields.Text(help='What stays in code whatever the wording says.')
    status = fields.Selection(STATUSES, default='live', required=True)
    instructions = fields.Text(help='The wording an admin saved. Empty means: as built.')
    version_ids = fields.One2many('piodoo.ai.agent.version', 'agent_id')

    _sql_constraints = [('key_unique', 'unique(key)', 'There is already an agent with this key.')]

    # ── What an assistant calls ──────────────────────────────────────────────

    @api.model
    def _instructions_for(self, key, default):
        """The wording the assistant `key` should use: what an admin saved, or
        `default`, its built-in wording. Never raises: a problem here must not
        stop the assistant."""
        try:
            agent = self.sudo().search([('key', '=', key)], limit=1)
            return (agent.instructions or '').strip() or default
        except Exception:  # noqa: BLE001
            _logger.exception("piodoo_ai: could not read the wording for %s", key)
            return default

    # ── Reading an assistant's own add-on ────────────────────────────────────

    @api.model
    def _installed_addons(self):
        names = sorted({spec['addon'] for spec in FEATURES.values()})
        return set(self.env['ir.module.module'].sudo().search(
            [('name', 'in', names), ('state', '=', 'installed')]).mapped('name'))

    def _spec(self):
        self.ensure_one()
        return FEATURES.get(self.key)

    def _feature_module(self):
        spec = self._spec()
        if not spec:
            return None
        try:
            return importlib.import_module(spec['path'])
        except Exception:  # noqa: BLE001
            _logger.warning("piodoo_ai: could not read %s", spec['path'], exc_info=True)
            return None

    def _built_in(self):
        """The wording in the assistant's own code, or ''."""
        module = self._feature_module()
        return (getattr(module, self._spec()['prompt'], '') or '').strip() if module else ''

    def _model_name(self):
        spec, module = self._spec(), self._feature_module()
        if not spec:
            return ''
        name = getattr(module, spec['llm'], '') if module else ''
        if spec['llm_param']:
            name = self.env['ir.config_parameter'].sudo().get_param(spec['llm_param']) or name
        return name or ''

    def _visible(self):
        """The agents whose assistant is installed here."""
        installed = self._installed_addons()
        return self.filtered(lambda a: a._spec() and a._spec()['addon'] in installed)

    # ── Runs and cost, from billing ──────────────────────────────────────────

    def _usage_domain(self, days=DAYS):
        source, feature = self._spec()['usage']
        return [('source', '=', source), ('feature', '=', feature),
                ('event_date', '>=', fields.Datetime.now() - timedelta(days=days))]

    def _money(self, amount, currency):
        if not currency:
            return '%.2f' % amount
        return formatLang(self.env, amount, currency_obj=currency)

    def _usage(self):
        """{'runs', 'cost'} over the last 30 days, or False when billing is not installed."""
        self.ensure_one()
        Event = self.env.get('comm.billing.event')
        if Event is None:
            return False
        Event, domain = Event.sudo(), self._usage_domain()
        runs = Event.search_count(domain + [('category', '=', 'llm_input')])
        groups = Event._read_group(domain, ['currency_id'], ['price_local:sum'])
        groups = sorted(groups, key=lambda g: -(g[1] or 0.0))
        cost = ' + '.join(self._money(total or 0.0, currency) for currency, total in groups if total)
        return {'runs': runs, 'cost': cost or (self._money(0.0, groups[0][0]) if groups else '')}

    def _days(self):
        """Runs and cost for each day it ran in the last 30 days, newest first."""
        self.ensure_one()
        Event = self.env.get('comm.billing.event')
        if Event is None:
            return []
        Event, domain = Event.sudo(), self._usage_domain()
        runs = dict(Event._read_group(domain + [('category', '=', 'llm_input')], ['event_date:day'], ['__count']))
        rows = {}
        for day, currency, total in Event._read_group(domain, ['event_date:day', 'currency_id'], ['price_local:sum']):
            rows.setdefault(day, []).append(self._money(total or 0.0, currency))
        return [{'day': fields.Date.to_string(day), 'runs': runs.get(day, 0), 'cost': ' + '.join(rows[day])}
                for day in sorted(rows, reverse=True) if day]

    # ── What the screen is given ─────────────────────────────────────────────

    @api.model
    def _check_admin(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Only an administrator can open AI Agents."))

    def _versions(self):
        """Every saved wording, newest first. Searched, because a list read
        earlier in the same request does not put a new save first."""
        return self.env['piodoo.ai.agent.version'].search([('agent_id', 'in', self.ids)])

    def _card(self):
        self.ensure_one()
        last = self._versions()[:1]
        return {
            'id': self.id,
            'key': self.key,
            'name': self.name,
            'letter': (self.name or '?')[:1].upper(),
            'color': self.color or '#374151',
            'status': self.status,
            'description': self.description or '',
            'works': [part.strip() for part in (self.works_in or '').split(',') if part.strip()],
            'runs_note': self.runs_note or '',
            'model': model_label(self._model_name()),
            'changed': bool((self.instructions or '').strip()),
            'changed_at': fields.Datetime.to_string(last.create_date) if last else False,
            'changed_by': last.user_id.name if last else '',
            'chat': bool(self._spec()['chat']),
            'usage': self._usage(),
        }

    def _own(self, agent_id):
        self._check_admin()
        agent = self.browse(int(agent_id or 0)).exists()._visible()
        if not agent:
            raise UserError(_("That agent is not on this system."))
        return agent

    @api.model
    def ui_home(self):
        self._check_admin()
        agents = self.search([])._visible()
        cards = [agent._card() for agent in agents]
        works = []
        for card in cards:
            works += [name for name in card['works'] if name not in works]
        return {'agents': cards, 'works': works}

    @api.model
    def ui_agent(self, agent_id):
        agent = self._own(agent_id)
        result = agent._card()
        built_in = agent._built_in()
        result.update({
            'instructions': (agent.instructions or '').strip() or built_in,
            'built_in': built_in,
            'fixed_note': agent.fixed_note or '',
            'versions': len(agent._versions()),
            'days': [] if result['chat'] else agent._days(),
            'chat_blocked': agent._chat_blocked() if result['chat'] else False,
        })
        return result

    @api.model
    def ui_save(self, agent_id, text):
        """Keep new wording. The same text as the built-in wording puts the agent back to "as built"."""
        agent = self._own(agent_id)
        text = (text or '').strip()
        if not text:
            raise UserError(_("An agent needs something to go on. To undo your changes, use \"Back to as built\"."))
        built_in = agent._built_in()
        current = (agent.instructions or '').strip() or built_in
        if text != current:
            as_built = text == built_in
            agent.write({'instructions': False if as_built else text})
            self.env['piodoo.ai.agent.version'].create({
                'agent_id': agent.id, 'instructions': text, 'as_built': as_built})
        return self.ui_agent(agent.id)

    @api.model
    def ui_reset(self, agent_id):
        agent = self._own(agent_id)
        return self.ui_save(agent.id, agent._built_in()) if agent._built_in() else self.ui_agent(agent.id)

    @api.model
    def ui_history(self, agent_id):
        agent = self._own(agent_id)
        return [{
            'id': version.id,
            'at': fields.Datetime.to_string(version.create_date),
            'by': version.user_id.name or '',
            'as_built': version.as_built,
            'text': version.instructions or '',
        } for version in agent._versions()]

    @api.model
    def ui_restore(self, version_id):
        self._check_admin()
        version = self.env['piodoo.ai.agent.version'].browse(int(version_id or 0)).exists()
        if not version:
            raise UserError(_("That version no longer exists."))
        return self.ui_save(version.agent_id.id, version.instructions)

    # ── Chats: the two Sidekicks keep their own, this only shows them ────────
    # Everything runs with the rights of the person on the screen, so a chat
    # here can do exactly what the same chat does in its own app.

    def _chat_blocked(self):
        """Why this person cannot chat with the agent here, or False."""
        kind = self._spec()['chat']
        if kind == 'cc' and not self.env['contact.centre.ai.chat'].has_access('create'):
            return _("You need the Contact Centre manager role to chat with this agent.")
        if kind == 'c2w' and not self.env.user.has_group('chat2work.group_agent'):
            return _("You need the Chat2Work agent role to chat with this agent.")
        return False

    def _chat_agent(self, agent_id):
        agent = self._own(agent_id)
        if not agent._spec()['chat']:
            raise UserError(_("Nobody chats with this agent: it runs on its own."))
        blocked = agent._chat_blocked()
        if blocked:
            raise AccessError(blocked)
        return agent

    def _cc_own(self, chat_id=False):
        domain = [('user_id', '=', self.env.uid)] + ([('id', '=', int(chat_id))] if chat_id else [])
        return self.env['contact.centre.ai.chat'].search(domain, limit=1 if chat_id else CHAT_LIMIT)

    def _cc_chat_out(self, chat):
        messages = [{
            'id': message.id,
            'role': 'me' if message.role == 'user' else 'agent',
            'text': message.content or '',
            'at': fields.Datetime.to_string(message.create_date),
            'buttons': [], 'draft': False, 'lines': [], 'note': '',
        } for message in chat.message_ids]
        if messages and messages[-1]['role'] == 'agent':
            messages[-1]['buttons'] = chat.message_ids[-1].suggestions or []
        return {'id': chat.id, 'name': chat.name, 'messages': messages,
                'waiting': bool(chat.pending_state)}

    def _c2w_chat_out(self, chat):
        messages = []
        for message in chat['messages']:
            mine = message['role'] == 'agent'
            rows = (message.get('list') or {}).get('rows') or []
            messages.append({
                'id': message['id'],
                'role': 'me' if mine else 'agent',
                'text': message['text'],
                'at': message['at'],
                'buttons': [],
                'draft': (message.get('draft') or {}).get('text') or False,
                'lines': [row.get('name') or '' for row in rows],
                'note': message.get('source') or '',
            })
        if messages and messages[-1]['role'] == 'agent':
            messages[-1]['buttons'] = chat['messages'][-1].get('follow_ups') or []
        return {'id': chat['id'], 'name': chat['name'], 'messages': messages, 'waiting': False}

    @api.model
    def ui_chats(self, agent_id, search=''):
        """The person's own chats with the agent, newest first."""
        agent = self._chat_agent(agent_id)
        term = (search or '').strip()
        if agent._spec()['chat'] == 'c2w':
            rows = self.env['chat2work.workspace'].ws_sidekick_chats('all', term, 0, CHAT_LIMIT)
            return [{'id': row['id'], 'name': row['name'], 'preview': row['preview'], 'at': row['at']}
                    for row in rows]
        chats = self._cc_own()
        if term:
            chats = chats.filtered(lambda c: term.lower() in (c.name or '').lower())
        return [{'id': chat.id, 'name': chat.name, 'preview': '',
                 'at': fields.Datetime.to_string(chat.write_date)} for chat in chats]

    @api.model
    def ui_chat(self, agent_id, chat_id):
        agent = self._chat_agent(agent_id)
        if agent._spec()['chat'] == 'c2w':
            chat = self.env['chat2work.workspace'].ws_sidekick_chat(int(chat_id or 0))
            return self._c2w_chat_out(chat) if chat else False
        chat = self._cc_own(chat_id)
        return self._cc_chat_out(chat) if chat else False

    @api.model
    def ui_ask(self, agent_id, chat_id, text):
        """Say `text` in the chat (a new chat when `chat_id` is False).
        Returns the chat, or {'error'} with nothing kept."""
        agent = self._chat_agent(agent_id)
        text = (text or '').strip()[:QUESTION_CHARS]
        if not text:
            return {'error': _("Type a message.")}
        if agent._spec()['chat'] == 'c2w':
            chat = self.env['chat2work.workspace'].ws_sidekick_ask(int(chat_id or 0) or False, text)
            return chat if chat.get('error') else self._c2w_chat_out(chat)
        if chat_id:
            chat = self._cc_own(chat_id)
            if not chat:
                return {'error': _("That chat no longer exists.")}
        else:
            chat = self.env['contact.centre.ai.chat'].create({'name': text[:TITLE_CHARS].strip()})
        chat.send_message(text)
        return self._cc_chat_out(chat)


class PiodooAiAgentVersion(models.Model):
    _name = 'piodoo.ai.agent.version'
    _description = 'AI Agent Wording, As Saved'
    _order = 'id desc'

    agent_id = fields.Many2one('piodoo.ai.agent', required=True, ondelete='cascade', index=True)
    instructions = fields.Text(required=True)
    as_built = fields.Boolean(help='This save put the agent back to its built-in wording.')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
