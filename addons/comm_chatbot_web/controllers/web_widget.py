# -*- coding: utf-8 -*-
"""HTTP endpoints for the web chat widget.

- GET /comm_chatbot_web/widget.js         — the standalone JS widget
- GET /comm_chatbot_web/widget.css        — widget styling
- GET /comm_chatbot_web/embed/<bot_id>    — a full HTML page that hosts the
                                             widget (for iframing in the
                                             device simulator + as an easy
                                             preview link)
- POST /comm_chatbot_web/session/start    — start a chat session
- POST /comm_chatbot_web/session/message  — send a user message; receive bot response
- POST /comm_chatbot_web/session/close    — end session
"""
import logging
import os
import uuid
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
WIDGET_DIR = os.path.abspath(os.path.join(HERE, '..', 'static', 'src', 'widget'))


class WebWidgetController(http.Controller):

    # ── Widget assets ────────────────────────────────────────────────
    @http.route('/comm_chatbot_web/widget.js',
                type='http', auth='public', methods=['GET'], csrf=False)
    def widget_js(self, **kwargs):
        return self._serve_static('widget.js', 'application/javascript')

    @http.route('/comm_chatbot_web/widget.css',
                type='http', auth='public', methods=['GET'], csrf=False)
    def widget_css(self, **kwargs):
        return self._serve_static('widget.css', 'text/css')

    def _serve_static(self, filename, content_type):
        path = os.path.join(WIDGET_DIR, filename)
        try:
            with open(path, 'rb') as f:
                body = f.read()
        except OSError:
            return request.not_found()
        return request.make_response(
            body,
            headers=[
                ('Content-Type', content_type + '; charset=utf-8'),
                ('Cache-Control', 'public, max-age=300'),
                ('Access-Control-Allow-Origin', '*'),
            ],
        )

    # ── Embed page ───────────────────────────────────────────────────
    @http.route('/comm_chatbot_web/embed/<int:bot_id>',
                type='http', auth='public', methods=['GET'], csrf=False)
    def embed_page(self, bot_id, preview=None, **kwargs):
        bot = request.env['comm.bot'].sudo().browse(bot_id)
        if not bot.exists():
            return request.not_found()
        is_preview = bool(preview)
        base = request.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '') or ''
        html = _EMBED_TEMPLATE.format(
            bot_name=(bot.name or '').replace('<', '&lt;'),
            bot_id=bot.id,
            preview='true' if is_preview else 'false',
            base_url=base,
        )
        return request.make_response(
            html, headers=[('Content-Type', 'text/html; charset=utf-8'),
                           ('X-Frame-Options', 'SAMEORIGIN')])

    # ── Session endpoints ────────────────────────────────────────────
    @http.route('/comm_chatbot_web/session/start',
                type='json', auth='public', csrf=False, cors='*')
    def session_start(self, bot_id, referer=None, user_agent=None,
                      preview=False, persona_name=None, persona_mobile=None,
                      **kwargs):
        env = request.env
        bot = env['comm.bot'].sudo().browse(int(bot_id))
        if not bot.exists() or not bot.entry_step_id:
            return {'error': 'bot has no entry step'}

        Session = env['comm.bot.web.session'].sudo()
        Partner = env['res.partner'].sudo()

        # For preview sessions, mint a throwaway partner; for real ones, an
        # anonymous "Web visitor" record so partner references resolve.
        if preview:
            partner = Partner.create({
                'name': persona_name or 'Web preview',
                'mobile': persona_mobile or '+27600000000',
            })
        else:
            partner = Partner.create({
                'name': persona_name or 'Web visitor',
            })

        channel = env['comm.channel'].sudo().get_by_code('web')
        if not channel:
            return {'error': 'web channel not configured'}

        conversation = env['comm.conversation'].sudo().create({
            'partner_id': partner.id,
            'bot_id': bot.id,
            'primary_channel_id': channel.id,
            'current_step_id': bot.entry_step_id.id,
            'outcome': '__preview_walker__' if preview else False,
            'lifecycle_state': 'open',
        })
        leg = env['comm.conversation.leg'].sudo().create({
            'conversation_id': conversation.id,
            'channel_id': channel.id,
            'external_session_id': f'web-{conversation.id}',
        })

        session = Session.create({
            'token': uuid.uuid4().hex,
            'bot_id': bot.id,
            'conversation_id': conversation.id,
            'partner_id': partner.id,
            'referer': referer,
            'user_agent': user_agent,
            'is_preview': bool(preview),
        })

        # Advance from entry — force shadow (widget captures rendered_body itself)
        ctx = {'comm_chatbot_force_shadow': True,
               'comm_chatbot_skip_llm': preview}
        env['comm.chatbot.executor'].sudo().with_context(**ctx).advance(
            conversation, leg)

        return _serialize(env, session, conversation)

    @http.route('/comm_chatbot_web/session/message',
                type='json', auth='public', csrf=False, cors='*')
    def session_message(self, token, body=None, option_value=None, **kwargs):
        env = request.env
        session = env['comm.bot.web.session'].sudo().get_by_token(token)
        if not session:
            return {'error': 'session not found'}
        session.touch()
        conversation = session.conversation_id
        if not conversation or conversation.lifecycle_state in (
                'closed', 'timeout'):
            return {'error': 'conversation closed',
                    **_serialize(env, session, conversation)}

        leg = conversation.leg_ids.filtered(lambda l: not l.closed_at)[:1]
        user_body = (option_value or body or '').strip()

        env['comm.interaction'].sudo().create({
            'conversation_id': conversation.id,
            'leg_id': leg.id if leg else False,
            'channel_id': conversation.primary_channel_id.id,
            'direction': 'inbound',
            'raw_body': user_body,
            'status': 'received',
            'step_id': (conversation.current_step_id.id
                         if conversation.current_step_id else False),
        })

        ctx = {'comm_chatbot_force_shadow': True,
               'comm_chatbot_skip_llm': session.is_preview}
        Exec = env['comm.chatbot.executor'].sudo().with_context(**ctx)
        step = conversation.current_step_id
        if step and step.kind in ('menu', 'input'):
            Exec._handle_input(conversation, leg, user_body)
        else:
            Exec.advance(conversation, leg)

        return _serialize(env, session, conversation)

    @http.route('/comm_chatbot_web/session/close',
                type='json', auth='public', csrf=False, cors='*')
    def session_close(self, token, **kwargs):
        session = request.env['comm.bot.web.session'].sudo().get_by_token(token)
        if session:
            session.close()
        return {'ok': True}


