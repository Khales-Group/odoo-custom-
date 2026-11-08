import re
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.kh_mail_inbox.models import kh_mail_box


class FakeMailbox:
    """What a test mailbox holds: folders of {uid: message values}."""

    def __init__(self):
        self.folders = {"INBOX": {"validity": 7, "messages": {}}, "INBOX.Sent": {"validity": 3, "messages": {}}}
        self.base = fields.Datetime.now() - timedelta(days=2)

    def add(self, uid, folder="INBOX", **values):
        message = {
            "subject": f"Subject {uid}", "from_name": "Ahmed", "from_email": "ahmed@example.com",
            "to": "info@khales.ae", "cc": "", "date": self.base + timedelta(minutes=uid),
            "message_id": f"m{uid}@example.com", "in_reply_to": "", "size": 1000,
            "seen": False, "answered": False, "flagged": False, "body": f"Body of message {uid}",
            "truncated": False, "attachments": [], "bulk": False, "refs": [],
        }
        message.update(values)
        self.folders[folder]["messages"][uid] = message
        return message


class FakeReader:
    def __init__(self, mailbox):
        self.mailbox = mailbox
        self.folder = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def messages_in(self):
        return self.mailbox.folders[self.folder]["messages"]

    def examine(self, folder):
        if folder not in self.mailbox.folders:
            raise OSError(f"no folder {folder}")
        self.folder = folder
        return self.mailbox.folders[folder]["validity"], len(self.messages_in)

    def search(self, criteria):
        uids = sorted(self.messages_in)
        if criteria == "ALL":
            return uids
        low, high = re.match(r"UID (\d+):(\*|\d+)", criteria).groups()
        found = [uid for uid in uids if uid >= int(low) and (high == "*" or uid <= int(high))]
        if high == "*" and not found and uids:
            found = [uids[-1]]  # as IMAP does: n:* always includes the last message
        return found

    def messages(self, uids):
        return [dict(self.messages_in[uid], uid=uid) for uid in uids if uid in self.messages_in]

    def flags(self, first_uid):
        return {uid: (m["seen"], m["answered"], m["flagged"]) for uid, m in self.messages_in.items() if uid >= first_uid}

    def reply_refs(self, uids):
        return {ref for uid in uids for ref in self.messages_in[uid]["refs"]}

    def part(self, uid, path, encoding):
        return b"%PDF-1.4 test" if uid in self.messages_in else None


