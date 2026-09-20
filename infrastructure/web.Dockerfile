FROM node:24-alpine AS build
ARG APP_VERSION=0.3.0
ARG RELEASE_COMMIT=unknown
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
COPY packages/shared/package.json packages/shared/package.json
RUN npm ci
COPY apps/web apps/web
COPY packages packages
ENV NEXT_TELEMETRY_DISABLED=1
ENV API_INTERNAL_URL=http://api:8000
ENV APP_VERSION=$APP_VERSION
ENV RELEASE_COMMIT=$RELEASE_COMMIT
RUN npm run build

FROM node:24-alpine AS runtime
ARG APP_VERSION=0.3.0
ARG RELEASE_COMMIT=unknown
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV API_INTERNAL_URL=http://api:8000
ENV APP_VERSION=$APP_VERSION
ENV RELEASE_COMMIT=$RELEASE_COMMIT
COPY --from=build --chown=node:node /app/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /app/apps/web/.next/static ./apps/web/.next/static
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
