# -*- coding: utf-8 -*-
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class CommVoipAccount(models.Model):
    _inherit = 'comm.voip.account'

    def originate(self, to_number, from_number=None):
        """Place an outbound call leg to ``to_number``.

        Provider-specific and stubbed for now. A follow-up per-provider module
        overrides this (Africa's Talking Voice / Infobip / Asterisk ARI) and
        returns the provider call id so the dialer can correlate the inbound
        webhook that reports answer / AMD / hangup.
        """
        self.ensure_one()
        _logger.info("VoIP originate (stub) via %s [%s]: %s -> %s",
                     self.name, self.provider, from_number or self.caller_id, to_number)
        return {'external_id': False, 'status': 'queued'}

    def bridge(self, call, agent_number):
        """Bridge an answered call leg to a free agent's endpoint. Stub."""
        self.ensure_one()
        _logger.info("VoIP bridge (stub) via %s: call %s -> agent %s",
                     self.name, call.id if call else None, agent_number)
        return {'status': 'bridged'}
