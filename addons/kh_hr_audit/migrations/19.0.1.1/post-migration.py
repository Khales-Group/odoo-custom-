from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # Stop the monthly employee report job (it ran on the 25th and gave every
    # manager one "Review Monthly Report" to-do per employee) and clear the
    # review to-dos it left open. The job stays in Scheduled Actions, archived,
    # in case it's ever wanted back.
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["ir.cron"].with_context(active_test=False).search([
        ("code", "ilike", "_cron_generate_monthly_reports"),
    ]).write({"active": False})
    env["mail.activity"].search([
        ("res_model", "=", "kh.hr.monthly.report"),
        ("summary", "=like", "Review Monthly Report:%"),
    ]).unlink()
