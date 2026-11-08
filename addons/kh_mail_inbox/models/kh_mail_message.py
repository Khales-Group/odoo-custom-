import logging
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.kh_wa_inbox.models.kh_wa_tools import arabic_age, utc_now

_logger = logging.getLogger(__name__)

PAGE = 50
MAX_PAGE = 500
NEEDS_REPLY_DAYS = 30
TASK_ATTACHMENTS_MAX = 25 * 1024 * 1024  # bytes copied into a task, in all
LIST_FIELDS = [
    "box_id", "subject", "from_name", "from_email", "date", "snippet", "seen", "answered",
    "replied", "followed", "bulk", "attachment_count",
]


class KhMailMessage(models.Model):
    """A message of a dashboard mailbox, as read from it. The text is kept
    (one-time passwords and card numbers masked); attachments stay in the
    mailbox and are fetched when someone opens them."""

    _name = "kh.mail.message"
    _description = "Dashboard Mailbox Message"
    _order = "date desc, id desc"
    _rec_name = "subject"

    box_id = fields.Many2one("kh.mail.box", required=True, ondelete="cascade", index=True)
    uid = fields.Integer(required=True)
    uidvalidity = fields.Char(required=True)
    message_id = fields.Char(index="btree_not_null")
    in_reply_to = fields.Char()
    subject = fields.Char()
    from_name = fields.Char()
    from_email = fields.Char(index="btree_not_null")
    to_text = fields.Char(string="To")
    cc_text = fields.Char(string="Cc")
    date = fields.Datetime(required=True, index=True)
    size = fields.Integer()
    snippet = fields.Char()
    body_text = fields.Text(string="Text")
    body_truncated = fields.Boolean(help="Only the beginning of a long message is kept.")
    attachment_meta = fields.Json(string="Attachments (in the mailbox)")
    attachment_count = fields.Integer()
    seen = fields.Boolean(string="Read in the Mailbox", index=True)
    answered = fields.Boolean(string="Marked Answered")
    replied = fields.Boolean(string="Answered (Sent folder)")
    flagged = fields.Boolean()
    bulk = fields.Boolean(string="Newsletter / Automatic", index=True)
    followed = fields.Boolean(string="Followed Up", index=True, help="Set on the dashboard: needs nothing more.")
    active = fields.Boolean(default=True, help="Archived when it leaves the mailbox folder.")
    task_ids = fields.One2many("project.task", "kh_mail_message_id", string="Tasks")

    _box_uid_unique = models.Constraint("UNIQUE(box_id, uidvalidity, uid)", "This message is already read.")

    @api.depends("subject", "from_email")
    def _compute_display_name(self):
        for message in self:
            message.display_name = message.subject or message.from_email or self.env._("(no subject)")

    # ------------------------------------------------------------------
    # The dashboard
    # ------------------------------------------------------------------

    def _kh_check_manager(self):
        if not self.env.user.has_group("kh_wa_inbox.group_kh_wa_manager"):
            raise AccessError("لوحة المتابعة للمدير فقط.")

    @api.model
    def _kh_filter_domain(self, name):
        if name == "unread":
            return [("seen", "=", False)]
        if name == "needs_reply":
            since = fields.Datetime.now() - timedelta(days=NEEDS_REPLY_DAYS)
            return [
                ("answered", "=", False), ("replied", "=", False), ("bulk", "=", False),
                ("followed", "=", False), ("date", ">=", since),
            ]
        return []

    @api.model
    def get_mail_dashboard(self, box_id=False, filter="all", search="", limit=PAGE):
        """The mail part of the dashboard: the boxes with their counts and one
        page of messages (newest first) for the picked box (or all of them),
        filter ("all", "unread", "needs_reply") and search."""
        self._kh_check_manager()
        boxes = self.env["kh.mail.box"].search([])
        box_id = int(box_id) if box_id and int(box_id) in boxes.ids else False
        scope = [("box_id", "=", box_id)] if box_id else [("box_id", "in", boxes.ids)]
        search = (search or "").strip()
        found = []
        if len(search) >= 2:
            found = ["|", "|", "|", "|",
                     ("subject", "ilike", search), ("from_name", "ilike", search),
                     ("from_email", "ilike", search), ("to_text", "ilike", search), ("snippet", "ilike", search)]
        domain = scope + self._kh_filter_domain(filter) + found
        limit = max(1, min(int(limit or PAGE), MAX_PAGE))
        rows = self.search_fetch(domain, LIST_FIELDS, limit=limit + 1)

        counts = {box.id: {"total": 0, "unread": 0, "needs_reply": 0} for box in boxes}
        everywhere = [("box_id", "in", boxes.ids)]
        for key in ("total", "unread", "needs_reply"):
            extra = self._kh_filter_domain("all" if key == "total" else key)
            for box, count in self._read_group(everywhere + extra, ["box_id"], ["__count"]):
                counts[box.id][key] = count
        now = utc_now()
        return {
            "boxes": [
                {
                    "id": box.id, "name": box.name, "email": box.email, "color": box.color,
                    "counts": counts[box.id], "server_count": box.server_count, "history_done": box.history_done,
                    "last_fetch_at": fields.Datetime.to_string(box.last_fetch_at) or False,
                    "error": box.last_error or False,
                }
                for box in boxes
            ],
            "box_id": box_id,
            "filter": filter,
            "filter_counts": {
                key: self.search_count(scope + self._kh_filter_domain(key) + found)
                for key in ("all", "unread", "needs_reply")
            },
            "messages": [message._kh_row(now) for message in rows[:limit]],
            "has_more": len(rows) > limit,
            "sync": self.env["kh.mail.box"]._kh_sync_status(boxes),
            "users": self.env["kh.wa.item"]._notebook_users(),
        }

    def _kh_needs_reply(self):
        since = fields.Datetime.now() - timedelta(days=NEEDS_REPLY_DAYS)
        return not (self.answered or self.replied or self.bulk or self.followed) and self.date >= since

    def _kh_row(self, now):
        return {
            "id": self.id,
            "box_id": self.box_id.id,
            "box_name": self.box_id.name,
            "box_color": self.box_id.color,
            "subject": self.subject or "",
            "from_name": self.from_name or "",
            "from_email": self.from_email or "",
            "date": fields.Datetime.to_string(self.date),
            "age": arabic_age(self.date, now),
            "snippet": self.snippet or "",
            "seen": self.seen,
            "answered": self.answered or self.replied,
            "needs_reply": self._kh_needs_reply(),
            "followed": self.followed,
            "bulk": self.bulk,
            "attachment_count": self.attachment_count,
        }

    def get_mail_detail(self):
        """One message, with its text, attachments and task."""
        self.ensure_one()
        self._kh_check_manager()
        task = self.sudo().task_ids.sorted("id", reverse=True)[:1]
        return {
            **self._kh_row(utc_now()),
            "to": self.to_text or "",
            "cc": self.cc_text or "",
            "body": self.body_text or "",
            "body_truncated": self.body_truncated,
            "attachments": [
                {
                    "index": index, "name": att.get("name") or "attachment",
                    "mimetype": att.get("mimetype") or "", "size": att.get("size") or 0,
                    "url": f"/kh_mail_inbox/attachment/{self.id}/{index}",
                }
                for index, att in enumerate(self.attachment_meta or [])
            ],
            "task": {
                "id": task.id,
                "user": task.user_ids[:1].name or "",
                "state": task.state,
                "closed": task.state in ("1_done", "1_canceled"),
            } if task else False,
        }

    def action_set_followed(self, followed=True):
        self._kh_check_manager()
        self.write({"followed": bool(followed)})
        return True

    # ------------------------------------------------------------------
    # Attachments (fetched from the mailbox when opened)
    # ------------------------------------------------------------------

    def _kh_attachment(self, index, reader=None):
        """(content, name, mimetype) of one attachment, read from the mailbox."""
        self.ensure_one()
        attachments = self.attachment_meta or []
        if not 0 <= index < len(attachments):
            raise UserError(self.env._("This attachment doesn't exist."))
        meta = attachments[index]
        if reader is None:
            with self.box_id._kh_reader() as session:
                return self._kh_attachment(index, session)
        validity, _exists = reader.examine(self.box_id.sudo().folder or "INBOX")
        content = reader.part(self.uid, meta["path"], meta.get("encoding")) if str(validity) == self.uidvalidity else None
        if content is None:
            raise UserError(self.env._("This message is no longer in the mailbox."))
        return content, meta.get("name") or "attachment", meta.get("mimetype") or "application/octet-stream"

    # ------------------------------------------------------------------
    # A task from a message
    # ------------------------------------------------------------------

    def _kh_task_description(self):
        rows = [
            ("الصندوق", self.box_id.email),
            ("من", f"{self.from_name} <{self.from_email}>" if self.from_name else self.from_email),
            ("إلى", self.to_text),
            ("نسخة", self.cc_text),
            ("التاريخ", fields.Datetime.to_string(self.date)),
        ]
        lines = [Markup("<p><b>%s:</b> %s</p>") % (label, value) for label, value in rows if value]
        if self.body_text:
            text = escape(self.body_text[:8000]).replace("\n", Markup("<br/>"))
            lines.append(Markup("<p>%s</p>") % text)
        lines.append(Markup("<p><i>%s</i></p>") % "عند الانتهاء اكتب ماذا تم في تعليق، ثم اضغط «تم».")
        return Markup("").join(lines)

    def action_make_task(self, user_id):
        """A project task for this message, assigned to user_id, with the
        message's text and attachments (copied from the mailbox)."""
        self.ensure_one()
        self._kh_check_manager()
        user = self.env["res.users"].sudo().browse(int(user_id)).exists()
        if not user or user.share:
            raise UserError(self.env._("Pick an employee to give the task to."))
        project = self.env["kh.wa.item"].sudo()._kh_default_project(create=True)
        context = {k: v for k, v in self.env.context.items() if k in ("lang", "tz", "allowed_company_ids")}
        task = self.env["project.task"].sudo().with_context(context).create({
            "name": self.subject or self.env._("(no subject)"),
            "project_id": project.id if project.active else False,
            "user_ids": [Command.set(user.ids)],
            "description": self._kh_task_description(),
            "kh_mail_message_id": self.id,
        })
        self._kh_copy_attachments(task)
        return {"id": task.id}

    def _kh_copy_attachments(self, task):
        """The message's attachments, copied into the task (up to 25 MB): the
        assignee can't open the mailbox. Trouble with the mailbox leaves a
        note on the task, not a failed task."""
        if not self.attachment_meta:
            return
        total = 0
        try:
            with self.box_id._kh_reader() as reader:
                for index, meta in enumerate(self.attachment_meta):
                    total += meta.get("size") or 0
                    if total > TASK_ATTACHMENTS_MAX:
                        break
                    content, name, mimetype = self._kh_attachment(index, reader)
                    self.env["ir.attachment"].sudo().create({
                        "name": name, "raw": content, "mimetype": mimetype,
                        "res_model": "project.task", "res_id": task.id,
                    })
        except Exception as error:  # noqa: BLE001
            _logger.warning("kh_mail_inbox: attachments of message %s not copied: %s", self.id, error)
            task.message_post(
                body="تعذّر نسخ مرفقات الإيميل إلى المهمة. اطلبها من المدير.",
                message_type="comment", subtype_xmlid="mail.mt_note",
            )
