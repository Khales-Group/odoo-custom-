import logging
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.kh_wa_inbox.models.kh_wa_tools import mask_text

from .kh_mail_imap import ImapReader

_logger = logging.getLogger(__name__)

NEW_BATCH = 200  # new messages read per box and run (the oldest new ones first)
HISTORY_BATCH = 300  # older messages read per box and run, until the whole folder is in
FLAGS_WINDOW = 500  # the newest messages whose read/answered flags are refreshed each run
SENT_BATCH = 1000  # sent messages scanned per run for the messages they answer
BODY_LIMIT = 20000  # characters of text kept per message
SNIPPET_LENGTH = 300
DUE_MINUTES = 4  # a box read this long ago is read again (the cron runs every 5 minutes)
ERROR_RETRY_MINUTES = 15  # a box whose last try failed waits this long
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class KhMailBox(models.Model):
    """A company mailbox the dashboard shows. It is read over IMAP, read-only:
    nothing is marked as read, moved, deleted or sent."""

    _name = "kh.mail.box"
    _description = "Dashboard Mailbox"
    _order = "sequence, id"

    name = fields.Char(required=True, help="As shown on the dashboard, e.g. info@")
    email = fields.Char(required=True)
    color = fields.Integer()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    host = fields.Char(string="IMAP Server", required=True, default="mail.khales.ae")
    port = fields.Integer(string="IMAP Port", required=True, default=993)
    login = fields.Char(groups="base.group_system", help="Empty: the email address.")
    password = fields.Char(groups="base.group_system")
    folder = fields.Char(required=True, default="INBOX")
    sent_folder = fields.Char(
        default="INBOX.Sent",
        help="Read to know which messages were answered (empty: only the mail programs' 'answered' flag).",
    )
    history_since = fields.Date(help="Older messages are not imported. Empty: the whole folder.")
    # Where the reading stands (set by the fetch).
    uidvalidity = fields.Char(readonly=True, copy=False)
    max_uid = fields.Integer(readonly=True, copy=False)
    min_uid = fields.Integer(readonly=True, copy=False)
    history_done = fields.Boolean(readonly=True, copy=False)
    sent_uidvalidity = fields.Char(readonly=True, copy=False)
    sent_max_uid = fields.Integer(readonly=True, copy=False)
    server_count = fields.Integer(string="Messages in the Folder", readonly=True, copy=False)
    last_fetch_at = fields.Datetime(readonly=True, copy=False, help="Last read that worked.")
    last_try_at = fields.Datetime(readonly=True, copy=False)
    last_error = fields.Char(readonly=True, copy=False)
    message_ids = fields.One2many("kh.mail.message", "box_id")

    _email_unique = models.Constraint("UNIQUE(email)", "This mailbox is already on the dashboard.")

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    @api.model
    def _cron_fetch(self):
        """Reads one box per call, the one tried longest ago, and tells the
        cron how many are still due: Odoo calls again while some are (so
        every box gets its turn, and a history comes in back to back), then
        waits for the next run."""
        due = self._kh_due_boxes()
        if not due:
            return
        due[0]._kh_fetch()
        self._kh_progress(1, remaining=len(self._kh_due_boxes()))

    @api.model
    def _kh_due_boxes(self):
        """Boxes to read now, tried longest ago first: never tried, still
        reading their history, or not tried for a few minutes. A box whose
        last try failed (a wrong password...) waits longer: repeated failed
        logins can get the mailbox locked."""
        now = fields.Datetime.now()

        def due(box):
            if not box.last_try_at:
                return True
            if box.last_error:
                return box.last_try_at <= now - timedelta(minutes=ERROR_RETRY_MINUTES)
            return not box.history_done or box.last_try_at <= now - timedelta(minutes=DUE_MINUTES)

        boxes = self.search([]).filtered(due)
        return boxes.sorted(lambda box: (bool(box.last_try_at), box.last_try_at or now))

    def _kh_progress(self, processed=0, remaining=None):
        """Commits a cron run's progress (outside the cron, e.g. in tests: nothing)."""
        if self.env.context.get("ir_cron_progress_id"):
            self.env["ir.cron"]._commit_progress(processed, remaining=remaining)

    def action_fetch_now(self):
        self._kh_fetch()
        return True

    def _kh_reader(self):
        """A read-only IMAP session on this box (the tests use a fake one)."""
        box = self.sudo()
        return ImapReader(box.host, box.port, box.login or box.email, box.password or "")

    def _kh_fetch(self):
        for box in self:
            sudo = box.sudo()
            sudo.last_try_at = fields.Datetime.now()
            try:
                with self.env.cr.savepoint():
                    with sudo._kh_reader() as reader:
                        sudo._kh_fetch_folder(reader)
                        sudo._kh_fetch_sent(reader)
                sudo.write({"last_fetch_at": fields.Datetime.now(), "last_error": False})
            except Exception as error:  # noqa: BLE001 - one box's trouble doesn't stop the others
                _logger.warning("kh_mail_inbox: fetching %s failed: %s", box.email, error)
                sudo.write({"last_error": (str(error) or type(error).__name__)[:300]})

    def _kh_fetch_folder(self, reader):
        """New messages first, then a batch of older ones (until the whole
        folder is in), then the flags of the newest ones."""
        self.ensure_one()
        Message = self.env["kh.mail.message"].with_context(active_test=False)
        validity, exists = reader.examine(self.folder or "INBOX")
        validity = str(validity)
        if self.uidvalidity and self.uidvalidity != validity:
            # The server renumbered the folder: read it again from the start.
            Message.search([("box_id", "=", self.id), ("uidvalidity", "=", self.uidvalidity)]).active = False
            self.write({"max_uid": 0, "min_uid": 0, "history_done": False})
        max_uid, min_uid, history_done = self.max_uid, self.min_uid, self.history_done
        if max_uid:
            new = [uid for uid in reader.search(f"UID {max_uid + 1}:*") if uid > max_uid][:NEW_BATCH]
        else:
            new = reader.search("ALL")[-NEW_BATCH:]
        if new:
            self._kh_import(reader, new, validity)
            max_uid = max(max_uid, new[-1])
            min_uid = min(min_uid, new[0]) if min_uid else new[0]
        if not history_done:
            older = []
            if min_uid > 1:
                criteria = f"UID 1:{min_uid - 1}"
                if self.history_since:
                    day = self.history_since
                    criteria += f" SINCE {day.day:02d}-{MONTHS[day.month - 1]}-{day.year}"
                older = [uid for uid in reader.search(criteria) if uid < min_uid]
            batch = older[-HISTORY_BATCH:]
            if batch:
                self._kh_import(reader, batch, validity)
                min_uid = batch[0]
            history_done = len(older) <= HISTORY_BATCH
        self.write({
            "uidvalidity": validity, "server_count": exists,
            "max_uid": max_uid, "min_uid": min_uid, "history_done": history_done,
        })
        self._kh_refresh_flags(reader, validity)

    def _kh_import(self, reader, uids, validity):
        Message = self.env["kh.mail.message"].with_context(active_test=False)
        known = set(Message.search([
            ("box_id", "=", self.id), ("uidvalidity", "=", validity), ("uid", "in", list(uids)),
        ]).mapped("uid"))
        todo = [uid for uid in uids if uid not in known]
        if not todo:
            return Message
        vals_list = [self._kh_message_vals(values, validity) for values in reader.messages(todo)]
        messages = Message.create([vals for vals in vals_list if vals["uid"]])
        self._kh_mark_replied()
        return messages

    def _kh_message_vals(self, values, validity):
        body = mask_text(values["body"] or "")
        truncated = values["truncated"] or len(body) > BODY_LIMIT
        return {
            "box_id": self.id,
            "uid": values["uid"],
            "uidvalidity": validity,
            "message_id": values["message_id"][:250] or False,
            "in_reply_to": values["in_reply_to"][:250] or False,
            "subject": mask_text(values["subject"])[:500] or False,
            "from_name": values["from_name"][:250] or False,
            "from_email": values["from_email"][:250] or False,
            "to_text": values["to"][:1000] or False,
            "cc_text": values["cc"][:1000] or False,
            "date": values["date"] or fields.Datetime.now(),
            "size": values["size"],
            "body_text": body[:BODY_LIMIT] or False,
            "body_truncated": truncated,
            "snippet": " ".join(body.split())[:SNIPPET_LENGTH] or False,
            "attachment_meta": values["attachments"],
            "attachment_count": len(values["attachments"]),
            "seen": values["seen"],
            "answered": values["answered"],
            "flagged": values["flagged"],
            "bulk": values["bulk"],
        }

    def _kh_refresh_flags(self, reader, validity):
        """Read/answered flags of the newest messages follow the mailbox; one
        gone from the folder (deleted, or moved to another folder) is archived."""
        Message = self.env["kh.mail.message"]
        recent = Message.search_fetch(
            [("box_id", "=", self.id), ("uidvalidity", "=", validity)],
            ["uid", "seen", "answered", "flagged"], order="uid desc", limit=FLAGS_WINDOW,
        )
        if not recent:
            return
        flags = reader.flags(min(recent.mapped("uid")))
        gone = recent.filtered(lambda m: m.uid not in flags)
        gone.active = False
        changed = {}
        for message in recent - gone:
            current = (message.seen, message.answered, message.flagged)
            if flags[message.uid] != current:
                changed.setdefault(flags[message.uid], Message)
                changed[flags[message.uid]] |= message
        for (seen, answered, flagged), messages in changed.items():
            messages.write({"seen": seen, "answered": answered, "flagged": flagged})

    def _kh_fetch_sent(self, reader):
        """Which messages were answered: the Message-IDs the sent ones refer to."""
        if not self.sent_folder:
            return
        try:
            validity, _exists = reader.examine(self.sent_folder)
        except Exception as error:  # noqa: BLE001 - no such folder: the flags alone tell
            _logger.info("kh_mail_inbox: no sent folder %r for %s: %s", self.sent_folder, self.email, error)
            return
        validity = str(validity)
        last = self.sent_max_uid if self.sent_uidvalidity == validity else 0
        uids = [uid for uid in reader.search(f"UID {last + 1}:*" if last else "ALL") if uid > last][:SENT_BATCH]
        if uids:
            refs = {ref[:250] for ref in reader.reply_refs(uids)}
            Reply = self.env["kh.mail.reply"]
            known = set(Reply.search([("box_id", "=", self.id), ("message_id", "in", list(refs))]).mapped("message_id"))
            Reply.create([{"box_id": self.id, "message_id": ref} for ref in refs - known])
            last = uids[-1]
        self.write({"sent_uidvalidity": validity, "sent_max_uid": last})
        self._kh_mark_replied()

    def _kh_mark_replied(self):
        self.env.flush_all()
        self.env.cr.execute("""
            UPDATE kh_mail_message m SET replied = TRUE
              FROM kh_mail_reply r
             WHERE m.box_id = %s AND r.box_id = m.box_id AND r.message_id = m.message_id
               AND m.replied IS NOT TRUE
        """, [self.id])
        if self.env.cr.rowcount:
            self.env["kh.mail.message"].invalidate_model(["replied"])

    @api.model
    def _kh_sync_status(self, boxes):
        """{"at": the oldest last fetch, "minutes", "errors": [box names]} (for the dashboard)."""
        times = [box.last_fetch_at for box in boxes if box.last_fetch_at]
        oldest = min(times) if times and len(times) == len(boxes) else False
        minutes = int((fields.Datetime.now() - oldest) / timedelta(minutes=1)) if oldest else False
        return {
            "at": fields.Datetime.to_string(oldest) or False,
            "minutes": minutes,
            "errors": [box.name for box in boxes if box.last_error],
        }


class KhMailReply(models.Model):
    """A Message-ID a sent message of the box answers."""

    _name = "kh.mail.reply"
    _description = "Answered Message (from the Sent folder)"

    box_id = fields.Many2one("kh.mail.box", required=True, ondelete="cascade", index=True)
    message_id = fields.Char(required=True, index=True)

    _box_message_unique = models.Constraint("UNIQUE(box_id, message_id)", "Already known.")