def _serialize(env, session, conversation):
    """Turn conversation state into the JSON the widget consumes."""
    if not conversation:
        return {'token': session.token, 'messages': [], 'waiting': 'done'}

    messages = []
    for i in conversation.interaction_ids.sorted('at'):
        entry = {
            'direction': i.direction,
            'body': i.rendered_body or i.raw_body or '',
            'at': i.at.isoformat() if i.at else '',
        }
        # Attach options/media from the outbound's step so the widget can
        # render buttons + list + attachments.
        if i.direction == 'outbound' and i.step_id:
            entry['step_name'] = i.step_id.name
            entry['options'] = [{
                'label': o.label,
                'value': o.value or o.label,
            } for o in i.step_id.option_ids.sorted('sequence')
                          if i.step_id.kind == 'menu' and i == conversation.interaction_ids.sorted('at')[-1]]
            entry['media'] = [{
                'kind': m.kind,
                'url':  m.url or (m.attachment_id.public_url
                                    if m.attachment_id else ''),
                'alt':  m.alt_text or '',
            } for m in i.step_id.media_ids]
        messages.append(entry)

    step = conversation.current_step_id
    waiting = 'none'
    current_options = []
    if not step or conversation.lifecycle_state in ('closed', 'timeout'):
        waiting = 'done'
    elif step.kind == 'menu':
        waiting = 'menu'
        current_options = [{'label': o.label, 'value': o.value or o.label}
                            for o in step.option_ids.sorted('sequence')]
    elif step.kind == 'input':
        waiting = 'input'

    return {
        'token': session.token,
        'bot_name': session.bot_id.name,
        'messages': messages,
        'waiting': waiting,
        'current_step_name': step.name if step else '',
        'current_options': current_options,
    }


_EMBED_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>{bot_name}</title>
    <link rel="stylesheet" href="/comm_chatbot_web/widget.css"/>
    <style>
        html, body {{ margin: 0; padding: 0; height: 100%%; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                Roboto, sans-serif; background: #f4f4f6; }}
        /* When embedded fullscreen, take the whole viewport */
        body.o_ccw_fullscreen .o_ccw_widget {{
            position: static; width: 100%%; height: 100%%; border-radius: 0;
            box-shadow: none;
        }}
        body.o_ccw_fullscreen .o_ccw_bubble {{ display: none; }}
    </style>
</head>
<body class="o_ccw_fullscreen">
    <script>
        window.COMM_CHATBOT_WEB = {{
            botId: {bot_id},
            preview: {preview},
            baseUrl: "{base_url}",
            autoOpen: true,
        }};
    </script>
    <script src="/comm_chatbot_web/widget.js"></script>
</body>
</html>
"""
