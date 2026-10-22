# -*- coding: utf-8 -*-
import re
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

_KH_INVOICE_TYPES = ("out_invoice", "out_refund")

# Arabic-Indic and Persian digits, plus the Arabic decimal/thousands marks,
# mapped to their plain equivalents ("٢٬٠٠٠٬٠٠٠" -> "2,000,000").
_KH_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬",
    "01234567890123456789.,",
)


def _kh_safe_float(value):
    # x_studio_value_of_the_contract is a Studio field and isn't reliably a
    # clean number on every record - never let one bad record break the
    # whole dashboard for everyone.
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return 0.0
    text = str(value).strip().translate(_KH_DIGITS)
    # Employees sometimes type things like "2,000,000 AED" or "AED 2,000,000"
    # instead of a plain number - strip anything that isn't a digit, dot,
    # comma or minus sign (currency codes/symbols, stray spaces...).
    text = re.sub(r"[^0-9.,-]", "", text)
    # ... and sometimes dots as thousand separators (e.g. "1.250.000" for
    # 1,250,000) - more than one dot can only mean that, never a real
    # decimal value.
    if text.count(".") > 1:
        text = text.replace(".", "")
    text = text.replace(",", "")
    try:
        return float(text) if text else 0.0
    except (TypeError, ValueError):
        return 0.0


