#!/usr/bin/env python3
"""Automatic test of the website calculator -> Odoo connection, done the
same way the website does it (XML-RPC, as the website's integration user).

    python scripts/staging_check.py               # staging: full test
    python scripts/staging_check.py --install     # also install kh_crm_calculator first if missing
    python scripts/staging_check.py --production  # production: read-only checks, creates nothing

Connection details are read from %USERPROFILE%\\.khales_odoo_test.ini (a
template is written there on first run). API keys: Odoo > avatar > My
Preferences > Account Security > New API Key. The keys never leave that file.

On staging one test lead is created (reference K-TEST-..., name starting
with [TEST]) and removed at the end: deleted when admin_key is filled in,
otherwise archived (the integration user can't delete leads).
"""
import argparse
import configparser
import sys
import time
import xmlrpc.client
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

[production]
url = https://YOUR-PRODUCTION-URL
db = YOUR-PRODUCTION-DATABASE
api_login =
api_key =
admin_login =
admin_key =
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


def install_module(admin):
    mod = admin.call("ir.module.module", "search_read", [("name", "=", "kh_crm_calculator")], fields=["state"])
    if mod and mod[0]["state"] == "installed":
        return
    print("Installing kh_crm_calculator ...")
    admin.call("ir.module.module", "update_list")
    mod_id = admin.call("ir.module.module", "search", [("name", "=", "kh_crm_calculator")])
    if not mod_id:
        raise RuntimeError("kh_crm_calculator not found on the server - is it deployed?")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--production", action="store_true", help="read-only checks, creates nothing")
    parser.add_argument("--install", action="store_true", help="install kh_crm_calculator first if missing")
    args = parser.parse_args()

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


if __name__ == "__main__":
    sys.exit(main())
