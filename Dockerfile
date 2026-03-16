FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no project source yet)
RUN uv sync --frozen --no-install-project

# Copy the rest of the project
COPY . .

# Install the project itself
RUN uv sync --frozen

# Persistent volume mount point for token cache (configure in Railway dashboard)
RUN mkdir -p /data

# Railway injects $PORT; default to 8000 for local docker run
ENV PORT=8000
ENV SPOTIFY_CACHE_DIR=/data

# All output goes to stderr – keeps the SSE stdout stream clean
ENV PYTHONUNBUFFERED=1

EXPOSE $PORT

CMD ["uv", "run", "fastmcp", "run", "src/server.py", "--transport", "sse", "--port", "$PORT"]
