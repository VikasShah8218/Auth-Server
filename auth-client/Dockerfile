# Web console: built with Node, then served by Caddy, which also terminates TLS and proxies the API.
# The Caddyfile is mounted at runtime from deploy/Caddyfile, so editing it needs no rebuild.

FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /src/dist /srv
