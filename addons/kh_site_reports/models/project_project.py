import base64
import logging
import os
import re
import threading

import odoo
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
PHOTOS_PER_VISIT = 4


class Project(models.Model):
    _inherit = "project.project"

    kh_site_report_state = fields.Selection(
        [
            ("none", "Not Requested"),
            ("processing", "Generating"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        string="Site Report Status",
        default="none",
        copy=False,
    )
    kh_site_report_error = fields.Text(string="Site Report Last Error", copy=False)

    def action_request_site_report(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Generate Monthly Site Report"),
            "res_model": "kh.site.report.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_project_id": self.id},
        }

    def action_generate_site_report(self, period_start, period_end, period_label):
        """Kicks off generation right away, in a background thread — not a
        scheduled action. The HTTP request returns immediately; the thread
        opens its own DB cursor and posts a chatter notification (to the
        requesting user) once it's done or if it fails.
        """
        self.ensure_one()
        if self.kh_site_report_state == "processing":
            raise UserError(_("A site report is already being generated for this project."))

        self.write({"kh_site_report_state": "processing", "kh_site_report_error": False})
        self.message_post(
            body=_("Monthly site report for %s requested by %s — generating now in the background.")
            % (period_label, self.env.user.name)
        )
        self.env.cr.commit()

        threading.Thread(
            target=self._run_site_report_thread,
            args=(self.env.cr.dbname, self.env.uid, self.id, period_start, period_end, period_label, self.env.user.id),
            daemon=True,
        ).start()

    @api.model
    def _run_site_report_thread(self, dbname, uid, project_id, period_start, period_end, period_label, requesting_user_id):
        registry = odoo.registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, uid, {})
            project = env["project.project"].browse(project_id)
            project._generate_site_report(period_start, period_end, period_label, requesting_user_id)

    def _fetch_visit_note(self, folder_date_label):
        self.ensure_one()
        message = self.env["mail.message"].sudo().search(
            [
                ("res_id", "=", self.id),
                ("model", "=", "project.project"),
                ("body", "like", folder_date_label),
            ],
            order="date desc",
            limit=1,
        )
        if not message:
            return None

        body = (message.body or "").strip()
        parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        if len(parts) < 2:
            return body

        start, end = 0, len(parts)
        if re.search(r"site visit report", parts[0], re.IGNORECASE):
            start += 1
        if re.search(r"photo\(s\)", parts[-1], re.IGNORECASE):
            end -= 1
        return "\n\n".join(parts[start:end]).strip() or body

    def _get_logo_path(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "img", "khales_logo.png")
        return path if os.path.exists(path) else None

    def _notify_done(self, requesting_user_id, body):
        partner_ids = []
        if requesting_user_id:
            user = self.env["res.users"].browse(requesting_user_id)
            if user.exists() and user.partner_id:
                partner_ids = [user.partner_id.id]
        self.message_post(body=body, partner_ids=partner_ids)

    def _generate_site_report(self, period_start, period_end, period_label, requesting_user_id):
        self.ensure_one()

        try:
            from ..lib import claude_synthesis, docx_report, google_drive

            ICP = self.env["ir.config_parameter"].sudo()
            service_account_json = ICP.get_param("kh_site_reports.google_service_account_json")
            if not service_account_json:
                raise ValueError(
                    "Missing system parameter kh_site_reports.google_service_account_json "
                    "(paste the Google Service Account JSON key there)."
                )
            if not HAS_ANTHROPIC:
                raise ValueError("The 'anthropic' Python package is not installed.")
            anthropic_api_key = ICP.get_param("mcp_server.anthropic_api_key")
            if not anthropic_api_key:
                raise ValueError("Missing system parameter mcp_server.anthropic_api_key.")
            anthropic_model = ICP.get_param("mcp_server.anthropic_model") or DEFAULT_ANTHROPIC_MODEL

            drive = google_drive.build_drive_client(service_account_json)
            folders = google_drive.resolve_project_folders(
                drive, self.x_studio_all_files_drive_, self.name
            )

            subfolders = google_drive.list_subfolders(drive, folders["site_photos_id"])
            dated = sorted(
                (
                    (f, d)
                    for f, d in (
                        (f, google_drive.parse_folder_date(f["name"])) for f in subfolders
                    )
                    if d
                ),
                key=lambda x: x[1],
            )
            visits_in_period = [(f, d) for f, d in dated if period_start <= d <= period_end]

            if not visits_in_period:
                self.write({"kh_site_report_state": "none"})
                self._notify_done(
                    requesting_user_id,
                    _("Site report for %s: no site-visit folders found in that period.") % period_label,
                )
                return

            visits_for_report = []
            skipped = []
            for folder, visit_date in visits_in_period:
                image_files = google_drive.list_image_files(drive, folder["id"])
                if not image_files:
                    skipped.append(f"{folder['name']} (no photos)")
                    continue

                narrative = self._fetch_visit_note(folder["name"])
                if not narrative:
                    skipped.append(f"{folder['name']} (no site-visit note found in Odoo)")
                    continue

                sampled = google_drive.sample_across(image_files, PHOTOS_PER_VISIT)
                photos = [google_drive.download_file_bytes(drive, f["id"]) for f in sampled]

                weekday = visit_date.strftime("%A")
                date_label = f"Site Visit — {visit_date.strftime('%d %B %Y')} ({weekday})"
                visits_for_report.append(
                    {
                        "date": visit_date,
                        "date_label": date_label,
                        "narrative": narrative,
                        "photos": photos,
                    }
                )

            if not visits_for_report:
                error = "No visit in this period had both photos and a matching Odoo note.\n" + "\n".join(skipped)
                self.write({"kh_site_report_state": "error", "kh_site_report_error": error})
                self._notify_done(
                    requesting_user_id,
                    _("Site report for %s failed: none of the visit folders had both photos and a "
                      "matching note: %s") % (period_label, ", ".join(skipped)),
                )
                return

            visit_dates_label = ", ".join(v["date"].isoformat() for v in visits_for_report)

            client = anthropic.Anthropic(api_key=anthropic_api_key)
            synthesis = claude_synthesis.synthesize_monthly_report(
                client, anthropic_model, self.name, visits_for_report
            )

            project_meta = {
                "project_no": str(self.id),
                "project_name": self.name,
                "location": getattr(self, "x_studio_project_location", "") or "",
                "contractor": getattr(self, "x_studio_contractor_1", "") or "",
                "consultant": getattr(self, "x_studio_consultant", "") or "",
                "client_name": getattr(self, "x_studio_client_name", "") or "",
                "plot_number": getattr(self, "x_studio_plot_number", "") or "",
                "manager_name": self.user_id.name if self.user_id else "",
            }

            docx_bytes = docx_report.build_report_docx(
                project_meta,
                period_label,
                visit_dates_label,
                visits_for_report,
                synthesis,
                logo_path=self._get_logo_path(),
            )

            filename = f"{self.name} - Monthly Report - {period_label}.docx".replace("/", "-")
            attachment = self.env["ir.attachment"].create(
                {
                    "name": filename,
                    "datas": base64.b64encode(docx_bytes),
                    "res_model": "project.project",
                    "res_id": self.id,
                    "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }
            )
            self.write({"kh_site_report_state": "done", "kh_site_report_error": False})
            self.message_post(
                body=_("Monthly site report generated (%s).") % period_label,
                attachment_ids=[attachment.id],
            )
            if skipped:
                self.message_post(body=_("Skipped visit folder(s): %s") % ", ".join(skipped))
            self._notify_done(
                requesting_user_id,
                _('Monthly site report for %s is ready — see the "%s" attachment on this project.')
                % (period_label, filename),
            )

        except Exception as exc:
            _logger.exception("Site report generation failed for project %s", self.name)
            self.write({"kh_site_report_state": "error", "kh_site_report_error": str(exc)})
            self._notify_done(
                requesting_user_id,
                _("Monthly site report generation for %s failed: %s") % (period_label, str(exc)),
            )
