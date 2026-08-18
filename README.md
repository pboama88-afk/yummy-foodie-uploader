# Yummy Foodie — Bulk Upload to ShortSync

Automatically uploads all videos from a Google Drive folder to ShortSync as drafts,
with **Snapchat Spotlight + Story** enabled on every post.

---

## Setup (one-time, ~10 minutes)

### Step 1 — Create a Google Cloud Service Account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Enable the **Google Drive API**: APIs & Services → Enable APIs → search "Drive API" → Enable
4. Go to **IAM & Admin → Service Accounts** → Create Service Account
   - Name: `yummy-uploader`
   - Role: `Viewer` (read-only)
5. Click the service account → **Keys** tab → **Add Key → JSON**
6. A JSON file downloads — keep it safe, you'll paste its contents as a secret

### Step 2 — Share your Drive folder with the service account

1. Open the downloaded JSON file — copy the `client_email` value (looks like `yummy-uploader@your-project.iam.gserviceaccount.com`)
2. In Google Drive, right-click the **JAB's TV Catch and Cook - Shorts** folder → Share
3. Paste the `client_email` and give **Viewer** access

### Step 3 — Add GitHub Secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

Add these four secrets:

| Secret name | Value |
|---|---|
| `SHORTSYNC_API_KEY` | `ss_live_X9mIKtqvcP3NKMmJCSAGQ2j3MIaUbpSP` |
| `GDRIVE_FOLDER_ID` | `1Wdy7YlNauyV9plEubgmW9rxsZyv0hZ0I` |
| `SNAPCHAT_CONNECTION_ID` | `6e1fccc4-0095-4195-95fa-58530fa72001` |
| `GOOGLE_CREDENTIALS_JSON` | Paste the entire contents of the downloaded JSON key file |

### Step 4 — Push these files to your repo

```
your-repo/
├── .github/
│   └── workflows/
│       └── upload.yml
├── upload_to_shortsync.py
├── requirements.txt
└── README.md
```

### Step 5 — Run it

1. Go to your repo on GitHub
2. Click **Actions** tab
3. Click **Yummy Foodie — Bulk Upload to ShortSync**
4. Click **Run workflow** → **Run workflow**

That's it. Watch the logs — it processes all 637 videos unattended.
Re-runs automatically skip already-completed files (state is cached between runs).

---

## What it does

- Reads all video files from your Drive folder
- For each video:
  1. Downloads it from Google Drive
  2. Reserves a ShortSync upload slot
  3. Uploads the video bytes
  4. Creates a **draft** post targeting **Snapchat Spotlight + Story**
- Saves progress so re-runs never duplicate
- Respects ShortSync rate limits (60 req/min)

## After uploading

Once all videos are in your Yummy Foodie ShortSync drafts, ping Claude to schedule them all 6/day.
