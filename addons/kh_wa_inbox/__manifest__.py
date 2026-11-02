{
    "name": "Khales WhatsApp Groups Notebook",
    "version": "19.0.1.0.0",
    "summary": "مفكرة القروبات: what is asked, decided and promised in the company's WhatsApp groups",
    "description": """
Khales WhatsApp Groups Notebook (مفكرة القروبات)
=================================================

A short, tidy notebook where the manager follows up what is asked, decided
and promised in the company's WhatsApp groups. Only what needs follow-up is
kept: open requests, decisions someone is waiting for, deadlines and
important alerts.

Odoo never talks to WhatsApp and calls no AI. An external bot reads the
groups, filters them and pushes ready-made items over XML-RPC, as a user in
"مفكرة القروبات / المدير":

- ``kh.wa.group.upsert_groups(rows)``: keyed by wa_chat_id.
- ``kh.wa.item.upsert_items(rows)``: keyed by source_msg_id. Fields a person
  changed in Odoo (state, assignee, urgent, needs_manager, manager_note)
  are never overwritten afterwards. A request already done within the
  quick-done threshold (Settings, 60 minutes) is not stored: it is counted
  once on the group's day page.
- ``kh.wa.day.upsert_days(rows)``: keyed by (date, wa_chat_id).
- ``kh.wa.item.get_notebook(date, group_id, search)``: everything the
  notebook screen shows, in one call.

Each method returns {"ids": [...], "errors": [...]}; a bad row is logged,
skipped and reported, never failing the batch.

One-time passwords and card numbers are masked in the stored texts. Voice
notes are never transcribed.

Access: "المدير" sees everything; "مستخدم" sees only the items assigned to
them or that they asked, without phone numbers or day pages. Nobody else
sees anything. No users are added by the module.
    """,
    "author": "Khales Group",
    "category": "Productivity",
    "depends": ["mail", "project"],
    "data": [
        "security/kh_wa_inbox_security.xml",
        "security/ir.model.access.csv",
        "security/kh_wa_inbox_rules.xml",
        "views/kh_wa_item_views.xml",
        "views/kh_wa_group_views.xml",
        "views/kh_wa_day_views.xml",
        "views/res_config_settings_views.xml",
        "views/kh_wa_menus.xml",
    ],
    "demo": [
        "demo/kh_wa_inbox_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "kh_wa_inbox/static/src/notebook/notebook.scss",
            "kh_wa_inbox/static/src/notebook/notebook.js",
            "kh_wa_inbox/static/src/notebook/notebook.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
