import logging
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import api, fields, models

from .kh_wa_tools import arabic_age, dubai_date, dubai_today

_logger = logging.getLogger(__name__)

DECISION_USER_PARAM = "kh_wa_inbox.decision_user_id"
BACKLOG_PARAM = "kh_wa_inbox.decision_backlog_done"
DECISION_PREFIX = "بانتظار قرارك: "
APPROVAL_PREFIX = "بانتظار موافقتك: "
APPROVAL_MODEL = "kh.approval.request"
OPEN_STATES = ("open", "waiting")
APPROVAL_STAGE_LABELS = {"procurement": "دورة الشراء", "pay_review": "دورة الدفع"}


class KhWaItem(models.Model):
    """«بانتظار قرارك»: the items waiting for the manager's decision and the
    approval requests waiting for his approval (kh_approvals, when
    installed) come to the decision maker (Settings) as To-Do activities,
    and the requests show on the dashboard beside the items."""

    _inherit = "kh.wa.item"

    kh_decision_activity_id = fields.Many2one(
        "mail.activity", string="Decision Activity", readonly=True, copy=False, ondelete="set null",
        help="The decision maker's To-Do while the item waits for his decision. Marking it done ends the wait.",
    )

    # ------------------------------------------------------------------
    # Who decides
    # ------------------------------------------------------------------

    @api.model
    def _kh_decision_user(self):
        value = self.env["ir.config_parameter"].sudo().get_param(DECISION_USER_PARAM)
        try:
            user = self.env["res.users"].sudo().browse(int(value)).exists() if value else self.env["res.users"]
        except ValueError:
            return self.env["res.users"]
        return user if user and user.active and not user.share else self.env["res.users"]

    # ------------------------------------------------------------------
    # The items' decision activity
    # ------------------------------------------------------------------

    def _kh_decision_note(self):
        self.ensure_one()
        asked = ""
        if self.asked_at:
            asked = f"{self.requester_name or '—'} · {fields.Date.to_string(dubai_date(self.asked_at))}"
        rows = [("القروب", self.group_id.name), ("سأل", asked), ("المسؤول", self.assignee_id.name or "")]
        lines = [Markup("<p><b>%s:</b> %s</p>") % (label, value) for label, value in rows if value]
        if self.source_text:
            text = escape(self.source_text[:1500]).replace("\n", Markup("<br/>"))
            lines.append(Markup("<p><b>الرسالة الأصلية:</b><br/>%s</p>") % text)
        lines.append(Markup("<p><i>%s</i></p>") % "بعد القرار اضغط «تم» (واكتب القرار إن شئت): يخرج البند من «بانتظار قرارك».")
        return Markup("").join(lines)

    def _kh_sync_decision_activity(self, notify=True):
        """One To-Do for the decision maker while an open item waits for his
        decision; gone when it no longer does."""
        user = self._kh_decision_user()
        Activity = self.env["mail.activity"].sudo().with_context(
            kh_wa_decision_sync=True, mail_activity_quick_update=not notify,
        )
        for item in self.sudo():
            activity = item.kh_decision_activity_id
            wanted = bool(user) and item.needs_manager and item.state in OPEN_STATES
            if activity and (not wanted or activity.user_id != user):
                Activity.browse(activity.id).unlink()
                activity = Activity
            if wanted and not activity:
                activity = item.with_context(
                    kh_wa_decision_sync=True, mail_activity_quick_update=not notify,
                ).activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=min(item.due_date or dubai_today(), dubai_today()),
                    summary=(DECISION_PREFIX + item.name)[:250],
                    note=item._kh_decision_note(),
                    user_id=user.id,
                )
                item.with_context(kh_wa_decision_sync=True).write({"kh_decision_activity_id": activity.id})

    def _kh_decision_done(self):
        """The decision maker marked the To-Do done: the item no longer waits."""
        self.sudo().with_context(kh_wa_decision_sync=True).write({
            "needs_manager": False, "kh_decision_activity_id": False,
        })

    # ------------------------------------------------------------------
    # Approval requests waiting for a user
    # ------------------------------------------------------------------

    @api.model
    def _kh_pending_approvals(self, user):
        """The approval requests waiting for this user's approval now (at
        their current stage), oldest first."""
        if APPROVAL_MODEL not in self.env or not user:
            return self.env["res.users"].browse()  # nothing (an empty recordset)
        lines = self.env["kh.approval.line"].sudo().search([
            ("approver_id", "=", user.id), ("state", "=", "pending"), ("request_id.state", "=", "in_review"),
        ])
        requests = lines.filtered(
            lambda line: line.approval_stage == (line.request_id.approval_stage or "procurement")
        ).request_id
        return requests.sorted(lambda r: (r.submitted_on or r.create_date, r.id))

    @api.model
    def _kh_approval_payloads(self, requests, now):
        payloads = []
        for request in requests:
            amount = ""
            if request.amount:
                amount = f"{request.amount:,.2f} {request.currency_id.name or ''}".strip()
            asked = request.submitted_on or request.create_date
            payloads.append({
                "id": f"approval-{request.id}",
                "approval": True,
                "request_id": request.id,
                "name": request.title or request.name,
                "ref": request.name,
                "requester": request.requester_id.name or "",
                "department": request.department_id.display_name or "",
                "rule": request.rule_id.display_name or "",
                "stage": APPROVAL_STAGE_LABELS.get(request.approval_stage or "", ""),
                "amount": amount,
                "vendor": request.partner_id.display_name or "",
                "project": request.x_studio_project.display_name or "",
                "asked_at": fields.Datetime.to_string(asked) or False,
                "age": arabic_age(asked, now),
                "steps": [
                    {"name": line.approver_id.name, "state": line.state}
                    for line in request.approval_line_ids.sorted("sequence")
                    if line.approval_stage == (request.approval_stage or "procurement")
                ],
                "attachment_count": request.message_attachment_count,
            })
        return payloads

    # ------------------------------------------------------------------
    # The cron: decisions as activities
    # ------------------------------------------------------------------

    @api.model
    def _cron_decision_activities(self):
        """Every «بانتظار قرارك» thing has its To-Do for the decision maker:
        the items (a safety net: they get it when flagged) and the approval
        requests waiting for him; his To-Dos made here for requests no
        longer waiting are removed. The first run (the backlog) sends no
        "assigned to you" notifications."""
        user = self._kh_decision_user()
        if not user:
            return
        Param = self.env["ir.config_parameter"].sudo()
        notify = bool(Param.get_param(BACKLOG_PARAM))
        items = self.search([("needs_manager", "=", True), ("state", "in", OPEN_STATES)])
        items.filtered(lambda i: not i.kh_decision_activity_id)._kh_sync_decision_activity(notify=notify)

        if APPROVAL_MODEL in self.env:
            Activity = self.env["mail.activity"].sudo()
            requests = self._kh_pending_approvals(user)
            mine = Activity.search([
                ("res_model", "=", APPROVAL_MODEL), ("user_id", "=", user.id),
            ])
            has_activity = set(mine.mapped("res_id"))
            for request in requests.filtered(lambda r: r.id not in has_activity):
                note = Markup("<p>%s</p>") % "طلب موافقة بانتظارك. وافق أو ارفض من الطلب أو من لوحة المتابعة."
                request.sudo().with_context(mail_activity_quick_update=not notify).activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=dubai_today(),
                    summary=(APPROVAL_PREFIX + (request.title or request.name))[:250],
                    note=note,
                    user_id=user.id,
                )
            stale = mine.filtered(lambda a: (a.summary or "").startswith(APPROVAL_PREFIX) and a.res_id not in requests.ids)
            stale.unlink()
        if not notify:
            Param.set_param(BACKLOG_PARAM, "1")
