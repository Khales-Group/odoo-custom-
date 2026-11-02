"""The follow-up dashboard's WhatsApp part, worked out from plain data.

No Odoo imports: get_dashboard reads the records, these functions turn them
into tiles and group boxes (and can be checked on their own).
"""
from collections import defaultdict
from datetime import datetime, timedelta

from .kh_wa_tools import arabic_age, arabic_days

STALE_AFTER = timedelta(days=3)  # oldest open item older than this -> "متابعة"
SYNC_WARN_MINUTES = 30
SYNC_LATE_MINUTES = 120
TOP_ITEMS = 3
STATUS_ORDER = {"red": 0, "amber": 1, "green": 2}


def _dt(value):
    return datetime.fromisoformat(value) if value else None


def item_priority(item):
    """needs_manager, then urgent, then overdue, then oldest."""
    return (not item["needs_manager"], not item["urgent"], not item["is_overdue"], item["asked_at"] or "", item["id"])


def box_status(counts, oldest_asked_at, now):
    if counts["needs_manager"] or counts["urgent"] or counts["overdue"]:
        return "red"
    if oldest_asked_at and now - oldest_asked_at > STALE_AFTER:
        return "amber"
    return "green"


def duration(seconds):
    """{"value": "18", "unit": "ساعة"} for a tile; False when unknown."""
    if seconds is None or seconds < 0:
        return False
    minutes = round(seconds / 60)
    if minutes < 60:
        n = max(minutes, 1)
        return {"value": str(n), "unit": "دقائق" if 2 <= n <= 10 else "دقيقة"}
    hours = round(seconds / 3600)
    if hours < 48:
        return {"value": str(hours), "unit": "ساعات" if 2 <= hours <= 10 else "ساعة"}
    days = round(seconds / 86400, 1)
    text = f"{days:g}"
    return {"value": text, "unit": "أيام" if days == int(days) and 3 <= days <= 10 else "يوم"}


def duration_text(seconds):
    parts = duration(seconds)
    return f"{parts['value']} {parts['unit']}" if parts else ""


def days_ago(days):
    """'منذ 5 أيام' for a whole number of days (0 -> 'اليوم')."""
    return "اليوم" if days <= 0 else "منذ " + arabic_days(days)


def sync_status(last_sync, now):
    """The header's 'آخر تحديث للبيانات' line."""
    if not last_sync:
        return {"at": False, "minutes": False, "label": "لم تصل بيانات بعد", "level": "late"}
    minutes = max(int((now - last_sync).total_seconds() // 60), 0)
    level = "late" if minutes >= SYNC_LATE_MINUTES else "warn" if minutes >= SYNC_WARN_MINUTES else "ok"
    return {
        "at": last_sync.strftime("%Y-%m-%d %H:%M:%S"),
        "minutes": minutes,
        "label": arabic_age(last_sync, now, prefix="قبل"),
        "level": level,
    }


def kpis(open_items, closed_week, today, now):
    """The six tiles. open_items / closed_week are item payloads."""
    waiting = [p for p in open_items if p["needs_manager"]]
    overdue = [p for p in open_items if p["is_overdue"]]
    oldest_waiting = min((p["asked_at"] for p in waiting), default=None)
    oldest_due = min((p["due_date"] for p in overdue), default=None)
    took = [
        (_dt(p["done_at"]) - _dt(p["asked_at"])).total_seconds()
        for p in closed_week if p["state"] == "done" and p["done_at"] and p["asked_at"]
    ]
    return {
        "needs_manager": {"value": len(waiting), "oldest": arabic_age(_dt(oldest_waiting), now) if oldest_waiting else ""},
        "urgent": {"value": sum(1 for p in open_items if p["urgent"])},
        "overdue": {
            "value": len(overdue),
            "oldest": days_ago((today - datetime.fromisoformat(oldest_due).date()).days) if oldest_due else "",
        },
        "open": {"value": len(open_items)},
        "closed_week": {"value": len(closed_week)},
        "avg_close": {"value": len(took), "duration": duration(sum(took) / len(took)) if took else False},
    }


def group_boxes(groups, open_items, closed_week, week_opened, day_pages, week_messages, now, week_start_utc,
                selected=False):
    """One box per group, in the order the dashboard shows them.

    groups: [{"id", "name", "color", "last_message_at" (datetime or None)}] in sequence order.
    open_items / closed_week: item payloads. week_opened: {group id: items asked since Monday}.
    day_pages: {group id: the selected day's page dict} (managers only).
    week_messages: {group id: messages since Monday} or None when unknown (no access to day pages).
    selected: a group was picked, so its box is never folded to one line.
    """
    open_by_group, closed_by_group = defaultdict(list), defaultdict(int)
    for payload in open_items:
        open_by_group[payload["group_id"]].append(payload)
    for payload in closed_week:
        closed_by_group[payload["group_id"]] += 1

    boxes = []
    for position, group in enumerate(groups):
        items = open_by_group.get(group["id"], [])
        counts = {
            "open": len(items),
            "urgent": sum(1 for p in items if p["urgent"]),
            "needs_manager": sum(1 for p in items if p["needs_manager"]),
            "overdue": sum(1 for p in items if p["is_overdue"]),
        }
        oldest = min(items, key=lambda p: (p["asked_at"] or "", p["id"]), default=None)
        top = sorted(items, key=item_priority)[:TOP_ITEMS]
        page = day_pages.get(group["id"])
        messages = (week_messages or {}).get(group["id"], 0)
        last = group["last_message_at"]
        quiet = (
            not items and not messages and not closed_by_group[group["id"]] and not week_opened.get(group["id"])
            and (not last or last < week_start_utc)
        )
        boxes.append({
            "group_id": group["id"],
            "name": group["name"],
            "color": group["color"],
            "status": box_status(counts, _dt(oldest["asked_at"]) if oldest else None, now),
            "compact": bool(quiet and not selected),
            "last_message_at": last.strftime("%Y-%m-%d %H:%M:%S") if last else False,
            "counts": counts,
            "oldest": {"age": oldest["age"], "name": oldest["name"], "id": oldest["id"]} if oldest else False,
            "top": [
                {"id": p["id"], "name": p["name"], "age": p["age"],
                 "assignee": p["assignee"]["name"] if p["assignee"] else ""}
                for p in top
            ],
            "more": max(len(items) - TOP_ITEMS, 0),
            "day": {
                "message_count": page["message_count"],
                "quick_done_count": page["quick_done_count"],
                "visit_count": page["visit_count"],
                "first_line": page["lines"][0] if page["lines"] else "",
            } if page else False,
            "week": {"opened": week_opened.get(group["id"], 0), "closed": closed_by_group[group["id"]]},
            "_position": position,
        })
    boxes.sort(key=lambda b: (b["compact"], STATUS_ORDER[b["status"]], b["_position"]))
    for box in boxes:
        del box["_position"]
    return boxes
