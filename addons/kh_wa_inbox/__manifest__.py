{
    "name": "Khales Follow-up Dashboard: WhatsApp Groups",
    "version": "19.0.1.5.0",
    "summary": "لوحة المتابعة: what is asked, decided and promised in the company's WhatsApp groups",
    "description": """
Khales Follow-up Dashboard: WhatsApp Groups (لوحة المتابعة)
============================================================

The follow-up dashboard where the manager follows up what is asked, decided
and promised in the company's WhatsApp groups. Only what needs follow-up is
kept: open requests, decisions someone is waiting for, deadlines and
important alerts.

The dashboard is a frame with a sidebar: its parts are registered in the OWL
registry ``kh_followup_dashboard_sections`` (a store, a Sidebar component for
the part's entries and a Main component for its pages). This module
provides the frame and the WhatsApp part (overview with six tiles and the
groups table; lists beside the selected item; my notes); other modules can
add parts (projects, CRM, ...) the same way.

Odoo never talks to WhatsApp and calls no AI. An external bot reads the
groups, filters them and pushes ready-made items over XML-RPC, as a user in
"مفكرة القروبات / المدير":

- ``kh.wa.group.upsert_groups(rows)``: keyed by wa_chat_id (also takes
  last_message_at).
- ``kh.wa.item.upsert_items(rows)``: keyed by source_msg_id. Fields a person
  changed in Odoo (state, assignee, urgent, needs_manager, manager_note,
  linked record) are never overwritten afterwards. A request already done
  within the quick-done threshold (Settings, 60 minutes) is not stored: it
  is counted once on the group's day page.
- ``kh.wa.day.upsert_days(rows)``: keyed by (date, wa_chat_id).
- ``kh.wa.item.get_dashboard(date, group_id, search)``: everything the
  WhatsApp part shows, in one call (``get_notebook`` still returns the
  lists alone).

Each upsert returns {"ids": [...], "errors": [...]}; a bad row is logged,
skipped and reported, never failing the batch. The time of the last
upsert that stored something is shown in the dashboard's header.

Assigning an item to someone outside the notebook managers gives them a
project task with the request (they can't open the dashboard or the item):
in the linked project, the item's or its group's project, or else the
private "WhatsApp Follow-ups" project. Closing the task closes the item
(their last comment is its result), cancelling it hands the item back to
the manager, its deadline and assignee follow the item's and the other way
round; when the item is closed (by the manager, or by the bot after a
reply in the group) the task closes with a word to its assignee. Only
notebook managers see the dashboard.

An item can be linked to a record of the other apps (project, task, Law
Pro file, invoice or bill, approval request, purchase order, lead,
signature request, site visit): the task shows it, and the record gets a
note with a link to the task. The bot can link by name (e.g. an invoice
number).

One-time passwords and card numbers are masked in the stored texts. Voice
notes are never transcribed.

Access: "المدير" sees everything and is the only one with the dashboard;
"مستخدم" can read the items assigned to them or that they asked (no phone
numbers, no day pages). No users are added by the module.
    """,
    "author": "Khales Group",
    "category": "Productivity",
    "depends": ["mail", "project"],
    "data": [
        "security/kh_wa_inbox_security.xml",
        "security/ir.model.access.csv",
        "security/kh_wa_inbox_rules.xml",
        "data/kh_wa_cron.xml",
        "views/kh_wa_item_views.xml",
        "views/project_task_views.xml",
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
            "kh_wa_inbox/static/src/dashboard/followup_dashboard.scss",
            "kh_wa_inbox/static/src/dashboard/dates.js",
            "kh_wa_inbox/static/src/dashboard/followup_dashboard.js",
            "kh_wa_inbox/static/src/dashboard/followup_dashboard.xml",
            "kh_wa_inbox/static/src/whatsapp/wa_section.scss",
            "kh_wa_inbox/static/src/whatsapp/wa_store.js",
            "kh_wa_inbox/static/src/whatsapp/wa_section.js",
            "kh_wa_inbox/static/src/whatsapp/wa_section.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
