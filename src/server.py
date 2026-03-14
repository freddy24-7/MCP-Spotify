"""
Spotify MCP Server
==================
A FastMCP 3.0 server that exposes Spotify controls as Model Context Protocol tools.

Transport : stdio (default) – configure via fastmcp.json
Auth      : Spotify OAuth 2.0 with automatic token refresh via spotipy.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import spotipy
from fastmcp import FastMCP
from spotipy.oauth2 import SpotifyOAuth

# Ensure the project root is on sys.path so `config.settings` is importable
# regardless of the working directory chosen by the MCP host.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config.settings import settings  # noqa: E402  (import after path fix)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("spotify-mcp")

# ---------------------------------------------------------------------------
# OAuth scopes
# ---------------------------------------------------------------------------
SPOTIFY_SCOPES: str = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "playlist-read-private "
    "playlist-read-collaborative "
    "playlist-modify-private "
    "playlist-modify-public "
    "user-read-recently-played "
    "user-top-read"
)

# ---------------------------------------------------------------------------
# Multi-user auth state
# ---------------------------------------------------------------------------

# Name of the currently active user profile.  Mutated by switch_user().
_current_user: str = settings.current_user_name

# Per-user SpotifyOAuth managers built lazily; keyed by profile name.
_auth_managers: dict[str, SpotifyOAuth] = {}


def _cache_path_for(user: str) -> str:
    """Return the absolute path to the token-cache file for *user*."""
    filename = ".cache" if user == "default" else f".cache-{user}"
    return os.path.join(_PROJECT_ROOT, filename)


def _build_auth_manager(user: str) -> SpotifyOAuth:
    """
    Return (or lazily build) a ``SpotifyOAuth`` manager for *user*.

    Each user gets their own manager pointing at a distinct cache file so
    tokens never collide across profiles.

    Raises
    ------
    EnvironmentError
        If Spotify credentials are still at their placeholder values.
    """
    if user not in _auth_managers:
        if settings.spotify_client_id == "YOUR_CLIENT_ID_HERE":
            raise EnvironmentError(
                "SPOTIFY_CLIENT_ID is not configured.  "
                "Copy .env.example → .env and fill in your credentials."
            )
        _auth_managers[user] = SpotifyOAuth(
            client_id=settings.spotify_client_id,
            client_secret=settings.spotify_client_secret,
            redirect_uri=settings.spotify_redirect_uri,
            scope=SPOTIFY_SCOPES,
            cache_path=_cache_path_for(user),
            open_browser=False,
        )
    return _auth_managers[user]


def get_spotify_client() -> spotipy.Spotify:
    """
    Return an authenticated ``spotipy.Spotify`` instance for the current user.

    Token refresh is handled transparently by the underlying SpotifyOAuth
    manager – every call through this client will use a valid access token.
    """
    return spotipy.Spotify(auth_manager=_build_auth_manager(_current_user))


def _uri_to_id(uri_or_id: str) -> str:
    """Extract the bare Spotify ID from a full URI, or return as-is."""
    # "spotify:track:4iV5W9uYEdYUVa79Axb7Rh" → "4iV5W9uYEdYUVa79Axb7Rh"
    return uri_or_id.split(":")[-1] if ":" in uri_or_id else uri_or_id


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name=settings.server_name,
    instructions=(
        "Agentic Spotify curation: inspect and control playback, create and "
        "manage playlists, queue tracks, fetch recommendations, and switch "
        "between family user profiles."
    ),
)

# ---------------------------------------------------------------------------
# Playback tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_current_track() -> dict[str, Any]:
    """
    Retrieve information about the track currently playing on Spotify.

    Queries the active Spotify device for the currently playing item and
    returns structured metadata including the track URI, which is needed by
    other tools such as ``add_to_queue`` and ``get_recommendations``.

    Returns
    -------
    dict
        Keys: ``is_playing``, ``track_name``, ``artists``, ``album``,
        ``duration_ms``, ``progress_ms``, ``track_url``, ``track_uri``.
        Returns ``{"is_playing": False}`` when nothing is playing or no
        active device is found.

    Raises
    ------
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    sp = get_spotify_client()
    playback = sp.current_playback()

    if not playback or not playback.get("item"):
        log.info("get_current_track: nothing playing")
        return {"is_playing": False}

    item = playback["item"]
    return {
        "is_playing": playback.get("is_playing", False),
        "track_name": item.get("name"),
        "artists": [a["name"] for a in item.get("artists", [])],
        "album": item.get("album", {}).get("name"),
        "duration_ms": item.get("duration_ms"),
        "progress_ms": playback.get("progress_ms"),
        "track_url": item.get("external_urls", {}).get("spotify"),
        "track_uri": item.get("uri"),
    }


