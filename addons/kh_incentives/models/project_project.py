# -*- coding: utf-8 -*-
import re

from odoo import models

# Stage names that mean the project is finished / handed over to the client.
_DONE_STAGE = re.compile(r"complet|hand(ed)?\s*-?\s*over|deliver|finish|\bdone\b", re.IGNORECASE)


class ProjectProject(models.Model):
    _inherit = "project.project"

    def _kh_is_completed(self):
        self.ensure_one()
        if self.last_update_status == "done":  # status "Complete"
            return True
        # stage_id is limited to the "Project Stages" group - read it as sudo
        return bool(_DONE_STAGE.search(self.sudo().stage_id.name or ""))

    def write(self, vals):
        # A project becoming complete (status set to "Complete", a project
        # update posted as Complete, or moved to a Done / Handed Over stage)
        # creates the project manager's handover bonus as a draft for the CEO.
        if not {"last_update_status", "last_update_id", "stage_id"} & set(vals):
            return super().write(vals)
        already_done = {project.id for project in self if project._kh_is_completed()}
        res = super().write(vals)
        newly_done = self.filtered(lambda p: p.id not in already_done and p._kh_is_completed())
        if newly_done:
            self.env["kh.incentive.claim"]._create_handover_bonuses(newly_done)
        return res
