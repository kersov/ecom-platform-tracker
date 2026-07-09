# Dockerfile
# Builds natively for the host platform (CI runners are amd64). No platform pin
# is needed now that detection is pure Python — curl_cffi ships amd64 + arm64
# wheels. Pass `docker build --platform=...` if you ever need to cross-build.
FROM python:3.11-slim

# Tier 2 (nodriver) drives a real headless Chromium for the JS-sensor holdouts.
# Install Chromium + the shared libraries a headless Chrome needs, then point
# detect_platform.py at it via CHROME_PATH. Tiers 0/1 remain pure HTTP and don't
# need it. (fonts-liberation/-noto avoid blank glyph rendering on some pages.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        fonts-liberation fonts-noto-core \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV CHROME_PATH=/usr/bin/chromium

# uv: fast, reproducible installs straight from the committed lockfile.
COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /usr/local/bin/uv

WORKDIR /app

# The CI job mounts the host workspace over /app at runtime, which would
# shadow a project-local .venv. Put the environment outside /app instead.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install the exact, hash-pinned dependencies from uv.lock. --frozen fails
# the build if pyproject.toml and uv.lock have drifted out of sync.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# copy repository files (script, sites.json, etc.)
COPY . .


# default command (we'll override with explicit command in workflow)
CMD ["python", "detect_platform.py"]