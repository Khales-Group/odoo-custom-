# -*- coding: utf-8 -*-
from odoo import api, fields, models


class XReports(models.Model):
    _inherit = "x_reports"

    kh_collection_case_id = fields.Many2one(
        "kh.collection.case", string="Collection Case", readonly=True, copy=False
    )
    kh_collection_amount = fields.Monetary(
        string="Amount to Collect", currency_field="x_studio_currency_id", readonly=True
    )
    kh_collection_received = fields.Monetary(
        string="Amount Received", currency_field="x_studio_currency_id",
        help="Update this as payments come in - it's reflected back on the collection case automatically.",
    )
    kh_collection_balance = fields.Monetary(
        string="Balance Remaining", currency_field="x_studio_currency_id",
        compute="_compute_kh_collection_balance", store=True,
    )
    kh_collection_can_view = fields.Boolean(compute="_compute_kh_collection_can_view")

    @api.depends("kh_collection_amount", "kh_collection_received")
    def _compute_kh_collection_balance(self):
        for rec in self:
            rec.kh_collection_balance = rec.kh_collection_amount - rec.kh_collection_received

    def _compute_kh_collection_can_view(self):
        can_view = self.env.user.has_group("kh_collection.group_kh_collection_user")
        for rec in self:
            rec.kh_collection_can_view = can_view

    # ------------------------------------------------------------------
    # Collection stage: files opened from the Collection app sit in their
    # department's "Collection" stage (PRO first, then Law on escalation).
    # ------------------------------------------------------------------
    def _kh_first_stage(self, department):
        # The Collection stage is first on the board, but regular files
        # never start there.
        return self.env["x_reports_stage"].search(
            [("kh_department", "=", department), ("kh_is_collection", "=", False)], limit=1
        )

    def _kh_collection_stage(self, department):
        return self.env["x_reports_stage"].search(
            [("kh_department", "=", department), ("kh_is_collection", "=", True)], limit=1
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("kh_collection_case_id") and vals.get("x_studio_type") and not vals.get("x_studio_stage_id"):
                stage = self._kh_collection_stage(vals["x_studio_type"])
                if stage:
                    vals["x_studio_stage_id"] = stage.id
        return super().create(vals_list)

    def write(self, vals):
        department = vals.get("x_studio_type")
        moving, stage = self.browse(), None
        if department and "x_studio_stage_id" not in vals:
            moving = self.filtered(
                lambda r: r.kh_collection_case_id and r.x_studio_stage_id.kh_department != department
            )
            stage = moving and self._kh_collection_stage(department)
        if stage:
            res = super(XReports, moving).write(dict(vals, x_studio_stage_id=stage.id))
            res = super(XReports, self - moving).write(vals) and res
        else:
            res = super().write(vals)
        if "kh_collection_received" in vals:
            for rec in self:
                case = rec.kh_collection_case_id
                if case and case.sudo().received_amount != rec.kh_collection_received:
                    case.sudo().received_amount = rec.kh_collection_received
        return res

    def action_view_collection_case(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "kh.collection.case",
            "res_id": self.kh_collection_case_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_escalate_collection_to_law(self):
        # Runs with sudo: a PRO officer who can't collect needs to be able to
        # trigger this even though (per design) they have no direct access
        # to the Collection app itself - only this one controlled action.
        self.ensure_one()
        self.kh_collection_case_id.sudo().action_request_law_escalation()
