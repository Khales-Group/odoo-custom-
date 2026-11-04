#!/usr/bin/env python3
"""Automatic test of the website calculator -> Odoo connection, done the
same way the website does it (XML-RPC, as the website's integration user).

    python scripts/staging_check.py               # staging: full test
    python scripts/staging_check.py --install     # also install kh_crm_calculator first if missing
    python scripts/staging_check.py --production  # production: read-only checks, creates nothing

With --wa-inbox the same is done for kh_wa_inbox (مفكرة القروبات), as the
WhatsApp bot's user (wa_login / wa_key):

    python scripts/staging_check.py --wa-inbox               # staging: full API test
    python scripts/staging_check.py --wa-inbox --read-only   # staging: only checks that write nothing
    python scripts/staging_check.py --wa-inbox --install     # also install kh_wa_inbox first if missing
    python scripts/staging_check.py --wa-inbox --production  # production: read-only checks

Connection details are read from %USERPROFILE%\\.khales_odoo_test.ini (a
template is written there on first run). API keys: Odoo > avatar > My
Preferences > Account Security > New API Key. The keys never leave that file.

On staging one test lead is created (reference K-TEST-..., name starting
with [TEST]) and removed at the end: deleted when admin_key is filled in,
otherwise archived (the integration user can't delete leads). --wa-inbox
creates one [TEST] group with a few items and deletes all of it at the end.
"""
import argparse
import base64
import configparser
import sys
import time
import xmlrpc.client
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG = Path.home() / ".khales_odoo_test.ini"
TEMPLATE = """\
# Filled in once, used by scripts/staging_check.py. Keep this file private.
[staging]
url = https://YOUR-STAGING-BUILD.dev.odoo.com
db = YOUR-STAGING-DATABASE
# The website's integration user (same login/API key the website uses).
api_login =
api_key =
# Optional: an administrator, to delete the test lead (otherwise it's
# archived) and to install the module with --install.
admin_login =
admin_key =
# The WhatsApp bot's user, in "مفكرة القروبات / المدير"; used by --wa-inbox.
wa_login =
wa_key =

[production]
url = https://YOUR-PRODUCTION-URL
db = YOUR-PRODUCTION-DATABASE
api_login =
api_key =
admin_login =
admin_key =
wa_login =
wa_key =
"""

CALC_FIELDS = {
    "reference": "char", "version": "char", "source": "char", "request_type": "char",
    "country": "char", "city": "char", "market_mode": "char", "market_confidence": "char",
    "pricing_source_date": "char", "anchor_date": "char", "input_mode": "char",
    "built_area_sqm": "float", "budget": "float", "currency": "char", "finish_level": "char",
    "result_low": "float", "result_expected": "float", "result_high": "float",
    "area_conservative_sqm": "float", "area_reference_sqm": "float", "area_max_sqm": "float",
    "special_items": "char", "land_status": "char", "start_timing": "char",
    "has_plan_or_quote": "boolean", "review_goal": "char", "preferred_contact": "char",
    "contact_consent": "boolean", "marketing_consent": "boolean", "lead_score": "integer",
    "floors": "char", "family_plan": "text", "lang": "char", "created_at": "char",
}
CALC_FIELDS = {"x_calc_" + k: v for k, v in CALC_FIELDS.items()}
CALC_TAGS = ["Calculator v2", "Design request", "Budget review"]
CALC_SOURCE = "Website Calculator v2"
FOLLOWER_PARTNERS = [9, 23]


class Report:
    def __init__(self):
        self.passed = self.failed = 0

    def check(self, label, ok, detail=""):
        self.passed += bool(ok)
        self.failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail and not ok else ""))
        return ok


class Odoo:
    def __init__(self, url, db, login, key):
        self.url, self.db, self.key = url.rstrip("/"), db, key
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self.uid = common.authenticate(db, login, key, {})
        if not self.uid:
            raise RuntimeError(f"login failed for {login}")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)

    def call(self, model, method, *args, **kwargs):
        return self.models.execute_kw(self.db, self.uid, self.key, model, method, list(args), kwargs)


