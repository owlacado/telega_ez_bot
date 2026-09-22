FROM node:24-bookworm-slim AS node-runtime

FROM node:24-bookworm-slim AS web-build
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
COPY packages/shared/package.json packages/shared/package.json
RUN npm ci
COPY apps/web apps/web
COPY packages packages
ENV NEXT_TELEMETRY_DISABLED=1
ENV API_INTERNAL_URL=http://127.0.0.1:8000
RUN npm run build

FROM caddy:2 AS router

FROM python:3.13-slim-bookworm AS api-base
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/apps/api
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY apps/api/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY apps/api/ ./
RUN pip install --no-cache-dir --no-deps . && useradd --create-home hub
USER hub

FROM api-base AS web
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=router /usr/bin/caddy /usr/bin/caddy
COPY --from=web-build --chown=hub:hub /app/apps/web/.next/standalone /app/
COPY --from=web-build --chown=hub:hub /app/apps/web/.next/static /app/apps/web/.next/static
COPY infrastructure/render.Caddyfile /app/render.Caddyfile
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV API_INTERNAL_URL=http://127.0.0.1:8000
ENV HOSTNAME=127.0.0.1
EXPOSE 10000
CMD ["python", "-m", "hub.render_runtime", "web"]
