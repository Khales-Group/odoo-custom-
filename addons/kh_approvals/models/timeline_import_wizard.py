# -*- coding: utf-8 -*-
import mimetypes

from odoo import fields, models
from odoo.exceptions import UserError

_SUPPORTED_MEDIA_TYPES = {
    'application/pdf': 'application/pdf',
    'image/png': 'image/png',
    'image/jpeg': 'image/jpeg',
    'image/gif': 'image/gif',
    'image/webp': 'image/webp',
}


class KhAiTimelineImportWizard(models.TransientModel):
    _name = 'kh.ai.timeline.import.wizard'
    _description = 'مطابقة تايم لاين المقاول مع تاسكات المشروع (AI)'

    project_id = fields.Many2one('project.project', required=True, string="المشروع")
    timeline_file = fields.Binary(string="ملف/صورة تايم لاين المقاول", required=True)
    timeline_filename = fields.Char(string="اسم الملف")

    def action_import(self):
        self.ensure_one()
        if not self.timeline_file:
            raise UserError('لازم ترفع ملف التايم لاين (صورة أو PDF) أول.')

        mimetype = mimetypes.guess_type(self.timeline_filename or '')[0]
        media_type = _SUPPORTED_MEDIA_TYPES.get(mimetype or '')
        if not media_type:
            raise UserError(
                'صيغة الملف غير مدعومة (%s) - لازم يكون صورة (PNG/JPG/GIF/WEBP) أو PDF.'
                % (self.timeline_filename or '?')
            )

        file_b64 = self.timeline_file.decode() if isinstance(self.timeline_file, bytes) else self.timeline_file
        self.project_id._kh_ai_integrate_contractor_timeline(file_b64, self.timeline_filename, media_type)
        return {'type': 'ir.actions.act_window_close'}
