"""
Spotify MCP Server
==================
A FastMCP 3.0 server that exposes Spotify controls as Model Context Protocol tools.

Transport : SSE (production) / stdio (local dev) – see entry point below.
Auth      : Spotify OAuth 2.0 with automatic token refresh via spotipy.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from google import genai as google_genai
import spotipy
from fastmcp import FastMCP
from spotipy.oauth2 import SpotifyOAuth
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

# ---------------------------------------------------------------------------
# Ensure project root is importable regardless of launch CWD
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config.settings import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Logging – all output goes to stderr so it never pollutes the SSE stream
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(levelname)s | %(name)s | %(message)s",
    stream=sys.stderr,
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

_current_user: str = settings.current_user_name
_auth_managers: dict[str, SpotifyOAuth] = {}


def _cache_path_for(user: str) -> str:
    """Return the absolute path to the token-cache file for *user*.

    Checks ``SPOTIFY_CACHE_DIR`` first so Railway volumes can be mounted
    at a persistent path (e.g. ``/data``).
    """
    cache_dir = os.environ.get("SPOTIFY_CACHE_DIR", _PROJECT_ROOT)
    filename = ".cache" if user == "default" else f".cache-{user}"
    return os.path.join(cache_dir, filename)


def _build_auth_manager(user: str) -> SpotifyOAuth:
    """
    Return (or lazily build) a ``SpotifyOAuth`` manager for *user*.

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
    """Return an authenticated Spotify client for the current user."""
    return spotipy.Spotify(auth_manager=_build_auth_manager(_current_user))


def _uri_to_id(uri_or_id: str) -> str:
    """Extract the bare Spotify ID from a full URI, or return as-is."""
    return uri_or_id.split(":")[-1] if ":" in uri_or_id else uri_or_id


def _active_device_id(sp: spotipy.Spotify) -> str | None:
    """Return the ID of the active device, or the first available one."""
    devices = sp.devices().get("devices", [])
    if not devices:
        return None
    active = next((d for d in devices if d.get("is_active")), None)
    return (active or devices[0])["id"]


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
# Health check (Railway probe + general liveness)
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Liveness probe used by Railway and other deployment platforms."""
    return JSONResponse({"status": "ok", "service": settings.server_name})


@mcp.custom_route("/app", methods=["GET"])
async def serve_web_app(request: Request) -> HTMLResponse:
    """Serve the mobile web app."""
    static_path = os.path.join(_PROJECT_ROOT, "static", "index.html")
    try:
        with open(static_path) as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>Web app not found</h1>", status_code=404)


@mcp.custom_route("/auth/login", methods=["GET"])
async def auth_login(request: Request) -> HTMLResponse | RedirectResponse:
    """
    Start the Spotify OAuth flow.

    Visit this URL in a browser to authorise the server.  Spotify will
    redirect back to ``/callback`` with an authorisation code.
    """
    try:
        user = request.query_params.get("user", _current_user)
        auth_manager = _build_auth_manager(user)
        auth_url = auth_manager.get_authorize_url()
        log.info("auth_login: redirecting user=%s to Spotify", user)
        return RedirectResponse(url=auth_url)
    except Exception as exc:
        log.exception("auth_login failed")
        return HTMLResponse(
            f"<h2>Configuration error</h2><pre>{exc}</pre>",
            status_code=500,
        )


@mcp.custom_route("/callback", methods=["GET"])
async def auth_callback(request: Request) -> HTMLResponse:
    """
    Handle the Spotify OAuth redirect and persist the token cache.

    Spotify calls this URL after the user approves access.  The
    authorisation code is exchanged for an access/refresh token pair
    which spotipy writes to the cache file automatically.
    """
    error = request.query_params.get("error")
    if error:
        log.error("auth_callback: Spotify returned error=%s", error)
        return HTMLResponse(
            f"<h2>Authorisation failed</h2><p>Spotify error: <code>{error}</code></p>",
            status_code=400,
        )

    code = request.query_params.get("code")
    if not code:
        return HTMLResponse(
            "<h2>Authorisation failed</h2><p>No code in callback.</p>",
            status_code=400,
        )

    user = request.query_params.get("state", _current_user)
    # SpotifyOAuth uses 'state' for CSRF by default; we read it as a
    # best-effort user hint but fall back to _current_user safely.
    try:
        auth_manager = _build_auth_manager(_current_user)
        auth_manager.get_access_token(code, as_dict=False, check_cache=False)
        log.info("auth_callback: token cached for user=%s", _current_user)
    except Exception as exc:
        log.exception("auth_callback: token exchange failed")
        return HTMLResponse(
            f"<h2>Token exchange failed</h2><pre>{exc}</pre>",
            status_code=500,
        )

    return HTMLResponse("""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Spotify Authorised</title>
