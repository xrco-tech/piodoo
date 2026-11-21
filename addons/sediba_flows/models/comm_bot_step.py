# -*- coding: utf-8 -*-
from odoo import fields, models


class CommBotStep(models.Model):
    _inherit = 'comm.bot.step'

    # Where the step's card was dragged to on the Sediba Flows canvas. A step
    # that was never dragged places itself.
    flow_placed = fields.Boolean(copy=False)
    flow_x = fields.Integer(copy=False)
    flow_y = fields.Integer(copy=False)
