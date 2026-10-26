# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

MODEL = "crm.lead"
FIELD_PREFIX = "x\\_calc\\_%"


def pre_init_hook(env):
    """ Some x_calc_* fields may already exist as manual fields (created
    through ir.model.fields / Studio). Nothing has to be done for them: the
    registry only adds a manual field when the class doesn't define it, and
    at install Odoo updates the existing ir_model_fields row in place
    (matched on model + name) to state 'base' and this module's xmlid. The
    column, and so the lead data, is kept.

    The one case that can lose sight of data is a manual field of another
    type whose column can't be cast (e.g. text -> integer): Odoo then renames
    the old column to <name>_moved<N> and creates a fresh one. Logged here so
    it's visible in the install log. """
    from odoo import fields
    from odoo.addons.kh_crm_calculator.models.crm_lead import CrmLead

    expected = {
        name: field.type for name, field in vars(CrmLead).items()
        if name.startswith("x_calc_") and isinstance(field, fields.Field)
    }
    env.cr.execute(
        "SELECT name, ttype, state FROM ir_model_fields WHERE model = %s AND name LIKE %s",
        [MODEL, FIELD_PREFIX],
    )
    for name, ttype, state in env.cr.fetchall():
        wanted = expected.get(name)
        if wanted and ttype != wanted:
            _logger.warning(
                "kh_crm_calculator: %s.%s already exists as a %s field (%s); it becomes %s. "
                "Check for a %s_moved* column if its data looks empty afterwards.",
                MODEL, name, ttype, state, wanted, name,
            )
        elif wanted:
            _logger.info("kh_crm_calculator: taking over existing field %s.%s (%s)", MODEL, name, state)


def uninstall_hook(env):
    """ Keep the fields and their data if the module is ever uninstalled:
    hand them back as manual fields and drop this module's xmlids on them,
    so the uninstall doesn't delete the fields (and their columns). """
    env.cr.execute(
        "UPDATE ir_model_fields SET state = 'manual' WHERE model = %s AND name LIKE %s",
        [MODEL, FIELD_PREFIX],
    )
    env.cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'kh_crm_calculator' AND model = 'ir.model.fields'"
    )
