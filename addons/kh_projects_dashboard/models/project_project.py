# -*- coding: utf-8 -*-
from odoo import api, fields, models


def _kh_safe_float(value):
    # x_studio_value_of_the_contract is a Studio field and isn't reliably a
    # clean number on every record (some have text in it) - never let one
    # bad record break the whole dashboard for everyone.
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class ProjectProject(models.Model):
    _inherit = "project.project"

    collection_case_ids = fields.One2many(
        "kh.collection.case", "project_id", string="Collection Cases"
    )
    kh_status = fields.Selection(
        [("green", "Green - On Track"), ("yellow", "Yellow - At Risk"), ("red", "Red - Problem")],
        string="Status", default="green", tracking=True,
    )
    kh_status_reason = fields.Selection(
        [
            ("complaint", "Complaint"),
            ("delay", "Delay"),
            ("missing_document", "Missing Document"),
            ("legal_deadline", "Legal Deadline"),
            ("payment_schedule", "Payment Schedule"),
        ],
        string="Status Reason", tracking=True,
    )
    kh_currency_id = fields.Many2one(
        "res.currency", string="Currency", related="company_id.currency_id"
    )
    # Not stored on purpose: this reflects live accounting data (invoices
    # posted/paid after the project was last touched should show up
    # immediately, not only after some unrelated write on the project).
    kh_collected_amount = fields.Monetary(
        string="Collected", currency_field="kh_currency_id",
        compute="_compute_kh_collected_amount",
    )
    kh_remaining_amount = fields.Monetary(
        string="Remaining", currency_field="kh_currency_id",
        compute="_compute_kh_collected_amount",
    )

    def _compute_kh_collected_amount(self):
        # Primary source: the invoice line's Analytic Distribution pointing
        # at this project's own Analytic Account (account_id) - this is how
        # the accountant is supposed to tag an invoice to a project.
        # One batch query for every project in `self`, instead of a fresh
        # search per record (this runs for every card in the dashboard).
        account_ids = {p.account_id.id for p in self if p.account_id}
        collected_by_account = {}
        if account_ids:
            lines = self.env["account.move.line"].search([
                ("analytic_distribution", "!=", False),
                ("move_id.move_type", "=", "out_invoice"),
                ("move_id.state", "=", "posted"),
            ])
            for line in lines:
                move = line.move_id
                if not move.amount_total:
                    continue
                paid_ratio = (move.amount_total - move.amount_residual) / move.amount_total
                for key, pct in (line.analytic_distribution or {}).items():
                    # A key can combine several analytic dimensions in one
                    # string (e.g. "1224,1381" - project + business unit),
                    # not always a single id.
                    for acc_id in (int(part) for part in key.split(",")):
                        if acc_id in account_ids:
                            collected_by_account[acc_id] = collected_by_account.get(acc_id, 0.0) + (
                                paid_ratio * line.price_total * (pct / 100.0)
                            )

        for project in self:
            collected = collected_by_account.get(project.account_id.id, 0.0) if project.account_id else 0.0
            # Fallback: the accountant sometimes forgets to tag the project
            # on the invoice (just picks the client). Only safe to fall back
            # to a plain client match when that client has exactly one
            # project - otherwise we can't tell which project an untagged
            # invoice belongs to, so we leave it at 0 rather than guess.
            if not collected and project.partner_id:
                sibling_count = self.search_count([("partner_id", "=", project.partner_id.id)])
                if sibling_count == 1:
                    invoices = self.env["account.move"].search([
                        ("partner_id", "=", project.partner_id.id),
                        ("move_type", "=", "out_invoice"),
                        ("state", "=", "posted"),
                    ])
                    collected = sum(inv.amount_total - inv.amount_residual for inv in invoices)
            project.kh_collected_amount = collected
            project.kh_remaining_amount = _kh_safe_float(project.x_studio_value_of_the_contract) - collected
