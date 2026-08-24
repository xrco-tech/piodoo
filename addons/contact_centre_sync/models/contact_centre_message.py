# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ContactCentreMessage(models.Model):
    _inherit = "contact.centre.message"

    channel = fields.Selection(selection_add=[("voice", "Voice")], ondelete={"voice": "cascade"})
    whatsapp_call_log_id = fields.Many2one("whatsapp.call.log", ondelete="set null", index=True)
    comm_voip_call_id = fields.Many2one("comm.voip.call", ondelete="set null", index=True)

    # Surfaced so the Inbox thread pane can offer inline playback right
    # on a call's message bubble. call_recording_url is data-driven so it works
    # for BOTH WhatsApp calls (/whatsapp/call/recording/<id>) and VoIP calls
    # (/voip/call/recording/<id>) — each route gates read vs. download.
    call_recording_id = fields.Many2one(
        "ir.attachment", compute="_compute_call_recording_id", store=False,
    )
    call_recording_url = fields.Char(
        compute="_compute_call_recording_id", store=False,
    )
    call_recording_duration = fields.Char(
        related="call_recording_id.recording_duration_display", string="Recording Length",
    )

    # Whisper transcript for an inbound WhatsApp voice note, surfaced so the
    # Inbox can show it under the player (computed, not related — the transcript
    # field only exists when comm_dialer is installed).
    voice_transcript = fields.Text(
        compute="_compute_call_recording_id", store=False, string="Voice Note Transcript",
    )

    # Surface the call's wrap-up disposition + note on the message so the
    # Inbox thread can show a call's outcome inline, next to its recording.
    call_disposition_id = fields.Many2one(
        "comm.disposition", related="whatsapp_call_log_id.disposition_id",
        string="Call Disposition", store=False,
    )
    call_disposition_note = fields.Text(
        related="whatsapp_call_log_id.disposition_note",
        string="Call Disposition Note", store=False,
    )

    @api.depends("whatsapp_call_log_id.recording_ids", "comm_voip_call_id.recording_ids",
                 "whatsapp_message_id.media_attachment_id", "whatsapp_message_id.message_type")
    def _compute_call_recording_id(self):
        for rec in self:
            att = self.env["ir.attachment"]
            url = False
            trans = False
            if rec.whatsapp_call_log_id:
                att = rec.whatsapp_call_log_id.recording_ids[:1]
                if att:
                    url = "/whatsapp/call/recording/%s" % att.id
            elif rec.comm_voip_call_id:
                att = rec.comm_voip_call_id.recording_ids[:1]
                if att:
                    url = "/voip/call/recording/%s" % att.id
            elif (rec.whatsapp_message_id
                    and rec.whatsapp_message_id.message_type == "audio"
                    and rec.whatsapp_message_id.media_attachment_id):
                att = rec.whatsapp_message_id.media_attachment_id
                url = "/whatsapp/voice_note/%s" % att.id
                # transcript only exists when comm_dialer is installed.
                if "transcript" in rec.whatsapp_message_id._fields:
                    trans = rec.whatsapp_message_id.transcript or False
            rec.call_recording_id = att[:1]
            rec.call_recording_url = url
            rec.voice_transcript = trans
