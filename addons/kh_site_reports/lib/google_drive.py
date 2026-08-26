import datetime
import io
import json
import re

import httplib2
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
# httplib2 has no default timeout — without one, a stalled connection (e.g. during
# the service-account token refresh) hangs forever instead of raising an error.
REQUEST_TIMEOUT_SECONDS = 30

_FOLDER_LINK_RE = re.compile(r'href="([^"]+)"[^>]*>([^<]+)<', re.IGNORECASE)
_FOLDER_ID_RE = re.compile(r"/folders/([a-zA-Z0-9_-]+)")

DATE_PATTERNS = [
    re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})$"),
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"),
]


def build_drive_client(service_account_json):
    """service_account_json: the raw JSON key content (str) for a Google
    Service Account that has been shared (as Viewer) on the relevant Drive
    folders. Using a service account avoids the 7-day refresh-token expiry
    that applies to a personal OAuth app left in "Testing" publishing mode.
    """
    info = json.loads(service_account_json)
    credentials = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
    authorized_http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=REQUEST_TIMEOUT_SECONDS))
    return build("drive", "v3", http=authorized_http, cache_discovery=False)


def extract_folder_by_label(html, label):
    """Parity with project-watcher.js's extractFolderByLabel: scans the
    project's x_studio_all_files_drive_ HTML field for a link whose visible
    text contains `label`, and returns the Drive folder id from its href.
    """
    if not html:
        return None
    keyword = label.lower()
    for href, text in _FOLDER_LINK_RE.findall(html):
        if keyword in text.lower():
            m = _FOLDER_ID_RE.search(href)
            if m:
                return m.group(1)
    return None


def find_folder(drive, parent_id, keyword):
    resp = drive.files().list(
        q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id,name)",
        pageSize=100,
    ).execute()
    keyword = keyword.lower()
    for f in resp.get("files", []):
        if keyword in f["name"].lower():
            return f
    return None


def resolve_project_folders(drive, drive_field_html, project_name):
    supervision_id = extract_folder_by_label(drive_field_html, "Site Supervision")
    if not supervision_id:
        raise ValueError(f'Project "{project_name}" has no "Site Supervision" link in its Drive field.')

    site_photos = find_folder(drive, supervision_id, "Site Photos")
    if not site_photos:
        raise ValueError(f'No "Site Photos" folder found under Site Supervision for "{project_name}".')

    return {"site_photos_id": site_photos["id"]}


def list_subfolders(drive, parent_id):
    resp = drive.files().list(
        q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id,name)",
        pageSize=500,
    ).execute()
    return resp.get("files", [])


def list_image_files(drive, parent_id):
    resp = drive.files().list(
        q=f"'{parent_id}' in parents and mimeType contains 'image/' and trashed=false",
        fields="files(id,name,mimeType)",
        pageSize=500,
    ).execute()
    return resp.get("files", [])


def download_file_bytes(drive, file_id):
    request = drive.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def parse_folder_date(name):
    trimmed = (name or "").strip()
    for pattern in DATE_PATTERNS:
        m = pattern.match(trimmed)
        if m:
            year, month, day = (int(x) for x in m.groups())
            try:
                return datetime.date(year, month, day)
            except ValueError:
                return None
    return None


def sample_across(items, n):
    """Evenly sample up to n items across the full list (not just the first
    n), so a visit with many photos still shows a spread of the whole visit.
    """
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]