def connect(cfg, who):
    login, key = cfg.get(f"{who}_login", "").strip(), cfg.get(f"{who}_key", "").strip()
    return Odoo(cfg["url"], cfg["db"], login, key) if login and key else None


def install_module(admin, name="kh_crm_calculator"):
    mod = admin.call("ir.module.module", "search_read", [("name", "=", name)], fields=["state"])
    if mod and mod[0]["state"] == "installed":
        return
    print(f"Installing {name} ...")
    admin.call("ir.module.module", "update_list")
    mod_id = admin.call("ir.module.module", "search", [("name", "=", name)])
    if not mod_id:
        raise RuntimeError(f"{name} not found on the server - is it deployed?")
    admin.call("ir.module.module", "button_immediate_install", mod_id)


def check_setup(api, report):
    print("\n== Setup (what the website relies on)")
    fields = api.call("crm.lead", "fields_get", [], attributes=["type", "required"])
    wrong = {n: fields.get(n, {}).get("type") for n, t in CALC_FIELDS.items() if fields.get(n, {}).get("type") != t}
    report.check(f"fields_get: all {len(CALC_FIELDS)} x_calc_* fields with the right type", not wrong,
                 f"{wrong} (is kh_crm_calculator installed?)")
    required = [n for n in CALC_FIELDS if fields.get(n, {}).get("required")]
    report.check("none of them is required", not required, str(required))
    for name in CALC_TAGS:
        n = api.call("crm.tag", "search_count", [("name", "=ilike", name)])
        report.check(f"tag '{name}' exists once", n == 1, f"found {n}")
    n = api.call("utm.source", "search_count", [("name", "=ilike", CALC_SOURCE)])
    report.check(f"source '{CALC_SOURCE}' exists once", n == 1, f"found {n}")
    count = api.call("crm.lead", "search_count", [("x_calc_reference", "!=", False)])
    report.check("search_count for the public counter", isinstance(count, int), str(count))
    views = api.call("crm.lead", "get_views", [[False, "form"], [False, "search"]])["views"]
    report.check("lead form has the Calculator page", 'name="kh_calculator"' in views["form"]["arch"])
    report.check("lead search has the calculator filters", 'name="kh_calc_leads"' in views["search"]["arch"])


