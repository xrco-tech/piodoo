# -*- coding: utf-8 -*-
"""Phase 7 — AI Ops: chat-to-draft-campaign, ported onto the Gen-2 models.

Safety posture preserved from contact_centre_ai_ops:
- NO sudo(): every tool runs as the person chatting, so their Odoo ACLs apply.
- Draft-only: create_campaign lands in draft (state default); update_campaign
  refuses non-draft campaigns; there is deliberately NO tool to start / schedule
  / launch / send — a human clicks Start in the UI.
- Per-tool savepoint: a failed tool call rolls back only itself, never the turn.

Reuses comm_chatbot's official `anthropic` SDK + comm_chatbot.anthropic_api_key.
"""
import json
import logging
import re

from odoo import api, models

try:
    import anthropic  # type: ignore
    _ANTHROPIC_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ANTHROPIC_AVAILABLE = False

_logger = logging.getLogger(__name__)

OPS_MODEL = 'claude-opus-5'
OPS_MAX_TOKENS = 4096
MAX_TOOL_ITERATIONS = 6

SYSTEM_PROMPT = (
    "You are the Unified CX marketing assistant inside an Odoo app. You help the "
    "user draft and edit outbound campaigns using the tools provided.\n\n"
    "Hard rules:\n"
    "- Campaigns you create or edit ALWAYS stay in draft. You have NO tool to "
    "start, launch, schedule, or send a campaign — a human reviews and clicks "
    "Start themselves. Never claim you launched or sent anything.\n"
    "- update_campaign only works on draft campaigns; if a campaign has already "
    "started it will refuse — tell the user plainly.\n"
    "- Every tool runs with the permissions of the person chatting with you, not "
    "an admin. If a tool fails with a permission error, that means this user "
    "lacks that access — say so plainly; don't imply a bug or suggest workarounds.\n"
    "- Use the read-only lookups (list_campaigns, list_bots, search_contacts) to "
    "find real ids yourself instead of asking the user or guessing. A campaign "
    "needs a bot_id (from list_bots) — pick one or ask which bot to run.\n"
    "- Keep replies short and practical. If a tool fails, explain it plainly "
    "rather than retrying blindly.\n\n"
    "When your reply ends on a genuine yes/no or a small choice between real "
    "options you just looked up, end the message with a quick-reply tag on its "
    "own final line: <<suggestions>>[\"short option 1\",\"short option 2\"]<<end>> "
    "— 2-4 options, each phrased as something the user would say, valid JSON, "
    "nothing after it. Only when there's a real decision point."
)

TOOLS = [
    {
        "name": "create_campaign",
        "description": "Create a new DRAFT campaign. It stays in draft; you cannot start it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "bot_id": {"type": "integer", "description": "comm.bot id (from list_bots)"},
                "purpose": {"type": "string", "description": "e.g. marketing / support"},
                "audience_domain": {"type": "string", "description": "Odoo domain on res.partner, e.g. [('category_id.name','=','VIP')]"},
                "budget_cap_local": {"type": "number"},
            },
            "required": ["name", "bot_id"],
        },
    },
    {
        "name": "update_campaign",
        "description": "Update a DRAFT campaign's fields. Refuses non-draft campaigns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "integer"},
                "name": {"type": "string"},
                "bot_id": {"type": "integer"},
                "purpose": {"type": "string"},
                "audience_domain": {"type": "string"},
                "budget_cap_local": {"type": "number"},
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "list_campaigns",
        "description": "List campaigns (id, name, state) to find a campaign_id.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_bots",
        "description": "List bots (id, name, ready) — a campaign needs a bot_id.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_contacts",
        "description": "Search contacts (res.partner) by free text over name/phone/email.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    },
]


