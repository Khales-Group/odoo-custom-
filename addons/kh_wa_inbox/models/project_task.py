from odoo import api, fields, models
from odoo.exceptions import UserError

# A change to one of these, made on a follow-up task, is passed on to its item.
ITEM_FIELDS = ("state", "user_ids", "date_deadline")


class ProjectTask(models.Model):
    """A follow-up task made from a WhatsApp notebook item. What is done
    with it (closing it, moving its deadline, handing it over) updates the
    item, which its assignee can't open."""

    _inherit = "project.task"

    kh_wa_item_id = fields.Many2one(
        "kh.wa.item", string="WhatsApp Notebook Item", readonly=True, copy=False,
        index="btree_not_null", ondelete="set null",
    )
    kh_wa_group_name = fields.Char(string="WhatsApp Group", related="kh_wa_item_id.group_id.name", store=True)
    kh_wa_linked_name = fields.Char(
        string="Linked Record", compute="_compute_kh_wa_linked_name", compute_sudo=True,
    )

    @api.depends("kh_wa_item_id.linked_ref")
    def _compute_kh_wa_linked_name(self):
        for task in self:
            task.kh_wa_linked_name = task.kh_wa_item_id._kh_linked_label() or False

    def write(self, vals):
        result = super().write(vals)
        changed = set(ITEM_FIELDS).intersection(vals)
        if changed and not self.env.context.get("kh_wa_task_sync"):
            for task in self.sudo().filtered("kh_wa_item_id"):
                task.kh_wa_item_id._kh_task_changed(task, changed)
        return result

    def action_kh_wa_done(self):
        """"Done" on a follow-up task, also for an assignee who may not edit tasks."""
        for task in self:
            if self.env.user not in task.user_ids and not task.has_access("write"):
                raise UserError(self.env._("Only the task's assignees can mark it done."))
        self.sudo().write({"state": "1_done"})
        return True

    def action_kh_wa_open_linked(self):
        self.ensure_one()
        record = self.sudo().kh_wa_item_id.linked_ref
        if not record or not record.exists():
            return False
        if not record.sudo(False).has_access("read"):
            raise UserError(self.env._("You don't have access to %s.", self.kh_wa_linked_name))
        return {
            "type": "ir.actions.act_window",
            "res_model": record._name,
            "res_id": record.id,
            "views": [[False, "form"]],
            "target": "current",
        }
