{
    "name": "Khales Collection",
    "version": "19.0.1.2.0",
    "summary": "Collection cases: accountant, then escalate (with manager approval) to PRO, then to Legal",
    "description": """
Khales Collection
==================

Tracks a collection case (amount owed by a client, tied to a contractor and
project) through an escalation chain:

- Starts with the accountant. If they can't collect it, they request to
  escalate to PRO (Hamam) - this needs Majed's approval first.
- Once approved, a file is opened in the Law & PRO app (department "PRO")
  assigned to Hamam, plus a task on the project.
- If PRO can't collect it either, the same approval-then-escalate flow moves
  the same Law & PRO file to department "Law", reassigned to the lawyer
  (Ahmed Ali), plus a new task.
- "Mark Collected" closes the case at any stage.

No step is automatic or time-based: every escalation is a manual request
that only takes effect once Majed approves it (a plain Odoo activity, not
tied to the separate Approvals app).

Each case has a type: Client, Contractor, VAT Return or VAT Refund (the VAT
ones get an orange badge). In the Law & PRO app, files opened from a
collection case sit in their department's own "Collection" stage (PRO, then
Law after escalation). "Handled By" / "Responsible" follow the case
(Accountant, then PRO, then Lawyer), and the "By Employee" menu lists the
cases in that order, per person, with Balance / Collected / Remaining
totals.
    """,
    "author": "Khales Group",
    "category": "Services",
    "depends": ["mail", "project", "kh_law"],
    "data": [
        "security/kh_collection_security.xml",
        "security/ir.model.access.csv",
        "views/kh_collection_case_views.xml",
        "data/x_reports_stage_data.xml",
        "views/x_reports_views.xml",
        "views/x_reports_stage_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
