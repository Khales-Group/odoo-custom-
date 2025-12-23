from odoo import models, fields

class ProjectTask(models.Model):
    _inherit = 'project.task'

    # We re-define the fields here to override the "Required" setting
    x_contractor = fields.Char(string="Contractor", required=False)
    
    # Make sure to use the exact same Selection options you had before, or just generic ones
    # If you don't know the options, just setting required=False is usually enough for the fix
    x_custom_state = fields.Selection(
        selection=[
            ('01_in_progress', 'In Progress'),
            ('02_changes_requested', 'Changes Requested'),
            ('03_approved', 'Approved'),
            ('1_done', 'Done'),
            ('1_canceled', 'Cancelled'),
            ('04_waiting_normal', 'Waiting'),
            ('05_Pending', 'Pending')
        ],
        string="Custom State",
        required=False
    )