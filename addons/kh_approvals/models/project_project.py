from odoo import models, fields, api, _
from odoo.exceptions import UserError

class Project(models.Model):
    _inherit = 'project.project'

    # حقول الزيارة الميدانية لشركة خالص
    x_site_visit_engineer_id = fields.Many2one('res.users', string="Assigned Engineer", tracking=True)
    x_site_visit_date = fields.Date(string="Visit Date")
    x_site_visit_note = fields.Text(string="Visit Notes")
    x_site_visit_state = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Completed')
    ], string="Visit Status", default='pending', copy=False)

    def action_mark_visit_done(self):
        for record in self:
            # التأكد إن المهندس المسند إليه هو اللي بيكبس الزر
            if self.env.user != record.x_site_visit_engineer_id:
                raise UserError(_("يا هندسة، بس المهندس المسند إليه ( %s ) هو اللي بيقدر يسكر الزيارة!") % record.x_site_visit_engineer_id.name)
            
            if not record.x_site_visit_note:
                raise UserError(_("الملاحظات فاضية يا معلم! اكتب شو صار بالزيارة أولاً."))
            
            record.x_site_visit_state = 'done'

    # ميثود لفتح التب (Tab) مباشرة من الـ Stat Button
    def action_view_site_visit_tab(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.project',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_active_tab': 'site_visit_khales'},
        }