@mcp.tool()
def play_pause(action: str = "toggle") -> dict[str, str]:
    """
    Control Spotify playback – play, pause, or toggle the current state.

    Parameters
    ----------
    action : str, optional
        One of ``"play"``, ``"pause"``, or ``"toggle"`` (default).

        - ``"play"``   – Resume or start playback on the active device.
        - ``"pause"``  – Pause playback on the active device.
        - ``"toggle"`` – Pause if currently playing; play if currently paused.

    Returns
    -------
    dict
        ``{"status": "playing" | "paused" | "no_active_device"}``

    Raises
    ------
    ValueError
        If ``action`` is not one of the accepted values.
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    valid_actions = {"play", "pause", "toggle"}
    if action not in valid_actions:
        raise ValueError(f"action must be one of {valid_actions}, got {action!r}")

    sp = get_spotify_client()
    playback = sp.current_playback()

    if not playback:
        log.warning("play_pause: no active Spotify device found")
        return {"status": "no_active_device"}

    currently_playing = playback.get("is_playing", False)

    if action == "toggle":
        action = "pause" if currently_playing else "play"

    if action == "play":
        sp.start_playback()
        log.info("play_pause: playback started")
        return {"status": "playing"}
    else:
        sp.pause_playback()
        log.info("play_pause: playback paused")
        return {"status": "paused"}


@mcp.tool()
def skip_track(direction: str = "next") -> dict[str, str]:
    """
    Skip to the next or previous track on the active Spotify device.

    Parameters
    ----------
    direction : str, optional
        ``"next"`` (default) to skip forward, ``"previous"`` to go back.

    Returns
    -------
    dict
        ``{"status": "skipped_next" | "skipped_previous" | "no_active_device"}``

    Raises
    ------
    ValueError
        If ``direction`` is not ``"next"`` or ``"previous"``.
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    if direction not in {"next", "previous"}:
        raise ValueError(f"direction must be 'next' or 'previous', got {direction!r}")

    sp = get_spotify_client()
    playback = sp.current_playback()

    if not playback:
        return {"status": "no_active_device"}

    if direction == "next":
        sp.next_track()
        log.info("skip_track: skipped to next")
        return {"status": "skipped_next"}
    else:
        sp.previous_track()
        log.info("skip_track: skipped to previous")
        return {"status": "skipped_previous"}


# ---------------------------------------------------------------------------
# Queue tools
# ---------------------------------------------------------------------------


@mcp.tool()
def add_to_queue(uri: str) -> dict[str, str]:
    """
    Add a track to the user's active Spotify playback queue.

    Parameters
    ----------
    uri : str
        Spotify track URI (``spotify:track:<id>``) or bare track ID.

    Returns
    -------
    dict
        ``{"status": "queued", "uri": "<full_spotify_uri>"}``

    Raises
    ------
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    track_id = _uri_to_id(uri)
    full_uri = f"spotify:track:{track_id}"

    sp = get_spotify_client()
    sp.add_to_queue(full_uri)
    log.info("add_to_queue: queued %s", full_uri)
    return {"status": "queued", "uri": full_uri}


@mcp.tool()
def get_recommendations(seed_tracks: list[str], limit: int = 5) -> dict[str, Any]:
    """
    Fetch track recommendations based on a list of seed track URIs or IDs.

    Uses the Spotify recommendations endpoint to suggest tracks sonically
    similar to the seeds – useful for building radio-style queues or
    auto-filling a new playlist.

    Note
    ----
    Spotify deprecated the public recommendations endpoint in November 2024.
    This tool works for apps created before that date or granted continued
    access by Spotify.

    Parameters
    ----------
    seed_tracks : list[str]
        Spotify track URIs or bare IDs to seed from.  The API accepts at most
        5 seeds; excess values are silently truncated.
    limit : int, optional
        Number of recommendations to return (1–100, default: 5).

    Returns
    -------
    dict
        Keys:

        - ``seeds`` (list[str]): Track IDs actually sent to the API.
        - ``tracks`` (list[dict]): Each entry has ``track_name``, ``artists``,
          ``track_uri``, ``track_url``.

    Raises
    ------
    ValueError
        If ``seed_tracks`` is empty or ``limit`` is out of range.
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    if not seed_tracks:
        raise ValueError("seed_tracks must contain at least one track URI or ID.")
    if not 1 <= limit <= 100:
        raise ValueError(f"limit must be between 1 and 100, got {limit}")

    seed_ids = [_uri_to_id(t) for t in seed_tracks[:5]]
    sp = get_spotify_client()
    result = sp.recommendations(seed_tracks=seed_ids, limit=limit)

    tracks = [
        {
            "track_name": t["name"],
            "artists": [a["name"] for a in t["artists"]],
            "track_uri": t["uri"],
            "track_url": t["external_urls"]["spotify"],
        }
        for t in result.get("tracks", [])
    ]

    log.info("get_recommendations: returned %d track(s)", len(tracks))
    return {"seeds": seed_ids, "tracks": tracks}


