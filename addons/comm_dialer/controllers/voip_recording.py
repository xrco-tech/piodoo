# -*- coding: utf-8 -*-
"""VoIP call-recording upload + streaming — mirrors comm_whatsapp_calling.

The agent softphone (JsSIP) mixes both audio tracks in the browser and posts the
result here; playback is served back inline for anyone who can read the call, and
download is gated to Call Recording Managers.
"""
import base64
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

RECORDING_MANAGER_GROUP = 'comm_whatsapp_calling.group_whatsapp_call_recording_manager'


class VoipRecordingController(http.Controller):

    @http.route(
        '/voip/call/upload_recording/<int:call_id>',
        type='http', auth='user', methods=['POST'], csrf=False,
    )
    def upload_recording(self, call_id, **kwargs):
        """Store a browser-recorded VoIP call as an attachment on its call log."""
        call = request.env['comm.voip.call'].sudo().browse(call_id)
        if not call.exists():
            return request.make_json_response({'success': False, 'error': 'Call not found'}, status=404)

        audio_file = request.httprequest.files.get('recording')
        if not audio_file:
            return request.make_json_response({'success': False, 'error': 'Missing recording file'}, status=400)
        data = audio_file.read()
        if not data:
            return request.make_json_response({'success': False, 'error': 'Empty recording'}, status=400)

        duration_raw = request.httprequest.form.get('duration')
        try:
            duration_seconds = max(0, int(float(duration_raw))) if duration_raw else 0
        except (TypeError, ValueError):
            duration_seconds = 0

        attachment = request.env['ir.attachment'].sudo().create({
            'name': 'voip_recording_%s.webm' % (call.external_id or call.id),
            'res_model': 'comm.voip.call',
            'res_id': call.id,
            'res_field': 'recording_ids',
            'type': 'binary',
            'datas': base64.b64encode(data),
            'mimetype': audio_file.mimetype or 'audio/webm',
            'recording_duration': duration_seconds,
        })
        # Keep the legacy single-URL field pointing at the latest recording too,
        # and queue the recording for transcription (the cron picks it up).
        call.write({
            'recording_url': '/voip/call/recording/%s' % attachment.id,
            'transcript_state': 'pending',
        })
        _logger.info('comm_dialer: stored recording (%d bytes) for call %s as attachment %s',
                     len(data), call_id, attachment.id)
        return request.make_json_response({'success': True, 'attachment_id': attachment.id})

    @http.route(
        '/voip/call/recording/<int:attachment_id>',
        type='http', auth='user', methods=['GET'],
    )
    def stream_recording(self, attachment_id, download=None, **kwargs):
        """Serve a recording inline (any reader of the call) or as a download
        (Call Recording Managers only)."""
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id)
        if (not attachment.exists()
                or attachment.res_model != 'comm.voip.call'
                or attachment.res_field != 'recording_ids'):
            return request.not_found()

        # Non-sudo search so this reflects what the requesting user may actually see.
        visible = request.env['comm.voip.call'].search([('id', '=', attachment.res_id)], limit=1)
        if not visible:
            return request.not_found()

        want_download = bool(download)
        if want_download and not request.env.user.has_group(RECORDING_MANAGER_GROUP):
            return request.make_json_response(
                {'error': 'Downloading recordings requires Call Recording Manager rights.'},
                status=403)

        data = base64.b64decode(attachment.datas or b'')
        disposition = 'attachment' if want_download else 'inline'
        headers = [
            ('Content-Type', attachment.mimetype or 'audio/webm'),
            ('Content-Length', str(len(data))),
            ('Content-Disposition', '%s; filename="%s"' % (disposition, attachment.name)),
            ('Cache-Control', 'private, max-age=0'),
        ]
        return request.make_response(data, headers=headers)

    @http.route(
        '/whatsapp/voice_note/<int:attachment_id>',
        type='http', auth='user', methods=['GET'],
    )
    def stream_voice_note(self, attachment_id, **kwargs):
        """Serve an inbound WhatsApp voice-note's audio inline for anyone who can
        read the underlying whatsapp.message (so the inbox can render a player)."""
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id)
        if not attachment.exists() or attachment.res_model != 'whatsapp.message':
            return request.not_found()

        # Non-sudo read so this only serves audio the requesting user may see.
        visible = request.env['whatsapp.message'].search(
            [('id', '=', attachment.res_id)], limit=1)
        if not visible:
            return request.not_found()

        data = base64.b64decode(attachment.datas or b'')
        headers = [
            ('Content-Type', attachment.mimetype or 'audio/ogg'),
            ('Content-Length', str(len(data))),
            ('Content-Disposition', 'inline; filename="%s"' % attachment.name),
            ('Cache-Control', 'private, max-age=0'),
        ]
        return request.make_response(data, headers=headers)
