#!/usr/bin/env python3
"""
Run this ONCE locally to get your Google OAuth token JSON.
It opens a browser for you to log in, then prints the token
JSON string to paste into GitHub Secrets as GOOGLE_TOKEN_JSON.

Usage:
  pip install google-auth-oauthlib
  python get_token.py
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow

# These are Google's own public OAuth client credentials for installed apps
# Safe to use - they only grant access to YOUR account after YOU log in
CLIENT_CONFIG = {
    "installed": {
        "client_id": "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
        "client_secret": "d-FL95Q19q7MQmFpd7hHD0Ty",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"]
    }
}

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, SCOPES)
creds = flow.run_local_server(port=0)

token_data = {
    "token": creds.token,
    "refresh_token": creds.refresh_token,
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
}

print("\n" + "="*60)
print("COPY THIS ENTIRE STRING INTO GITHUB SECRET: GOOGLE_TOKEN_JSON")
print("="*60)
print(json.dumps(token_data))
print("="*60 + "\n")
