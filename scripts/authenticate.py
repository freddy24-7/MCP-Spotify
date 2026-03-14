"""
scripts/authenticate.py
=======================
One-time Spotify OAuth flow.

Run this once to generate the .cache token file that the MCP server reuses.
Token refresh is automatic from then on — you won't need to run this again
unless you delete .cache or revoke the app's access.

Usage
-----
    uv run python scripts/authenticate.py
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

# Make sure the project root is on sys.path so we can import src/
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import os

from spotipy.oauth2 import SpotifyOAuth

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "")
if not REDIRECT_URI:
    print("ERROR: SPOTIFY_REDIRECT_URI is not set in .env")
    sys.exit(1)

SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "playlist-read-private "
    "playlist-read-collaborative"
)

if not CLIENT_ID or CLIENT_ID == "your_client_id_here":
    print("ERROR: SPOTIFY_CLIENT_ID is not set in .env")
    sys.exit(1)

print("\n" + "=" * 60)
print("CONFIG CHECK — verify these match your Spotify Dashboard")
print("=" * 60)
print(f"  Client ID    : {CLIENT_ID[:8]}{'*' * (len(CLIENT_ID) - 8)}")
print(f"  Redirect URI : {REDIRECT_URI}")
print("=" * 60)

auth_manager = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPES,
    open_browser=False,
)

auth_url = auth_manager.get_authorize_url()

print("\n" + "=" * 60)
print("STEP 1 — Open this URL in your browser:")
print("=" * 60)
print(f"\n{auth_url}\n")

try:
    webbrowser.open(auth_url)
    print("(Browser opened automatically — if not, copy the URL above.)\n")
except Exception:
    print("(Could not open browser automatically — copy the URL above.)\n")

print("=" * 60)
print("STEP 2 — After you approve access, Spotify will redirect")
print(f"         your browser to:  {REDIRECT_URI}?code=...")
print()
print("         The page will show an error — that is EXPECTED.")
print("         Copy the FULL URL from your browser's address bar.")
print("=" * 60)
redirected_url = input("\nPaste the full redirect URL here: ").strip()

try:
    code = auth_manager.parse_response_code(redirected_url)
    token_info = auth_manager.get_access_token(code, as_dict=False)
    print("\n✓  Authentication successful! Token cached in .cache")
    print("   You can now run the MCP server:\n")
    print("   uv run fastmcp run src/server.py\n")
except Exception as exc:
    print(f"\nERROR: Could not exchange code for token: {exc}")
    print("Make sure the redirect URI in your .env matches exactly what")
    print("is registered in your Spotify Developer Dashboard.")
    sys.exit(1)
