# syntax=docker/dockerfile:1
#
# ACME City permits.  Build context: this directory (repo/).
#
#   docker build --target production -t acme-permits:prod .
#   docker build --target demo       -t acme-permits:demo .
#
# `production` is the default target: it carries config, migrations, templates
# and static files, and leaves out the demonstration scripts (reset, loaders,
# walkthrough) and the recorded replay fixtures.  `demo` adds them back.
# Both run as a non-root user and default to ACME_DEPLOYMENT_MODE of their own
# target.  Migrations run once in the entrypoint (docker/entrypoint.py).

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:${PYTHON_VERSION}-slim AS runtime-base
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --create-home --home-dir /home/acme --shell /usr/sbin/nologin acme \
    && mkdir -p /app/var && chown -R acme:acme /app
WORKDIR /app
COPY --from=base /opt/venv /opt/venv
COPY --from=base /app/src ./src
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY config ./config
COPY docker/entrypoint.py /app/entrypoint.py
# Runtime data the service reads (rules text, GIS layers, document samples).
COPY fixtures ./fixtures
VOLUME ["/app/var"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/readyz', timeout=4).status == 200 else 1)"]

# ----------------------------------------------------------------- demo
FROM runtime-base AS demo
COPY scripts ./scripts
RUN chown -R acme:acme /app
USER acme
ENV ACME_DEPLOYMENT_MODE=demo
ENTRYPOINT ["python", "/app/entrypoint.py"]

# ----------------------------------------------------------- production
FROM runtime-base AS production
# No reset script, no loaders, no walkthrough, no recorded replay fixtures.
RUN rm -rf /app/fixtures/replay
USER acme
ENV ACME_DEPLOYMENT_MODE=production \
    ACME_DATABASE_URL=sqlite:////app/var/acme_city.db
ENTRYPOINT ["python", "/app/entrypoint.py"]
