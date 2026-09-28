import logging
import re

_logger = logging.getLogger(__name__)

# Studio models this module redefines in Python.
OWNED_MODELS = ("x_reports", "x_reports_stage")

# Existing (Studio) legal stages, in order, renamed in place so that the files
# already in them follow: (key, names it may currently have, new name, closing).
LAW_STAGES = [
    ("open", ["new-جديد", "new", "جديد"], "فتح", False),
    ("prep", ["تحت الاجراء", "تحت الإجراء"], "تحضير", False),
    ("hearing", ["تحت التداول"], "جلسات", False),
    ("judgment", ["دعاوي مفصولة", "دعاوى مفصولة"], "حكم", False),
    ("execution", ["تنفيذات"], "تنفيذ", False),
    ("closed", ["completed", "done"], "مغلقة", True),
]

# New PRO stages: (key, name, closing).
PRO_STAGES = [
    ("not_started", "لم تبدأ", False),
    ("docs", "تجهيز المستندات", False),
    ("submitted", "قيد التقديم", False),
    ("waiting", "بانتظار الحكومة", False),
    ("done", "مكتملة", True),
]

# Where existing PRO files go, based on the legal stage they currently sit in.
PRO_FROM_LAW = {
    "open": "not_started",
    "prep": "submitted",
    "hearing": "waiting",
    "judgment": "done",
    "execution": "done",
    "closed": "done",
}

ARCHIVED_MENUS_PARAM = "kh_law.archived_studio_menu_ids"


def _normalize(name):
    return re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", (name or "").strip().lower()))


def _set_name(record, name, langs):
    for lang in langs:
        record.with_context(lang=lang).x_name = name


def pre_init_hook(env):
    # Studio models are rebuilt from ir_model at every registry load and would
    # replace this module's Python classes; marking them as code-owned stops that.
    env.cr.execute(
        "UPDATE ir_model SET state = 'base' WHERE model IN %s AND state = 'manual'",
        [OWNED_MODELS],
    )


def post_init_hook(env):
    langs = sorted({code for code, _name in env["res.lang"].get_installed()} | {"en_US"})
    Stage = env["x_reports_stage"].with_context(active_test=False)
    Report = env["x_reports"].with_context(active_test=False, tracking_disable=True, mail_notrack=True)

    # 1. Legal stages: rename the existing ones in place, create missing ones.
    lookup = {_normalize(n): key for key, names, _new, _closed in LAW_STAGES for n in names}
    law_stages, unmatched = {}, Stage
    for stage in Stage.search([]):
        names = {_normalize(stage.with_context(lang=lang).x_name) for lang in langs}
        key = next((lookup[n] for n in names if n in lookup), None)
        if key and key not in law_stages:
            law_stages[key] = stage
        else:
            unmatched |= stage

    for index, (key, _names, new_name, closed) in enumerate(LAW_STAGES, start=1):
        vals = {"kh_department": "Law", "kh_sequence": index * 10, "kh_is_closed": closed, "kh_fold": closed}
        stage = law_stages.get(key)
        if stage:
            stage.write(vals)
        else:
            stage = law_stages[key] = Stage.create(dict(vals, x_name=new_name))
        _set_name(stage, new_name, langs)

    for offset, stage in enumerate(unmatched, start=1):
        stage.write({"kh_department": "Law", "kh_sequence": 100 + offset})
        _logger.warning("kh_law: stage %r (id %s) did not match any legal stage; kept as a legal stage",
                        stage.x_name, stage.id)

    # 2. PRO stages.
    pro_stages = {}
    for index, (key, name, closed) in enumerate(PRO_STAGES, start=1):
        pro_stages[key] = stage = Stage.create({
            "x_name": name, "kh_department": "PRO", "kh_sequence": index * 10,
            "kh_is_closed": closed, "kh_fold": closed,
        })
        _set_name(stage, name, langs)

    # 3. Move existing PRO files out of the legal stages.
    key_of_stage = {stage.id: key for key, stage in law_stages.items()}
    moves = {}
    for rec in Report.search([("x_studio_type", "=", "PRO")]):
        target = pro_stages[PRO_FROM_LAW.get(key_of_stage.get(rec.x_studio_stage_id.id), "not_started")]
        moves.setdefault(target, Report)
        moves[target] |= rec
    for target, records in moves.items():
        records.write({"x_studio_stage_id": target.id})

    # 4. Old boolean "High Priority" becomes the High star.
    Report.search([("x_studio_priority", "=", True)]).write({"kh_priority": "2"})

    # 5. Closing date of closed files: date of their last stage change, else last update.
    closed = Report.search([("kh_is_closed", "=", True)])
    stage_field = env["ir.model.fields"]._get("x_reports", "x_studio_stage_id")
    changed_on = {}
    if closed and stage_field:
        env.cr.execute("""
            SELECT m.res_id, MAX(m.date)::date
              FROM mail_tracking_value t
              JOIN mail_message m ON m.id = t.mail_message_id
             WHERE t.field_id = %s AND m.model = 'x_reports' AND m.res_id IN %s
          GROUP BY m.res_id
        """, [stage_field.id, tuple(closed.ids)])
        changed_on = dict(env.cr.fetchall())
    for rec in closed:
        rec.kh_close_date = changed_on.get(rec.id) or (rec.write_date and rec.write_date.date())

    # 6. Hide the old Studio app menu: the new app menu replaces it.
    own_actions = {env.ref(xmlid).id for xmlid in ("kh_law.action_x_reports_law", "kh_law.action_x_reports_pro")}
    studio_actions = env["ir.actions.act_window"].search([("res_model", "=", "x_reports")]).filtered(
        lambda a: a.id not in own_actions
    )
    menus = env["ir.ui.menu"].search([
        ("action", "in", [f"ir.actions.act_window,{a.id}" for a in studio_actions]),
    ])
    own_root = env.ref("kh_law.menu_kh_law_root")
    root_ids = {int(m.parent_path.split("/")[0]) for m in menus if m.parent_path} - {own_root.id}
    roots = env["ir.ui.menu"]
    for root in env["ir.ui.menu"].browse(sorted(root_ids)):
        # Only hide an app whose menus all open Law models; never a shared app
        # (e.g. Project) that merely contains a Law menu.
        descendants = env["ir.ui.menu"].with_context(active_test=False).search([
            ("id", "child_of", root.id), ("action", "!=", False),
        ])
        targets = {
            menu.action.res_model if menu.action._name == "ir.actions.act_window" else menu.action._name
            for menu in descendants
        }
        if all(target and target.startswith("x_reports") for target in targets):
            roots |= root
        else:
            _logger.warning("kh_law: menu %r also opens %s; left visible", root.name, sorted(targets))
    if roots:
        roots.write({"active": False})
        env["ir.config_parameter"].sudo().set_param(ARCHIVED_MENUS_PARAM, ",".join(map(str, roots.ids)))
        _logger.info("kh_law: archived Studio menus %s", roots.mapped("name"))


def uninstall_hook(env):
    # Hand the models and their Studio fields back to Studio so they survive.
    env.cr.execute("UPDATE ir_model SET state = 'manual' WHERE model IN %s", [OWNED_MODELS])
    env.cr.execute(
        "UPDATE ir_model_fields SET state = 'manual' WHERE model IN %s AND name LIKE 'x\\_%%'",
        [OWNED_MODELS],
    )
    menu_ids = env["ir.config_parameter"].sudo().get_param(ARCHIVED_MENUS_PARAM)
    if menu_ids:
        env["ir.ui.menu"].with_context(active_test=False).browse(
            [int(i) for i in menu_ids.split(",")]
        ).exists().write({"active": True})
