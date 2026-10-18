# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

MAJID_ID = 369  # ماجد - المدير، لازم يوافق على أي تصعيد
PRO_OFFICER_LOGIN = "hmam.h7@khales.ae"  # حمام - مسؤول العلاقات العامة
LAWYER_LOGIN = "as.sami71@hotmail.com"  # أحمد علي - المحامي


class KhCollectionCase(models.Model):
    _name = "kh.collection.case"
    _description = "ملف تحصيل"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _rec_name = "name"

    name = fields.Char(string="المرجع", compute="_compute_name", store=True)
    client_id = fields.Many2one("res.partner", string="العميل", required=True, tracking=True)
    contractor_id = fields.Many2one("res.partner", string="المقاول", required=True, tracking=True)
    project_id = fields.Many2one("project.project", string="المشروع", required=True, tracking=True)
    amount = fields.Monetary(string="المبلغ المطلوب تحصيله", required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", string="العملة", default=lambda self: self.env.company.currency_id
    )
    accountant_id = fields.Many2one(
        "res.users", string="المحاسب المسؤول", default=lambda self: self.env.user, required=True, tracking=True
    )
    note = fields.Text(string="ملاحظات")

    state = fields.Selection(
        [
            ("accountant", "مع المحاسب"),
            ("pending_pro_approval", "بانتظار موافقة المدير (تصعيد لـ PRO)"),
            ("pro", "مع العلاقات العامة"),
            ("pending_law_approval", "بانتظار موافقة المدير (تصعيد للمحامي)"),
            ("law", "مع المحامي"),
            ("collected", "تم التحصيل"),
        ],
        string="الحالة",
        default="accountant",
        required=True,
        tracking=True,
    )

    report_id = fields.Many2one("x_reports", string="ملف Law/PRO", readonly=True, copy=False)
    pro_task_id = fields.Many2one("project.task", string="مهمة العلاقات العامة", readonly=True, copy=False)
    law_task_id = fields.Many2one("project.task", string="مهمة المحامي", readonly=True, copy=False)
    is_manager = fields.Boolean(string="هو ماجد؟", compute="_compute_is_manager")

    def _compute_is_manager(self):
        for rec in self:
            rec.is_manager = self.env.user.id == MAJID_ID

    @api.depends("client_id", "project_id")
    def _compute_name(self):
        for rec in self:
            parts = [p for p in (rec.client_id.name, rec.project_id.name) if p]
            rec.name = _("تحصيل - %s") % " / ".join(parts) if parts else _("تحصيل")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_manager(self):
        return self.env["res.users"].browse(MAJID_ID)

    def _get_pro_officer(self):
        return self.env["res.users"].search([("login", "=", PRO_OFFICER_LOGIN)], limit=1)

    def _get_lawyer(self):
        return self.env["res.users"].search([("login", "=", LAWYER_LOGIN)], limit=1)

    def _check_is_manager(self):
        if self.env.user.id != MAJID_ID:
            raise UserError(_("بس ماجد يقدر يوافق على التصعيد."))

    def _request_manager_approval(self, message):
        manager = self._get_manager()
        for rec in self:
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=manager.id,
                summary=_("طلب موافقة على تصعيد ملف تحصيل"),
                note=message,
            )
            rec.message_post(body=message)

    def _close_my_pending_activities(self):
        self.activity_ids.filtered(lambda a: a.user_id.id == self.env.user.id).action_feedback(
            feedback=_("تمت الموافقة")
        )

    # ------------------------------------------------------------------
    # Stage 1: accountant -> PRO (needs Majed's approval)
    # ------------------------------------------------------------------
    def action_request_pro_escalation(self):
        for rec in self:
            if rec.state != "accountant":
                raise UserError(_("بس ممكن تطلب تصعيد وانت بمرحلة 'مع المحاسب'."))
            rec.state = "pending_pro_approval"
            rec._request_manager_approval(
                _("المحاسب %s ما قدر يحصّل مبلغ %s من %s. بانتظار موافقتك للتحويل لمسؤول العلاقات العامة.")
                % (rec.accountant_id.name, rec.amount, rec.client_id.name)
            )

    def action_reject_pro_escalation(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_pro_approval":
                continue
            rec.state = "accountant"
            rec._close_my_pending_activities()
            rec.message_post(body=_("ماجد رفض التصعيد، الملف رجع للمحاسب."))

    def action_approve_pro_escalation(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_pro_approval":
                raise UserError(_("هاد الملف مش بانتظار موافقة تصعيد لـ PRO."))
            pro_officer = rec._get_pro_officer()
            report = self.env["x_reports"].create(
                {
                    "x_name": rec.name,
                    "x_studio_type": "PRO",
                    "x_studio_user_id": pro_officer.id,
                    "x_studio_partner_id": rec.client_id.id,
                    "x_studio_company_id": rec.project_id.company_id.id or self.env.company.id,
                    "x_studio_notes": rec.note,
                }
            )
            task = self.env["project.task"].create(
                {
                    "name": _("تحصيل: %s") % rec.name,
                    "project_id": rec.project_id.id,
                    "user_ids": [(6, 0, [pro_officer.id])],
                    "description": _("مطلوب تحصيل %s من %s (مقاول: %s). ما قدر المحاسب %s يحصّلها.")
                    % (rec.amount, rec.client_id.name, rec.contractor_id.name, rec.accountant_id.name),
                }
            )
            rec.write(
                {
                    "state": "pro",
                    "report_id": report.id,
                    "pro_task_id": task.id,
                }
            )
            rec._close_my_pending_activities()
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=pro_officer.id,
                summary=_("ملف تحصيل جديد تحوّل إلك"),
                note=_("انحوّل إلك ملف تحصيل %s بمبلغ %s - شوف الملف %s والمهمة المرتبطة فيه.")
                % (rec.name, rec.amount, report.x_name),
            )
            rec.message_post(body=_("ماجد وافق - الملف تحوّل لـ %s (PRO).") % pro_officer.name)

    # ------------------------------------------------------------------
    # Stage 2: PRO -> Law (needs Majed's approval)
    # ------------------------------------------------------------------
    def action_request_law_escalation(self):
        for rec in self:
            if rec.state != "pro":
                raise UserError(_("بس ممكن تطلب تصعيد وانت بمرحلة 'مع العلاقات العامة'."))
            rec.state = "pending_law_approval"
            rec._request_manager_approval(
                _("مسؤول العلاقات العامة ما قدر يحصّل مبلغ %s من %s. بانتظار موافقتك للتحويل للمحامي.")
                % (rec.amount, rec.client_id.name)
            )

    def action_reject_law_escalation(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_law_approval":
                continue
            rec.state = "pro"
            rec._close_my_pending_activities()
            rec.message_post(body=_("ماجد رفض التصعيد، الملف رجع للعلاقات العامة."))

    def action_approve_law_escalation(self):
        self._check_is_manager()
        for rec in self:
            if rec.state != "pending_law_approval":
                raise UserError(_("هاد الملف مش بانتظار موافقة تصعيد للمحامي."))
            lawyer = rec._get_lawyer()
            if rec.report_id:
                # Same file, moved to the Law department - kh_law automatically
                # resets it to the first Law stage when x_studio_type changes.
                rec.report_id.write({"x_studio_type": "Law", "x_studio_user_id": lawyer.id})
            task = self.env["project.task"].create(
                {
                    "name": _("تحصيل (قانوني): %s") % rec.name,
                    "project_id": rec.project_id.id,
                    "user_ids": [(6, 0, [lawyer.id])],
                    "description": _("مطلوب تحصيل %s من %s (مقاول: %s) عن طريق الإجراءات القانونية.")
                    % (rec.amount, rec.client_id.name, rec.contractor_id.name),
                }
            )
            rec.write({"state": "law", "law_task_id": task.id})
            rec._close_my_pending_activities()
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=lawyer.id,
                summary=_("ملف تحصيل جديد تحوّل إلك"),
                note=_("انحوّل إلك ملف تحصيل %s بمبلغ %s للمتابعة القانونية.") % (rec.name, rec.amount),
            )
            rec.message_post(body=_("ماجد وافق - الملف تحوّل لـ %s (محامي).") % lawyer.name)

    # ------------------------------------------------------------------
    # Any stage -> Collected
    # ------------------------------------------------------------------
    def action_mark_collected(self):
        for rec in self:
            rec.state = "collected"
            rec.activity_ids.action_feedback(feedback=_("تم التحصيل"))
            rec.message_post(body=_("تم تحصيل المبلغ."))
