from odoo import fields, models


class KhWaMemo(models.Model):
    """The manager's own notes on the notebook page ("ملاحظاتي").
    A record rule keeps them private to their author, managers included."""

    _name = "kh.wa.memo"
    _description = "My Note (Groups Notebook)"
    _order = "pinned desc, done, id desc"
    _rec_name = "text"

    text = fields.Text(required=True)
    user_id = fields.Many2one(
        "res.users", string="Owner", required=True, index=True, ondelete="cascade",
        default=lambda self: self.env.user,
    )
    done = fields.Boolean()
    pinned = fields.Boolean()
    item_id = fields.Many2one("kh.wa.item", string="Item", ondelete="set null", index="btree_not_null")
