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

    def write(self, vals):
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
