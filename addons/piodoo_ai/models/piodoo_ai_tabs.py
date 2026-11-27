# -*- coding: utf-8 -*-
"""Skills, Knowledge, Triggers and Limits of an agent.

Like the wording, each of these is something the assistant asks this app for
(`_tools_for`, `_library_only`, `_model_for`, `_stopped`, `_answer_cap`), so
an assistant with nothing set here behaves exactly as built. None of the
calls an assistant makes may raise: a problem here must not stop it.
"""
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date

from .piodoo_ai_agent import model_label

_logger = logging.getLogger(__name__)

LIBRARY_TOOL = 'look_up_reference'

# What each agent has beyond its wording.
#   skills: (key, name, 'reads' | 'makes', what it is for, tool names)
#   library: the Library space it reads, or False
#   crons: (xml id, what it does, why it cannot be switched off here or '')
#   places: where people meet it
#   who: who may use it (decided by the assistant's own add-on)
TABS = {
    'cc_sidekick': {
        'skills': [
            ('campaigns', "Campaigns", 'makes', "List, make and change campaigns. They stay drafts.",
             ['list_campaigns', 'create_campaign', 'update_campaign']),
            ('contacts', "Contacts", 'makes', "Find, add and change contacts.",
             ['search_contacts', 'list_contact_categories', 'create_contacts_from_partners',
              'create_contact', 'update_contact']),
            ('templates', "Templates", 'makes', "Message templates and WhatsApp templates. Never sent to Meta.",
             ['list_templates', 'create_template', 'update_template',
              'list_whatsapp_templates', 'create_whatsapp_template', 'update_whatsapp_template']),
            ('call_teams', "Call teams and routing", 'makes', "Teams and who a call goes to.",
             ['list_call_teams', 'create_call_team', 'update_call_team',
              'list_call_routing_rules', 'create_call_routing_rule', 'update_call_routing_rule']),
            ('flows', "Chatbot flows", 'makes', "List, make and extend simple flows. They stay unpublished.",
             ['list_chatbots', 'create_chatbot_flow', 'update_chatbot_flow', 'list_chatbot_sessions']),
            ('dashboard', "Dashboard cards", 'makes', "Add, change and remove cards on the dashboard.",
             ['create_dashboard_card', 'update_dashboard_card', 'delete_dashboard_card']),
            ('history', "Messages and calls", 'reads', "Look through recent messages and calls.",
             ['list_messages', 'list_call_logs']),
            ('library', "Library", 'reads', "Look something up in the Library.", [LIBRARY_TOOL]),
        ],
        'asks_first': True,
        'library': 'contact_centre',
        'crons': [],
        'places': ["Sidekick in the Contact Centre workspace", "The chat on this screen"],
        'who': "Contact Centre managers",
    },
    'c2w_sidekick': {
        'skills': [
            ('people', "Candidates and lists", 'reads', "Who is on each list, and one candidate's record.",
             ['count_lists', 'list_people', 'find_candidate', 'get_candidate']),
            ('notes', "How-to notes", 'reads', "The notes written for agents.", ['read_notes']),
            ('bookings', "Bookings", 'reads', "Interview slots and how full they are.", ['list_bookings']),
            ('drafts', "Drafts for you to send", 'reads',
             "Writes a message for you to read, edit and send yourself. It sends nothing.", ['draft_message']),
            ('library', "Library", 'reads', "Look something up in the Library.", [LIBRARY_TOOL]),
        ],
        'asks_first': False,
        'library': 'chat2work',
        'crons': [],
        'places': ["Sidekick in the Chat2Work workspace", "The chat on this screen"],
        'who': "Chat2Work agents",
    },
    'reply_helper': {
        'skills': [], 'asks_first': False, 'library': False,
        'crons': [('contact_centre_ai_copilot.ir_cron_ai_copilot',
                   "Go through conversations with new messages", '')],
        'places': ["The conversation panel in the Contact Centre inbox"],
        'who': "Nobody starts it. Contact Centre agents see what it wrote.",
    },
    'call_notes': {
        'skills': [], 'asks_first': False, 'library': False,
        'crons': [('comm_dialer.ir_cron_dialer_transcribe', "Type out new call recordings, then write the notes",
                   "This timer also types out recordings and WhatsApp voice notes, so it is not switched off from here.")],
        'places': ["The call record, under the recording"],
        'who': "Nobody starts it. Whoever can open the call sees its notes.",
    },
    'cv_reader': {
        'skills': [], 'asks_first': False, 'library': False,
        'crons': [('chat2work.ir_cron_chat2work_cv_rebuild', "Read newly uploaded CVs", '')],
        'places': ["The candidate's CV in Chat2Work"],
        'who': "Nobody starts it. Chat2Work agents see the CV it filled in.",
    },
    'job_sorter': {
        'skills': [], 'asks_first': False, 'library': False,
        'crons': [('chat2work_jobs.ir_cron_chat2work_occupations', "Sort job posts with no occupation",
                   "This timer also sorts candidates' CVs, so it is not switched off from here.")],
        'places': ["The occupation on each job post in Chat2Work"],
        'who': "Nobody starts it. Chat2Work agents can ask for a new suggestion on a job post.",
    },
}

