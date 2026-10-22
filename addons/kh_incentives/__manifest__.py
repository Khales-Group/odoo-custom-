{
    "name": "Khales Bonuses",
    "version": "19.0.1.1.0",
    "summary": "Employee bonuses (collection, design start, project handover, other), with CEO approval",
    "description": """
Khales Bonuses
==============

Bonuses, connected to the apps the work actually happens in:

1. Collection - created automatically every time money is collected on a
   Collection case, for whoever holds the case at that moment:
   Accountant 0.25%, PRO 0.5%, Lawyer 1% of the amount received.
2. Design Start - 4% of the client's payment that starts the design process,
   for the designer responsible (entered by hand; the amount can be taken
   from the client's invoice).
3. Project Handover - 500 to 3,500 for the project manager once the project
   is handed over / complete. A draft is created automatically when the
   project's status is set to "Complete" (or it moves to a Done / Handed Over
   stage); the CEO sets the amount and approves.
4. Other - any other bonus, amount entered by hand.

Every bonus needs the CEO's approval before it can be marked paid. An
employee only sees their own bonuses; the CEO, Admin and anyone in
"Incentives Access" see everything, listed Collection (Accountant, PRO,
Lawyer), Design, Handover, Other, then by employee, with totals.
    """,
    "author": "Khales Group",
    "category": "Human Resources",
    "depends": ["mail", "project", "account", "kh_collection"],
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
