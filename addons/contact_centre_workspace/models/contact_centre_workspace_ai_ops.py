# -*- coding: utf-8 -*-
"""What the AI Ops section of the workspace reads: the copilot chats and one
chat with its messages and the actions the copilot took.

The chat itself (talking to the AI, running its tools, holding changes until
a human says yes) stays in contact_centre_ai_ops: the section sends through
that addon's own send_message. This file only reads, starts a chat and
renames one, and only works when that addon is installed.

Managers only, as the AI Ops screen has always been."""

import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .contact_centre_workspace_campaigns import MANAGER

CHAT = 'contact.centre.ai.chat'
# The marks of the copilot's markdown, left out of a one-line preview.
INLINE_MARKS = re.compile(r'[*`#]+')
BLOCK_MARKS = re.compile(r'\||^\s*[-:]+\s*', re.M)


class ContactCentreWorkspace(models.AbstractModel):
    _inherit = 'contact.centre.workspace'

    # ── Helpers ──────────────────────────────────────────────────────────
    @api.model
    def _ai_ops_available(self):
        return CHAT in self.env and self.env.user.has_group(MANAGER)

    def _ai_ops(self):
        self._agent()
        if CHAT not in self.env:
            raise UserError(_("The AI copilot isn't installed."))
        if not self.env.user.has_group(MANAGER):
            raise AccessError(_("Only Contact Centre managers can use the AI copilot."))

    @api.model
    def _ai_chat(self, chat_id):
        chat = self.env[CHAT].search([('id', '=', int(chat_id or 0))], limit=1)
        if not chat:
            raise UserError(_("This chat no longer exists."))
        return chat

    @api.model
    def _ai_held(self, chat):
        """The changes the copilot is holding until the user says yes."""
        pending = chat.pending_state or {}
        return [{'tool': call.get('name') or '', 'input': call.get('input') or {}} for call in pending.get('held') or []]

    @api.model
    def ws_boot(self):
        boot = super().ws_boot()
        boot['ai_ops'] = self._ai_ops_available()
        return boot

    # ── The list ─────────────────────────────────────────────────────────
    @api.model
    def ws_ai_chats(self, search='', offset=0, limit=40):
        self._ai_ops()
        domain = []
        term = (search or '').strip()
        if term:
            domain += ['|', ('name', 'ilike', term), ('message_ids.content', 'ilike', term)]
        Chat = self.env[CHAT]
        total = Chat.search_count(domain)
        chats = Chat.search(domain, order='write_date desc, id desc', offset=int(offset), limit=int(limit))
        last = {}
        if chats:
            self.env['contact.centre.ai.chat.message'].flush_model()
            self.env.cr.execute("""
                SELECT DISTINCT ON (session_id) session_id, role, content
                  FROM contact_centre_ai_chat_message
                 WHERE session_id IN %s
                 ORDER BY session_id, create_date DESC, id DESC
            """, [tuple(chats.ids)])
            last = {chat_id: (role, content) for chat_id, role, content in self.env.cr.fetchall()}
        rows = []
        for chat in chats:
            role, content = last.get(chat.id, (False, ''))
            rows.append({
                'id': chat.id,
                'name': chat.name,
                'at': fields.Datetime.to_string(chat.write_date),
                'preview': self._preview(BLOCK_MARKS.sub(' ', INLINE_MARKS.sub('', content or ''))),
                'mine_last': role == 'user',
                'waiting': bool(self._ai_held(chat)),
                'by': chat.user_id.name if chat.user_id != self.env.user else '',
            })
        return {'rows': rows, 'total': total, 'more': total > int(offset) + len(rows)}

    # ── One chat ─────────────────────────────────────────────────────────
    @api.model
    def ws_ai_chat(self, chat_id):
        self._ai_ops()
        chat = self._ai_chat(chat_id)
        return {
            'id': chat.id,
            'name': chat.name,
            'by': chat.user_id.name if chat.user_id != self.env.user else '',
            'messages': [{
                'id': m.id, 'mine': m.role == 'user', 'content': m.content or '',
                'suggestions': m.suggestions if isinstance(m.suggestions, list) else [],
                'at': fields.Datetime.to_string(m.create_date),
            } for m in chat.message_ids],
            'actions': [{
                'id': a.id, 'tool': a.tool_name, 'input': a.tool_input or {}, 'result': a.tool_result or {},
                'ok': bool(a.success),
                'declined': isinstance(a.tool_result, dict) and bool(a.tool_result.get('declined')),
                'at': fields.Datetime.to_string(a.create_date),
            } for a in chat.action_ids],
            'held': self._ai_held(chat),
        }

    @api.model
    def ws_ai_new_chat(self):
        self._ai_ops()
        return self.env[CHAT].create({'name': _("New chat")}).id

    @api.model
    def ws_ai_rename(self, chat_id, name):
        self._ai_ops()
        name = ' '.join((name or '').split())
        if not name:
            raise UserError(_("A chat needs a name."))
        self._ai_chat(chat_id).write({'name': name})
        return name
