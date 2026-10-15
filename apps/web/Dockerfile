# Production web image: build in Node, serve standalone as non-root.
FROM node:20-slim AS builder
WORKDIR /srv
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim
WORKDIR /srv
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /srv/package.json ./package.json
COPY --from=builder /srv/node_modules ./node_modules
COPY --from=builder /srv/.next ./.next
COPY --from=builder /srv/public ./public
COPY --from=builder /srv/next.config.js ./next.config.js
RUN useradd --create-home --uid 10001 xray && chown -R xray:xray /srv
USER xray
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["npm", "start"]
