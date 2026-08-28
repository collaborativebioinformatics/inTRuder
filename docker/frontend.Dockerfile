# syntax=docker/dockerfile:1

# novelTRs frontend — Next.js + Tailwind + assistant-ui, served by `next start`.
#
#   docker compose up frontend                                   # from the repo root
#   docker build -f docker/frontend.Dockerfile -t noveltrs-frontend .
#
# The build context is the REPOSITORY ROOT, not frontend/ — see .dockerignore.

ARG NODE_VERSION=22


# --------------------------------------------------------------------------- #
# Dependencies — the full set, including the build-only toolchain.
# --------------------------------------------------------------------------- #
FROM node:${NODE_VERSION}-bookworm-slim AS deps

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci


# --------------------------------------------------------------------------- #
# Build — compile the production bundle.
# --------------------------------------------------------------------------- #
FROM node:${NODE_VERSION}-bookworm-slim AS builder

ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./

# The browser talks to the API directly, and NEXT_PUBLIC_* is inlined into the
# client bundle at BUILD time. So this is the URL *your browser* resolves, never
# a container name — `backend:8000` would not resolve outside the compose
# network. Changing it means rebuilding: `docker compose build frontend`.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

RUN npm run build


# --------------------------------------------------------------------------- #
# Production dependencies — the same lockfile without the build toolchain.
# --------------------------------------------------------------------------- #
FROM node:${NODE_VERSION}-bookworm-slim AS prod-deps

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev


# --------------------------------------------------------------------------- #
# Runtime.
# --------------------------------------------------------------------------- #
FROM node:${NODE_VERSION}-bookworm-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

COPY --from=prod-deps --chown=node:node /app/node_modules ./node_modules
COPY --from=builder  --chown=node:node /app/.next ./.next
COPY --from=builder  --chown=node:node /app/public ./public
COPY --from=builder  --chown=node:node /app/package.json ./package.json

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["npm", "run", "start"]
