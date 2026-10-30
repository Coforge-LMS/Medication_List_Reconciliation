# syntax=docker/dockerfile:1
FROM python:3.12.16-slim-trixie AS dependencies

# Keep the installer aligned with CI; the runtime needs only the resulting venv.
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

FROM python:3.12.16-slim-trixie AS runtime

ARG VCS_REF=unknown
LABEL org.opencontainers.image.revision=${VCS_REF}
ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /srv
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin medrec

COPY --from=dependencies /srv/.venv /srv/.venv
# app.version reads pyproject.toml at runtime. Code and data stay with the image
# during a rollback; none of these directories is bind-mounted by Compose.
COPY pyproject.toml uv.lock ./
COPY app/ ./app/
COPY contract/ ./contract/
COPY db/ ./db/
COPY ingest/ ./ingest/
COPY rules/ ./rules/
COPY data/aliases.json ./data/aliases.json
COPY data/intake/ ./data/intake/
COPY data/pharmacy/ ./data/pharmacy/

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
