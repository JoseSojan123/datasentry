# DataSentry: one image that serves the API and the built web app.
#   docker build -t datasentry .
#   docker run -p 8000:8000 --env-file .env datasentry

# ---- web app -------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Empty means "same origin as the API", which is how this image serves it.
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

# ---- API -----------------------------------------------------------------
FROM python:3.12-slim AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# Dependencies first so code changes do not reinstall them.
COPY backend/pyproject.toml ./
RUN mkdir -p app datasentry_core && touch app/__init__.py datasentry_core/__init__.py \
    && pip install . && pip uninstall -y datasentry-backend && rm -rf app datasentry_core build *.egg-info

COPY backend/app ./app
COPY backend/datasentry_core ./datasentry_core
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --from=web /web/dist ./static

RUN useradd --uid 10001 --create-home datasentry \
    && mkdir -p /data/storage && chown -R datasentry /data \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV STATIC_DIR=/app/static \
    STORAGE_DIR=/data/storage \
    PORT=8000
USER datasentry
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY:-1}"]
