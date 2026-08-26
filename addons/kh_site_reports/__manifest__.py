{
    "name": "Site Progress Reports",
    "version": "19.0.1.0.0",
    "summary": "One-click monthly site-progress Word report, generated in the background",
    "description": """
Site Progress Reports
======================

Adds a "Request Site Report" button on the Project form. Clicking it opens
a small wizard to pick the report month, then generation starts immediately
in the background (no scheduled action/polling — one background thread per
request):

- Resolves the project's Google Drive "Site Photos" folder from its
  x_studio_all_files_drive_ field.
- Finds dated site-visit subfolders that fall within the picked month.
- Reuses the AI-written visit note already posted on the project's chatter
  (by the external site-visit watcher) as that visit's narrative — no new
  photo analysis, just a single cheap text-only Claude call to synthesize
  the month's notes into a summary, planned activities, and
  recommendations.
- Builds a .docx matching the Khales "Monthly Report" template and attaches
  it directly to the project's chatter, then notifies the requesting user.

Setup required before use:
- System Parameter "kh_site_reports.google_service_account_json": paste the
  JSON key of a Google Service Account that has been shared (Viewer) on the
  project's Drive "Site Supervision" folder.
- System Parameter "mcp_server.anthropic_api_key" (reused from the existing
  AI Project Manager setup) must be configured.
- Optionally place the company logo at
  static/img/khales_logo.png inside this module for it to appear on the
  report's cover page.
    """,
    "author": "Khales Group",
    "category": "Project",
    "depends": ["project", "mail"],
    "external_dependencies": {
        "python": ["anthropic", "docx", "googleapiclient", "google", "PIL"],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/site_report_wizard_views.xml",
        "views/project_project_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