def simulate_website(api, admin, report):
    print("\n== Website flow (test lead, as the integration user)")
    ref = f"K-TEST-{int(time.time())}"
    lead_id = None
    try:
        tag_ids = []
        for name in ("Calculator v2", "Design request"):
            found = api.call("crm.tag", "search", [("name", "=", name)], limit=1)
            tag_ids += found or [api.call("crm.tag", "create", {"name": name})]
        source = api.call("utm.source", "search", [("name", "=", CALC_SOURCE)], limit=1)
        source_id = source[0] if source else api.call("utm.source", "create", {"name": CALC_SOURCE})
        report.check("search/create crm.tag and utm.source", len(tag_ids) == 2 and bool(source_id))
        values = {
            "x_calc_reference": ref, "x_calc_version": "v2.0", "x_calc_source": "website_calculator_v2",
            "x_calc_request_type": "design", "x_calc_country": "AE", "x_calc_city": "ae_dubai",
            "x_calc_market_mode": "direct_city", "x_calc_market_confidence": "medium",
            "x_calc_pricing_source_date": "2026-10-01", "x_calc_anchor_date": "2026-10-01",
            "x_calc_input_mode": "area", "x_calc_built_area_sqm": 450.5, "x_calc_budget": 2500000.0,
            "x_calc_currency": "AED", "x_calc_finish_level": "family", "x_calc_result_low": 2100000.0,
            "x_calc_result_expected": 2400000.0, "x_calc_result_high": 2800000.0,
            "x_calc_area_conservative_sqm": 400.0, "x_calc_area_reference_sqm": 450.0,
            "x_calc_area_max_sqm": 520.0, "x_calc_special_items": "pool, basement",
            "x_calc_land_status": "owned", "x_calc_start_timing": "within_3_months",
            "x_calc_has_plan_or_quote": True, "x_calc_review_goal": "design_request",
            "x_calc_preferred_contact": "whatsapp", "x_calc_contact_consent": True,
            "x_calc_marketing_consent": False, "x_calc_lead_score": 3, "x_calc_floors": "2",
            "x_calc_family_plan": "Parents + 4 kids\nMaid room\nMajlis", "x_calc_lang": "en",
            "x_calc_created_at": "2026-10-26T10:00:00Z",
        }
        lead_id = api.call("crm.lead", "create", {
            "name": f"[TEST] Calculator v2 - Design request - Dubai - {ref}",
            "contact_name": "Automatic test - please ignore", "email_from": "test@example.com",
            "phone": "+971500000000", "description": "Automatic test<br>Please ignore",
            "priority": "3", "source_id": source_id, "tag_ids": [(6, 0, tag_ids)], **values,
        })
        report.check("create crm.lead with every x_calc_* field", bool(lead_id))
        api.call("crm.lead", "message_subscribe", [lead_id], partner_ids=FOLLOWER_PARTNERS)
        followers = api.call("crm.lead", "read", [lead_id], fields=["message_partner_ids"])[0]["message_partner_ids"]
        report.check("message_subscribe partners 9 and 23", set(FOLLOWER_PARTNERS) <= set(followers), str(followers))
        found = api.call("crm.lead", "search", [("x_calc_reference", "=", ref), ("active", "in", [True, False])])
        report.check("search including archived finds it", found == [lead_id], str(found))
        back = api.call("crm.lead", "read", [lead_id], fields=list(values) + ["source_id", "tag_ids"])[0]
        diff = {k: (v, back[k]) for k, v in values.items() if back[k] != v}
        report.check("every x_calc_* value reads back unchanged", not diff, str(diff))
        report.check("source and tags are set", back["source_id"] and back["source_id"][0] == source_id
                     and set(back["tag_ids"]) == set(tag_ids))

        # A salesperson taking the lead over must not hide it from the website.
        other = api.call("res.users", "search", [("share", "=", False), ("id", "!=", api.uid)], limit=1)
        if other:
            api.call("crm.lead", "write", [lead_id], {"user_id": other[0]})
            found = api.call("crm.lead", "search", [("x_calc_reference", "=", ref), ("active", "in", [True, False])])
            report.check("still found after it's reassigned to a salesperson", found == [lead_id])
    except xmlrpc.client.Fault as e:
        report.check("website flow", False, e.faultString.strip().splitlines()[-1])
    finally:
        if lead_id:
            if admin:
                admin.call("crm.lead", "unlink", [lead_id])
                print(f"  (test lead {ref} deleted)")
            else:
                api.call("crm.lead", "write", [lead_id], {"active": False})
                print(f"  (test lead {ref} archived - fill in admin_key to have it deleted)")


# ---------------------------------------------------------------------------
# kh_wa_inbox (مفكرة القروبات), as the WhatsApp bot
# ---------------------------------------------------------------------------

WA_ITEM_FIELDS = [
    "name", "kind", "state", "urgent", "needs_manager", "group_id", "project_id", "partner_id",
    "requester_name", "requester_phone", "requester_user_id", "assignee_id", "asked_at", "due_date",
    "done_at", "done_note", "source_msg_id", "source_text", "context_text", "source_kind",
    "attachment_ids", "linked_ref", "remind_on", "manager_note", "manual_fields", "age_label", "is_overdue",
    "task_id",
]
WA_SECTIONS = {"needs_manager", "urgent", "open", "upcoming", "day_summary", "closed", "memos"}


