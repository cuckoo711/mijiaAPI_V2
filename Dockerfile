# syntax=docker/dockerfile:1

FROM node:20-alpine AS web-builder

WORKDIR /build/web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MIJIA_SERVER_HOST=0.0.0.0 \
    MIJIA_SERVER_PORT=8123 \
    MIJIA_SERVER_DATA_DIR=/data \
    MIJIA_SERVER_DATABASE_PATH=/data/server/server.sqlite3 \
    MIJIA_CREDENTIAL_PATH=/data/credential.json \
    MIJIA_WEB_DIST_DIR=/app/web/dist

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gosu \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY mijiaAPI_V2/ mijiaAPI_V2/
COPY server/ server/
RUN pip install --no-cache-dir .

COPY configs/*.toml.template configs/
COPY --from=web-builder /build/web/dist web/dist/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN groupadd --gid 1000 mijia \
    && useradd --uid 1000 --gid mijia --home-dir /home/mijia --shell /usr/sbin/nologin mijia \
    && mkdir -p /data/server /data/cache \
    && chown -R mijia:mijia /app /data \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8123

VOLUME ["/data"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["mijia-server", "run"]
