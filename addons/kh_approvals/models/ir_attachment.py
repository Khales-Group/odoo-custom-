# -*- coding: utf-8 -*-
from odoo import models
from odoo.tools.misc import format_datetime


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _to_store(self, store, fields=None, **kwargs):
        super()._to_store(store, fields, **kwargs)
        for attachment in self:
            att = attachment.sudo()
            upload_date = ""
            if att.create_date:
                try:
                    upload_date = format_datetime(
                        self.env, att.create_date, dt_format="dd MMM yyyy, HH:mm"
                    )
                except Exception:
                    upload_date = att.create_date.strftime("%d %b %Y, %H:%M")
            store.add(attachment, {
                "upload_user_name": att.create_uid.name or "",
                "upload_date": upload_date,
            })
