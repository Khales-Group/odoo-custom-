import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # The follow-up To-Dos of 19.0.1.4.0 are replaced by project tasks: the
    # To-Dos go (their link gave the assignee an access error) and every
    # open item assigned outside the notebook managers gets its task.
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
    items = env["kh.wa.item"].search([("state", "in", ("open", "waiting")), ("assignee_id", "!=", False)])
    items = items.filtered(lambda item: item._kh_needs_task() and not item.task_id)
    items._kh_sync_task()
    _logger.info("kh_wa_inbox: follow-up task sent for %s assigned items", len(items))
