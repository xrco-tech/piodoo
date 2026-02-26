# -*- coding: utf-8 -*-
# Source: botle_buhle_custom
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class ResVetting(models.Model):
    _name = "res.vetting"
    _description = "Vetting"

    stage_id = fields.Many2one(
        "sf.recruit.stage", "Status", related="recruit_id.stage_id"
    )
    recruit_id = fields.Many2one("sf.recruit", "Recruit")
    date = fields.Date("Date")
    credit_rating = fields.Char("Credit Rating")
    colour = fields.Char("Colour")
    income_range = fields.Char("Income Range")
    affluence_segment = fields.Char("Affluence Segment")
    fin_sophistication = fields.Char("Fin Sophistication")
    lsm = fields.Char("SLM")
    credit_active = fields.Boolean("Credit Active")
    maritial_staus = fields.Char("Marital Status")
    home_owner = fields.Char("Home Owner")
    director_indicated = fields.Char("Director Indicated")
    ethnicity = fields.Char("Ethnicity")
    property_value = fields.Char("Property Value")
    partner_id = fields.Many2one("res.partner", "Customer")
