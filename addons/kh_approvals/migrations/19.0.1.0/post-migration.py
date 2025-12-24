import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    _logger.info("========================================================")
    _logger.info("STARTING NUCLEAR CLEANUP OF email_configurator_advanced")
    _logger.info("========================================================")

    # 1. Force Delete from Module List
    cr.execute("DELETE FROM ir_module_module WHERE name = 'email_configurator_advanced'")
    _logger.info(f"Deleted {cr.rowcount} rows from ir_module_module")

    # 2. Force Delete Dependencies
    cr.execute("DELETE FROM ir_module_module_dependency WHERE name = 'email_configurator_advanced'")
    _logger.info(f"Deleted {cr.rowcount} rows from ir_module_module_dependency")

    # 3. Force Delete Model Data (XML IDs)
    cr.execute("DELETE FROM ir_model_data WHERE module = 'email_configurator_advanced'")
    _logger.info(f"Deleted {cr.rowcount} rows from ir_model_data")

    _logger.info("========================================================")
    _logger.info("CLEANUP COMPLETE - SERVER SHOULD START NOW")
    _logger.info("========================================================")