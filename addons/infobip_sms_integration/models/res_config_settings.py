from odoo import models, fields, api, _

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sms_use_infobip_api = fields.Boolean(
        string='Use InfoBip API',
        config_parameter='sms.use_infobip_api'
    )

    infobip_base_url = fields.Char(
        string='InfoBip Base URL',
        config_parameter='infobip.base_url'
    )

    infobip_api_key = fields.Char(
        string='InfoBip API Key',
        config_parameter='infobip.api_key',
        password=True
    )

    infobip_default_from_number = fields.Char(
        string='InfoBip Default From Number',
        config_parameter='infobip.default_from_number',
    )

    infobip_retention_period = fields.Integer(
        string='InfoBip Retention Period',
        config_parameter='infobip.retention_period', 
        default=1
    )