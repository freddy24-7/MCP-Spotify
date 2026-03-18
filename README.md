# spotify-mcp-server

A **FastMCP 3.0** server that exposes Spotify controls as
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) tools.
Use it in two ways:

- **Claude Desktop / Claude Code** — let Claude control Spotify during a conversation ("play something relaxing", "create a jazz playlist for dinner")
- **Web app** — a mobile-friendly player at `/app` for playback control, playlist management, and AI playlist generation

---

## Tools

| Tool | Description |
|---|---|
| `get_current_track` | Metadata for the currently playing track |
| `play_pause` | Play, pause, or toggle playback |
| `skip_track` | Skip to next or previous track |
| `add_to_queue` | Add a track to the playback queue |
| `get_recommendations` | Fetch track recommendations from seed tracks |
| `get_user_playlists` | List the user's playlists |
| `create_playlist` | Create a new empty playlist |
| `add_to_playlist` | Add tracks to an existing playlist |
| `search_and_add` | Search for a track and add it to a playlist |
| `play_context` | Start playback of a playlist, album, or artist |
| `get_devices` | List available Spotify playback devices |
| `transfer_playback` | Transfer playback to a specific device |
| `switch_user` | Switch between pre-authenticated user profiles |
| `generate_playlist` | Generate and populate a playlist from a natural-language prompt (requires Gemini API key) |

---

## Prerequisites

| Requirement | Notes |
|---|---|
| [uv](https://docs.astral.sh/uv/) ≥ 0.4 | Python package manager |
| Python ≥ 3.10 | Managed automatically by uv |
| Spotify account | Free or Premium |
| Spotify Developer App | [Create one here](https://developer.spotify.com/dashboard) |
| Gemini API key | Optional — only needed for `generate_playlist` |

---

## Quick Start

### 1. Clone the repo

```bash
git clone <repo-url> spotify-mcp-server
cd spotify-mcp-server
```

### 2. Install dependencies

```bash
uv sync
```

uv downloads Python 3.12, creates a virtual environment, and installs all
locked dependencies automatically.

### 3. Create a Spotify Developer App

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Click **Create App**
3. Add a **Redirect URI** — use `http://127.0.0.1:8888/callback` for local use, or `https://your-domain/callback` for Railway
4. Note your **Client ID** and **Client Secret**

### 4. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback

# Optional — for AI playlist generation
GEMINI_API_KEY=your_gemini_api_key_here
```

> `.env` is gitignored. Never commit it.

### 5. Authenticate with Spotify (one-time)

```bash
uv run python scripts/authenticate.py
```

This opens a browser for Spotify OAuth. After approving, the token is cached
in `.cache` for all subsequent runs.

---

## Option A — Claude Desktop (local, stdio)

This runs the server locally on your machine. Claude Desktop launches it
automatically when you start a conversation.

**Add to `claude_desktop_config.json`:**

```json
{
  "mcpServers": {
    "spotify": {
      "command": "uv",
      "args": ["run", "fastmcp", "run", "src/server.py"],
      "cwd": "/absolute/path/to/spotify-mcp-server",
      "env": {
        "SPOTIFY_CLIENT_ID": "your_client_id",
        "SPOTIFY_CLIENT_SECRET": "your_client_secret",
        "SPOTIFY_REDIRECT_URI": "http://127.0.0.1:8888/callback"
      }
    }
  }
}
```

The config file is located at:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Restart Claude Desktop after saving. The Spotify tools will appear automatically
in your next conversation.

**Example prompts for Claude:**
- "What's playing on Spotify?"
- "Skip this track"
- "Create a playlist called Dinner Jazz and add 10 tracks"
- "Generate a playlist of 10 summer hits from 2024"

---

## Option B — Railway (cloud, web app + MCP)

Deploy to [Railway](https://railway.app) to get a persistent URL accessible
from any device, including mobile.

### 1. Fork and connect

1. Fork this repo to your GitHub account
2. Create a new Railway project and connect your fork
3. Railway will detect the `Dockerfile` and deploy automatically

### 2. Set environment variables in Railway

| Variable | Value |
|---|---|
| `SPOTIFY_CLIENT_ID` | From Spotify Developer Dashboard |
| `SPOTIFY_CLIENT_SECRET` | From Spotify Developer Dashboard |
| `SPOTIFY_REDIRECT_URI` | `https://your-railway-domain/callback` |
| `MCP_TRANSPORT` | `sse` |
| `GEMINI_API_KEY` | Optional — for AI playlist generation |

### 3. Add the redirect URI to Spotify

In your Spotify Developer App settings, add `https://your-railway-domain/callback`
as an allowed Redirect URI and click **Save**.

### 4. Authenticate

Visit `https://your-railway-domain/auth/login` in a browser to complete the
Spotify OAuth flow. The token is stored on the Railway volume at `/data/.cache`.

### 5. Access the web app

Open `https://your-railway-domain/app` on any device — desktop or mobile.

**Web app features:**
- Now Playing card with album art and progress bar
- Play / pause / skip / queue controls
- Device picker — switch playback between laptop, phone, Bluetooth speakers
- Search and add tracks to playlists
- Create playlists and browse your library
- AI playlist generation from natural-language prompts (requires Gemini API key)

### Connect Claude Desktop to the Railway server

You can also point Claude Desktop at the Railway deployment instead of
running the server locally:

```json
{
  "mcpServers": {
    "spotify": {
      "type": "http",
      "url": "https://your-railway-domain/mcp"
    }
  }
}
```

---

## Multi-user / Family Accounts

The server supports multiple pre-authenticated Spotify accounts on the same
deployment.

**One-time setup per user:**

Each family member visits:
```
https://your-railway-domain/auth/login?user=theirname
```
and logs in with their own Spotify account. Their token is stored as
`.cache-theirname` on the Railway volume.

**Switching accounts:**

Call the `switch_user` tool with the profile name, or ask Claude:
> "Switch to mum's Spotify account"

Switch back to the default account with `switch_user("default")`.

> **Note:** Spotify limits development apps to 25 users. Beyond that, submit
> your app for [extended quota mode](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
> (free, requires review).

---

## Project Structure

```
.
├── src/
│   └── server.py          # FastMCP server + all tool definitions
├── static/
│   └── index.html         # Mobile web app (served at /app)
├── config/
│   └── settings.py        # pydantic-settings config loader
├── scripts/
│   └── authenticate.py    # One-time local OAuth helper
├── .env.example           # Credential template
├── Dockerfile             # Railway deployment
├── railway.json           # Railway configuration
├── pyproject.toml         # Dependencies (managed by uv)
├── uv.lock                # Locked dependency graph
└── CLAUDE.md              # Project conventions
```

---

## License

MIT
