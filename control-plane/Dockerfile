# Chimera control-plane dashboard — v4.45.
#
# Next.js 15 with Turbopack. Multi-stage:
#   1. deps      → npm ci into a clean layer
#   2. builder   → next build (compiles RSC + client bundles)
#   3. runner    → minimal runtime; reads ./state/chimera.db + ./mind/
#                 via volume mounts from the host (NOT bundled).

# ───────────────── deps ─────────────────
FROM node:20-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# better-sqlite3 needs build-essential at install time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential python3 \
    && rm -rf /var/lib/apt/lists/* \
    && npm ci --omit=optional

# ───────────────── builder ─────────────────
FROM node:20-bookworm-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ───────────────── runner ─────────────────
FROM node:20-bookworm-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user.
RUN groupadd --gid 1001 nextjs && \
    useradd  --uid 1001 --gid 1001 --shell /bin/bash --create-home nextjs

# Only ship what next start needs.
COPY --from=builder --chown=nextjs:nextjs /app/.next ./.next
COPY --from=builder --chown=nextjs:nextjs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nextjs /app/public ./public
COPY --from=builder --chown=nextjs:nextjs /app/package.json ./package.json
COPY --from=builder --chown=nextjs:nextjs /app/next.config.* ./

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:'+process.env.PORT+'/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["npm", "run", "start"]
