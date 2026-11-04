from odoo import models
from odoo.tools import html2plaintext


class MailActivity(models.Model):
    """What an assignee does with their follow-up To-Do updates the item:
    "Done" closes it (the feedback becomes its result), a new date moves its
    due date. The item itself stays out of their reach."""

    _inherit = "mail.activity"

    def _kh_items(self):
        return self.env["kh.wa.item"].sudo().search([("kh_activity_id", "in", self.ids)])

    def _action_done(self, feedback=False, attachment_ids=None):
        items = {item.kh_activity_id.id: item for item in self._kh_items()}
        result = super()._action_done(feedback=feedback, attachment_ids=attachment_ids)
        for item in items.values():
            if item.state not in ("open", "waiting"):
                continue
            note = " ".join(html2plaintext(feedback or "").split())[:250]
            vals = {"state": "done"}
            if note:
                vals["done_note"] = note
            # As the assignee (they may not read the item): their close counts
            # as a person's edit, so the bot won't reopen it.
            item.with_context(kh_wa_activity_sync=True).write(vals)
        return result

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("kh_wa_activity_sync") or not {"date_deadline", "user_id"} & set(vals):
            return result
        for item in self._kh_items():
            activity = item.kh_activity_id
            changes = {}
            if item.due_date != activity.date_deadline:
                changes["due_date"] = activity.date_deadline
            if activity.user_id and item.assignee_id != activity.user_id:
                changes["assignee_id"] = activity.user_id.id
            if changes:
                item.with_context(kh_wa_activity_sync=True).write(changes)
            partner = activity.user_id.partner_id
            if "user_id" in vals and not activity.user_id.has_group("kh_wa_inbox.group_kh_wa_manager"):
                # Handed to someone else: they get the To-Do, not the item's emails.
                item.message_unsubscribe(partner_ids=partner.ids)
        return result
