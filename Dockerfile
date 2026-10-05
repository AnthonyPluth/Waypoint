# Waypoint: a household's travel, read privately from its email.

# The base images are pinned by digest (the tag is for reading); Dependabot moves the digests weekly.

# 1. Install the dependencies (pyproject.toml / poetry.lock) into a virtualenv with Poetry. The virtualenv gets no pip:
#    Waypoint never installs anything at run time, and pip's bundled libraries only add to what the image scan flags.
FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS deps
ENV PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_VIRTUALENVS_OPTIONS_NO_PIP=true \
    POETRY_NO_INTERACTION=1
RUN pip install "poetry==2.5.1"
WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-ansi

# 2. Build the web app (frontend/) into waypoint/static/app. It's plain files, so it's built once on the build machine
#    whatever the image's architecture.
FROM --platform=$BUILDPLATFORM node:26-slim@sha256:ec7758ee051e457b468b32bde57b0879010b325bb9862718e9615225ce4aaae1 AS web
WORKDIR /web/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# The release build uploads the web app's source maps to Sentry, so its errors show readable stack traces (see
# frontend/vite.config.ts). The token is a build secret: it's never in the image or its layers. Without it (any other
# build) nothing is uploaded and the build is the same as ever.
ARG VERSION=dev
ARG SENTRY_ORG=""
ARG SENTRY_BROWSER_PROJECT=waypoint-web
RUN --mount=type=secret,id=sentry_auth_token \
    SENTRY_AUTH_TOKEN="$(cat /run/secrets/sentry_auth_token 2>/dev/null || true)" \
    WAYPOINT_VERSION="$VERSION" SENTRY_ORG="$SENTRY_ORG" SENTRY_BROWSER_PROJECT="$SENTRY_BROWSER_PROJECT" \
    npm run build

# 3. The image itself: Python, that virtualenv and Waypoint, without Poetry or pip.
FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

LABEL org.opencontainers.image.source="https://github.com/AnthonyPluth/waypoint" \
      org.opencontainers.image.description="Waypoint: a household's travel, read privately from its email"

# Set by the release workflow (v1.2.3); shown in Settings.
ARG VERSION=dev

ENV WAYPOINT_VERSION=$VERSION \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WAYPOINT_DATA=/data \
    WAYPOINT_HOST=0.0.0.0 \
    WAYPOINT_PORT=8765 \
    TZ=America/New_York

# Debian's security fixes that came out after the base image was built (OpenSSL's, most often), and no pip: nothing
# runs it, and the libraries it bundles (msgpack, setuptools) are flagged by the image scan. ensurepip's copy goes too.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall --yes --no-cache-dir --root-user-action=ignore pip \
 && rm -rf /usr/local/lib/python3.*/ensurepip/_bundled

# Run as an ordinary user; your database lives in /data (mount a folder or volume there).
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin waypoint \
 && mkdir -p /data && chown waypoint:waypoint /data

# The code stays owned by root, so it's read-only for the user it runs as; the app writes only to /data.
WORKDIR /app
COPY --from=deps /app/.venv ./.venv
COPY run.py alembic.ini ./
COPY waypoint ./waypoint
COPY --from=web /web/waypoint/static/app ./waypoint/static/app

USER waypoint
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('WAYPOINT_PORT', '8765'), timeout=4)" || exit 1

CMD ["python", "run.py"]
