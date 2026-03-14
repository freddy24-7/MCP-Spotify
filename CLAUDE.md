# CLAUDE.md – Project Conventions for spotify-mcp-server

This file is read automatically by Claude Code at the start of every session.
It captures the conventions, decisions, and constraints that govern this project.

---

## Project Overview

`spotify-mcp-server` is a **FastMCP 3.0** server that exposes Spotify controls
(playback, playlists, track info) as **Model Context Protocol (MCP) tools**.

- **Framework**: [FastMCP 3.x](https://github.com/jlowin/fastmcp)
- **Spotify SDK**: [spotipy](https://spotipy.readthedocs.io/)
- **Auth**: Spotify OAuth 2.0, token refresh handled by `SpotifyOAuth`
- **Transport**: `stdio` (default) – configured in `fastmcp.json`
- **Python**: ≥ 3.10 (pinned to 3.12 via `.python-version`)
- **Package manager**: `uv` (do **not** use pip directly)

---

## Directory Layout

```
.
├── src/
│   └── server.py          # FastMCP server, OAuth factory, all tool definitions
├── config/
│   └── settings.py        # pydantic-settings config loader (singleton: settings)
├── .env                   # Local credentials – NEVER commit this file
├── .env.example           # Template for environment variables
├── fastmcp.json           # FastMCP server configuration (transport, module ref)
├── pyproject.toml         # Project metadata & dependencies (managed by uv)
├── uv.lock                # Locked dependency graph – commit this file
├── .python-version        # Pins Python 3.12 for uv
├── CLAUDE.md              # ← you are here
└── README.md              # Setup and usage instructions
```

---

## Development Conventions

### Dependency Management
- Use `uv add <package>` to add dependencies – this updates both `pyproject.toml`
  and `uv.lock`.
- Use `uv remove <package>` to remove dependencies.
- **Never** edit `uv.lock` by hand; **never** run `pip install`.
- `uv sync` to recreate the venv from the lock file.

### Adding New MCP Tools
1. Define a new function in `src/server.py` decorated with `@mcp.tool()`.
2. Write a **NumPy-style docstring** – FastMCP surfaces the docstring text as
   the tool's description to MCP clients (LLMs read this to decide when to
   call the tool).
3. Document every parameter in the `Parameters` section; document the return
   value in the `Returns` section.
4. Raise typed exceptions (`ValueError` for bad inputs, `SpotifyException` for
   API errors) rather than returning error strings.
5. Re-use `get_spotify_client()` to obtain an authenticated client; do not
   instantiate `spotipy.Spotify` directly.

### OAuth / Secrets
- Credentials live exclusively in `.env` (gitignored).
- `config/settings.py` is the single source of truth for reading env vars.
- The `_build_auth_manager()` function in `server.py` raises `EnvironmentError`
  early if placeholder values are detected – keep this guard in place.
- Spotify scopes are declared in `SPOTIFY_SCOPES` (top of `server.py`).  Add
  the minimum required scope for each new tool.

### Code Style
- Python ≥ 3.10 features are allowed (match/case, `X | Y` union types, etc.).
- `from __future__ import annotations` is used for deferred evaluation.
- Type hints are required on all public functions.
- Logging via the standard `logging` module; use the module-level `log` logger.
- No print statements in production code paths.

### Testing (future)
- Tests live in `tests/` (not yet created).
- Use `pytest` with `pytest-asyncio` for async tool tests.
- Mock Spotify API calls with `unittest.mock.patch` – do not hit the live API
  in CI.

---

## Running the Server

```bash
# Activate the managed venv (uv does this automatically with `uv run`)
uv run fastmcp run src/server.py

# Or run directly (stdio transport):
uv run python src/server.py
```

---

## Common Tasks

| Task | Command |
|---|---|
| Add a dependency | `uv add <pkg>` |
| Sync venv from lockfile | `uv sync` |
| Syntax check server | `uv run python -m py_compile src/server.py` |
| List installed packages | `uv pip list` |
| Run the server | `uv run fastmcp run src/server.py` |