@tagged("post_install", "-at_install")
class TestKhMailInbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="kh_mail_test_manager", groups="kh_wa_inbox.group_kh_wa_manager")
        cls.employee = new_test_user(cls.env, login="kh_mail_test_employee", groups="base.group_user")
        cls.box = cls.env["kh.mail.box"].create({
            "name": "info@", "email": "info@test.example", "password": "secret", "host": "imap.test.example",
        })

    def setUp(self):
        super().setUp()
        self.mailbox = FakeMailbox()
        mailboxes = {self.box.email: self.mailbox}
        Box = type(self.env["kh.mail.box"])

        def reader(box):
            if box.email not in mailboxes:
                raise OSError("connection refused")
            return FakeReader(mailboxes[box.email])

        patcher = patch.object(Box, "_kh_reader", reader)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mailboxes = mailboxes

    def messages(self, **domain):
        return self.env["kh.mail.message"].with_context(active_test=False).search(
            [("box_id", "=", self.box.id)] + [(k, "=", v) for k, v in domain.items()]
        )

    def by_uid(self, uid):
        return self.messages().filtered(lambda m: m.uid == uid)

    def dashboard(self, **kwargs):
        return self.env["kh.mail.message"].with_user(self.manager).get_mail_dashboard(**kwargs)

    # ------------------------------------------------------------------

    def test_newest_first_then_the_history(self):
        for uid in range(1, 11):
            self.mailbox.add(uid)
        with patch.object(kh_mail_box, "NEW_BATCH", 3), patch.object(kh_mail_box, "HISTORY_BATCH", 4):
            self.box._kh_fetch()
            self.assertFalse(self.box.last_error)
            self.assertEqual(sorted(self.messages().mapped("uid")), [4, 5, 6, 7, 8, 9, 10])
            self.assertFalse(self.box.history_done)
            self.assertEqual((self.box.server_count, self.box.max_uid, self.box.min_uid), (10, 10, 4))
            self.box._kh_fetch()
            self.assertEqual(sorted(self.messages().mapped("uid")), list(range(1, 11)), "the history is in")
            self.assertTrue(self.box.history_done)
            self.mailbox.add(11)
            self.box._kh_fetch()
            self.assertEqual(len(self.messages()), 11, "new mail comes in, nothing twice")
        message = self.by_uid(11)
        self.assertEqual((message.subject, message.from_email, message.body_text), ("Subject 11", "ahmed@example.com", "Body of message 11"))
        self.assertTrue(self.box.last_fetch_at)

    def test_flags_follow_the_mailbox_and_gone_messages_are_archived(self):
        for uid in (1, 2, 3):
            self.mailbox.add(uid)
        self.box._kh_fetch()
        self.mailbox.folders["INBOX"]["messages"][2]["seen"] = True
        del self.mailbox.folders["INBOX"]["messages"][3]
        self.box._kh_fetch()
        self.assertTrue(self.by_uid(2).seen)
        self.assertFalse(self.by_uid(3).active, "filed elsewhere or deleted: archived, not deleted")
        self.assertTrue(self.by_uid(1).active)

    def test_sent_folder_tells_what_was_answered(self):
        for uid in range(1, 6):
            self.mailbox.add(uid)
        self.mailbox.add(1, folder="INBOX.Sent", refs=["m5@example.com", "m1@example.com"])
        with patch.object(kh_mail_box, "NEW_BATCH", 2), patch.object(kh_mail_box, "HISTORY_BATCH", 1):
            self.box._kh_fetch()
            self.assertTrue(self.by_uid(5).replied)
            self.assertFalse(self.by_uid(1), "not read yet")
            self.box._kh_fetch()
            self.box._kh_fetch()
        self.assertTrue(self.box.history_done)
        self.assertTrue(self.by_uid(1).replied, "a message read later, with the history, is matched too")
        self.assertFalse(self.by_uid(3).replied)
        self.assertEqual(self.box.sent_max_uid, 1)

    def test_renumbered_folder_is_read_again(self):
        self.mailbox.add(1)
        self.box._kh_fetch()
        self.mailbox.folders["INBOX"]["validity"] = 8
        self.box._kh_fetch()
        old, new = self.messages(uidvalidity="7"), self.messages(uidvalidity="8")
        self.assertFalse(old.active)
        self.assertEqual(len(new), 1)
        self.assertTrue(new.active)

    def test_one_box_failing_does_not_stop_the_others(self):
        other = self.env["kh.mail.box"].create({"name": "hr@", "email": "hr@test.example", "password": "x"})
        self.mailbox.add(1)
        (other | self.box)._kh_fetch()
        self.assertIn("connection refused", other.last_error)
        self.assertFalse(self.box.last_error)
        self.assertEqual(len(self.messages()), 1)

    def test_cron_takes_turns_and_spares_a_failing_box(self):
        Box = self.env["kh.mail.box"]
        other_mailbox = FakeMailbox()
        other = Box.create({"name": "hr@", "email": "hr@test.example", "password": "x"})
        broken = Box.create({"name": "ceo@", "email": "ceo@test.example", "password": "wrong"})
        self.mailboxes[other.email] = other_mailbox
        self.mailbox.add(1)
        other_mailbox.add(1)
        Box._cron_fetch()
        self.assertTrue(self.box.last_try_at)
        self.assertFalse(other.last_try_at, "one box per call")
        Box._cron_fetch()
        Box._cron_fetch()
        self.assertTrue(other.last_try_at and broken.last_try_at, "every box gets its turn")
        self.assertTrue(broken.last_error)
        self.assertFalse(Box._kh_due_boxes(), "all read, histories in, the failing box waits")
        tried = broken.last_try_at
        Box._cron_fetch()
        self.assertEqual(broken.last_try_at, tried, "no login again right after a failed one")
        self.assertEqual(len(other.message_ids), 1)

    def test_secrets_are_masked_and_passwords_kept_from_managers(self):
        self.mailbox.add(1, body="Your OTP code is 482913, do not share it.")
        self.box._kh_fetch()
        self.assertNotIn("482913", self.by_uid(1).body_text)
        with self.assertRaises(AccessError):
            self.box.with_user(self.manager).read(["password"])

    def test_dashboard(self):
        self.mailbox.add(1, bulk=True)
        self.mailbox.add(2, seen=True)
        self.mailbox.add(3, attachments=[{"path": "2", "name": "contract.pdf", "mimetype": "application/pdf", "size": 900, "encoding": "base64"}])
        self.mailbox.add(4, date=fields.Datetime.now() - timedelta(days=60), subject="Old invoice")
        self.box._kh_fetch()
        data = self.dashboard()
        box = data["boxes"][0]
        self.assertEqual(box["counts"], {"total": 4, "unread": 3, "needs_reply": 2})
        self.assertEqual([m["subject"] for m in data["messages"]], ["Subject 3", "Subject 2", "Subject 1", "Old invoice"], "newest first")
        self.assertEqual(data["filter_counts"], {"all": 4, "unread": 3, "needs_reply": 2})
        needs = self.dashboard(filter="needs_reply")["messages"]
        self.assertEqual({m["subject"] for m in needs}, {"Subject 2", "Subject 3"}, "no newsletters, nothing older than 30 days")
        self.assertEqual([m["subject"] for m in self.dashboard(search="invoice")["messages"]], ["Old invoice"])
        page = self.dashboard(limit=2)
        self.assertEqual((len(page["messages"]), page["has_more"]), (2, True))

        message = self.by_uid(3)
        detail = message.with_user(self.manager).get_mail_detail()
        self.assertEqual(detail["attachments"][0]["name"], "contract.pdf")
        self.assertEqual(detail["attachments"][0]["url"], f"/kh_mail_inbox/attachment/{message.id}/0")
        self.assertEqual(message._kh_attachment(0)[0], b"%PDF-1.4 test", "read from the mailbox when opened")

        message.with_user(self.manager).action_set_followed(True)
        self.assertEqual(self.dashboard()["boxes"][0]["counts"]["needs_reply"], 1)
        with self.assertRaises(AccessError):
            self.env["kh.mail.message"].with_user(self.employee).get_mail_dashboard()

    def test_message_to_task(self):
        self.mailbox.add(1, body="Please renew the trade licence.", attachments=[
            {"path": "2", "name": "licence.pdf", "mimetype": "application/pdf", "size": 900, "encoding": "base64"},
        ])
        self.box._kh_fetch()
        message = self.by_uid(1)
        message.with_user(self.manager).action_make_task(self.employee.id)
        task = message.task_ids
        self.assertEqual(task.user_ids, self.employee)
        self.assertEqual(task.name, "Subject 1")
        self.assertIn("Please renew the trade licence.", task.description)
        self.assertEqual(task.kh_mail_box_email, self.box.email)
        files = self.env["ir.attachment"].search([("res_model", "=", "project.task"), ("res_id", "=", task.id)])
        self.assertEqual(files.mapped("name"), ["licence.pdf"], "the attachment is copied into the task")
        self.assertEqual(message.with_user(self.manager).get_mail_detail()["task"]["user"], self.employee.name)
        task.with_user(self.employee).action_kh_wa_done()
        self.assertTrue(message.followed, "closing the task marks the message followed up")
