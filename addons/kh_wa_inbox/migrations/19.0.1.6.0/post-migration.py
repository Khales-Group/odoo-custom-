import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # «بانتظار قرارك» as To-Dos: the decision maker is the one notebook
    # manager who isn't the administrator (the bot works as the
    # administrator); with several, it is left for Settings. The To-Dos
    # themselves are made by the cron once the update is over.
    env = api.Environment(cr, SUPERUSER_ID, {})
    Param = env["ir.config_parameter"]
    if not Param.get_param("kh_wa_inbox.decision_user_id"):
        admin = env.ref("base.user_admin", raise_if_not_found=False)
        managers = env.ref("kh_wa_inbox.group_kh_wa_manager").all_user_ids.filtered(
            lambda user: user.active and not user.share and user != admin
        )
        if len(managers) == 1:
            Param.set_param("kh_wa_inbox.decision_user_id", str(managers.id))
            _logger.info("kh_wa_inbox: decision maker set to %s", managers.name)
    env.ref("kh_wa_inbox.ir_cron_kh_wa_decision_activities")._trigger()
