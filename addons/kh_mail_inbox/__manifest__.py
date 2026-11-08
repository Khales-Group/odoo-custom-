{
    "name": "Khales Follow-up Dashboard: Mailboxes",
    "version": "19.0.1.0.1",
    "summary": "لوحة المتابعة: the company mailboxes (info@, hr@, ceo@ ...) on the follow-up dashboard",
    "description": """
Khales Follow-up Dashboard: Mailboxes
=====================================

Adds a "الإيميلات" part to the follow-up dashboard (kh_wa_inbox): the
inbox of each company mailbox, newest first, with its whole history.

- Each mailbox (Follow-up Dashboard > Configuration > Mailboxes, for
  administrators: they alone see the login and password) is read over
  IMAP every 5 minutes, read-only: the folder is opened with EXAMINE and
  messages with BODY.PEEK, so nothing is marked as read, moved, deleted
  or sent. New mail comes first; the older mail follows in batches until
  the whole folder is in.
- The text of each message is kept (one-time passwords and card numbers
  masked); attachments stay in the mailbox and are read from it when
  someone opens them.
- A message gone from the folder (deleted or filed elsewhere) is archived;
  read and answered flags follow the mailbox. "Needs a reply": not answered
  (the mail program's flag, or a reply found in the Sent folder), not a
  newsletter or automatic mail, not marked followed up, from the last 30
  days.
- A message can become a project task for an employee, with its text and
  attachments; closing the task marks the message followed up.

Only the dashboard's managers ("مفكرة القروبات / المدير") see the part and
the messages.
    """,
    "author": "Khales Group",
    "category": "Productivity",
    "depends": ["kh_wa_inbox"],
    "data": [
        "security/ir.model.access.csv",
        "data/kh_mail_cron.xml",
        "views/kh_mail_box_views.xml",
        "views/project_task_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "kh_mail_inbox/static/src/mail/mail_section.scss",
            "kh_mail_inbox/static/src/mail/mail_store.js",
            "kh_mail_inbox/static/src/mail/mail_section.js",
            "kh_mail_inbox/static/src/mail/mail_section.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
