import base64
import logging
import time
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.kh_wa_inbox.models.kh_wa_tools import dubai_date, dubai_today, mask_text, read_last_sync

_logger = logging.getLogger(__name__)

CHAT = "test-legal@g.us"


@tagged("post_install", "-at_install")
class TestKhWaInbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login="kh_wa_test_manager", groups="kh_wa_inbox.group_kh_wa_manager")
        cls.user_a = new_test_user(cls.env, login="kh_wa_test_user_a", groups="kh_wa_inbox.group_kh_wa_user")
        cls.user_b = new_test_user(cls.env, login="kh_wa_test_user_b", groups="kh_wa_inbox.group_kh_wa_user")
        # The bot works as a manager.
        cls.Item = cls.env["kh.wa.item"].with_user(cls.manager)
        result = cls.env["kh.wa.group"].with_user(cls.manager).upsert_groups(
            [{"wa_chat_id": CHAT, "name": "Legal (test)", "category": "legal"}]
        )
        cls.group = cls.env["kh.wa.group"].browse(result["ids"])
        cls.asked = fields.Datetime.now() - timedelta(hours=3)

    def row(self, key, **values):
        return {
            "source_msg_id": key,
            "wa_chat_id": CHAT,
            "name": f"Item {key}",
            "asked_at": fields.Datetime.to_string(self.asked),
            **values,
        }

    def at(self, minutes):
        return fields.Datetime.to_string(self.asked + timedelta(minutes=minutes))

    def upsert(self, *rows):
        result = self.Item.upsert_items(list(rows))
        self.assertFalse([e for e in result["errors"] if not e["saved"]], result["errors"])
        return result

    def item(self, key):
        return self.env["kh.wa.item"].search([("source_msg_id", "=", key)])

    def day_page(self):
        return self.env["kh.wa.day"].search([("group_id", "=", self.group.id), ("date", "=", dubai_date(self.asked))])

    # ------------------------------------------------------------------

    def test_groups_upsert_is_keyed_by_chat_id(self):
        Group = self.env["kh.wa.group"].with_user(self.manager)
        again = Group.upsert_groups([{"wa_chat_id": CHAT, "name": "Legal", "color": 3}])
        self.assertEqual(again["ids"], self.group.ids)
        self.assertEqual((self.group.name, self.group.color), ("Legal", 3))
        missing_name = Group.upsert_groups([{"wa_chat_id": "new@g.us"}])
        self.assertFalse(missing_name["ids"])
        self.assertEqual(len(missing_name["errors"]), 1)

    def test_same_message_twice_gives_one_item(self):
        file = {"name": "plan.pdf", "mimetype": "application/pdf", "datas": base64.b64encode(b"%PDF-1 test").decode()}
        first = self.upsert(self.row("m1", attachments=[file]))
        second = self.upsert(self.row("m1", name="Item m1 (updated)", attachments=[file]))
        self.assertEqual(first["ids"], second["ids"])
        item = self.item("m1")
        self.assertEqual(len(item), 1)
        self.assertEqual(item.name, "Item m1 (updated)")
        self.assertEqual(len(item.attachment_ids), 1, "the same file pushed twice is kept once")

    def test_one_bad_row_does_not_fail_the_batch(self):
        result = self.Item.upsert_items([
            self.row("ok1"),
            self.row("bad", wa_chat_id="unknown@g.us"),
            self.row("ok2", kind="nonsense"),
            self.row("ok3", assignee_login="nobody-with-this-login"),
        ])
        self.assertEqual(len(result["ids"]), 2)
        self.assertEqual(
            [(e["index"], e["saved"]) for e in result["errors"]], [(1, False), (2, False), (3, True)],
        )
        self.assertTrue(self.item("ok3"))
        self.assertFalse(self.item("ok3").assignee_id)

    def test_quick_done_is_counted_not_stored(self):
        quick = self.row("q1", state="done", done_at=self.at(30))
        self.assertEqual(self.upsert(quick)["ids"], [])
        self.assertFalse(self.item("q1"))
        self.assertEqual(self.day_page().quick_done_count, 1)

        self.upsert(quick)  # the bot sends it again
        self.assertEqual(self.day_page().quick_done_count, 1, "counted once per message")

        slow = self.row("q2", state="done", done_at=self.at(90))
        self.assertEqual(len(self.upsert(slow)["ids"]), 1)
        self.assertEqual(self.item("q2").state, "done")
        self.assertEqual(self.day_page().quick_done_count, 1)

    def test_quick_done_threshold_is_a_setting(self):
        self.env["ir.config_parameter"].sudo().set_param("kh_wa_inbox.quick_done_minutes", "20")
        self.upsert(self.row("t1", state="done", done_at=self.at(30)))
        self.assertTrue(self.item("t1"), "30 minutes is over a 20-minute threshold")

    def test_upsert_days_ignores_quick_done_count(self):
        Day = self.env["kh.wa.day"].with_user(self.manager)
        self.upsert(self.row("q1", state="done", done_at=self.at(10)))
        day = fields.Date.to_string(dubai_date(self.asked))
        result = Day.upsert_days([{"date": day, "wa_chat_id": CHAT, "summary": "a\nb", "message_count": 7,
                                   "quick_done_count": 99}])
        self.assertEqual(result["ids"], self.day_page().ids)
        self.assertEqual(self.day_page().quick_done_count, 1)
        self.assertEqual(self.day_page().message_count, 7)

    def test_existing_item_done_quickly(self):
        # Untouched: removed and counted.
        self.upsert(self.row("e1"))
        self.upsert(self.row("e1", state="done", done_at=self.at(20)))
        self.assertFalse(self.item("e1"))
        self.assertEqual(self.day_page().quick_done_count, 1)

        # Someone wrote on it: closed, not removed.
        self.upsert(self.row("e2"))
        self.item("e2").with_user(self.manager).message_post(body="On it", message_type="comment")
        self.upsert(self.row("e2", state="done", done_at=self.at(20)))
        self.assertEqual(self.item("e2").state, "done")

        # A reminder was set: closed, not removed.
        self.upsert(self.row("e3"))
        self.item("e3").with_user(self.manager).action_remind("tomorrow")
        self.upsert(self.row("e3", state="done", done_at=self.at(20)))
        self.assertEqual(self.item("e3").state, "done")
        self.assertEqual(self.day_page().quick_done_count, 1)

    def test_manual_edits_are_not_overwritten(self):
        self.upsert(self.row("x1", assignee_login=self.user_a.login))
        item = self.item("x1")
        item.with_user(self.manager).write({"state": "waiting", "assignee_id": self.user_b.id, "manager_note": "Call"})
        self.assertEqual(set(item.manual_fields.split(",")), {"state", "assignee_id", "manager_note"})

        self.upsert(self.row("x1", name="Renamed", state="done", done_at=self.at(200),
                             assignee_login=self.user_a.login, manager_note="from the bot", urgent=True))
        self.assertEqual(item.state, "waiting")
        self.assertFalse(item.done_at)
        self.assertEqual(item.assignee_id, self.user_b)
        self.assertEqual(item.manager_note, "Call")
        self.assertEqual(item.name, "Renamed", "fields nobody edited still follow the bot")
        self.assertTrue(item.urgent)

    def test_otp_and_card_numbers_are_masked(self):
        self.upsert(self.row("otp", source_text="OTP 482913",
                             context_text="رمز التحقق ٤٨٢٩١٣\nالبطاقة 4111 1111 1111 1234"))
        item = self.item("otp")
        self.assertEqual(item.source_text, "OTP ••••")
        self.assertEqual(item.context_text, "رمز التحقق ••••\nالبطاقة •••• 1234")
        item.with_user(self.manager).write({"done_note": "paid by 4111111111111234"})
        self.assertEqual(item.done_note, "paid by •••• 1234")
        # Dates, times, amounts, phone numbers and IBANs stay readable.
        for text in ("visit 2026-11-02 at 10:45", "AED 1,250.00", "+971501234567",
                     "AE07 0331 2345 6789 0123 456", "050 123 4567"):
            self.assertEqual(mask_text(text), text)

    def test_user_sees_only_their_items(self):
        self.upsert(
            self.row("a1", assignee_login=self.user_a.login, requester_phone="+971500000001"),
            self.row("b1", assignee_login=self.user_b.login),
            self.row("c1", requester_login=self.user_b.login),
        )
        a1, b1, c1 = self.item("a1"), self.item("b1"), self.item("c1")
        as_a = self.env["kh.wa.item"].with_user(self.user_a)
        as_b = self.env["kh.wa.item"].with_user(self.user_b)
        keys = ["a1", "b1", "c1"]
        self.assertEqual(as_a.search([("source_msg_id", "in", keys)]), a1)
        self.assertEqual(as_b.search([("source_msg_id", "in", keys)]), b1 | c1, "assigned to b, or asked by b")
        with self.assertRaises(AccessError):
            b1.with_user(self.user_a).read(["name"])
        with self.assertRaises(AccessError):
            a1.with_user(self.user_a).read(["requester_phone"])
        with self.assertRaises(AccessError):
            a1.with_user(self.user_a).unlink()
        with self.assertRaises(AccessError):
            self.env["kh.wa.day"].with_user(self.user_a).search([])

        with self.assertRaises(AccessError):
            as_a.get_notebook(group_id=self.group.id)

    def test_notes_are_private_even_for_managers(self):
        memo = self.env["kh.wa.memo"].with_user(self.manager).create({"text": "mine"})
        other_manager = new_test_user(self.env, login="kh_wa_test_manager_2", groups="kh_wa_inbox.group_kh_wa_manager")
        self.assertFalse(self.env["kh.wa.memo"].with_user(other_manager).search([("id", "=", memo.id)]))

    def test_requester_found_by_phone(self):
        self.user_a.partner_id.phone = "+971 50 000 7319"
        self.upsert(self.row("p1", requester_phone="00971500007319"))
        self.assertEqual(self.item("p1").requester_user_id, self.user_a)
        self.user_b.partner_id.phone = "050 000 7319"
        self.upsert(self.row("p2", requester_phone="0500007319"))
        self.assertFalse(self.item("p2").requester_user_id, "two users with this number: left empty")

    def test_get_notebook_returns_all_sections(self):
        today = dubai_today()
        now = fields.Datetime.to_string(fields.Datetime.now())
        self.upsert(
            self.row("n1", needs_manager=True, due_date=str(today - timedelta(days=2))),
            self.row("n2", urgent=True),
            self.row("n3", due_date=str(today - timedelta(days=1))),
            self.row("n4", kind="deadline", due_date=str(today + timedelta(days=2))),
            self.row("n5", state="done", done_at=now, done_note="Sent",
                     attachments=[{"name": "a.txt", "mimetype": "text/plain", "datas": base64.b64encode(b"x").decode()}]),
        )
        self.env["kh.wa.day"].with_user(self.manager).upsert_days(
            [{"date": str(today), "wa_chat_id": CHAT, "summary": "line 1\nline 2", "message_count": 12}]
        )
        self.env["kh.wa.memo"].with_user(self.manager).create({"text": "Call the lawyer"})

        data = self.Item.get_notebook(group_id=self.group.id)
        sections = data["sections"]
        self.assertEqual(set(sections), {"needs_manager", "urgent", "open", "upcoming", "day_summary", "closed", "memos"})
        self.assertEqual([p["id"] for p in sections["needs_manager"]], self.item("n1").ids)
        self.assertEqual([p["id"] for p in sections["urgent"]], self.item("n2").ids)
        self.assertEqual([p["id"] for g in sections["open"] for p in g["items"]], self.item("n3").ids)
        self.assertEqual([p["id"] for p in sections["upcoming"]], self.item("n4").ids)
        self.assertEqual(sections["day_summary"][0]["lines"], ["line 1", "line 2"])
        self.assertEqual([p["done_note"] for p in sections["closed"]], ["Sent"])
        self.assertEqual([m["text"] for m in sections["memos"]], ["Call the lawyer"])
        # Counters count every matching item, wherever it is shown.
        self.assertEqual(data["counters"], {"needs_manager": 1, "urgent": 1, "overdue": 2, "open": 4})
        # Attachments: metadata only.
        self.assertEqual(set(sections["closed"][0]["attachments"][0]), {"id", "name", "mimetype", "url"})

    def test_get_notebook_with_5000_items_is_fast(self):
        Item = self.env["kh.wa.item"].with_context(tracking_disable=True, mail_create_nolog=True)
        now = fields.Datetime.now()
        today = dubai_today()
        vals = []
        for i in range(5000):
            closed = i % 10 != 0  # 500 open, 4500 closed over the last months
            vals.append({
                "name": f"Perf item {i}",
                "group_id": self.group.id,
                "source_msg_id": f"perf-{i}",
                "asked_at": now - timedelta(hours=i),
                "state": "done" if closed else "open",
                "done_at": now - timedelta(hours=i - 1) if closed else False,
                "urgent": i % 7 == 0,
                "needs_manager": i % 11 == 0,
                "due_date": today + timedelta(days=i % 20 - 10),
                "source_text": "نص الرسالة الأصلية " * 10,
                "context_text": "سياق " * 30,
            })
        Item.create(vals)
        self.env.flush_all()
        self.env.invalidate_all()

        for method in ("get_notebook", "get_dashboard"):
            self.env.invalidate_all()
            start = time.perf_counter()
            data = getattr(self.Item, method)()
            elapsed = time.perf_counter() - start
            _logger.info("%s with 5000 items: %.3f s", method, elapsed)
            self.assertGreaterEqual(data["counters"]["open"], 500)
            self.assertLess(elapsed, 1.0, method)

    # ------------------------------------------------------------------
    # The follow-up dashboard
    # ------------------------------------------------------------------

    def test_get_dashboard(self):
        now = fields.Datetime.now()
        today = dubai_today()
        week_start = today - timedelta(days=today.weekday())
        self.env["kh.wa.group"].with_user(self.manager).upsert_groups([
            {"wa_chat_id": CHAT, "last_message_at": fields.Datetime.to_string(now)},
            {"wa_chat_id": "test-calm@g.us", "name": "Calm (test)", "sequence": 1},
            {"wa_chat_id": "test-old@g.us", "name": "Old (test)", "sequence": 2},
            {"wa_chat_id": "test-quiet@g.us", "name": "Quiet (test)", "sequence": 3,
             "last_message_at": "2020-01-01 00:00:00"},
        ])
        self.upsert(
            self.row("d1", needs_manager=True),
            self.row("d2", urgent=True),
            self.row("d3"), self.row("d4"), self.row("d5"),
            self.row("d6", state="done", done_at=fields.Datetime.to_string(now)),
            self.row("c1", wa_chat_id="test-calm@g.us"),
            self.row("o1", wa_chat_id="test-old@g.us",
                     asked_at=fields.Datetime.to_string(now - timedelta(days=5))),
        )
        self.env["kh.wa.day"].with_user(self.manager).upsert_days(
            [{"date": str(today), "wa_chat_id": CHAT, "summary": "first line\nsecond", "message_count": 140}]
        )

        data = self.Item.get_dashboard()
        boxes = {box["group_id"]: box for box in data["boxes"]}
        ids = {name: self.env["kh.wa.group"].search([("wa_chat_id", "=", chat)]).id for name, chat in
               (("legal", CHAT), ("calm", "test-calm@g.us"), ("old", "test-old@g.us"), ("quiet", "test-quiet@g.us"))}
        self.assertEqual(
            [boxes[ids[n]]["status"] for n in ("legal", "old", "calm", "quiet")], ["red", "amber", "green", "green"],
        )
        self.assertTrue(boxes[ids["quiet"]]["compact"], "nothing open, no messages this week: one line")
        order = [box["group_id"] for box in data["boxes"]]
        self.assertLess(order.index(ids["legal"]), order.index(ids["old"]), "needs attention first")
        self.assertLess(order.index(ids["old"]), order.index(ids["calm"]))
        compact = [box["compact"] for box in data["boxes"]]
        self.assertEqual(compact, sorted(compact), "one-line boxes at the end")

        legal = boxes[ids["legal"]]
        self.assertEqual(legal["counts"], {"open": 5, "urgent": 1, "needs_manager": 1, "overdue": 0})
        self.assertEqual([t["id"] for t in legal["top"]][:2], [self.item("d1").id, self.item("d2").id])
        self.assertEqual(legal["more"], 2)
        self.assertTrue(legal["last_message_at"])
        self.assertEqual((legal["day"]["message_count"], legal["day"]["first_line"]), (140, "first line"))
        opened_this_week = dubai_date(self.asked) >= week_start
        self.assertEqual(legal["week"], {"opened": 6 if opened_this_week else 0, "closed": 1})

        picked = self.Item.get_dashboard(group_id=self.group.id)
        kpis = picked["kpis"]
        self.assertEqual(
            [kpis[k]["value"] for k in ("needs_manager", "urgent", "overdue", "open", "closed_week")], [1, 1, 0, 5, 1],
        )
        self.assertTrue(kpis["needs_manager"]["oldest"])
        self.assertEqual(kpis["avg_close"]["duration"], {"value": "3", "unit": "ساعات"})
        self.assertEqual([box["group_id"] for box in picked["boxes"] if box["selected"]], self.group.ids)
        self.assertEqual(len(picked["boxes"]), len(data["boxes"]), "every group keeps its card")
        self.assertEqual(picked["group_days"][0]["lines"], ["first line", "second"])
        self.assertEqual(len(picked["closed_week"]), 1)
        self.assertEqual(set(picked["sections"]), set(self.Item.get_notebook()["sections"]))

        self.assertEqual(picked["last_sync"]["level"], "ok")
        self.assertTrue(read_last_sync(self.env))

    def test_dashboard_is_for_the_manager_only(self):
        self.upsert(self.row("u1", assignee_login=self.user_a.login, urgent=True))
        for user in (self.user_a, new_test_user(self.env, login="kh_wa_test_plain", groups="base.group_user")):
            with self.assertRaises(AccessError):
                self.env["kh.wa.item"].with_user(user).get_dashboard()
        self.assertTrue(self.Item.get_dashboard()["boxes"])

    # ------------------------------------------------------------------
    # The assignee's follow-up task
    # ------------------------------------------------------------------

    def payload(self, item):
        data = self.Item.get_notebook()
        sections = data["sections"]
        found = [p for s in sections["open"] for p in s["items"]] + sections["needs_manager"] + sections["urgent"]
        found += sections["upcoming"] + sections["closed"]
        return next(p for p in found if p["id"] == item.id)

    def test_assignee_gets_a_follow_up_task(self):
        # Project rights, no notebook access.
        nizar = new_test_user(self.env, login="kh_wa_test_nizar", groups="base.group_user,project.group_project_user")
        due = dubai_today() + timedelta(days=3)
        self.upsert(self.row("task1", source_text="please send the contract", due_date=str(due)))
        item = self.item("task1")
        item.with_user(self.manager).write({"assignee_id": nizar.id})

        task = item.task_id
        self.assertEqual(task.user_ids, nizar)
        self.assertEqual(task.name, item.name)
        self.assertEqual(task.project_id, self.env.ref("kh_wa_inbox.project_kh_wa_followups"), "no project: the follow-ups one")
        self.assertIn("please send the contract", task.description)
        self.assertEqual(dubai_date(task.date_deadline), due)
        self.assertNotIn(nizar.partner_id, item.message_partner_ids, "the assignee is not made a follower of the item")
        self.assertTrue(self.env["mail.message"].search_count([
            ("model", "=", "project.task"), ("res_id", "=", task.id),
            ("message_type", "=", "user_notification"), ("partner_ids", "in", nizar.partner_id.ids),
        ]), "he gets Odoo's \"assigned to you\" message")
        with self.assertRaises(AccessError):
            item.with_user(nizar).read(["name"])
        # His task opens for him (the To-Do's link didn't).
        values = task.with_user(nizar).read(["name", "kh_wa_group_name", "kh_wa_linked_name"])[0]
        self.assertEqual(values["kh_wa_group_name"], self.group.name)
        self.assertEqual(self.payload(item)["task"]["user"], nizar.name)

        # He moves the deadline: the item follows.
        moved = due + timedelta(days=2)
        task.with_user(nizar).write({"date_deadline": fields.Datetime.to_datetime(f"{moved} 10:00:00")})
        self.assertEqual(item.due_date, moved)

        # He writes what he did and closes the task: the item closes with it.
        task.with_user(nizar).message_post(body="أرسلت العقد", message_type="comment", subtype_xmlid="mail.mt_comment")
        task.with_user(nizar).write({"state": "1_done"})
        self.assertEqual(item.state, "done")
        self.assertEqual(item.done_note, "أرسلت العقد")
        self.assertIn("state", item.manual_fields, "the bot won't reopen it")

        # Reopened by him: the item is open again.
        task.with_user(nizar).write({"state": "01_in_progress"})
        self.assertEqual(item.state, "open")

    def test_done_button_without_project_rights(self):
        plain = new_test_user(self.env, login="kh_wa_test_plain_task", groups="base.group_user")
        self.upsert(self.row("task5"))
        item = self.item("task5")
        item.with_user(self.manager).write({"assignee_id": plain.id})
        task = item.task_id.with_user(plain)
        task.message_post(body="تم التسليم", message_type="comment", subtype_xmlid="mail.mt_comment")
        with self.assertRaises(AccessError):
            task.write({"state": "1_done"})
        task.action_kh_wa_done()
        self.assertEqual(item.state, "done")
        self.assertEqual(item.done_note, "تم التسليم")
        outsider = new_test_user(self.env, login="kh_wa_test_outsider", groups="base.group_user,project.group_project_user")
        item.with_user(self.manager).action_reopen()
        with self.assertRaises((AccessError, UserError)):
            item.task_id.with_user(outsider).action_kh_wa_done()

    def test_follow_up_task_follows_the_item(self):
        first_user = new_test_user(self.env, login="kh_wa_test_first", groups="base.group_user")
        second_user = new_test_user(self.env, login="kh_wa_test_second", groups="base.group_user")
        self.upsert(self.row("task2"))
        item = self.item("task2")
        as_manager = item.with_user(self.manager)

        as_manager.write({"assignee_id": first_user.id})
        task = item.task_id
        self.assertFalse(task.date_deadline, "no due date: no deadline")
        as_manager.write({"assignee_id": second_user.id})
        self.assertEqual(item.task_id, task, "handed over: the same task")
        self.assertEqual(task.user_ids, second_user)

        as_manager.write({"due_date": dubai_today() + timedelta(days=9)})
        self.assertEqual(dubai_date(task.date_deadline), item.due_date)

        as_manager.action_done(note="done by the manager")
        self.assertEqual(task.state, "1_done")
        self.assertTrue(any("done by the manager" in (m.body or "") for m in task.message_ids), "the assignee is told why")

        as_manager.action_reopen()
        self.assertEqual(task.state, "01_in_progress", "reopened: the task too")
        self.assertEqual(task.user_ids, second_user)

        as_manager.write({"assignee_id": self.manager.id})
        self.assertEqual(task.state, "1_canceled", "taken back by a manager: the task is closed")
        self.assertEqual(len(item.task_ids), 1)

    def test_cancelled_task_goes_back_to_the_manager(self):
        user = new_test_user(self.env, login="kh_wa_test_cancel", groups="base.group_user,project.group_project_user")
        self.upsert(self.row("task6", assignee_login=user.login))
        item = self.item("task6")
        item.task_id.with_user(user).write({"state": "1_canceled"})
        self.assertEqual(item.state, "open")
        self.assertTrue(item.needs_manager, "it waits for the manager's decision")

    def test_follow_ups_project_is_made_once_and_kept(self):
        self.upsert(self.row("task7", assignee_login=self.user_b.login), self.row("task8", assignee_login=self.user_b.login))
        project = self.item("task7").task_id.project_id
        self.assertEqual(self.item("task8").task_id.project_id, project, "one follow-ups project")
        self.assertEqual(project.privacy_visibility, "followers", "private: assignees and project managers only")
        xmlid = self.env["ir.model.data"].search([("module", "=", "kh_wa_inbox"), ("name", "=", "project_kh_wa_followups")])
        self.assertEqual((xmlid.res_id, xmlid.noupdate), (project.id, True), "a module update won't delete it")

    def test_cron_sends_the_missing_tasks(self):
        self.upsert(self.row("task9", assignee_login=self.user_b.login))
        item = self.item("task9")
        item.task_id.unlink()
        self.assertFalse(item.task_id)
        self.env["kh.wa.item"]._cron_send_missing_tasks()
        self.assertEqual(item.task_id.user_ids, self.user_b)
        self.assertTrue(self.env.ref("kh_wa_inbox.ir_cron_kh_wa_send_tasks").active)
        self.env["kh.wa.item"]._cron_send_missing_tasks()
        self.assertEqual(len(item.task_ids), 1, "run again: nothing more")

    def test_no_task_for_a_notebook_manager(self):
        self.upsert(self.row("task4"))
        item = self.item("task4")
        item.with_user(self.manager).write({"assignee_id": self.manager.id})
        self.assertFalse(item.task_ids, "managers follow their items on the dashboard")

    def test_bot_assignment_also_sends_the_task(self):
        self.upsert(self.row("task3", assignee_login=self.user_b.login))
        task = self.item("task3").task_id
        self.assertEqual(task.user_ids, self.user_b)
        self.assertTrue(self.env["mail.message"].search_count([
            ("model", "=", "project.task"), ("res_id", "=", task.id), ("message_type", "=", "user_notification"),
        ]), "the bot's quiet mail flags don't silence the assignment")
        self.upsert(self.row("task3", name="renamed"))
        self.assertEqual(len(self.item("task3").task_ids), 1, "a later upsert doesn't add another one")
        self.assertEqual(task.name, "renamed")

        # The group answered: the bot closes the item, the task closes too.
        self.upsert(self.row("task3", state="done", done_at=self.at(120), done_note="sent in the group"))
        self.assertEqual(task.state, "1_done")

    def test_linked_record_gets_the_task(self):
        project = self.env["project.project"].create({"name": "KH WA Test Project"})
        parent = self.env["project.task"].create({"name": "KH WA parent", "project_id": project.id})
        self.upsert(self.row(
            "link1", assignee_login=self.user_b.login, linked_ref={"model": "project.project", "name": "kh wa test project"},
        ))
        item = self.item("link1")
        self.assertEqual(item.linked_ref, project, "the bot links by name")
        self.assertEqual(item.task_id.project_id, project, "the task goes into the linked project")
        self.assertTrue(
            any("فتح المهمة" in (m.body or "") for m in project.message_ids), "the project shows the follow-up and its task",
        )
        self.assertEqual(self.payload(item)["linked"]["label"], "Project")

        # Linked to a task later: a task still in the follow-ups project becomes its sub-task.
        self.upsert(self.row("link2", assignee_login=self.user_b.login))
        item2 = self.item("link2")
        item2.with_user(self.manager).write({"linked_ref": f"project.task,{parent.id}"})
        self.assertEqual(item2.task_id.project_id, project)
        self.assertEqual(item2.task_id.parent_id, parent)
        self.assertIn("linked_ref", item2.manual_fields, "the bot won't change a link a person made")

        missing = self.Item.upsert_items([self.row("link3", linked_ref={"model": "project.project", "name": "nothing like it"})])
        self.assertTrue(missing["errors"] and missing["errors"][0]["saved"], "saved, with a warning")

    # ------------------------------------------------------------------
    # «بانتظار قرارك» as the decision maker's To-Dos
    # ------------------------------------------------------------------

    def set_decision_maker(self, user):
        self.env["ir.config_parameter"].sudo().set_param("kh_wa_inbox.decision_user_id", str(user.id) if user else "")

    def test_decision_todo_follows_the_wait(self):
        self.set_decision_maker(self.manager)
        self.upsert(self.row("dec1", needs_manager=True))
        item = self.item("dec1")
        todo = item.kh_decision_activity_id
        self.assertEqual(todo.user_id, self.manager)
        self.assertTrue(todo.summary.startswith("بانتظار قرارك"))
        self.assertTrue(item._is_untouched(), "the decision To-Do is the item's own, not someone's touch")

        # He decides: marks it done. The item no longer waits for him.
        todo.with_user(self.manager).action_feedback(feedback="موافق")
        self.assertFalse(item.needs_manager)
        self.assertFalse(item.kh_decision_activity_id)
        self.assertIn("needs_manager", item.manual_fields, "the bot won't flag it again")

        # Flagged again by a person, then closed: the To-Do goes with it.
        item.with_user(self.manager).write({"needs_manager": True})
        self.assertTrue(item.kh_decision_activity_id)
        item.with_user(self.manager).action_done(note="ok")
        self.assertFalse(item.kh_decision_activity_id)
        self.assertFalse(item.activity_ids.filtered(lambda a: (a.summary or "").startswith("بانتظار قرارك")))

    def test_assigning_someone_is_the_decision(self):
        self.set_decision_maker(self.manager)
        self.upsert(self.row("dec3", needs_manager=True))
        item = self.item("dec3")
        self.assertTrue(item.kh_decision_activity_id)

        # The bot naming an assignee doesn't decide for the manager.
        self.upsert(self.row("dec3", needs_manager=True, assignee_login=self.user_a.login))
        self.assertTrue(item.needs_manager)
        self.assertTrue(item.kh_decision_activity_id)

        # The manager hands it to someone: decided, and the task goes out.
        item.with_user(self.manager).write({"assignee_id": self.user_b.id})
        self.assertFalse(item.needs_manager)
        self.assertFalse(item.kh_decision_activity_id)
        self.assertEqual(item.task_id.user_ids, self.user_b)

    def test_decision_todos_wait_for_a_decision_maker(self):
        self.set_decision_maker(False)
        self.upsert(self.row("dec2", needs_manager=True))
        self.assertFalse(self.item("dec2").kh_decision_activity_id)
        self.set_decision_maker(self.manager)
        self.env["kh.wa.item"]._cron_decision_activities()
        self.assertEqual(self.item("dec2").kh_decision_activity_id.user_id, self.manager, "the cron catches up")

    def test_approvals_waiting_for_me(self):
        if "kh.approval.request" not in self.env:
            self.skipTest("kh_approvals is not installed")
        Request, Line = self.env["kh.approval.request"], self.env["kh.approval.line"]
        mine = Request.create({"title": "Buy cement (test)", "amount": 1500})
        mine.write({"state": "in_review"})
        Line.create({"request_id": mine.id, "approver_id": self.manager.id, "state": "pending"})
        other = Request.create({"title": "Not mine (test)"})
        other.write({"state": "in_review"})
        Line.create({"request_id": other.id, "approver_id": self.user_a.id, "state": "pending"})

        approvals = self.Item.get_dashboard()["approvals"]
        self.assertEqual([a["request_id"] for a in approvals], [mine.id], "only what waits for this user")
        self.assertEqual((approvals[0]["name"], approvals[0]["id"]), ("Buy cement (test)", f"approval-{mine.id}"))

        self.set_decision_maker(self.manager)
        self.env["kh.wa.item"]._cron_decision_activities()
        self.env["kh.wa.item"]._cron_decision_activities()
        todos = mine.activity_ids.filtered(lambda a: a.user_id == self.manager)
        self.assertEqual(len(todos), 1, "one To-Do, not one per run")
        self.assertTrue(todos.summary.startswith("بانتظار موافقتك"))

        mine.approval_line_ids.write({"state": "approved"})
        self.env["kh.wa.item"]._cron_decision_activities()
        self.assertFalse(mine.activity_ids.filtered(lambda a: a.user_id == self.manager), "no longer waiting: gone")

    def test_item_views_open_for_a_manager_who_isnt_an_administrator(self):
        # Majed (no administrator rights) got an error opening an item: the
        # attachments field made the views search every attachment.
        self.assertTrue(self.Item._fields["attachment_ids"].bypass_search_access)
        views = self.Item.get_views([(False, "form"), (False, "list"), (False, "search")])
        self.assertIn("attachment_ids", views["models"]["kh.wa.item"]["fields"])

    def test_archived_group_with_open_items_keeps_its_card(self):
        self.upsert(self.row("a1"), self.row("a2", urgent=True))
        self.group.active = False
        data = self.Item.get_dashboard()
        box = next((b for b in data["boxes"] if b["group_id"] == self.group.id), None)
        self.assertTrue(box, "its open items still need a home")
        self.assertEqual(box["counts"]["open"], 2)
        self.assertEqual(sum(b["counts"]["open"] for b in data["boxes"]), data["kpis"]["open"]["value"])

    def test_last_message_only_moves_forward(self):
        Group = self.env["kh.wa.group"].with_user(self.manager)
        Group.upsert_groups([{"wa_chat_id": CHAT, "last_message_at": "2026-11-02 08:00:00"}])
        Group.upsert_groups([{"wa_chat_id": CHAT, "last_message_at": "2026-11-01 08:00:00"}])
        self.assertEqual(fields.Datetime.to_string(self.group.last_message_at), "2026-11-02 08:00:00")
