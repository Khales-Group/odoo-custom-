# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

# ---------------------------------------------------------------------------
# Approval Request
# ---------------------------------------------------------------------------

class KhApprovalRequest(models.Model):
    _name = "kh.approval.request"
    _description = "Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        index=True,
        tracking=True,
    )
    department_id = fields.Many2one(
        "kh.approvals.department",
        string="Department",
        index=True,
        tracking=True,
    )
    requester_id = fields.Many2one(
        "res.users",
        string="Requester",
        default=lambda self: self.env.user,
        required=True,
        index=True,
        tracking=True,
    )

    # ORIGINAL flow uses a single rule selected on the request
    rule_id = fields.Many2one(
        "kh.approval.rule",
        string="Approval Rule",
        required=True,
        tracking=True,
        ondelete="restrict",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_review", "In Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        tracking=True,
        index=True,
    )

    # approval lines generated from the chosen rule (or its steps)
    approval_line_ids = fields.One2many(
        "kh.approval.request.line",
        "request_id",
        string="Approval Lines",
        copy=False,
    )

    # -----------------------------------------------------------------------
    # Button actions (called by form buttons / server actions)
    # -----------------------------------------------------------------------

    def action_submit(self):
        """Requester submits:
        - (Re)build approval lines from rule
        - move to in_review
        - notify first approver (activity), post a note (no emails)
        """
        for rec in self:
            if rec.state != "draft":
                continue

            rec._build_approval_lines()

            # 🔇 Avoid emails from tracking on state change
            rec.with_context(tracking_disable=True).write({"state": "in_review"})

            # Post chatter note (no email)
            rec._post_note(_("Request submitted for approval."))

            # Notify the first pending approver
            rec._notify_first_pending()
        return True

    def action_approve_request(self):
        """Current approver approves their step; finish or notify next approver."""
        for rec in self:
            if rec.state != "in_review":
                raise UserError(_("Only in-review requests can be approved."))

            line = rec._current_pending_line_for_user()
            if not line:
                raise UserError(_("You are not the current approver."))

            # close my open TODOs for this request
            rec._close_my_open_todos()

            # approve my step
            line.write({"state": "approved"})
            rec._post_note(_("Approved by <b>%s</b>.") % rec.env.user.name)

            # next approver or finish
            next_line = rec._first_pending_line()
            if next_line:
                rec._notify_first_pending()
            else:
                rec.with_context(tracking_disable=True).write({"state": "approved"})
                rec._post_note(_("✅ Request approved."))
                rec._dm_ping(rec.requester_id.partner_id, _("✅ <b>Approved</b>: %s") % rec.name)
        return True

    def action_reject_request(self):
        """Current approver rejects; request becomes Rejected; requester is pinged."""
        for rec in self:
            if rec.state != "in_review":
                raise UserError(_("Only in-review requests can be rejected."))

            line = rec._current_pending_line_for_user()
            if not line:
                raise UserError(_("You are not the current approver."))

            # close my open TODOs for this request
            rec._close_my_open_todos()

            line.write({"state": "rejected"})
            # 🔇 Avoid emails from tracking on state change
            rec.with_context(tracking_disable=True).write({"state": "rejected"})
            rec._post_note(_("❌ Rejected by <b>%s</b>.") % rec.env.user.name)
            rec._dm_ping(rec.requester_id.partner_id, _("❌ <b>Rejected</b>: %s") % rec.name)
        return True

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _build_approval_lines(self):
        """Regenerate approval lines from the rule. Two sources supported:
        - kh.approval.rule.step (preferred if present)
        - rule.user_id as a single approver fallback
        This method NEVER sends emails.
        """
        for rec in self:
            rec.approval_line_ids.unlink()
            steps_model = self.env["kh.approval.rule.step"]
            steps = steps_model.search([("rule_id", "=", rec.rule_id.id)], order="sequence asc")

            lines = []
            if steps:
                for st in steps:
                    if not st.user_id:
                        # allow rules to be partially defined; skip empty step user
                        continue
                    lines.append(
                        (0, 0, {
                            "sequence": st.sequence or 10,
                            "approver_id": st.user_id.id,
                            "state": "pending",
                        })
                    )
            else:
                # fallback: single approver from rule.user_id
                if not rec.rule_id or not rec.rule_id.user_id:
                    raise UserError(_("The selected rule has no approver configured."))
                lines.append(
                    (0, 0, {
                        "sequence": 10,
                        "approver_id": rec.rule_id.user_id.id,
                        "state": "pending",
                    })
                )
            rec.write({"approval_line_ids": lines})

    def _first_pending_line(self):
        self.ensure_one()
        return self.approval_line_ids.filtered(lambda l: l.state == "pending")[:1]

    def _current_pending_line_for_user(self):
        self.ensure_one()
        uid = self.env.uid
        return self.approval_line_ids.filtered(
            lambda l: l.state == "pending" and l.approver_id.id == uid
        )[:1]

    def _post_note(self, body, partner_ids=None):
        """Post an internal note without sending any email."""
        for rec in self:
            rec.with_context(
                mail_notify_force_send=False,
                mail_create_nosubscribe=True,
            ).message_post(
                body=body,
                message_type="comment",
                subtype_xmlid="mail.mt_note",
                partner_ids=partner_ids or [],
            )

    def _notify_first_pending(self):
        """Schedule a todo for the first pending approver (no email required)."""
        for rec in self:
            line = rec._first_pending_line()
            if not line or not line.approver_id:
                continue
            # schedule an activity on the request for the approver user
            rec.activity_schedule(
                activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                user_id=line.approver_id.id,
                summary=_("Approval required"),
                note=_("Please review and approve: %s") % rec.name,
            )

    def _close_my_open_todos(self):
        """Mark my TODO activities on this record as done (no email)."""
        me = self.env.user
        for rec in self:
            todos = rec.activity_ids.filtered(
                lambda a: a.user_id.id == me.id and a.activity_type_id.category == "todo"
            )
            for act in todos:
                # mark done without email
                act.action_feedback(feedback=_("Handled."))

    def _dm_ping(self, partner, body):
        """Optional: log a silent note addressed to a partner (no email)."""
        if not partner:
            return
        self._post_note(body, partner_ids=[partner.id])

    # Useful deeplink if you want to include it in notes/DMs
    def _deeplink(self):
        self.ensure_one()
        return "/web#id=%s&model=kh.approval.request&view_type=form" % self.id


# ---------------------------------------------------------------------------
# Approval Request Line
# ---------------------------------------------------------------------------

class KhApprovalRequestLine(models.Model):
    _name = "kh.approval.request.line"
    _description = "Approval Request Line"
    _order = "sequence, id"

    request_id = fields.Many2one(
        "kh.approval.request",
        string="Request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    approver_id = fields.Many2one("res.users", string="Approver", required=True, index=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        index=True,
    )


# ---------------------------------------------------------------------------
# (Optional) Rule Step model reference — if it’s declared in another file,
# this stub is harmless; if not present, we simply won’t find any steps
# and will fall back to rule.user_id in _build_approval_lines().
# ---------------------------------------------------------------------------

class KhApprovalRuleStep(models.Model):
    _name = "kh.approval.rule.step"
    _description = "Approval Rule Step"

    rule_id = fields.Many2one("kh.approval.rule", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    user_id = fields.Many2one("res.users", string="Approver")
