ARG FRONTEND_IMAGE=frontend-build-output

FROM node:22-alpine AS frontend-deps

ENV npm_config_cache=/tmp/npm-cache

ARG DOCKER_USER=1000
WORKDIR /home/frontend/

RUN mkdir -p /tmp/npm-cache && chown -R ${DOCKER_USER} /tmp/npm-cache /home/frontend

# Install deps and run all npm commands as the user running the container
USER ${DOCKER_USER}
COPY --chown=${DOCKER_USER} package*.json ./
# npm ci installs exactly what package-lock.json pins. The cache is cleaned in
# the same layer so the downloaded tarballs don't ship in the image. (A
# BuildKit cache mount would keep them across rebuilds, but its root-owned
# mount point makes npm bail out on CI runners building as a non-root user.)
RUN npm ci --no-audit --no-fund && npm cache clean --force

FROM frontend-deps AS frontend-build

ARG DOCKER_USER=1000
WORKDIR /home/frontend/
COPY --chown=${DOCKER_USER} . ./

ARG API_ORIGIN
ENV NEXT_PUBLIC_API_ORIGIN=${API_ORIGIN}

RUN npm run build

# Normalize output path to /app (matches the runtime-prod layout)
FROM scratch AS frontend-build-output
COPY --from=frontend-build /home/frontend/dist /app

# When FRONTEND_IMAGE is set to an external image, BuildKit skips
# frontend-deps, frontend-build, and frontend-build-output entirely
FROM ${FRONTEND_IMAGE} AS frontend-source

# Caddy and lprobe release binaries lag Go's security fixes (Caddy 2.11.7 ships
# go1.26.8), so both are built with a patched toolchain and golang.org/x/net
# raised past their pins. The Go checksum database verifies every module.
FROM --platform=$BUILDPLATFORM golang:1.26.9-alpine@sha256:cdfd4fe2da6b225d8b40c6b7a105736e548e83ff56d5d8f9394446eeb5eb84e0 AS go-build
ARG TARGETARCH
ARG GO_X_NET_VERSION=v0.60.0
ENV CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH}

# Caddy's own cmd/caddy/main.go: the standard modules, no plugin.
FROM go-build AS caddy-build
ARG CADDY_VERSION=v2.11.7
WORKDIR /src
RUN printf '%s\n' 'package main' \
      'import (' '	_ "time/tzdata"' \
      '	caddycmd "github.com/caddyserver/caddy/v2/cmd"' \
      '	_ "github.com/caddyserver/caddy/v2/modules/standard"' ')' \
      'func main() { caddycmd.Main() }' > main.go \
    && go mod init caddy \
    && go get "github.com/caddyserver/caddy/v2@${CADDY_VERSION}" "golang.org/x/net@${GO_X_NET_VERSION}" \
    && go mod tidy \
    && go build -trimpath -ldflags="-w -s" -o /out/caddy .

FROM go-build AS lprobe-build
ARG LPROBE_VERSION=v0.2.1
ARG LPROBE_COMMIT=e2b91f80dfbebbb7b244a7daa515d6d71ef9f68b
RUN apk add --no-cache git \
    && git clone --depth 1 --branch "${LPROBE_VERSION}" https://github.com/fivexl/lprobe.git /src \
    && test "$(git -C /src rev-parse HEAD)" = "${LPROBE_COMMIT}" \
    && cd /src \
    && go get "golang.org/x/net@${GO_X_NET_VERSION}" \
    && go build -trimpath -ldflags="-w -s" -o /out/lprobe .

FROM gcr.io/distroless/static-debian13:nonroot AS runtime-prod

COPY --from=caddy-build /out/caddy /usr/bin/caddy
COPY --from=lprobe-build /out/lprobe /usr/bin/lprobe
COPY --from=frontend-source /app /app
COPY caddy/Caddyfile /etc/caddy/Caddyfile

ENV PORT=8080
ENV TRANSFERTS_FRONTEND_ROOT=/app
ENV TRANSFERTS_FRONTEND_BACKEND_SERVER=localhost:8000
ENV DJANGO_ADMIN_URL=admin

ENTRYPOINT ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]

# Port is hardcoded below because distroless has no shell to expand $PORT.
# If you change ENV PORT above, update the healthcheck port to match.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["/usr/bin/lprobe", "-mode=http", "-port=8080", "-endpoint=/__lbheartbeat__"]
