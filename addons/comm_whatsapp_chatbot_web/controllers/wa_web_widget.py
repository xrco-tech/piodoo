# -*- coding: utf-8 -*-
"""HTTP endpoints for embedding WA chatbots as a web widget.

Reuses comm_chatbot_web's widget.js — the widget accepts an
`endpointPrefix` config option so we can point it at
`/comm_whatsapp_chatbot_web/session/*` here.

session/start + session/message wrap whatsapp.chatbot.message's existing
simulate_turn to preserve session_state per widget token.
"""
import logging
import uuid
from urllib.parse import urlparse
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WaWebWidgetController(http.Controller):

    # ── Embed page (iframable) ───────────────────────────────────────
    @http.route('/comm_whatsapp_chatbot_web/embed/<int:chatbot_id>',
                type='http', auth='public', methods=['GET'], csrf=False)
    def embed_page(self, chatbot_id, preview=None, **kwargs):
        chatbot = request.env['whatsapp.chatbot'].sudo().browse(chatbot_id)
        if not chatbot.exists():
            return request.not_found()
        is_preview = bool(preview)
        base = request.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '') or ''
        allowed = chatbot._web_allowed_domain_list()
        frame_ancestors = "'self'"
        if allowed:
            frame_ancestors = "'self' " + ' '.join(allowed)

        html = _EMBED_TEMPLATE.format(
            chatbot_name=(chatbot.name or '').replace('<', '&lt;'),
            chatbot_id=chatbot.id,
            preview='true' if is_preview else 'false',
            base_url=base,
        )
        return request.make_response(
            html, headers=[
                ('Content-Type', 'text/html; charset=utf-8'),
                ('Content-Security-Policy',
                  f'frame-ancestors {frame_ancestors}'),
            ])

    # ── Session endpoints ────────────────────────────────────────────
    @http.route('/comm_whatsapp_chatbot_web/session/start',
                type='json', auth='public', csrf=False, cors='*')
    def session_start(self, chatbot_id, referer=None, user_agent=None,
                      preview=False, persona_name=None, persona_mobile=None,
                      **kwargs):
        env = request.env
        chatbot = env['whatsapp.chatbot'].sudo().browse(int(chatbot_id))
        if not chatbot.exists():
            return {'error': 'chatbot not found'}

        # Allowlist check
        origin = (request.httprequest.headers.get('Origin')
                  or request.httprequest.headers.get('Referer') or '')
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme:
                origin = f'{parsed.scheme}://{parsed.netloc}'
        if not chatbot._web_origin_allowed(origin):
            _logger.warning('WA web widget: origin %s not allowed for %s',
                            origin, chatbot.name)
            return {'error': 'origin not allowed'}

        Session = env['whatsapp.chatbot.web.session'].sudo()
        session = Session.create({
            'token': uuid.uuid4().hex,
            'chatbot_id': chatbot.id,
            'persona_name': persona_name or 'Web visitor',
            'persona_mobile': persona_mobile or '',
            'referer': referer,
            'user_agent': user_agent,
            'is_preview': bool(preview),
        })

        # Kick off the simulator with no user input
        result = self._simulate(env, session, user_input=None)
        return {'token': session.token, **result}

    @http.route('/comm_whatsapp_chatbot_web/session/message',
                type='json', auth='public', csrf=False, cors='*')
    def session_message(self, token, body=None, option_value=None, **kwargs):
        env = request.env
        session = env['whatsapp.chatbot.web.session'].sudo().get_by_token(token)
        if not session:
            return {'error': 'session not found'}
        session.touch()

        result = self._simulate(env, session,
                                 user_input=(option_value or body or ''))
        return {'token': session.token, **result}

    @http.route('/comm_whatsapp_chatbot_web/session/close',
                type='json', auth='public', csrf=False, cors='*')
    def session_close(self, token, **kwargs):
        session = request.env['whatsapp.chatbot.web.session'].sudo(
        ).get_by_token(token)
        if session:
            session.close()
        return {'ok': True}

    # ── Adapter to the WA simulator engine ───────────────────────────
    def _simulate(self, env, session, user_input=None):
        Msg = env['whatsapp.chatbot.message'].sudo()
        contact_details = {
            'name': session.persona_name,
            'mobile_number': session.persona_mobile,
        }
        try:
            result = Msg.simulate_turn(
                chatbot_id=session.chatbot_id.id,
                session_state=session.session_state or None,
                user_input=user_input,
                contact_details=contact_details,
                initial_variables=None,
            )
        except Exception as e:
            _logger.error('WA simulator turn failed: %s', e, exc_info=True)
            return {
                'bot_name': session.chatbot_id.name,
                'messages': [{'direction': 'outbound',
                               'body': 'Simulator error — please try again.',
                               'step_name': 'error'}],
                'waiting': 'done',
                'current_step_name': '',
                'current_options': [],
            }

        # Persist session_state for the next turn
        session.session_state = result.get('session_state') or {}

        # Map WA simulator response to the widget's JSON shape
        messages = list(session.session_state.get('_widget_transcript') or [])
        if user_input:
            messages.append({
                'direction': 'inbound',
                'body': user_input,
                'step_name': '',
            })
        for b in result.get('bubbles') or []:
            msg = {
                'direction': 'outbound',
                'body': b.get('text') or '',
                'step_name': b.get('step_type') or '',
            }
            buttons = b.get('buttons') or []
            if buttons:
                msg['options'] = [{'label': btn.get('title', ''),
                                    'value': btn.get('id') or btn.get('title')}
                                   for btn in buttons]
            media = []
            if b.get('image_url'):
                media.append({'kind': 'image', 'url': b['image_url'], 'alt': ''})
            if b.get('video_url'):
                media.append({'kind': 'video', 'url': b['video_url'], 'alt': ''})
            if b.get('document_url'):
                media.append({'kind': 'document', 'url': b['document_url'],
                               'alt': b.get('document_name', 'Document')})
            if media:
                msg['media'] = media
            messages.append(msg)

        # Store transcript back on session_state so re-attach works
        session.session_state = dict(session.session_state,
                                      _widget_transcript=messages)

        terminate = bool(result.get('terminate'))
        wait_for_input = bool(result.get('wait_for_input'))
        options = []
        # Last bubble may carry options for a menu-style question
        last = (result.get('bubbles') or [{}])[-1]
        for btn in (last.get('buttons') or []):
            options.append({'label': btn.get('title', ''),
                             'value': btn.get('id') or btn.get('title')})

        if terminate:
            waiting = 'done'
        elif options:
            waiting = 'menu'
        elif wait_for_input:
            waiting = 'input'
        else:
            waiting = 'none'

        return {
            'bot_name': session.chatbot_id.name,
            'messages': messages,
            'waiting': waiting,
            'current_step_name': last.get('step_type') or '',
            'current_options': options,
        }


_EMBED_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>{chatbot_name}</title>
    <link rel="stylesheet" href="/comm_chatbot_web/widget.css"/>
    <style>
        html, body {{ margin: 0; padding: 0; height: 100%; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                Roboto, sans-serif; background: #f4f4f6; }}
        body.o_ccw_fullscreen .o_ccw_widget {{
            position: static; width: 100%; height: 100%; border-radius: 0;
            box-shadow: none;
        }}
        body.o_ccw_fullscreen .o_ccw_bubble {{ display: none; }}
    </style>
</head>
<body class="o_ccw_fullscreen">
    <script>
        window.COMM_CHATBOT_WEB = {{
            botId: {chatbot_id},
            preview: {preview},
            baseUrl: "{base_url}",
            endpointPrefix: "/comm_whatsapp_chatbot_web",
            botIdKey: "chatbot_id",
            autoOpen: true,
        }};
    </script>
    <script src="/comm_chatbot_web/widget.js"></script>
</body>
</html>
"""
