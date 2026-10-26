from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # Files already opened from the Collection app move to the new
    # "Collection" stage of their department (created by the data file).
    # Closed files stay closed.
    env = api.Environment(cr, SUPERUSER_ID, {})
    Report = env["x_reports"].with_context(tracking_disable=True, mail_notrack=True)
    for department in ("PRO", "Law"):
        stage = Report._kh_collection_stage(department)
        if not stage:
            continue
        Report.search([
            ("kh_collection_case_id", "!=", False),
            ("x_studio_type", "=", department),
            ("kh_is_closed", "=", False),
            ("x_studio_stage_id", "!=", stage.id),
        ]).write({"x_studio_stage_id": stage.id})
