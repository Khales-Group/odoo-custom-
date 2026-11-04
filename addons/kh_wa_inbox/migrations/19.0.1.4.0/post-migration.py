import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Items assigned before the follow-up activity existed: their assignees
    # (outside the notebook managers) get their To-Do now.
    env = api.Environment(cr, SUPERUSER_ID, {})
    items = env["kh.wa.item"].search([
        ("state", "in", ("open", "waiting")), ("assignee_id", "!=", False), ("kh_activity_id", "=", False),
    ])
    items = items.filtered(lambda item: item._kh_needs_activity())
    items._kh_sync_activity()
    _logger.info("kh_wa_inbox: follow-up activity sent for %s assigned items", len(items))
