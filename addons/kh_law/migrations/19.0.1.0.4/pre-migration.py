from odoo.addons.kh_law.hooks import relax_required_studio_fields


def migrate(cr, version):
    # Same as at install (see pre_init_hook), for databases where the module
    # was already installed while Studio still marked these fields required.
    relax_required_studio_fields(cr)
