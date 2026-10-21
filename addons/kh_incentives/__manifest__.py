{
    "name": "Khales Incentives",
    "version": "19.0.1.0.0",
    "summary": "Employee commission/incentive claims (new contracts and collections), with CEO approval",
    "description": """
Khales Incentives
===================

Tracks the "Monthly Incentives Sheet" on paper, as a simple Odoo model:

- An employee (engineer, lawyer, etc.) files an incentive claim for a file/
  contract: which role they played (source, relationship, offer, negotiation,
  execution, or collection), the type (new contract vs. overdue debt
  collected), the amount collected, the approved margin, and the incentive
  amount being claimed.
- The claim goes through a financial reviewer, then needs the CEO's approval
  before it can be marked paid.
- Visibility: an employee only sees their own claims; the CEO, Admin, and
  anyone in "Incentives Access" see everything (same pattern as the
  Collection app).
- A Pivot dashboard breaks down claimed/approved/paid amounts by employee,
  month, and role.
    """,
    "author": "Khales Group",
    "category": "Human Resources",
    "depends": ["mail", "project"],
    "data": [
        "security/kh_incentives_security.xml",
        "security/ir.model.access.csv",
        "views/kh_incentive_claim_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