EVERY = {'minutes': ("Every minute", "Every %s minutes"), 'hours': ("Every hour", "Every %s hours"),
         'days': ("Every day", "Every %s days"), 'weeks': ("Every week", "Every %s weeks"),
         'months': ("Every month", "Every %s months")}


class PiodooAiAgentTabs(models.Model):
    _inherit = 'piodoo.ai.agent'

    skills_off = fields.Char(help='Keys of the skills switched off, separated by commas.')
    knowledge = fields.Json(help="{'docs': [ids], 'topics': [ids]} from the Library. Empty: all it is allowed.")
    library_only = fields.Boolean(help='Told to answer facts only from the Library.')
    model_name = fields.Char(help='The model an admin chose. Empty: as built.')
    monthly_cap = fields.Float(help='In the company currency. 0: no limit.')
    answer_cap = fields.Float(help='What one answer may cost, for an agent people chat with. 0: no limit.')

    def _tabs(self):
        self.ensure_one()
        return TABS.get(self.key) or {'skills': [], 'asks_first': False, 'library': False,
                                      'crons': [], 'places': [], 'who': ''}

    @api.model
    def _by_key(self, key):
        return self.sudo().search([('key', '=', key)], limit=1)

    # ── Skills ───────────────────────────────────────────────────────────────

    def _skills_off(self):
        return {part.strip() for part in (self.skills_off or '').split(',') if part.strip()}

    def _off_skills(self):
        """The skills switched off, as their registry rows."""
        if not self:
            return []
        off = self._skills_off()
        return [skill for skill in self._tabs()['skills'] if skill[0] in off]

    def _off_tools(self):
        return {tool for skill in self._off_skills() for tool in skill[4]}

    @api.model
    def _tools_for(self, key, tools):
        """`tools` without those of a skill that is switched off."""
        try:
            off = self._by_key(key)._off_tools()
            return [tool for tool in tools if tool.get('name') not in off] if off else tools
        except Exception:  # noqa: BLE001
            _logger.exception("piodoo_ai: could not read the skills of %s", key)
            return tools

    @api.model
    def _tool_allowed(self, key, name):
        try:
            return name not in self._by_key(key)._off_tools()
        except Exception:  # noqa: BLE001
            _logger.exception("piodoo_ai: could not read the skills of %s", key)
            return True

    # ── Knowledge ────────────────────────────────────────────────────────────

    def _knowledge(self):
        data = self.knowledge if self and isinstance(self.knowledge, dict) else {}
        return {'docs': [int(i) for i in data.get('docs') or []], 'topics': [int(i) for i in data.get('topics') or []]}

    @api.model
    def _library_only(self, key):
        """{'docs', 'topics'} the agent's look-ups are narrowed to, or None for all it is allowed."""
        try:
            chosen = self._by_key(key)._knowledge()
            return chosen if chosen['docs'] or chosen['topics'] else None
        except Exception:  # noqa: BLE001
            _logger.exception("piodoo_ai: could not read the knowledge of %s", key)
            return None

    def _library(self):
        """(the Library's assistant model or None, the space this agent reads or False)."""
        space = self._tabs()['library']
        return (self.env.get('sediba.assistant') if space else None), space

    def _library_allowed(self):
        """(docs, topics) the Library lets this agent read."""
        Assistant, space = self._library()
        return Assistant._docs(space), Assistant._findings(space).mapped('topic_id')

    def _doc_row(self, doc, allowed=True):
        version = doc._published() if allowed else doc.env['sediba.doc.version']
        published = version.published_on if version else False
        return {'kind': 'doc', 'id': doc.id, 'title': (version.name if version else doc.name) or '',
                'meta': _("Published %s", format_date(self.env, published.date(), date_format='d MMM y')) if published else '',
                'gone': not allowed}

    def _topic_row(self, topic, findings, allowed=True):
        count = len(findings.filtered(lambda f: f.topic_id == topic))
        return {'kind': 'topic', 'id': topic.id, 'title': topic.name or '',
                'meta': _("1 verified finding") if count == 1 else _("%s verified findings", count),
                'gone': not allowed}

    def _knowledge_out(self):
        Assistant, space = self._library()
        if not space:
            return {'reads': False}
        if Assistant is None:
            return {'reads': True, 'installed': False}
        docs, topics = self._library_allowed()
        findings = Assistant._findings(space)
        chosen = self._knowledge()
        Doc, Topic = self.env['sediba.doc'].sudo(), self.env['sediba.topic'].sudo()
        items = [self._doc_row(doc, doc in docs) for doc in Doc.browse(chosen['docs']).exists()]
        items += [self._topic_row(topic, findings, topic in topics)
                  for topic in Topic.browse(chosen['topics']).exists()]
        return {'reads': True, 'installed': True, 'only': self.library_only, 'items': items,
                'all_docs': len(docs), 'all_topics': len(topics)}

    # ── Triggers ─────────────────────────────────────────────────────────────

    def _cron_rows(self):
        rows = []
        for xml_id, label, locked in self._tabs()['crons']:
            cron = self.env.ref(xml_id, raise_if_not_found=False)
            if not cron:
                continue
            cron = cron.sudo()
            one, many = EVERY.get(cron.interval_type, ("", "%s"))
            rows.append({
                'id': cron.id, 'label': label, 'locked': locked, 'active': cron.active,
                'every': one if cron.interval_number == 1 else many % cron.interval_number,
                'last': fields.Datetime.to_string(cron.lastcall) if cron.lastcall else False,
                'next': fields.Datetime.to_string(cron.nextcall) if cron.active and cron.nextcall else False,
            })
        return rows

    # ── Limits ───────────────────────────────────────────────────────────────

    @api.model
    def _model_for(self, key, default):
        """The model the assistant `key` should call: what an admin chose, or `default`."""
        try:
            return (self._by_key(key).model_name or '').strip() or default
        except Exception:  # noqa: BLE001
            _logger.exception("piodoo_ai: could not read the model of %s", key)
            return default

    def _model_name(self):
        return (self.model_name or '').strip() or super()._model_name()

    def _model_options(self):
        """The models billing has a price for, so a chosen model's cost is always known."""
        names = []
        Rate = self.env.get('comm.billing.rate')
        if Rate is not None:
            names = [name for name in Rate.sudo().search([('category', '=', 'llm_input')]).mapped('carrier')
                     if (name or '').startswith('claude-')]
        return sorted(set(names))

    @api.model
    def _cost_of(self, events):
        """What the billing rows of one call cost, in the company currency."""
        try:
            return sum(events.sudo().mapped('price_local')) if events else 0.0
        except Exception:  # noqa: BLE001
            return 0.0

    def _month_spend(self):
        """Spent this calendar month, or None when billing is not installed."""
        Event = self.env.get('comm.billing.event')
        if Event is None or not self._spec():
            return None
        source, feature = self._spec()['usage']
        start = fields.Datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        groups = Event.sudo()._read_group(
            [('source', '=', source), ('feature', '=', feature), ('event_date', '>=', start)],
            [], ['price_local:sum'])
        return groups[0][0] or 0.0

    def _cap_reached(self):
        self.ensure_one()
        if not self.monthly_cap:
            return False
        spent = self._month_spend()
        return spent is not None and spent >= self.monthly_cap

    @api.model
    def _stopped(self, key):
        """Why the assistant `key` must not run now, or ''."""
        try:
            agent = self._by_key(key)
            if agent and agent._cap_reached():
                return _("%s has reached its spending limit for this month, so it has stopped. "
                         "An administrator can raise the limit in AI Agents.", agent.name)
        except Exception:  # noqa: BLE001
            _logger.exception("piodoo_ai: could not check the limit of %s", key)
        return ''

    @api.model
    def _answer_cap(self, key):
        try:
            return self._by_key(key).answer_cap or 0.0
        except Exception:  # noqa: BLE001
            return 0.0

    # ── The wording, with what the switches add ──────────────────────────────

    @api.model
    def _instructions_for(self, key, default):
        text = super()._instructions_for(key, default)
        try:
            agent = self._by_key(key)
            off = [skill[1] for skill in agent._off_skills()]
            if off:
                text += ("\n\nAn administrator has switched these off, so you cannot do them now: %s. "
                         "If asked, say so plainly." % ', '.join(off))
            if agent.library_only and agent._tabs()['library'] and LIBRARY_TOOL not in agent._off_tools():
                text += ("\n\nFor facts about the company, its rules, prices or how things are done, answer only "
                         "from the %s look-up. If it is not there, say you do not know." % LIBRARY_TOOL)
        except Exception:  # noqa: BLE001
            _logger.exception("piodoo_ai: could not add the switches to the wording of %s", key)
        return text

    # ── What the screen is given ─────────────────────────────────────────────

    def _card(self):
        card = super()._card()
        card['stopped'] = self._cap_reached()
        return card

    def _tabs_out(self):
        self.ensure_one()
        tabs, off = self._tabs(), self._skills_off()
        currency = self.env.company.currency_id
        spent = self._month_spend()
        as_built = super()._model_name()
        # Billing prices a dated name (…-20251001) as its family, so the two are one choice.
        options = self._model_options()
        for name in (self.model_name, as_built):
            if name and name not in options and re.sub(r'-\d{8}$', '', name) not in options:
                options.append(name)
        return {
            'skills': [{'key': key, 'label': label, 'level': level, 'hint': hint, 'on': key not in off}
                       for key, label, level, hint, _tools in tabs['skills']],
            'asks_first': tabs['asks_first'],
            'knowledge': self._knowledge_out(),
            'crons': self._cron_rows(),
            'places': tabs['places'],
            'limits': {
                'model': self.model_name or '',
                'as_built': as_built,
                'as_built_label': model_label(as_built),
                'options': [{'value': name, 'label': model_label(name)} for name in sorted(options)],
                'billing': spent is not None,
                'spent': spent or 0.0,
                'spent_text': self._money(spent or 0.0, currency),
                'monthly_cap': self.monthly_cap or 0.0,
                'monthly_cap_text': self._money(self.monthly_cap or 0.0, currency),
                'answer_cap': self.answer_cap or 0.0,
                'currency': currency.symbol or currency.name or '',
                'chat': bool(self._spec()['chat']),
                'who': tabs['who'],
            },
        }

    @api.model
    def ui_agent(self, agent_id):
        result = super().ui_agent(agent_id)
        result['tabs'] = self.browse(result['id'])._tabs_out()
        return result

    @api.model
    def ui_set_skill(self, agent_id, key, on):
        agent = self._own(agent_id)
        if key not in {skill[0] for skill in agent._tabs()['skills']}:
            raise UserError(_("This agent has no such skill."))
        off = agent._skills_off()
        off.discard(key) if on else off.add(key)
        agent.skills_off = ','.join(sorted(off)) or False
        return self.ui_agent(agent.id)

    def _library_agent(self, agent_id):
        agent = self._own(agent_id)
        Assistant, space = agent._library()
        if not space or Assistant is None:
            raise UserError(_("This agent does not read the Library."))
        return agent

    @api.model
    def ui_knowledge_options(self, agent_id):
        """What can still be added: all the Library lets this agent read, less what is listed."""
        agent = self._library_agent(agent_id)
        docs, topics = agent._library_allowed()
        chosen = agent._knowledge()
        findings = agent._library()[0]._findings(agent._tabs()['library'])
        return ([agent._doc_row(doc) for doc in docs if doc.id not in chosen['docs']]
                + [agent._topic_row(topic, findings) for topic in topics if topic.id not in chosen['topics']])

    @api.model
    def ui_knowledge_set(self, agent_id, kind, record_id, listed):
        """Add a doc or topic to the agent's list, or take it off."""
        agent = self._library_agent(agent_id)
        if kind not in ('doc', 'topic'):
            raise UserError(_("Choose a doc or a topic."))
        chosen, part, record_id = agent._knowledge(), kind + 's', int(record_id)
        if listed:
            docs, topics = agent._library_allowed()
            if record_id not in (docs if kind == 'doc' else topics).ids:
                raise UserError(_("The Library does not let this agent read that. Change it in the Library first."))
            if record_id not in chosen[part]:
                chosen[part].append(record_id)
        else:
            chosen[part] = [i for i in chosen[part] if i != record_id]
        agent.knowledge = chosen
        return self.ui_agent(agent.id)

    @api.model
    def ui_set_library_only(self, agent_id, on):
        agent = self._library_agent(agent_id)
        agent.library_only = bool(on)
        return self.ui_agent(agent.id)

    @api.model
    def ui_set_cron(self, agent_id, cron_id, active):
        """Switch one of the agent's own timers on or off."""
        agent = self._own(agent_id)
        row = next((row for row in agent._cron_rows() if row['id'] == int(cron_id)), None)
        if not row:
            raise UserError(_("This agent has no such timer."))
        if row['locked']:
            raise UserError(row['locked'])
        self.env['ir.cron'].sudo().browse(row['id']).active = bool(active)
        return self.ui_agent(agent.id)

    @api.model
    def ui_set_limits(self, agent_id, model, monthly_cap, answer_cap):
        agent = self._own(agent_id)
        model = (model or '').strip()
        if model and model not in agent._model_options() + [agent.model_name]:
            raise UserError(_("Ops Costs has no price for that model, so its cost could not be shown. Add its price first."))
        try:
            monthly_cap, answer_cap = float(monthly_cap or 0), float(answer_cap or 0)
        except (TypeError, ValueError):
            raise UserError(_("A limit is an amount, for example 250.")) from None
        if monthly_cap < 0 or answer_cap < 0:
            raise UserError(_("A limit cannot be less than nothing. Leave it empty for no limit."))
        if (monthly_cap or answer_cap) and agent._month_spend() is None:
            raise UserError(_("Limits need Ops Costs, which is not installed here."))
        agent.write({'model_name': model or False, 'monthly_cap': monthly_cap,
                     'answer_cap': answer_cap if agent._spec()['chat'] else 0.0})
        return self.ui_agent(agent.id)
