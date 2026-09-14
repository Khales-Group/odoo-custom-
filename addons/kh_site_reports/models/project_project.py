import base64
import logging
import os
import re

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
PHOTOS_PER_VISIT = 4

ARABIC_MONTHS = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]
ARABIC_WEEKDAYS = {
    "Monday": "الاثنين", "Tuesday": "الثلاثاء", "Wednesday": "الأربعاء",
    "Thursday": "الخميس", "Friday": "الجمعة", "Saturday": "السبت", "Sunday": "الأحد",
}


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

    def action_generate_site_report(self, period_start, period_end, period_label, language="en"):
        """Runs generation synchronously, right in this request — no thread,
        no scheduled action. Takes roughly 15-30s depending on the number of
        visits; the button just shows a loading spinner until it returns
        with either the attached report or a clear error.
        """
        self.ensure_one()
        self.write({"kh_site_report_state": "processing", "kh_site_report_error": False})
        self.message_post(
            body=_("Monthly site report for %s requested by %s — generating now.")
            % (period_label, self.env.user.name)
        )
        self._generate_site_report(period_start, period_end, period_label, self.env.user.id, language)

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
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "img", "khales-logo.png")
        return path if os.path.exists(path) else None

    def _notify_done(self, requesting_user_id, body):
        partner_ids = []
        if requesting_user_id:
            user = self.env["res.users"].browse(requesting_user_id)
            if user.exists() and user.partner_id:
                partner_ids = [user.partner_id.id]
        self.message_post(body=body, partner_ids=partner_ids)

    def _generate_site_report(self, period_start, period_end, period_label, requesting_user_id, language="en"):
        self.ensure_one()
        _logger.info("Site report [%s / %s]: starting", self.name, period_label)

        try:
            from ..lib import docx_report, gemini_synthesis, google_drive

            ICP = self.env["ir.config_parameter"].sudo()
            service_account_json = ICP.get_param("kh_site_reports.google_service_account_json")
            if not service_account_json:
                raise ValueError(
                    "Missing system parameter kh_site_reports.google_service_account_json "
                    "(paste the Google Service Account JSON key there)."
                )
            if not HAS_GENAI:
                raise ValueError("The 'google-genai' Python package is not installed.")
            gemini_api_key = ICP.get_param("gemini.api.key")
            if not gemini_api_key:
                raise ValueError("Missing system parameter gemini.api.key.")
            gemini_model = ICP.get_param("gemini.model") or DEFAULT_GEMINI_MODEL

            _logger.info("Site report [%s / %s]: authenticating with Google Drive", self.name, period_label)
            drive = google_drive.build_drive_client(service_account_json)
            folders = google_drive.resolve_project_folders(
                drive, self.x_studio_all_files_drive_, self.name
            )

            _logger.info("Site report [%s / %s]: listing site-visit folders", self.name, period_label)
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
            no_note = []
            skipped = []
            for folder, visit_date in visits_in_period:
                _logger.info("Site report [%s / %s]: processing visit folder %s", self.name, period_label, folder["name"])
                image_files = google_drive.list_image_files(drive, folder["id"])
                if not image_files:
                    skipped.append(f"{folder['name']} (no photos)")
                    continue

                narrative = self._fetch_visit_note(folder["name"])
                if not narrative:
                    no_note.append(folder["name"])

                sampled = google_drive.sample_across(image_files, PHOTOS_PER_VISIT)
                photos = [google_drive.download_file_bytes(drive, f["id"]) for f in sampled]

                weekday = visit_date.strftime("%A")
                if language == "ar":
                    date_label = (
                        f"زيارة ميدانية — {visit_date.day:02d} {ARABIC_MONTHS[visit_date.month - 1]} "
                        f"{visit_date.year} ({ARABIC_WEEKDAYS[weekday]})"
                    )
                else:
                    date_label = f"Site Visit — {visit_date.strftime('%d %B %Y')} ({weekday})"
                # A visit is included in the report (photos always shown) as long as it has
                # photos — a missing chatter note (project-watcher.js hasn't caught up yet)
                # only means that visit contributes nothing to the written summary below,
                # it does not exclude the visit's photos from the report.
                visits_for_report.append(
                    {
                        "date": visit_date,
                        "date_label": date_label,
                        "narrative": narrative,
                        "photos": photos,
                    }
                )

            if not visits_for_report:
                error = "No visit folder in this period had any photos.\n" + "\n".join(skipped)
                self.write({"kh_site_report_state": "error", "kh_site_report_error": error})
                self._notify_done(
                    requesting_user_id,
                    _("Site report for %s failed: no visit folders in this period had photos: %s")
                    % (period_label, ", ".join(skipped)),
                )
                return

            visit_dates_label = ", ".join(v["date"].isoformat() for v in visits_for_report)
            narrated_visits = [v for v in visits_for_report if v["narrative"]]
            client = genai.Client(api_key=gemini_api_key)

            if narrated_visits:
                _logger.info("Site report [%s / %s]: synthesizing with Gemini", self.name, period_label)
                synthesis = gemini_synthesis.synthesize_monthly_report(
                    client, gemini_model, self.name, narrated_visits, language
                )
            elif language == "ar":
                synthesis = {
                    "site_update_summary": (
                        "لم تتوفر ملاحظات مكتوبة للزيارات خلال هذه الفترة — يُرجى مراجعة صور الموقع "
                        "المرفقة أدناه للاطلاع على سير العمل هذا الشهر."
                    ),
                    "planned_activities": [],
                    "recommendations": "لا توجد ملاحظات زيارة متاحة لمراجعة أي إجراءات مطلوبة من المالك خلال هذه الفترة.",
                }
            else:
                synthesis = {
                    "site_update_summary": (
                        "No written visit notes were available for this period — see the attached "
                        "site photos below for this month's progress."
                    ),
                    "planned_activities": [],
                    "recommendations": "No visit notes were available to review for owner actions this period.",
                }

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

            if language == "ar":
                try:
                    _logger.info("Site report [%s / %s]: localizing project details with Gemini", self.name, period_label)
                    project_meta = gemini_synthesis.localize_project_meta(client, gemini_model, project_meta)
                except Exception:
                    _logger.exception(
                        "Site report [%s / %s]: Arabic localization of project details failed, "
                        "falling back to the raw values", self.name, period_label,
                    )

            _logger.info("Site report [%s / %s]: building .docx", self.name, period_label)
            docx_bytes = docx_report.build_report_docx(
                project_meta,
                period_label,
                visit_dates_label,
                visits_for_report,
                synthesis,
                logo_path=self._get_logo_path(),
                language=language,
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
                self.message_post(body=_("Skipped visit folder(s) with no photos: %s") % ", ".join(skipped))
            if no_note:
                self.message_post(
                    body=_("Visit folder(s) included with photos only (no chatter note found, so not "
                           "reflected in the written summary): %s") % ", ".join(no_note)
                )
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
