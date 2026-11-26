from odoo import SUPERUSER_ID, api

from odoo.addons.kh_collection.models.kh_collection_case import PRO_OFFICER_LOGIN

TRANSFERRED = "A collection case has been transferred to you"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Case = env["kh.collection.case"]

    # The sequence continues after the references given in pre-migration.
    cr.execute("SELECT count(*) FROM kh_collection_case")
    env.ref("kh_collection.seq_kh_collection_case").number_next_actual = cr.fetchone()[0] + 1

    cr.execute("SELECT id FROM kh_collection_pro_moved")
    moved = Case.browse([row[0] for row in cr.fetchall()]).exists()
    cr.execute("DROP TABLE kh_collection_pro_moved")

    # The PRO's open collection files and tasks go to each case's accountant.
    pro = env["res.users"].with_context(active_test=False).search([("login", "=", PRO_OFFICER_LOGIN)], limit=1)
    if pro:
        files = env["x_reports"].search([
            ("kh_collection_case_id", "!=", False),
            ("x_studio_user_id", "=", pro.id),
            ("kh_is_closed", "=", False),
        ])
        for file in files:
            file.x_studio_user_id = file.kh_collection_case_id.accountant_id
        files.activity_ids.filtered(lambda a: a.user_id == pro and a.summary == TRANSFERRED).unlink()
        tasks = Case.search([("pro_task_id", "!=", False)]).pro_task_id.filtered(
            lambda t: pro in t.user_ids and t.state not in ("1_done", "1_canceled")
        )
        for task in tasks:
            case = Case.search([("pro_task_id", "=", task.id)], limit=1)
            task.user_ids = [(3, pro.id), (4, case.accountant_id.id)]

    for case in moved:
        case.message_post(body="There is no PRO step any more: the case is back with the accountant %s."
                          % case.accountant_id.name)

    cases = Case.search([])
    cases.modified(["state"])
    for case in cases.filtered("report_id"):
        case.report_id.x_name = case.display_name
    env.flush_all()
