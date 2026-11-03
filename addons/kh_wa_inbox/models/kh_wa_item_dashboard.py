from odoo import api, fields, models

from .kh_wa_board import group_boxes, kpis, sync_status
from .kh_wa_tools import read_last_sync

CLOSED_WEEK_LIMIT = 200
GROUP_DAYS = 7


class KhWaItem(models.Model):
    _inherit = "kh.wa.item"

    @api.model
    def get_dashboard(self, date=None, group_id=None, search=None):
        """Everything the follow-up dashboard's WhatsApp part shows, in one
        call: get_notebook's sections plus the header's last sync, the six
        tiles, one card per group, the items closed this week and, when a
        group is picked, its last 7 day pages.

        A picked group narrows the tiles and the lists; the group cards
        always show every group (the picked one is marked "selected").
        """
        result, ctx = self._build_notebook(date, group_id, search, with_week=True)
        payloads, now = ctx["payloads"], ctx["now"]
        closed_week = [payloads[item.id] for item in ctx["closed_week"]]

        week_opened = {
            group.id: count for group, count in self._read_group(
                [("asked_at", ">=", ctx["week_start_utc"])], ["group_id"], ["__count"],
            )
        }
        day_pages, week_messages = {}, None
        if ctx["is_manager"]:
            pages = (
                self._notebook_day_summary(ctx["day"], False, ctx["group_order"]) if ctx["group_id"]
                else result["sections"]["day_summary"]
            )
            day_pages = {page["group_id"]: page for page in pages}
            week_messages = {
                group.id: total for group, total in self.env["kh.wa.day"]._read_group(
                    [("date", ">=", ctx["week_start"])], ["group_id"], ["message_count:sum"],
                )
            }

        result.update({
            "now": fields.Datetime.to_string(now),
            "week_start": fields.Date.to_string(ctx["week_start"]),
            "last_sync": sync_status(read_last_sync(self.env), now),
            "kpis": kpis([payloads[item.id] for item in ctx["open_items"]], closed_week, ctx["today"], now),
            "boxes": group_boxes(
                [{"id": g.id, "name": g.name, "color": g.color, "last_message_at": g.last_message_at}
                 for g in ctx["groups"]],
                [payloads[item.id] for item in ctx["open_all"]],
                [payloads[item.id] for item in ctx["closed_week_all"]],
                week_opened, day_pages, week_messages, now, ctx["week_start_utc"],
                selected=ctx["group_id"],
            ),
            "closed_week": closed_week[:CLOSED_WEEK_LIMIT],
            "group_days": self._dashboard_group_days(ctx) if ctx["group_id"] and ctx["is_manager"] else [],
        })
        return result

    @api.model
    def _dashboard_group_days(self, ctx):
        pages = self.env["kh.wa.day"].search_fetch(
            [("group_id", "=", ctx["group_id"]), ("date", "<=", ctx["day"])],
            ["date", "summary", "message_count", "quick_done_count", "visit_count"],
            order="date desc", limit=GROUP_DAYS,
        )
        return [
            {
                "date": fields.Date.to_string(page.date),
                "lines": [line.strip() for line in (page.summary or "").splitlines() if line.strip()],
                "message_count": page.message_count,
                "quick_done_count": page.quick_done_count,
                "visit_count": page.visit_count,
            }
            for page in pages
        ]
