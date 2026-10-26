{
    "name": "Khales Leads Dashboard",
    "version": "19.0.1.4.0",
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

The cards show the CRM's own Studio fields Service Type
(x_studio_service_type) and Source (x_studio_source: WhatsApp, Instagram,
Facebook, Google, Phone Call, Website, Direct, Referral).

The standard Source (source_id) is limited to the ones the sales team uses: Instagram,
Facebook, WhatsApp, Referral, Direct Call (created if missing; older sources
stay on the leads that have them but can't be picked anymore).
    """,
    "author": "Khales Group",
    "category": "Sales/CRM",
    "depends": ["crm", "utm", "kh_inline_edit"],
    "data": [
        "data/utm_source_data.xml",
        "views/crm_lead_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
