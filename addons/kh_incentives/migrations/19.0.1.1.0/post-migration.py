from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # Incentive claims became bonuses: the old "type"/"role" choices are gone
    # and existing records are kept as "Other" bonuses with their amount
    # unchanged. Only their reference is rebuilt ("Bonus - ...").
    env = api.Environment(cr, SUPERUSER_ID, {})
    claims = env["kh.incentive.claim"].with_context(active_test=False).search([])
    env.add_to_compute(claims._fields["name"], claims)
    claims.flush_recordset(["name"])
