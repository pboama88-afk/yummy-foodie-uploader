#!/usr/bin/env python3
"""
Yummy Foodie — Google Drive → ShortSync bulk uploader
Uses OAuth2 refresh token. Handles SSL timeouts, saves state correctly.
"""

import os, io, json, time, logging, requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

SHORTSYNC_API_KEY  = os.environ["SHORTSYNC_API_KEY"]
GDRIVE_FOLDER_ID   = os.environ["GDRIVE_FOLDER_ID"]
SNAPCHAT_CONN_ID   = os.environ["SNAPCHAT_CONNECTION_ID"]
GOOGLE_TOKEN_JSON  = os.environ["GOOGLE_TOKEN_JSON"]

SHORTSYNC_BASE     = "https://api.shortsync.app/v1"
RATE_LIMIT_DELAY   = 1.5
MAX_RETRIES        = 4
DOWNLOAD_TIMEOUT   = 600  # 10 min per file

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

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
    if not creds.valid:
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
    for attempt in range(MAX_RETRIES):
        try:
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(
                buf, service.files().get_media(fileId=file_id), chunksize=16*1024*1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            buf.seek(0)
            return buf.read()
        except Exception as e:
            log.warning(f"  Download attempt {attempt+1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(10 * (attempt + 1))
            else:
                raise

SS_HEADERS = {"Authorization": f"Bearer {SHORTSYNC_API_KEY}", "Content-Type": "application/json"}

def ss_get_upload_slot(filename):
    for attempt in range(MAX_RETRIES):
        r = requests.post(f"{SHORTSYNC_BASE}/uploads", headers=SS_HEADERS,
                          json={"filename": filename}, timeout=30)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 20))); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Failed to get upload slot")

def ss_put_video(presigned_url, video_bytes, required_headers=None):
    headers = {"Content-Type": "video/mp4"}
    if required_headers:
        headers.update(required_headers)
    for attempt in range(MAX_RETRIES):
        try:
            requests.put(presigned_url, data=video_bytes, headers=headers, timeout=600).raise_for_status()
            return
        except Exception as e:
            log.warning(f"  Upload attempt {attempt+1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(10)
            else:
                raise

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
    for attempt in range(MAX_RETRIES):
        r = requests.post(f"{SHORTSYNC_BASE}/posts", headers=SS_HEADERS,
                          json=payload, timeout=30)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 20))); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Failed to create draft")

STATE_FILE = "upload_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
            log.info(f"Loaded state: {len(state['done'])} already done")
            return state
    log.info("No state file found — starting fresh")
    return {"done": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

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
        video_bytes = None
        try:
            video_bytes = download_video_bytes(drive, vid["id"], vid["name"])
            time.sleep(RATE_LIMIT_DELAY)
            slot = ss_get_upload_slot(vid["name"])
            ss_put_video(slot["presigned_url"], video_bytes, slot.get("required_headers"))
            time.sleep(RATE_LIMIT_DELAY)
            result = ss_create_draft(slot["upload_id"])
            statuses = [p.get("status") for p in result.get("data", [])]
            log.info(f"  ✅ Draft created — {statuses}")
            done_ids.add(vid["id"])
            state["done"].append(vid["id"])
            save_state(state)
            success += 1
        except Exception as e:
            log.error(f"  ❌ FAILED: {e}")
            fail += 1
        finally:
            if video_bytes is not None:
                del video_bytes

    log.info(f"\n✅ Done — Success: {success}  Failed: {fail}  Already done: {len(done_ids) - success}")

if __name__ == "__main__":
    main()
