# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.tools.misc import format_datetime


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    upload_user_name = fields.Char(
        compute='_compute_upload_info',
        string='Uploaded By',
    )
    upload_date = fields.Char(
        compute='_compute_upload_info',
        string='Upload Date',
    )

    @api.depends('create_uid', 'create_date')
    def _compute_upload_info(self):
        for att in self:
            rec = att.sudo()
            att.upload_user_name = rec.create_uid.name or ''
            if rec.create_date:
                try:
                    att.upload_date = format_datetime(
                        self.env, rec.create_date, dt_format="dd MMM yyyy, HH:mm"
                    )
                except Exception:
                    att.upload_date = rec.create_date.strftime("%d %b %Y, %H:%M")
            else:
                att.upload_date = ''

    def _to_store(self, store, fields=None, **kwargs):
        if isinstance(fields, list):
            fields = list(fields)
            for f in ('upload_user_name', 'upload_date'):
                if f not in fields:
                    fields.append(f)
        super()._to_store(store, fields, **kwargs)
