# AIBO Studio v8.0 - Next.js UI Server (RunPod)
# Next.js 15 standalone output 対応

FROM node:20-alpine AS base

# 依存関係インストールステージ
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --production

# ビルドステージ
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# 本番実行イメージ（最小構成）
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# standalone 出力をコピー
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Next.js standalone サーバー起動
CMD ["node", "server.js"]