class CxAiOps(models.TransientModel):
    _name = 'cx.ai.ops'
    _description = 'UCX AI Ops assistant'

    @api.model
    def chat(self, messages):
        """Run the tool loop over the client-supplied history (list of
        {role, content} text turns). Returns {reply, suggestions}."""
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'comm_chatbot.anthropic_api_key')
        if not (api_key and _ANTHROPIC_AVAILABLE):
            return {'reply': 'AI Ops is not configured yet — set '
                             'comm_chatbot.anthropic_api_key in Settings.',
                    'suggestions': []}

        convo = [{'role': m['role'], 'content': m['content']}
                 for m in (messages or []) if m.get('content')]
        client = anthropic.Anthropic(api_key=api_key)

        for _iteration in range(MAX_TOOL_ITERATIONS):
            try:
                resp = client.messages.create(
                    model=OPS_MODEL, max_tokens=OPS_MAX_TOKENS,
                    system=SYSTEM_PROMPT, messages=convo, tools=TOOLS)
            except Exception as e:  # pragma: no cover
                _logger.warning('cx ai ops request failed: %s', e)
                return {'reply': 'Sorry, the AI request failed.', 'suggestions': []}

            tool_uses = [b for b in resp.content if getattr(b, 'type', None) == 'tool_use']
            if not tool_uses:
                text = "".join(getattr(b, 'text', '') for b in resp.content
                               if getattr(b, 'type', None) == 'text')
                clean, suggestions = self._cx_extract_suggestions(text)
                return {'reply': clean, 'suggestions': suggestions}

            convo.append({'role': 'assistant', 'content': resp.content})
            results = []
            for block in tool_uses:
                result = self._cx_execute_tool(block.name, block.input or {})
                results.append({
                    'type': 'tool_result',
                    'tool_use_id': block.id,
                    'content': json.dumps(result),
                })
            convo.append({'role': 'user', 'content': results})

        return {'reply': "I couldn't finish that within the allowed steps.",
                'suggestions': []}

    # ------------------------------------------------------------------ tools
    def _cx_execute_tool(self, name, args):
        handlers = {
            'create_campaign': self._tool_create_campaign,
            'update_campaign': self._tool_update_campaign,
            'list_campaigns': self._tool_list_campaigns,
            'list_bots': self._tool_list_bots,
            'search_contacts': self._tool_search_contacts,
        }
        handler = handlers.get(name)
        if not handler:
            return {'error': 'Unknown tool: %s' % name}
        try:
            # Savepoint: a failed tool rolls back only itself, not the turn.
            with self.env.cr.savepoint():
                return handler(args)
        except Exception as e:
            _logger.warning('cx ai ops tool %s failed: %s', name, e)
            return {'error': str(e)}

    def _campaign_vals(self, args):
        vals = {}
        for key in ('name', 'bot_id', 'purpose', 'audience_domain', 'budget_cap_local'):
            if key in args and args[key] not in (None, ''):
                vals[key] = args[key]
        return vals

    def _tool_create_campaign(self, args):
        # No sudo — runs as the calling user. state defaults to 'draft'.
        campaign = self.env['comm.campaign'].create(self._campaign_vals(args))
        return {'campaign_id': campaign.id, 'name': campaign.name,
                'state': campaign.state}

    def _tool_update_campaign(self, args):
        campaign = self.env['comm.campaign'].browse(args['campaign_id'])
        if not campaign.exists():
            return {'error': 'Campaign %s not found' % args['campaign_id']}
        if campaign.state != 'draft':
            return {'error': 'Campaign %s is %s, not draft — only draft campaigns '
                             'can be edited here.' % (campaign.id, campaign.state)}
        vals = self._campaign_vals(args)
        campaign.write(vals)
        return {'campaign_id': campaign.id, 'updated_fields': list(vals.keys())}

    def _tool_list_campaigns(self, args):
        campaigns = self.env['comm.campaign'].search([], limit=50)
        return {'campaigns': [
            {'id': c.id, 'name': c.name, 'state': c.state} for c in campaigns]}

    def _tool_list_bots(self, args):
        bots = self.env['comm.bot'].search([], limit=50)
        return {'bots': [
            {'id': b.id, 'name': b.name, 'ready': bool(b.entry_step_id)} for b in bots]}

    def _tool_search_contacts(self, args):
        query = (args.get('query') or '').strip()
        domain = []
        if query:
            domain = ['|', '|', ('name', 'ilike', query),
                      ('phone', 'ilike', query), ('email', 'ilike', query)]
        partners = self.env['res.partner'].search(domain, limit=20)
        return {'contacts': [
            {'id': p.id, 'name': p.name, 'phone': p.phone or p.mobile,
             'email': p.email} for p in partners]}

    # ------------------------------------------------------------- suggestions
    @staticmethod
    def _cx_extract_suggestions(text):
        m = re.search(r'<<suggestions>>\s*(\[.*?\])\s*<<end>>', text, re.DOTALL)
        if not m:
            return text.strip(), []
        clean = text[:m.start()].strip()
        try:
            suggestions = json.loads(m.group(1))
            if not isinstance(suggestions, list):
                suggestions = []
        except (ValueError, TypeError):
            suggestions = []
        return clean, [str(s) for s in suggestions][:4]
