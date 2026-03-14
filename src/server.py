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
from functools import lru_cache
from typing import Any

import spotipy
from dotenv import load_dotenv
from fastmcp import FastMCP
from spotipy.oauth2 import SpotifyOAuth

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("spotify-mcp")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv()  # reads .env (or .env.local) from the project root

SPOTIFY_CLIENT_ID: str = os.environ.get("SPOTIFY_CLIENT_ID", "YOUR_CLIENT_ID_HERE")
SPOTIFY_CLIENT_SECRET: str = os.environ.get("SPOTIFY_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
SPOTIFY_REDIRECT_URI: str = os.environ.get(
    "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"
)

# Scopes required across all tools in this server.
# Add more here as new tools are introduced.
SPOTIFY_SCOPES: str = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "playlist-read-private "
    "playlist-read-collaborative"
)

# ---------------------------------------------------------------------------
# OAuth / Spotify client factory
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _build_auth_manager() -> SpotifyOAuth:
    """
    Build and cache a SpotifyOAuth manager.

    The manager is cached for the lifetime of the process.  It stores the
    access/refresh token in a local `.cache` file (default spotipy behaviour)
    and automatically calls the refresh endpoint when the token expires, so
    callers never have to think about token lifecycle.

    Returns
    -------
    SpotifyOAuth
        Configured OAuth manager ready for use with ``spotipy.Spotify``.

    Raises
    ------
    EnvironmentError
        If the required credential env-vars are still set to their placeholder
        values, surfacing an early, actionable error.
    """
    if SPOTIFY_CLIENT_ID == "YOUR_CLIENT_ID_HERE":
        raise EnvironmentError(
            "SPOTIFY_CLIENT_ID is not configured. "
            "Copy .env.example → .env and fill in your credentials."
        )

    cache_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache")
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPES,
        cache_path=cache_path,
        open_browser=False,
    )


def get_spotify_client() -> spotipy.Spotify:
    """
    Return an authenticated ``spotipy.Spotify`` instance.

    Token refresh is handled transparently by the underlying SpotifyOAuth
    manager – every call through this client will use a valid access token.

    Returns
    -------
    spotipy.Spotify
        Ready-to-use authenticated Spotify client.
    """
    auth_manager = _build_auth_manager()
    return spotipy.Spotify(auth_manager=auth_manager)


# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="spotify-mcp-server",
    instructions=(
        "Control Spotify playback, inspect the currently playing track, "
        "and manage playlists using the tools provided."
    ),
)

# ---------------------------------------------------------------------------
# Tool: get_current_track
# ---------------------------------------------------------------------------


@mcp.tool()
def get_current_track() -> dict[str, Any]:
    """
    Retrieve information about the track currently playing on Spotify.

    Queries the active Spotify device for the currently playing item.
    Returns structured metadata including track name, artist(s), album,
    playback progress, and whether playback is active.

    Returns
    -------
    dict
        A dictionary with the following keys:

        - ``is_playing`` (bool): Whether a track is actively playing.
        - ``track_name`` (str | None): Title of the current track.
        - ``artists`` (list[str]): Artist name(s) for the track.
        - ``album`` (str | None): Album name.
        - ``duration_ms`` (int | None): Total track duration in milliseconds.
        - ``progress_ms`` (int | None): Current playback position in milliseconds.
        - ``track_url`` (str | None): Spotify web URL for the track.

    Notes
    -----
    Returns ``{"is_playing": False}`` when nothing is playing or no active
    device is found.

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
    }


# ---------------------------------------------------------------------------
# Tool: play_pause
# ---------------------------------------------------------------------------


@mcp.tool()
def play_pause(action: str = "toggle") -> dict[str, str]:
    """
    Control Spotify playback – play, pause, or toggle the current state.

    Sends a play or pause command to the active Spotify device.  The
    ``toggle`` action inspects the current playback state and issues the
    opposite command, making it convenient for a single-button workflow.

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


# ---------------------------------------------------------------------------
# Tool: get_user_playlists
# ---------------------------------------------------------------------------


@mcp.tool()
def get_user_playlists(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """
    Fetch a paginated list of the current user's Spotify playlists.

    Retrieves both owned and followed playlists visible to the authenticated
    user.  Use ``limit`` and ``offset`` to page through large collections.

    Parameters
    ----------
    limit : int, optional
        Maximum number of playlists to return per call.  Capped at 50 by the
        Spotify API (default: 20).
    offset : int, optional
        Zero-based index of the first playlist to return, used for pagination
        (default: 0).

    Returns
    -------
    dict
        A dictionary with the following keys:

        - ``total`` (int): Total number of playlists in the user's library.
        - ``limit`` (int): Limit that was applied.
        - ``offset`` (int): Offset that was applied.
        - ``playlists`` (list[dict]): List of playlist summaries, each with:
            - ``id`` (str): Spotify playlist ID.
            - ``name`` (str): Playlist name.
            - ``owner`` (str): Display name of the playlist owner.
            - ``tracks_total`` (int): Number of tracks in the playlist.
            - ``public`` (bool | None): Whether the playlist is public.
            - ``url`` (str): Spotify web URL for the playlist.

    Raises
    ------
    ValueError
        If ``limit`` is outside the range [1, 50].
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Running directly → stdio transport (matches fastmcp.json config).
    # Use `fastmcp run src/server.py` for the standard launcher.
    mcp.run(transport="stdio")
