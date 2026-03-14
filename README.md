# spotify-mcp-server

A **FastMCP 3.0** server that exposes Spotify playback and playlist controls
as [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) tools,
allowing LLM clients (Claude, Cursor, etc.) to control Spotify on your behalf.

---

## Features

| Tool | Description |
|---|---|
| `get_current_track` | Returns metadata for the currently playing Spotify track |
| `play_pause` | Plays, pauses, or toggles Spotify playback |
| `get_user_playlists` | Lists the authenticated user's playlists with pagination |

---

## Prerequisites

| Requirement | Version |
|---|---|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.4 |
| Python | ≥ 3.10 (managed automatically by uv) |
| Spotify account | Free or Premium |
| Spotify Developer App | [Create one here](https://developer.spotify.com/dashboard) |

---

## Setup

### 1. Clone and enter the project

```bash
git clone <repo-url> spotify-mcp-server
cd spotify-mcp-server
```

### 2. Install dependencies

```bash
uv sync
```

uv will download Python 3.12, create a virtual environment, and install all
locked dependencies automatically.

### 3. Create your Spotify Developer App

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
2. Click **Create App**.
3. Set the **Redirect URI** to `http://127.0.0.1:8888/callback`.
4. Note your **Client ID** and **Client Secret**.

### 4. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

```dotenv
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

> **Security**: `.env` is gitignored. Never commit it.

### 5. First-run OAuth flow (one-time)

The first time the server starts it will print an authorisation URL.
Open that URL in your browser, approve access, and paste the redirect URL
back into the terminal when prompted. The token is cached in `.cache` for all
subsequent runs.

---

## Running the Server

### stdio transport (default)

```bash
uv run fastmcp run src/server.py
```

### Direct execution

```bash
uv run python src/server.py
```

---

## Connecting to an MCP Client

### Claude Desktop (`claude_desktop_config.json`)

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

### Claude Code (CLI)

```bash
claude mcp add spotify -- uv run fastmcp run src/server.py
```

---

## Adding New Tools

1. Add a function to [src/server.py](src/server.py) decorated with `@mcp.tool()`.
2. Write a NumPy-style docstring (FastMCP exposes this as the tool description).
3. Add any new Spotify scopes to `SPOTIFY_SCOPES` in `server.py`.
4. Run `uv run python -m py_compile src/server.py` to syntax-check.

See [CLAUDE.md](CLAUDE.md) for full project conventions.

---

## Project Structure

```
.
├── src/
│   └── server.py          # FastMCP server + all tool definitions
├── config/
│   └── settings.py        # pydantic-settings config loader
├── .env.example           # Credential template
├── fastmcp.json           # FastMCP transport & server config
├── pyproject.toml         # Dependencies (managed by uv)
├── uv.lock                # Locked dependency graph
└── CLAUDE.md              # Project conventions for AI assistants
```

---

## License

MIT