def _kh_client_key(name):
    # The same client entered twice ("Mousa Saleh" / "mousa  saleh ") is
    # still one client.
    return " ".join((name or "").lower().split())


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
            ("payment_delay", "Delayed Payment"),
            ("on_track", "Work Going Well"),
        ],
        string="Status Reason", tracking=True,
    )
    kh_currency_id = fields.Many2one(
        "res.currency", string="Currency", related="company_id.currency_id"
    )

    @api.ondelete(at_uninstall=False)
    def _kh_unlink_never(self):
        # Company rule: a project is never deleted - not by the admin either,
        # and not through code/sudo. Archive it instead (keeps its invoices,
        # tasks, files and history linked).
        raise UserError(_("Projects can't be deleted. Archive the project instead."))
    # x_studio_value_of_the_contract is shown directly with widget="monetary"
    # in a couple of places and displays "NaN" whenever it holds text instead
    # of a clean number. This is the same value run through the same safe
    # parser used everywhere else, so the display is never broken.
    kh_contract_value = fields.Monetary(
        string="Contract Value", currency_field="kh_currency_id",
        compute="_compute_kh_contract_value", inverse="_inverse_kh_contract_value",
    )

    def _compute_kh_contract_value(self):
        for project in self:
            project.kh_contract_value = _kh_safe_float(project.x_studio_value_of_the_contract)

    def _inverse_kh_contract_value(self):
        # Editing this from the dashboard writes a clean number back into
        # the real Studio field, instead of whatever messy text was there -
        # this fixes the underlying data, not just the display. That field
        # is text, so the number is written the way people read it
        # ("2,000,000" / "1,250,000.50").
        for project in self:
            text = "{:,.2f}".format(project.kh_contract_value or 0.0)
            if text.endswith(".00"):
                text = text[:-3]
            project.x_studio_value_of_the_contract = text

    # Not stored on purpose: this reflects live accounting data (invoices
    # posted/paid after the project was last touched should show up
    # immediately, not only after some unrelated write on the project).
    kh_collected_amount = fields.Monetary(
        string="Received", currency_field="kh_currency_id",
        compute="_compute_kh_collected_amount",
    )
    kh_remaining_amount = fields.Monetary(
        string="Remaining", currency_field="kh_currency_id",
        compute="_compute_kh_collected_amount",
    )
    kh_unlinked_amount = fields.Monetary(
        string="Unlinked Client Payments", currency_field="kh_currency_id",
        compute="_compute_kh_collected_amount",
        help="Paid by this project's client on invoices with no project in Analytic "
             "Distribution, while the client has several projects - so the system "
             "can't tell which project it belongs to. Not included in Received: "
             "set the project on those invoices and it moves there.",
    )
    kh_last_activity_date = fields.Datetime(
        string="Last Update", compute="_compute_kh_last_activity_date"
    )

    def _compute_kh_last_activity_date(self):
        # "Last update" = the most recent of: the project's own write_date,
        # a chatter entry on the project itself, or anything on one of its
        # tasks (write_date or chatter entry - a note, a finished task, an
        # attachment). A chatter post alone doesn't bump write_date in
        # standard Odoo, which is why it needs to be checked separately.
        tasks = self.env["project.task"].search([("project_id", "in", self.ids)]) if self.ids else self.env["project.task"]

        last_msg_by_project = {}
        if self.ids:
            last_msg_by_project = dict(self.env["mail.message"].sudo()._read_group(
                [("model", "=", "project.project"), ("res_id", "in", self.ids)],
                ["res_id"], ["date:max"],
            ))

        last_msg_by_task = {}
        if tasks:
            last_msg_by_task = dict(self.env["mail.message"].sudo()._read_group(
                [("model", "=", "project.task"), ("res_id", "in", tasks.ids)],
                ["res_id"], ["date:max"],
            ))

        task_latest_by_project = {}
        for task in tasks:
            candidates = [task.write_date, last_msg_by_task.get(task.id)]
            candidates = [d for d in candidates if d]
            if not candidates:
                continue
            latest = max(candidates)
            project_id = task.project_id.id
            if project_id not in task_latest_by_project or latest > task_latest_by_project[project_id]:
                task_latest_by_project[project_id] = latest

        for project in self:
            candidates = [
                project.write_date,
                last_msg_by_project.get(project.id),
                task_latest_by_project.get(project.id),
            ]
            candidates = [d for d in candidates if d]
            project.kh_last_activity_date = max(candidates) if candidates else project.write_date

    def _compute_kh_collected_amount(self):
        collected, unlinked = self._kh_allocate_customer_payments()
        for project in self:
            project.kh_collected_amount = collected.get(project._origin.id, 0.0)
            project.kh_unlinked_amount = unlinked.get(project._origin.id, 0.0)
            project.kh_remaining_amount = (
                _kh_safe_float(project.x_studio_value_of_the_contract) - project.kh_collected_amount
            )

    def _kh_allocate_customer_payments(self):
        """Money actually received on posted customer invoices (minus credit
        notes), per project of `self`. Invoices are tagged inconsistently -
        sometimes the project in Analytic Distribution, sometimes only the
        client, sometimes both - so every invoice is counted exactly once,
        for the first rule that identifies its project:

        1. A project picked in Analytic Distribution on any of its lines
           (split by line amount if it names several projects).
        2. No project picked: the client. Only one project for that client
           -> that project. Several -> the one whose number (the "00134" in
           "Project: 00134 - ...") is written on the invoice.
        3. Still can't tell: "unlinked" - shown on each of the client's
           project cards but not added to Received, rather than guessing.

        Returns two {project_id: amount} dicts: collected, unlinked.
        """
        screen_ids = {project._origin.id for project in self if project._origin.id}
        collected, unlinked = defaultdict(float), defaultdict(float)
        if not screen_ids:
            return collected, unlinked
        # Totals only: not everyone who sees the dashboard has Invoicing
        # access, and a project's invoices can be in any of the companies.
        env = self.sudo().env
        Project = env["project.project"].with_context(active_test=False)
        screen = Project.browse(screen_ids)

        # Every project's analytic account - not only the ones on screen - so
        # an invoice tagged to *another* project never reaches this one
        # through the client rule.
        projects_by_account = {
            account.id: project_ids
            for account, project_ids in Project._read_group(
                [("account_id", "!=", False)], ["account_id"], ["id:array_agg"]
            )
        }

        # Clients: the commercial entity of each project's customer, plus any
        # duplicate contact typed with the same name.
        clients = screen.partner_id.commercial_partner_id
        keys = {_kh_client_key(client.name) for client in clients} - {""}
        client_key_by_partner = {}
        if keys:
            env["res.partner"].flush_model(["name"])
            env.cr.execute(
                "SELECT id FROM res_partner"
                " WHERE lower(regexp_replace(btrim(name), '\\s+', ' ', 'g')) IN %s",
                [tuple(keys)],
            )
            same_name = env["res.partner"].browse(row[0] for row in env.cr.fetchall())
            for partner in same_name | clients:
                key = _kh_client_key(partner.name)
                if partner.commercial_partner_id == partner and key in keys:
                    client_key_by_partner[partner.id] = key
        projects_by_client = defaultdict(list)
        if client_key_by_partner:
            for project in Project.search([
                ("partner_id.commercial_partner_id", "in", list(client_key_by_partner)),
                ("is_template", "=", False),
            ]):
                key = client_key_by_partner.get(project.partner_id.commercial_partner_id.id)
                if key:
                    projects_by_client[key].append(project)

        Move = env["account.move"]
        moves = Move
        screen_accounts = [
            account_id for account_id, project_ids in projects_by_account.items()
            if screen_ids.intersection(project_ids)
        ]
        if screen_accounts:
            # "in" on analytic_distribution also matches combined keys such
            # as "1224,1381" (project + business unit).
            moves |= env["account.move.line"].search([
                ("parent_state", "=", "posted"),
                ("move_id.move_type", "in", _KH_INVOICE_TYPES),
                ("analytic_distribution", "in", screen_accounts),
            ]).move_id
        if client_key_by_partner:
            moves |= Move.search([
                ("state", "=", "posted"),
                ("move_type", "in", _KH_INVOICE_TYPES),
                ("commercial_partner_id", "in", list(client_key_by_partner)),
            ])

        for move in moves:
            # Company currency, signed: credit notes come out negative.
            paid = move.amount_total_signed - move.amount_residual_signed
            if move.company_currency_id.is_zero(paid):
                continue

            # Rule 1 - project(s) in Analytic Distribution.
            weights = defaultdict(float)
            for line in move.invoice_line_ids:
                for key, percentage in (line.analytic_distribution or {}).items():
                    for account_id in key.split(","):
                        account_id = account_id.strip()
                        owners = projects_by_account.get(int(account_id), []) if account_id.isdigit() else []
                        for project_id in owners:
                            weights[project_id] += (
                                abs(line.price_total) * (percentage or 0.0) / 100.0 / len(owners)
                            )
            if weights:
                total = sum(weights.values())
                for project_id in screen_ids.intersection(weights):
                    share = weights[project_id] / total if total else 1.0 / len(weights)
                    collected[project_id] += paid * share
                continue

            # Rule 2 - the client (same company as the invoice).
            candidates = [
                project
                for project in projects_by_client.get(client_key_by_partner.get(move.commercial_partner_id.id), [])
                if not project.company_id or project.company_id == move.company_id
            ]
            if len(candidates) > 1:
                candidates = self._kh_projects_named_on_invoice(move, candidates) or candidates
            if len(candidates) == 1:
                if candidates[0].id in screen_ids:
                    collected[candidates[0].id] += paid
            else:
                # Rule 3 - can't tell which of the client's projects.
                for project in candidates:
                    if project.id in screen_ids:
                        unlinked[project.id] += paid
        return collected, unlinked

    @api.model
    def _kh_projects_named_on_invoice(self, move, projects):
        """The projects whose number (e.g. "00134" in "Project: 00134 -
        Client: ...") is written on the invoice: customer reference, notes
        or a line label. The invoice/sale-order numbers themselves are left
        out - they're numbered the same way and would match by accident."""
        text = " ".join(filter(None, [
            move.ref,
            html2plaintext(move.narration or ""),
            *move.invoice_line_ids.mapped("name"),
        ]))
        if not text:
            return []
        return [
            project for project in projects
            if any(
                re.search(r"(?<!\w)%s(?!\w)" % re.escape(code), text)
                for code in re.findall(r"\d{3,}", project.name or "")
            )
        ]
