#!/usr/bin/env python3
"""
Yummy Foodie — Google Drive → ShortSync bulk uploader
Uploads all videos from a Drive folder to ShortSync as drafts
with Snapchat Spotlight + Story enabled.
"""

import os
import io
import json
import time
import logging
import requests
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ── Config (set via GitHub Actions secrets / env vars) ──────────────────────
SHORTSYNC_API_KEY   = os.environ["SHORTSYNC_API_KEY"]
GDRIVE_FOLDER_ID    = os.environ["GDRIVE_FOLDER_ID"]          # 1Wdy7YlNauyV9plEubgmW9rxsZyv0hZ0I
SNAPCHAT_CONN_ID    = os.environ["SNAPCHAT_CONNECTION_ID"]    # 6e1fccc4-0095-4195-95fa-58530fa72001
GOOGLE_CREDS_JSON   = os.environ["GOOGLE_CREDENTIALS_JSON"]   # full service-account JSON string

SHORTSYNC_BASE      = "https://api.shortsync.app/v1"
RATE_LIMIT_DELAY    = 1.2   # seconds between ShortSync API calls
MAX_RETRIES         = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Google Drive client ──────────────────────────────────────────────────────
def get_drive_service():
    creds_info = json.loads(GOOGLE_CREDS_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_drive_videos(service, folder_id):
    """Return list of {id, name, size} for all video files in folder."""
    videos = []
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and mimeType contains 'video/'",
            fields="nextPageToken, files(id, name, size, mimeType)",
            pageSize=100,
            pageToken=page_token
        ).execute()
        videos.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.3)
    log.info(f"Found {len(videos)} videos in Drive folder")
    return videos


def download_video_bytes(service, file_id, file_name):
    """Stream-download a Drive file and return bytes."""
    log.info(f"  Downloading: {file_name}")
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request, chunksize=8 * 1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read()


# ── ShortSync helpers ────────────────────────────────────────────────────────
SS_HEADERS = {
    "Authorization": f"Bearer {SHORTSYNC_API_KEY}",
    "Content-Type": "application/json",
}


def ss_get_upload_slot(filename):
    """Reserve an upload slot and get the presigned PUT URL."""
    for attempt in range(MAX_RETRIES):
        r = requests.post(
            f"{SHORTSYNC_BASE}/uploads",
            headers=SS_HEADERS,
            json={"filename": filename},
            timeout=30
        )
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 15))
            log.warning(f"  Rate limited — waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Failed to get upload slot after retries")


def ss_put_video(presigned_url, video_bytes, required_headers=None):
    """PUT video bytes to the presigned S3 URL."""
    headers = {"Content-Type": "video/mp4"}
    if required_headers:
        headers.update(required_headers)
    r = requests.put(presigned_url, data=video_bytes, headers=headers, timeout=300)
    r.raise_for_status()


def ss_create_draft(upload_id, caption=""):
    """Create a ShortSync draft post targeting Snapchat Spotlight + Story."""
    payload = {
        "upload_id": upload_id,
        "publish_mode": "draft",
        "caption": caption,
        "targets": [
            {
                "connection_id": SNAPCHAT_CONN_ID,
                "platform_options": {
                    "snapchat": {
                        "post_to_spotlight": True,
                        "post_to_story": True,
                    }
                }
            }
        ]
    }
    for attempt in range(MAX_RETRIES):
        r = requests.post(
            f"{SHORTSYNC_BASE}/posts",
            headers=SS_HEADERS,
            json=payload,
            timeout=30
        )
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 15))
            log.warning(f"  Rate limited — waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Failed to create draft after retries")


# ── State tracking (so re-runs skip already-uploaded files) ─────────────────
STATE_FILE = "upload_state.json"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"done": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    state = load_state()
    done_ids = set(state["done"])

    drive = get_drive_service()
    videos = list_drive_videos(drive, GDRIVE_FOLDER_ID)

    todo = [v for v in videos if v["id"] not in done_ids]
    log.info(f"To upload: {len(todo)} / {len(videos)} (skipping {len(done_ids)} already done)")

    success = 0
    failed  = 0

    for i, vid in enumerate(todo, 1):
        file_id   = vid["id"]
        file_name = vid["name"]
        log.info(f"[{i}/{len(todo)}] {file_name}")

        try:
            # 1. Download from Drive
            video_bytes = download_video_bytes(drive, file_id, file_name)

            # 2. Reserve ShortSync upload slot
            time.sleep(RATE_LIMIT_DELAY)
            slot = ss_get_upload_slot(file_name)
            upload_id      = slot["upload_id"]
            presigned_url  = slot["presigned_url"]
            required_hdrs  = slot.get("required_headers")

            # 3. PUT bytes to presigned URL
            log.info(f"  Uploading to ShortSync ({len(video_bytes)//1024}KB)...")
            ss_put_video(presigned_url, video_bytes, required_hdrs)

            # 4. Create draft post (Spotlight + Story)
            time.sleep(RATE_LIMIT_DELAY)
            result = ss_create_draft(upload_id, caption="")
            posts = result.get("data", [])
            statuses = [p.get("status") for p in posts]
            log.info(f"  Draft created — statuses: {statuses}")

            # 5. Mark done
            done_ids.add(file_id)
            state["done"].append(file_id)
            save_state(state)
            success += 1

        except Exception as e:
            log.error(f"  FAILED: {e}")
            failed += 1

        # Free memory
        del video_bytes

    log.info(f"\n✅ Done — Success: {success}  Failed: {failed}  Total: {len(todo)}")


if __name__ == "__main__":
    main()
