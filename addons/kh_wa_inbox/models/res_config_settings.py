from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    kh_wa_quick_done_minutes = fields.Integer(
        string="Quick-Done Threshold (minutes)",
        config_parameter="kh_wa_inbox.quick_done_minutes",
        default=60,
        help="A WhatsApp request asked and finished within this many minutes is not kept "
             "in the notebook; it only adds to the day's \"finished within the threshold\" count.",
    )
