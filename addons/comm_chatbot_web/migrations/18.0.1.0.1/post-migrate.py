# -*- coding: utf-8 -*-
"""Archive the "Web preview" contacts that earlier previews of the widget
left behind, one per preview. Previews now share one hidden contact."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    archived = env['comm.bot.web.session']._archive_minted_preview_contacts()
    _logger.info('comm_chatbot_web: archived %s preview contacts', len(archived))