# ---------------------------------------------------------------------------
# Playlist tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_user_playlists(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """
    Fetch a paginated list of the current user's Spotify playlists.

    Parameters
    ----------
    limit : int, optional
        Maximum number of playlists to return (1–50, default: 20).
    offset : int, optional
        Zero-based index of the first playlist to return (default: 0).

    Returns
    -------
    dict
        Keys: ``total``, ``limit``, ``offset``, ``playlists``.
        Each playlist entry has: ``id``, ``name``, ``owner``,
        ``tracks_total``, ``public``, ``url``.

    Raises
    ------
    ValueError
        If ``limit`` is outside [1, 50].
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    if not 1 <= limit <= 50:
        raise ValueError(f"limit must be between 1 and 50, got {limit}")

    sp = get_spotify_client()
    result = sp.current_user_playlists(limit=limit, offset=offset)

    playlists = [
        {
            "id": p["id"],
            "name": p["name"],
            "owner": p["owner"]["display_name"],
            "tracks_total": p["tracks"]["total"],
            "public": p.get("public"),
            "url": p["external_urls"]["spotify"],
        }
        for p in result.get("items", [])
    ]

    log.info("get_user_playlists: returned %d playlist(s)", len(playlists))
    return {
        "total": result.get("total", 0),
        "limit": limit,
        "offset": offset,
        "playlists": playlists,
    }


@mcp.tool()
def create_playlist(name: str, description: str = "") -> dict[str, Any]:
    """
    Create a new empty private playlist for the current user.

    Parameters
    ----------
    name : str
        Display name for the new playlist.  Must not be blank.
    description : str, optional
        Short description shown in Spotify clients (default: empty string).

    Returns
    -------
    dict
        Keys: ``id``, ``name``, ``url``.

    Raises
    ------
    ValueError
        If ``name`` is blank.
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    if not name.strip():
        raise ValueError("Playlist name must not be blank.")

    sp = get_spotify_client()
    playlist = sp.current_user_playlist_create(
        name=name.strip(),
        public=False,
        description=description,
    )

    log.info("create_playlist: created '%s' (%s)", playlist["name"], playlist["id"])
    return {
        "id": playlist["id"],
        "name": playlist["name"],
        "url": playlist["external_urls"]["spotify"],
    }


@mcp.tool()
def add_to_playlist(playlist_id: str, track_uris: list[str]) -> dict[str, Any]:
    """
    Add one or more tracks to an existing Spotify playlist.

    Handles batching automatically: the Spotify API limits each request to
    100 tracks, so larger lists are split into sequential calls.

    Parameters
    ----------
    playlist_id : str
        Spotify playlist ID or full URI.
    track_uris : list[str]
        Spotify track URIs (``spotify:track:<id>``) or bare track IDs.

    Returns
    -------
    dict
        Keys: ``playlist_id`` (str), ``tracks_added`` (int).

    Raises
    ------
    ValueError
        If ``track_uris`` is empty.
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    if not track_uris:
        raise ValueError("track_uris must contain at least one URI.")

    pid = _uri_to_id(playlist_id)
    full_uris = [f"spotify:track:{_uri_to_id(u)}" for u in track_uris]

    sp = get_spotify_client()
    for i in range(0, len(full_uris), 100):  # API max: 100 per request
        sp.playlist_add_items(pid, full_uris[i : i + 100])

    log.info("add_to_playlist: added %d track(s) to %s", len(full_uris), pid)
    return {"playlist_id": pid, "tracks_added": len(full_uris)}


