{
    "name": "Khales Collection",
    "version": "19.0.1.4.0",
    "summary": "Collection cases: accountant, then escalate (with manager approval) to Legal",
    "description": """
Khales Collection
==================

Tracks a collection case (amount owed by a client, tied to a contractor and
project). Each case gets a unique reference from the system (COL-00001...).

- Starts with the accountant. If they can't collect it, they request to
  escalate to the lawyer (Ahmed Ali) - this needs Majed's approval first.
- Once approved, a file is opened in the Law & PRO app (department "Law",
  its "Collection" stage) assigned to the lawyer, plus a task on the project.
- "Mark Collected" closes the case at any stage.

There is no PRO step any more (19.0.1.4.0): the cases, files and tasks the
PRO held went back to the accountant.

No step is automatic or time-based: every escalation is a manual request
that only takes effect once Majed approves it (a plain Odoo activity, not
tied to the separate Approvals app).

Each case has a type: Client, Contractor, VAT Return or VAT Refund (the VAT
ones get an orange badge). "Responsible" follows the case (accountant, then
lawyer), and the "By Employee" menu lists the cases per person, with
Balance / Collected / Remaining totals.
    """,
    "author": "Khales Group",
    "category": "Services",
    "depends": ["mail", "project", "kh_law"],
    "data": [
        "security/kh_collection_security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
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