<style>
  body{font-family:sans-serif;display:flex;align-items:center;
       justify-content:center;height:100vh;background:#121212;color:#fff}
  .card{text-align:center;padding:40px;border-radius:16px;background:#1a1a1a}
  h2{color:#1db954}
</style></head>
<body>
  <div class="card">
    <h2>✓ Spotify connected!</h2>
    <p>Token saved. You can close this tab.</p>
    <p style="color:#666;font-size:13px">The MCP server is ready to use.</p>
  </div>
</body>
</html>""")


# ---------------------------------------------------------------------------
# Playback tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_current_track() -> dict[str, Any]:
    """
    Retrieve information about the track currently playing on Spotify.

    Returns structured metadata including the track URI, which is needed by
    other tools such as ``add_to_queue`` and ``get_recommendations``.

    Returns
    -------
    dict
        Keys: ``is_playing``, ``track_name``, ``artists``, ``album``,
        ``duration_ms``, ``progress_ms``, ``track_url``, ``track_uri``.
        Returns ``{"is_playing": False}`` when nothing is playing.

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
        device_id = _active_device_id(sp)
        sp.start_playback(device_id=device_id)
        log.info("play_pause: playback started on device=%s", device_id)
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

    Note
    ----
    Spotify deprecated the public recommendations endpoint in November 2024.
    This tool works for apps created before that date or granted continued access.

    Parameters
    ----------
    seed_tracks : list[str]
        Spotify track URIs or bare IDs (max 5 seeds; excess are truncated).
    limit : int, optional
        Number of recommendations to return (1–100, default: 5).

    Returns
    -------
    dict
        Keys: ``seeds`` (list[str]), ``tracks`` (list[dict]).

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

    playlists = []
    for p in result.get("items", []):
        if not p:
            continue
        # Spotify's simplified playlist object no longer reliably includes
        # tracks.total, so fetch it via the tracks pagination endpoint.
        try:
            page = sp.playlist_tracks(p["id"], limit=1, fields="total")
            tracks_total = page.get("total") or 0
            log.info("playlist %r: tracks_total=%r", p.get("name"), tracks_total)
        except Exception as exc:
            log.warning("playlist %r: failed to fetch tracks_total: %s", p.get("name"), exc)
            tracks_total = 0
        playlists.append({
            "id": p["id"],
            "name": p["name"],
            "owner": (p.get("owner") or {}).get("display_name", ""),
            "tracks_total": tracks_total,
            "public": p.get("public"),
            "url": (p.get("external_urls") or {}).get("spotify", ""),
        })

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
        Display name for the new playlist.
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

    Handles batching automatically (Spotify API limit: 100 tracks per request).

    Parameters
    ----------
    playlist_id : str
        Spotify playlist ID or full URI.
    track_uris : list[str]
        Spotify track URIs or bare track IDs.

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
    for i in range(0, len(full_uris), 100):
        sp.playlist_add_items(pid, full_uris[i : i + 100])

    log.info("add_to_playlist: added %d track(s) to %s", len(full_uris), pid)
    return {"playlist_id": pid, "tracks_added": len(full_uris)}


@mcp.tool()
def search_and_add(query: str, playlist_id: str) -> dict[str, Any]:
    """
    Search for a track and add the top result to a playlist in one step.

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
    token cache for *name*.  Each user's token lives in ``.cache-<name>`` in
    the project root; pass ``"default"`` to return to the primary account.

    Parameters
    ----------
    name : str
        User profile name.  Must have a corresponding cache file or be
        ``"default"``.

    Returns
    -------
    dict
        ``{"previous_user": str, "current_user": str}``

    Raises
    ------
    ValueError
        If ``name`` is blank or no token cache exists for that profile.
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
# Playback context tool
# ---------------------------------------------------------------------------


@mcp.tool()
def play_context(context_uri: str) -> dict[str, str]:
    """
    Start playback of a Spotify context (playlist, album, or artist).

    Parameters
    ----------
    context_uri : str
        Spotify URI (e.g. ``spotify:playlist:<id>``) or bare playlist ID.

    Returns
    -------
    dict
        ``{"status": "playing", "context_uri": str}``

    Raises
    ------
    spotipy.SpotifyException
        Propagated if the Spotify API returns a non-2xx response.
    """
    if ":" not in context_uri:
        context_uri = f"spotify:playlist:{context_uri}"

    sp = get_spotify_client()
    device_id = _active_device_id(sp)
    if not device_id:
        raise ValueError("No Spotify device available. Open Spotify on any device first.")
    try:
        sp.start_playback(device_id=device_id, context_uri=context_uri)
    except spotipy.SpotifyException:
        # Device may have gone inactive; retry without a specific device ID
        sp.start_playback(context_uri=context_uri)
    log.info("play_context: started %s on device=%s", context_uri, device_id)
    return {"status": "playing", "context_uri": context_uri}


# ---------------------------------------------------------------------------
# AI playlist generation tool
# ---------------------------------------------------------------------------


@mcp.tool()
def generate_playlist(prompt: str, playlist_name: str = "") -> dict[str, Any]:
    """
    Generate and populate a Spotify playlist from a natural-language prompt.

    Uses Claude to interpret the prompt and produce a tracklist, then
    creates a new playlist and searches for each track on Spotify.

    Parameters
    ----------
    prompt : str
        Natural-language description, e.g. ``"10 summer hits from 2024"``.
    playlist_name : str, optional
        Name for the new playlist.  If omitted, Claude will suggest one.

    Returns
    -------
    dict
        Keys: ``playlist_id``, ``playlist_name``, ``playlist_url``,
        ``tracks_added`` (int), ``tracks_not_found`` (list[str]).

    Raises
    ------
    EnvironmentError
        If ``GEMINI_API_KEY`` is not configured.
    ValueError
        If ``prompt`` is blank.
    """
    if not prompt.strip():
        raise ValueError("prompt must not be blank.")
    if not settings.gemini_api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY is not set. Add it to Railway environment variables."
        )

    client = google_genai.Client(api_key=settings.gemini_api_key)

    user_msg = (
        "You are a music curator. Return ONLY a JSON object with two keys:\n"
        '  "name": a short playlist name\n'
        '  "tracks": an array of objects, each with "title" and "artist"\n'
        "No markdown, no explanation — raw JSON only.\n\n"
        f'Prompt: "{prompt.strip()}"'
    )
    if playlist_name.strip():
        user_msg += f'\nPlaylist name: "{playlist_name.strip()}"'

    log.info("generate_playlist: calling Gemini for prompt=%r", prompt)
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=user_msg,
    )

    import json as _json
    raw = response.text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    data = _json.loads(raw)

    final_name = playlist_name.strip() or data.get("name", prompt[:50])
    sp = get_spotify_client()
    playlist = sp.current_user_playlist_create(name=final_name, public=False)
    pid = playlist["id"]

    added, not_found = [], []
    for t in data.get("tracks", []):
        query = f"{t.get('title', '')} {t.get('artist', '')}".strip()
        results = sp.search(q=query, type="track", limit=1)
        items = results.get("tracks", {}).get("items", [])
        if items:
            sp.playlist_add_items(pid, [items[0]["uri"]])
            added.append(items[0]["name"])
            log.info("generate_playlist: added '%s'", items[0]["name"])
        else:
            not_found.append(query)
            log.warning("generate_playlist: not found '%s'", query)

    return {
        "playlist_id": pid,
        "playlist_name": final_name,
        "playlist_url": playlist["external_urls"]["spotify"],
        "tracks_added": len(added),
        "tracks_not_found": not_found,
    }


# ---------------------------------------------------------------------------
# Resource: now-playing plain card (stdio / Inspector)
# ---------------------------------------------------------------------------


@mcp.resource("ui://now-playing")
def now_playing_ui() -> str:
    """
    HTML snippet showing the current track with Skip / Play / Queue buttons.

    Buttons carry ``data-mcp-tool`` / ``data-mcp-args`` attributes for thin
    clients that can dispatch MCP tool calls directly from the DOM.

    Returns
    -------
    str
        Self-contained HTML fragment with inline CSS.
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
      <button data-mcp-tool="play_pause" data-mcp-args='{{"action":"toggle"}}'
        style="flex:1;padding:10px;border:none;border-radius:8px;
               background:#1db954;color:#fff;font-weight:700;cursor:pointer">
        {play_label}
      </button>
      <button data-mcp-tool="skip_track" data-mcp-args='{{"direction":"next"}}'
        style="flex:1;padding:10px;border:none;border-radius:8px;
               background:#333;color:#fff;font-weight:700;cursor:pointer">
        ⏭ Skip
      </button>
      <button data-mcp-tool="add_to_queue" data-mcp-args='{{"uri":"{track_uri}"}}'
        style="flex:1;padding:10px;border:none;border-radius:8px;
               background:#333;color:#fff;font-weight:700;cursor:pointer">
        ＋ Queue
      </button>
    </div>
  </div>
</div>
""".strip()


# ---------------------------------------------------------------------------
# Resource: interactive mini-player (SSE / Railway)
# ---------------------------------------------------------------------------


@mcp.resource("ui://spotify-mini-player")
def spotify_mini_player() -> str:
    """
    A fully interactive now-playing card for SSE-connected clients.

    Includes the MCP JS SDK so the Play/Pause, Skip, and Queue buttons
    dispatch real tool calls back to this server over the active SSE
    connection.  The ``_meta`` block advertises a dependency on
    ``get_current_track`` so MCP clients can refresh the card when
    playback changes.

    Returns
    -------
    str
        Self-contained HTML page with inline CSS and embedded JS.
    """
    sp = get_spotify_client()
    playback = sp.current_playback()

    if not playback or not playback.get("item"):
        track_name, artists, album, art_url, track_uri = (
            "Nothing playing", "", "", "", ""
        )
        is_playing = False
    else:
        item = playback["item"]
        track_name = item.get("name", "Unknown")
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        album = item.get("album", {}).get("name", "")
        art_url = (item.get("album", {}).get("images") or [{}])[0].get("url", "")
        track_uri = item.get("uri", "")
        is_playing = playback.get("is_playing", False)

    play_label = "⏸ Pause" if is_playing else "▶ Play"
    art_html = f'<img id="art" src="{art_url}" style="width:100%;display:block">' if art_url else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Spotify Mini Player</title>
  <!-- MCP JS SDK – enables mcp.callTool() from the browser -->
  <script src="https://cdn.jsdelivr.net/npm/@modelcontextprotocol/sdk/dist/browser/index.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #121212; color: #fff;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh;
    }}
    #card {{
      width: 340px; border-radius: 16px; overflow: hidden;
      box-shadow: 0 8px 32px rgba(0,0,0,.5); background: #1a1a1a;
    }}
    #info {{ padding: 16px; }}
    #track  {{ font-size: 18px; font-weight: 700; margin-bottom: 4px; }}
    #artist {{ font-size: 14px; color: #b3b3b3; }}
    #album  {{ font-size: 12px; color: #555; margin-top: 2px; }}
    #controls {{ display: flex; gap: 8px; margin-top: 16px; }}
    button {{
      flex: 1; padding: 11px 8px; border: none; border-radius: 10px;
      font-weight: 700; font-size: 13px; cursor: pointer; transition: opacity .15s;
    }}
    button:hover {{ opacity: .85; }}
    button:disabled {{ opacity: .4; cursor: default; }}
    #btn-play  {{ background: #1db954; color: #fff; }}
    #btn-skip  {{ background: #2a2a2a; color: #fff; }}
    #btn-queue {{ background: #2a2a2a; color: #fff; }}
    #status {{
      font-size: 11px; color: #666; text-align: center;
      padding: 10px 16px; min-height: 30px;
    }}
  </style>
</head>
<body>
  <div id="card">
    {art_html}
    <div id="info">
      <div id="track">{track_name}</div>
      <div id="artist">{artists}</div>
      <div id="album">{album}</div>
      <div id="controls">
        <button id="btn-play"  onclick="callTool('play_pause',  {{action:'toggle'}})">{play_label}</button>
        <button id="btn-skip"  onclick="callTool('skip_track',  {{direction:'next'}})">⏭ Skip</button>
        <button id="btn-queue" onclick="callTool('add_to_queue',{{uri:TRACK_URI}})">＋ Queue</button>
      </div>
    </div>
    <div id="status">Ready</div>
  </div>

  <script>
    // Current track URI injected server-side; buttons close over it.
    const TRACK_URI = {repr(track_uri)};

    // _meta: advertise dependency on get_current_track so MCP clients
    // can trigger a resource refresh when playback state changes.
    const _meta = {{
      resourceDependencies: ["tool://get_current_track"],
      refreshOnToolCall: ["play_pause", "skip_track", "add_to_queue"],
    }};

    let mcp = null;

    async function initMCP() {{
      // Connect to the SSE endpoint on the same origin.
      const serverUrl = window.location.origin + "/mcp";
      try {{
        // @modelcontextprotocol/sdk ≥ 1.x browser bundle exposes MCPClient
        mcp = new MCPClient({{ transport: "sse", url: serverUrl }});
        await mcp.connect();
        setStatus("Connected to Spotify MCP");
      }} catch (e) {{
        setStatus("MCP not connected — buttons will no-op (" + e.message + ")");
      }}
    }}

    async function callTool(toolName, args) {{
      if (!mcp) {{ setStatus("Not connected"); return; }}
      setStatus("Calling " + toolName + "…");
      setButtons(true);
      try {{
        const result = await mcp.callTool(toolName, args);
        setStatus("✓ " + JSON.stringify(result?.content?.[0]?.text ?? result));
      }} catch (e) {{
        setStatus("✗ " + e.message);
      }} finally {{
        setButtons(false);
      }}
    }}

    function setStatus(msg) {{ document.getElementById("status").textContent = msg; }}
    function setButtons(disabled) {{
      ["btn-play","btn-skip","btn-queue"].forEach(id => {{
        document.getElementById(id).disabled = disabled;
      }});
    }}

    initMCP();
  </script>
</body>
</html>""".strip()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    transport = os.environ.get("MCP_TRANSPORT", "stdio")

    if transport in ("sse", "http", "streamable-http"):
        log.info("Starting streamable-HTTP server on 0.0.0.0:%d /mcp", port)
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=port,
            path="/mcp",
        )
    else:
        mcp.run(transport="stdio")