def utc(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def check_wa_setup(bot, report):
    print("\n== Setup (what the bot relies on)")
    fields = bot.call("kh.wa.item", "fields_get", [], attributes=["type"])
    missing = [name for name in WA_ITEM_FIELDS if name not in fields]
    report.check(f"kh.wa.item has all {len(WA_ITEM_FIELDS)} fields", not missing, f"missing {missing} (installed?)")
    report.check("no transcript field", not [n for n in fields if "transcript" in n])
    for model, method in (("kh.wa.group", "upsert_groups"), ("kh.wa.item", "upsert_items"), ("kh.wa.day", "upsert_days")):
        result = bot.call(model, method, [])
        report.check(f"{model}.{method}([]) answers {{ids, errors}}", result == {"ids": [], "errors": []}, str(result))
    notebook = bot.call("kh.wa.item", "get_notebook")
    report.check("get_notebook returns the seven sections", set(notebook["sections"]) == WA_SECTIONS,
                 str(sorted(notebook["sections"])))
    report.check("the bot's user is a notebook manager", notebook["is_manager"],
                 "add it to 'مفكرة القروبات / المدير'")
    print(f"  (quick-done threshold: {notebook['quick_done_minutes']} minutes)")
    check_wa_dashboard(bot, report, notebook)
    check_wa_tasks(bot, report)
    return notebook


WA_TILES = {"needs_manager", "urgent", "overdue", "open", "closed_week", "avg_close"}
STATUS_ORDER = {"red": 0, "amber": 1, "green": 2}


def check_wa_dashboard(bot, report, notebook):
    """Read-only: the follow-up dashboard's numbers agree with each other."""
    print("\n== Follow-up dashboard (get_dashboard, read-only)")
    start = time.perf_counter()
    board = bot.call("kh.wa.item", "get_dashboard")
    elapsed = time.perf_counter() - start
    report.check(f"get_dashboard round trip under 1 s ({elapsed:.2f} s)", elapsed < 1.0)
    report.check("same seven sections as get_notebook", set(board["sections"]) == WA_SECTIONS)
    report.check("six tiles", set(board["kpis"]) == WA_TILES, str(sorted(board["kpis"])))
    sync = board["last_sync"]
    print(f"  (last sync: {sync['label']}, level {sync['level']})")
    report.check("last sync has a label and a level", sync["label"] and sync["level"] in ("ok", "warn", "late"))
    kpis, boxes, counters = board["kpis"], board["boxes"], board["counters"]
    for key in ("needs_manager", "urgent", "overdue", "open"):
        total = sum(box["counts"][key] for box in boxes)
        report.check(f"tile '{key}' = counter = sum of the boxes ({kpis[key]['value']})",
                     kpis[key]["value"] == counters[key] == notebook["counters"][key] == total,
                     f"tile {kpis[key]['value']}, counter {counters[key]}, boxes {total}")
    report.check("closed this week = its list",
                 kpis["closed_week"]["value"] == len(board["closed_week"]) or len(board["closed_week"]) == 200)
    wrong = [box["name"] for box in boxes
             if (box["status"] == "red") != bool(box["counts"]["urgent"] or box["counts"]["needs_manager"]
                                                 or box["counts"]["overdue"])]
    report.check("each box's status matches its numbers", not wrong, str(wrong))
    order = [(box["compact"], STATUS_ORDER[box["status"]]) for box in boxes]
    report.check("boxes: needing attention first, one-line boxes last", order == sorted(order), str(order))
    report.check("at most 3 items per box, the rest as '+N'",
                 all(len(b["top"]) <= 3 and b["more"] == max(b["counts"]["open"] - 3, 0) for b in boxes))
    if boxes:
        first = boxes[0]
        picked = bot.call("kh.wa.item", "get_dashboard", group_id=first["group_id"])
        report.check(f"picking a group narrows the tiles to it, every card stays ({first['name']})",
                     [b["group_id"] for b in picked["boxes"] if b["selected"]] == [first["group_id"]]
                     and len(picked["boxes"]) == len(boxes)
                     and picked["kpis"]["open"]["value"] == first["counts"]["open"], str(picked["kpis"]["open"]))


def check_wa_tasks(bot, report):
    """Read-only: assigned items have their follow-up task, in line with them."""
    print("\n== Follow-up tasks (read-only)")
    xmlids = {x["name"]: x["res_id"] for x in bot.call(
        "ir.model.data", "search_read",
        [("module", "=", "kh_wa_inbox"), ("name", "in", ("project_kh_wa_followups", "group_kh_wa_manager"))],
        fields=["name", "res_id"])}
    report.check("the 'WhatsApp Follow-ups' project exists", "project_kh_wa_followups" in xmlids)
    group = bot.call("res.groups", "read", [xmlids["group_kh_wa_manager"]], fields=["all_user_ids"])
    managers = set(group[0]["all_user_ids"])
    items = bot.call("kh.wa.item", "search_read", [("state", "in", ("open", "waiting")), ("assignee_id", "!=", False)],
                     fields=["name", "assignee_id", "task_id"])
    needing = [i for i in items if i["assignee_id"][0] not in managers]
    report.check(f"every open item assigned outside the managers has a task ({len(needing)})",
                 all(i["task_id"] for i in needing), str([i["name"] for i in needing if not i["task_id"]][:5]))
    tasks = bot.call("project.task", "search_read", [("kh_wa_item_id", "!=", False)],
                     fields=["state", "user_ids", "kh_wa_item_id"])
    states = {i["id"]: i["state"] for i in bot.call(
        "kh.wa.item", "search_read", [("id", "in", [t["kh_wa_item_id"][0] for t in tasks])], fields=["state"])}
    # A task can be cancelled by its assignee while its item stays open (it goes back to the manager).
    wrong = [t["id"] for t in tasks if t["state"] == "1_done" and states.get(t["kh_wa_item_id"][0]) in ("open", "waiting")]
    report.check(f"no done task with an open item ({len(tasks)} tasks)", not wrong, str(wrong[:5]))


def simulate_bot(bot, report, threshold):
    print("\n== Bot flow ([TEST] group, as the bot's user)")
    stamp = int(time.time())
    chat, prefix = f"test-{stamp}@g.us", f"test-{stamp}-"
    asked = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(hours=3)
    group_id = None

    def row(key, **values):
        return {"source_msg_id": prefix + key, "wa_chat_id": chat, "name": f"[TEST] {key}",
                "asked_at": utc(asked), **values}

    def items(key):
        return bot.call("kh.wa.item", "search_read", [("source_msg_id", "=", prefix + key)],
                        fields=["state", "name", "source_text", "context_text", "manual_fields", "attachment_ids"])

    def day_page():
        return bot.call("kh.wa.day", "search_read", [("group_id", "=", group_id)],
                        fields=["quick_done_count", "message_count"])

    try:
        first = bot.call("kh.wa.group", "upsert_groups",
                         [{"wa_chat_id": chat, "name": "[TEST] notebook check", "category": "other", "color": 3}])
        group_id = first["ids"][0] if first["ids"] else None
        again = bot.call("kh.wa.group", "upsert_groups", [{"wa_chat_id": chat, "name": "[TEST] notebook check"}])
        report.check("upsert_groups twice: one group", group_id and again["ids"] == [group_id], f"{first} / {again}")

        file = {"name": "test.txt", "mimetype": "text/plain", "datas": base64.b64encode(b"test file").decode()}
        one = bot.call("kh.wa.item", "upsert_items", [row("m1", attachments=[file])])
        two = bot.call("kh.wa.item", "upsert_items", [row("m1", name="[TEST] m1 updated", attachments=[file])])
        found = items("m1")
        report.check("same source_msg_id twice: one item", len(found) == 1 and one["ids"] == two["ids"], f"{one} / {two}")
        report.check("second push updates it", found and found[0]["name"] == "[TEST] m1 updated")
        report.check("same file twice: kept once", found and len(found[0]["attachment_ids"]) == 1)

        quick = row("q1", state="done", done_at=utc(asked + timedelta(minutes=max(1, threshold // 4))))
        first, second = (bot.call("kh.wa.item", "upsert_items", [quick]) for _ in range(2))
        pages = day_page()
        report.check(f"done within {threshold} min: not stored", not first["ids"] and not items("q1"), str(first))
        report.check("... counted once on the day page", [p["quick_done_count"] for p in pages] == [1], str(pages))
        slow = row("q2", state="done", done_at=utc(asked + timedelta(minutes=threshold + 30)))
        result = bot.call("kh.wa.item", "upsert_items", [slow])
        report.check(f"done after {threshold + 30} min: stored", len(result["ids"]) == 1, str(result))

        dubai_day = str((asked + timedelta(hours=4)).date())  # Dubai is UTC+4, no DST
        bot.call("kh.wa.day", "upsert_days", [{"date": dubai_day, "wa_chat_id": chat, "summary": "سطر 1\nسطر 2",
                                               "message_count": 9, "quick_done_count": 99}])
        pages = day_page()
        report.check("upsert_days updates the same page, ignores quick_done_count",
                     [(p["quick_done_count"], p["message_count"]) for p in pages] == [(1, 9)], str(pages))

        bot.call("kh.wa.item", "upsert_items", [row("x1")])
        item_id = items("x1")[0]["id"]
        bot.call("kh.wa.item", "write", [item_id], {"state": "waiting"})
        bot.call("kh.wa.item", "upsert_items", [row("x1", state="open", name="[TEST] x1 renamed")])
        found = items("x1")[0]
        report.check("a state changed in Odoo survives the next upsert", found["state"] == "waiting", str(found))
        report.check("... and other fields still follow the bot", found["name"] == "[TEST] x1 renamed")
        report.check("... manual_fields records it", "state" in (found["manual_fields"] or ""))

        bot.call("kh.wa.item", "upsert_items", [row("otp", source_text="OTP 482913",
                                                    context_text="card 4111 1111 1111 1234")])
        found = items("otp")[0]
        report.check("OTP masked", found["source_text"] == "OTP ••••", found["source_text"])
        report.check("card number masked", found["context_text"] == "card •••• 1234", found["context_text"])

        batch = bot.call("kh.wa.item", "upsert_items", [row("b1"), row("b2", wa_chat_id="unknown@g.us"), row("b3")])
        report.check("one bad row doesn't fail the batch", len(batch["ids"]) == 2
                     and [e["index"] for e in batch["errors"]] == [1], str(batch))

        notebook = bot.call("kh.wa.item", "get_notebook", group_id=group_id)
        report.check("get_notebook(group) has the seven sections", set(notebook["sections"]) == WA_SECTIONS)
        bot.call("kh.wa.group", "upsert_groups", [{"wa_chat_id": chat, "last_message_at": utc(asked + timedelta(hours=2))}])
        board = bot.call("kh.wa.item", "get_dashboard", group_id=group_id)
        box = next((b for b in board["boxes"] if b["group_id"] == group_id), {})
        report.check("get_dashboard(group): its box, with last_message_at",
                     box.get("group_id") == group_id and box.get("last_message_at") == utc(asked + timedelta(hours=2)),
                     str(box.get("last_message_at")))
        open_ids = bot.call("kh.wa.item", "search", [("group_id", "=", group_id), ("state", "in", ["open", "waiting"])])
        report.check("... its box counts the group's open items", box.get("counts", {}).get("open") == len(open_ids))
        report.check("... and the upserts refreshed the last sync", board["last_sync"]["level"] == "ok",
                     str(board["last_sync"]))
        start = time.perf_counter()
        bot.call("kh.wa.item", "get_notebook")
        elapsed = time.perf_counter() - start
        report.check(f"get_notebook round trip under 1 s ({elapsed:.2f} s)", elapsed < 1.0)
    except xmlrpc.client.Fault as e:
        report.check("bot flow", False, e.faultString.strip().splitlines()[-1])
    finally:
        if group_id:
            item_ids = bot.call("kh.wa.item", "search", [("group_id", "=", group_id)])
            bot.call("kh.wa.item", "unlink", item_ids)
            bot.call("kh.wa.group", "unlink", [group_id])  # day pages and the quick-done log go with it
            print(f"  ([TEST] group and its {len(item_ids)} items deleted)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--production", action="store_true", help="read-only checks, creates nothing")
    parser.add_argument("--install", action="store_true", help="install the module first if missing")
    parser.add_argument("--wa-inbox", action="store_true", help="test kh_wa_inbox as the WhatsApp bot")
    parser.add_argument("--read-only", action="store_true", help="with --wa-inbox: only checks that write nothing")
    args = parser.parse_args()
    if args.wa_inbox:
        return main_wa_inbox(args)

    if not CONFIG.exists():
        CONFIG.write_text(TEMPLATE, encoding="utf-8")
        print(f"Created {CONFIG}\nFill in the url, db and API keys there, then run this again.")
        return 2
    section = "production" if args.production else "staging"
    parser_cfg = configparser.ConfigParser()
    parser_cfg.read(CONFIG, encoding="utf-8")
    cfg = parser_cfg[section]
    if "YOUR-" in cfg.get("url", "") or "YOUR-" in cfg.get("db", ""):
        print(f"Fill in the [{section}] url and db in {CONFIG} first.")
        return 2
    if not args.production and ".dev.odoo.com" not in cfg["url"]:
        print("The [staging] url is not a .dev.odoo.com build - refusing to create a test lead there.")
        return 2

    print(f"Testing {section}: {cfg['url']} (database {cfg['db']})")
    try:
        api, admin = connect(cfg, "api"), connect(cfg, "admin")
    except Exception as e:  # noqa: BLE001 - bad URL/db/key: say so plainly
        print(f"Could not log in: {e}")
        return 1
    if not api:
        print(f"Fill in api_login / api_key in {CONFIG} first.")
        return 2
    if args.install:
        if not admin:
            print("--install needs admin_login / admin_key.")
            return 2
        install_module(admin)

    report = Report()
    check_setup(api, report)
    if args.production:
        print("\n(production: website flow skipped, no test lead created)")
    else:
        simulate_website(api, admin, report)
    print(f"\n{report.passed} passed, {report.failed} failed")
    return 1 if report.failed else 0


def main_wa_inbox(args):
    section = "production" if args.production else "staging"
    parser_cfg = configparser.ConfigParser()
    parser_cfg.read(CONFIG, encoding="utf-8")
    if section not in parser_cfg:
        print(f"No [{section}] section in {CONFIG}.")
        return 2
    cfg = parser_cfg[section]
    if not args.production and ".dev.odoo.com" not in cfg.get("url", ""):
        print("The [staging] url is not a .dev.odoo.com build - refusing to create test data there.")
        return 2

    print(f"Testing kh_wa_inbox on {section}: {cfg['url']} (database {cfg['db']})")
    try:
        bot, admin = connect(cfg, "wa"), connect(cfg, "admin")
    except Exception as e:  # noqa: BLE001 - bad URL/db/key: say so plainly
        print(f"Could not log in: {e}")
        return 1
    if args.install:
        if not admin:
            print("--install needs admin_login / admin_key.")
            return 2
        install_module(admin, "kh_wa_inbox")
    if not bot:
        print(f"Fill in wa_login / wa_key (the WhatsApp bot's user) in {CONFIG} first.")
        return 2

    report = Report()
    try:
        notebook = check_wa_setup(bot, report)
    except xmlrpc.client.Fault as e:
        report.check("setup", False, e.faultString.strip().splitlines()[-1])
        notebook = None
    if args.production or args.read_only:
        print(f"\n({'production' if args.production else 'read-only'}: bot flow skipped, nothing created)")
    elif notebook:
        simulate_bot(bot, report, notebook["quick_done_minutes"])
    print(f"\n{report.passed} passed, {report.failed} failed")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
