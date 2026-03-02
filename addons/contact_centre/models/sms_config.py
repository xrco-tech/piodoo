# -*- coding: utf-8 -*-

from odoo import models, fields


class ContactCentreSMSConfig(models.Model):
    _name = 'contact.centre.sms.config'
    _description = 'SMS Configuration'

    name = fields.Char('Configuration Name', required=True)
    active = fields.Boolean('Active', default=True)
    provider = fields.Selection([
        ('infobip', 'InfoBip'),
        ('twilio', 'Twilio'),
        ('odoo_iap', 'Odoo IAP'),
    ], 'Provider', required=True, default='infobip')

    # InfoBip settings (mirrors comm_sms res_config_settings)
    use_infobip_api = fields.Boolean('Use InfoBip API',
                                     config_parameter='sms.use_infobip_api')
    infobip_base_url = fields.Char('InfoBip Base URL',
                                   config_parameter='infobip.base_url')
    infobip_api_key = fields.Char('InfoBip API Key', password=True,
                                  config_parameter='infobip.api_key')
    infobip_default_from_number = fields.Char('Default Sender Number',
                                              config_parameter='infobip.default_from_number')
    infobip_retention_period = fields.Integer('Retention Period (days)',
                                              config_parameter='infobip.retention_period',
                                              default=30)
