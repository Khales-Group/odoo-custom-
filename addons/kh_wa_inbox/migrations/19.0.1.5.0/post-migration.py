import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # The follow-up To-Dos of 19.0.1.4.0 are replaced by project tasks: the
    # To-Dos go (their link gave the assignee an access error). The tasks
    # are made by the cron once the update is over: during the update, the
    # modules that extend projects and load after this one are missing.
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'kh_wa_item' AND column_name = 'kh_activity_id'
    """)
    if cr.fetchone():
        cr.execute("SELECT kh_activity_id FROM kh_wa_item WHERE kh_activity_id IS NOT NULL")
        activities = env["mail.activity"].browse([row[0] for row in cr.fetchall()]).exists()
        activities.unlink()
        _logger.info("kh_wa_inbox: %s follow-up To-Dos removed", len(activities))
    env.ref("kh_wa_inbox.ir_cron_kh_wa_send_tasks")._trigger()
