"""One-time helper: obtain a YouTube OAuth refresh token on your own computer.

Download an OAuth 2.0 Desktop app client JSON from Google Cloud Console and save it
as client_secret.json beside this script. Do not commit that file.
"""
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_FILE = Path(__file__).with_name("client_secret.json")

if not CLIENT_FILE.exists():
    raise SystemExit(
        "Missing client_secret.json. Download the OAuth client JSON for a Desktop app "
        "from Google Cloud Console and place it beside this script."
    )

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
if not credentials.refresh_token:
    raise SystemExit(
        "Google did not return a refresh token. Revoke this app's access in your Google Account, "
        "then run again and consent with prompt=consent."
    )
print("\nCopy this value into GitHub Actions secret YOUTUBE_REFRESH_TOKEN. Keep it private:\n")
print(credentials.refresh_token)
print("\nClient ID:", json.loads(CLIENT_FILE.read_text(encoding="utf-8"))["installed"]["client_id"])