@mcp.tool()
def search_and_add(query: str, playlist_id: str) -> dict[str, Any]:
    """
    Search for a track and add the top result to a playlist in one step.

    Combines a Spotify track search with a playlist-add so the agent can
    fulfil requests like "add Shape of You to my Chill Mix" without a
    separate search step.

    Parameters
    ----------
    query : str
        Free-text search query (e.g. ``"Shape of You Ed Sheeran"``).
    playlist_id : str
        Spotify playlist ID or full URI to add the track to.

    Returns
    -------
    dict
        Keys: ``track_name``, ``artists``, ``track_uri``, ``playlist_id``.

    Raises
    ------
    ValueError
        If ``query`` is blank or the search returns no results.
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    if not query.strip():
        raise ValueError("query must not be blank.")

    sp = get_spotify_client()
    results = sp.search(q=query.strip(), type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])

    if not items:
        raise ValueError(f"No tracks found for query: {query!r}")

    track = items[0]
    uri = track["uri"]
    pid = _uri_to_id(playlist_id)

    sp.playlist_add_items(pid, [uri])

    log.info("search_and_add: added '%s' to playlist %s", track["name"], pid)
    return {
        "track_name": track["name"],
        "artists": [a["name"] for a in track["artists"]],
        "track_uri": uri,
        "playlist_id": pid,
    }


# ---------------------------------------------------------------------------
# Multi-user tool
# ---------------------------------------------------------------------------


@mcp.tool()
def switch_user(name: str) -> dict[str, str]:
    """
    Switch the active Spotify user profile.

    Updates the server's internal state so all subsequent tool calls use the
    token cache for *name*.  Each user's token is stored in a separate file
    (``.cache-<name>`` in the project root), enabling seamless switching
    between family or shared accounts without re-authentication — provided
    the cache file for *name* already exists.

    This is the groundwork for multi-user support when the server is deployed
    to a remote host such as Railway.

    Parameters
    ----------
    name : str
        User profile name.  Pass ``"default"`` to return to the primary
        account.  Any other value must have a corresponding ``.cache-<name>``
        file in the project root (created by a prior OAuth login).

    Returns
    -------
    dict
        ``{"previous_user": str, "current_user": str}``

    Raises
    ------
    ValueError
        If ``name`` is blank, or if no token cache exists for that profile.
    """
    global _current_user

    target = name.strip()
    if not target:
        raise ValueError("name must not be blank.")

    cache = _cache_path_for(target)
    if target != "default" and not os.path.exists(cache):
        raise ValueError(
            f"No token cache found for user {target!r} (expected {cache!r}).  "
            "The user must authenticate at least once before switching."
        )

    previous = _current_user
    _current_user = target
    log.info("switch_user: %s → %s", previous, target)
    return {"previous_user": previous, "current_user": _current_user}


# ---------------------------------------------------------------------------
# Resource: interactive now-playing UI card
# ---------------------------------------------------------------------------


@mcp.resource("ui://now-playing")
def now_playing_ui() -> str:
    """
    An HTML snippet showing the current track with interactive control buttons.

    Returns a self-contained card with Skip, Play/Pause, and Queue buttons.
    Buttons carry ``data-mcp-tool`` / ``data-mcp-args`` attributes so a thin
    client (mobile app, web shell) can dispatch the corresponding MCP tool
    calls without custom JavaScript.

    Returns
    -------
    str
        Self-contained HTML fragment with inline CSS.  Returns a plain
        ``<p>`` element when nothing is playing.
    """
    sp = get_spotify_client()
    playback = sp.current_playback()

    if not playback or not playback.get("item"):
        return (
            "<p style='font-family:sans-serif;color:#888'>"
            "Nothing is playing right now.</p>"
        )

    item = playback["item"]
    track_name = item.get("name", "Unknown")
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    album = item.get("album", {}).get("name", "")
    art_url = (item.get("album", {}).get("images") or [{}])[0].get("url", "")
    track_uri = item.get("uri", "")
    is_playing = playback.get("is_playing", False)
    play_label = "⏸ Pause" if is_playing else "▶ Play"

    art_html = f'<img src="{art_url}" style="width:100%;display:block">' if art_url else ""

    return f"""
<div style="font-family:sans-serif;max-width:360px;border-radius:12px;
            overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,.18);
            background:#1a1a1a;color:#fff">
  {art_html}
  <div style="padding:16px">
    <div style="font-size:18px;font-weight:700;margin-bottom:4px">{track_name}</div>
    <div style="font-size:14px;color:#b3b3b3">{artists}</div>
    <div style="font-size:12px;color:#666;margin-top:2px">{album}</div>
    <div style="display:flex;gap:10px;margin-top:16px">
      <button
        data-mcp-tool="play_pause"
        data-mcp-args='{{"action":"toggle"}}'
        style="flex:1;padding:10px;border:none;border-radius:8px;
               background:#1db954;color:#fff;font-weight:700;cursor:pointer">
        {play_label}
      </button>
      <button
        data-mcp-tool="skip_track"
        data-mcp-args='{{"direction":"next"}}'
        style="flex:1;padding:10px;border:none;border-radius:8px;
               background:#333;color:#fff;font-weight:700;cursor:pointer">
        ⏭ Skip
      </button>
      <button
        data-mcp-tool="add_to_queue"
        data-mcp-args='{{"uri":"{track_uri}"}}'
        style="flex:1;padding:10px;border:none;border-radius:8px;
               background:#333;color:#fff;font-weight:700;cursor:pointer">
        ＋ Queue
      </button>
    </div>
  </div>
</div>
""".strip()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Running directly → stdio transport (matches fastmcp.json config).
    # Use `fastmcp run src/server.py` for the standard launcher.
    mcp.run(transport="stdio")
