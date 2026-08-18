#!/usr/bin/env python3
"""
Yummy Foodie — Google Drive → ShortSync bulk uploader
Uses OAuth2 refresh token (no service account needed).
"""

import os, io, json, time, logging, requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ── Config ───────────────────────────────────────────────────────────────────
SHORTSYNC_API_KEY  = os.environ["SHORTSYNC_API_KEY"]
GDRIVE_FOLDER_ID   = os.environ["GDRIVE_FOLDER_ID"]
SNAPCHAT_CONN_ID   = os.environ["SNAPCHAT_CONNECTION_ID"]
GOOGLE_TOKEN_JSON  = os.environ["GOOGLE_TOKEN_JSON"]   # full token JSON string

SHORTSYNC_BASE     = "https://api.shortsync.app/v1"
RATE_LIMIT_DELAY   = 1.2
MAX_RETRIES        = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Google Drive client (OAuth refresh token) ────────────────────────────────
def get_drive_service():
    token_data = json.loads(GOOGLE_TOKEN_JSON)
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    if creds.expired or not creds.valid:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_drive_videos(service, folder_id):
    videos, page_token = [], None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and mimeType contains 'video/'",
            fields="nextPageToken, files(id, name, size, mimeType)",
            pageSize=100, pageToken=page_token
        ).execute()
        videos.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.3)
    log.info(f"Found {len(videos)} videos in Drive folder")
    return videos


def download_video_bytes(service, file_id, file_name):
    log.info(f"  Downloading: {file_name}")
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(
        buf, service.files().get_media(fileId=file_id), chunksize=8*1024*1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read()


# ── ShortSync helpers ─────────────────────────────────────────────────────────
SS_HEADERS = {"Authorization": f"Bearer {SHORTSYNC_API_KEY}", "Content-Type": "application/json"}

def ss_get_upload_slot(filename):
    for _ in range(MAX_RETRIES):
        r = requests.post(f"{SHORTSYNC_BASE}/uploads", headers=SS_HEADERS,
                          json={"filename": filename}, timeout=30)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 15))); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Failed to get upload slot")

def ss_put_video(presigned_url, video_bytes, required_headers=None):
    headers = {"Content-Type": "video/mp4"}
    if required_headers:
        headers.update(required_headers)
    requests.put(presigned_url, data=video_bytes, headers=headers, timeout=300).raise_for_status()

def ss_create_draft(upload_id):
    payload = {
        "upload_id": upload_id,
        "publish_mode": "draft",
        "targets": [{
            "connection_id": SNAPCHAT_CONN_ID,
            "platform_options": {
                "snapchat": {"post_to_spotlight": True, "post_to_story": True}
            }
        }]
    }
    for _ in range(MAX_RETRIES):
        r = requests.post(f"{SHORTSYNC_BASE}/posts", headers=SS_HEADERS,
                          json=payload, timeout=30)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 15))); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Failed to create draft")


# ── State (skip already-uploaded files on re-runs) ───────────────────────────
STATE_FILE = "upload_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f: return json.load(f)
    return {"done": []}

def save_state(state):
    with open(STATE_FILE, "w") as f: json.dump(state, f, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    state = load_state()
    done_ids = set(state["done"])

    drive = get_drive_service()
    videos = list_drive_videos(drive, GDRIVE_FOLDER_ID)
    todo = [v for v in videos if v["id"] not in done_ids]
    log.info(f"To upload: {len(todo)} / {len(videos)} (skipping {len(done_ids)} already done)")

    success = fail = 0
    for i, vid in enumerate(todo, 1):
        log.info(f"[{i}/{len(todo)}] {vid['name']}")
        try:
            video_bytes = download_video_bytes(drive, vid["id"], vid["name"])
            time.sleep(RATE_LIMIT_DELAY)
            slot = ss_get_upload_slot(vid["name"])
            ss_put_video(slot["presigned_url"], video_bytes, slot.get("required_headers"))
            time.sleep(RATE_LIMIT_DELAY)
            result = ss_create_draft(slot["upload_id"])
            statuses = [p.get("status") for p in result.get("data", [])]
            log.info(f"  Draft created — {statuses}")
            done_ids.add(vid["id"])
            state["done"].append(vid["id"])
            save_state(state)
            success += 1
        except Exception as e:
            log.error(f"  FAILED: {e}")
            fail += 1
        del video_bytes

    log.info(f"\n✅ Done — Success: {success}  Failed: {fail}")

if __name__ == "__main__":
    main()
