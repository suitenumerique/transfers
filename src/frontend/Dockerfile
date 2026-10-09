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

FROM alpine:3.21 AS tools-download
ARG TARGETARCH

ARG CADDY_VERSION=2.11.7
# When upgrading, run
# for arch in amd64 arm64; do printf "CADDY_SHA256_%s=%s\n" "$(echo $arch | tr a-z A-Z)" "$(wget -qO- "https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_linux_${arch}.tar.gz" | sha256sum | cut -d' ' -f1)"; done
# and update checksums accordingly (bin/scalingo_postfrontend pins the same version and amd64 checksum)
ARG CADDY_SHA256_AMD64=727b91701a392de6ebc5027509f548bf39979e5216340d0faed8fa5e69c84f8b
ARG CADDY_SHA256_ARM64=d8fc6d179a5d283028a472a5618564f6ad8a86fed513e64f032b3b0b7cc45e42
RUN wget -qO /tmp/caddy.tar.gz "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${TARGETARCH}.tar.gz" \
    && case "${TARGETARCH}" in \
         amd64) echo "${CADDY_SHA256_AMD64}  /tmp/caddy.tar.gz" | sha256sum -c - ;; \
         arm64) echo "${CADDY_SHA256_ARM64}  /tmp/caddy.tar.gz" | sha256sum -c - ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && tar -xzf /tmp/caddy.tar.gz caddy \
    && mv caddy /usr/bin/caddy \
    && rm /tmp/caddy.tar.gz

# lprobe's release binaries lag Go's security fixes (v0.2.1 ships go1.26.0), so
# it is built from its pinned commit with a patched toolchain. Its go.sum and
# the Go checksum database verify the dependencies.
FROM --platform=$BUILDPLATFORM golang:1.26.9-alpine@sha256:cdfd4fe2da6b225d8b40c6b7a105736e548e83ff56d5d8f9394446eeb5eb84e0 AS lprobe-build
ARG TARGETARCH
ARG LPROBE_VERSION=v0.2.1
ARG LPROBE_COMMIT=e2b91f80dfbebbb7b244a7daa515d6d71ef9f68b
RUN apk add --no-cache git \
    && git clone --depth 1 --branch "${LPROBE_VERSION}" https://github.com/fivexl/lprobe.git /src \
    && test "$(git -C /src rev-parse HEAD)" = "${LPROBE_COMMIT}" \
    && cd /src \
    && CGO_ENABLED=0 GOOS=linux GOARCH="${TARGETARCH}" \
       go build -trimpath -ldflags="-w -s" -o /out/lprobe .

FROM gcr.io/distroless/static-debian13:nonroot AS runtime-prod

COPY --from=tools-download /usr/bin/caddy /usr/bin/caddy
COPY --from=lprobe-build /out/lprobe /usr/bin/lprobe
COPY --from=frontend-source /app /app
COPY caddy/Caddyfile /etc/caddy/Caddyfile

ENV PORT=8080
ENV TRANSFERS_FRONTEND_ROOT=/app
ENV TRANSFERS_FRONTEND_BACKEND_SERVER=localhost:8000
ENV DJANGO_ADMIN_URL=admin

ENTRYPOINT ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]

# Port is hardcoded below because distroless has no shell to expand $PORT.
# If you change ENV PORT above, update the healthcheck port to match.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["/usr/bin/lprobe", "-mode=http", "-port=8080", "-endpoint=/__lbheartbeat__"]
