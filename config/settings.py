"""
config/settings.py
==================
Centralised settings loader using pydantic-settings.

All values are read from environment variables (or a .env file via
python-dotenv).  Import ``settings`` wherever configuration is needed.

Usage
-----
    from config.settings import settings
    print(settings.spotify_client_id)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration, sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Unknown env vars are silently ignored so the server tolerates
        # extra vars that other tools might inject into the environment.
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Spotify OAuth
    # ------------------------------------------------------------------
    spotify_client_id: str = Field(
        default="YOUR_CLIENT_ID_HERE",
        description="Spotify application client ID.",
    )
    spotify_client_secret: str = Field(
        default="YOUR_CLIENT_SECRET_HERE",
        description="Spotify application client secret.",
    )
    spotify_redirect_uri: str = Field(
        default="http://127.0.0.1:8888/callback",
        description="OAuth redirect URI (must be registered in the Spotify dashboard).",
    )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        description="Python logging level (DEBUG | INFO | WARNING | ERROR).",
    )

    # ------------------------------------------------------------------
    # Server identity
    # ------------------------------------------------------------------
    server_name: str = Field(
        default="spotify-mcp-server",
        description="Name shown to MCP clients that inspect the server.",
    )

    # ------------------------------------------------------------------
    # Multi-user
    # ------------------------------------------------------------------
    current_user_name: str = Field(
        default="default",
        description=(
            "Active user profile name.  Determines which token-cache file is "
            "loaded on startup (`.cache` for 'default', `.cache-<name>` for "
            "all others).  Override via the CURRENT_USER_NAME env var or the "
            "switch_user MCP tool at runtime."
        ),
    )


# Singleton – import this everywhere instead of instantiating Settings().
settings = Settings()
