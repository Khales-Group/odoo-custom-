{
    "name": "Khales Leads Dashboard",
    "version": "19.0.1.1.0",
    "summary": "Leads/opportunities pivot dashboard grouped by the manager's 4-stage funnel",
    "description": """
Khales Leads Dashboard
========================

Groups the CRM pipeline's real stages into the 4 simplified stages used on
the manager's paper tracking card ("Opportunity Card 9.2"): Capture, Verify,
Offer, Contract & Delivery - plus Lost, shown separately.

Mapping (adjust models/crm_lead.py if a stage should move):
- Capture: New, Hold List
- Verify: Qualified, Meeting Scheduled
- Offer: Proposal, Open File, Pending Documents
- Contract & Delivery: Contract, Won, Completed
- Lost: Canceled
    """,
    "author": "Khales Group",
    "category": "Sales/CRM",
    "depends": ["crm", "kh_inline_edit"],
    "data": [
        "views/crm_lead_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
