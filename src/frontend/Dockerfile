ARG FRONTEND_IMAGE=frontend-build-output

FROM node:22-alpine AS frontend-deps

ENV npm_config_cache=/tmp/npm-cache

ARG DOCKER_USER=1000
WORKDIR /home/frontend/

RUN mkdir -p /tmp/npm-cache && chown -R ${DOCKER_USER} /tmp/npm-cache /home/frontend

# Install deps and run all npm commands as the user running the container
USER ${DOCKER_USER}
COPY --chown=${DOCKER_USER} package*.json ./
RUN npm install

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

ARG CADDY_VERSION=2.11.4
# When upgrading, run
# for arch in amd64 arm64; do printf "CADDY_SHA256_%s=%s\n" "$(echo $arch | tr a-z A-Z)" "$(wget -qO- "https://github.com/caddyserver/caddy/releases/download/v2.11.4/caddy_2.11.4_linux_${arch}.tar.gz" | sha256sum | cut -d' ' -f1)"; done
# and update checksums accordingly (bin/scalingo_postfrontend pins the same version)
ARG CADDY_SHA256_AMD64=527fbf917c39189a1e3b31d34fa955601680b2d5c8055d2a87b8b9588dec7bb9
ARG CADDY_SHA256_ARM64=52d42ae12b3462097e9868da6dfed3c9648ae12edd3b3638102312af84cb6904
RUN wget -qO /tmp/caddy.tar.gz "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${TARGETARCH}.tar.gz" \
    && case "${TARGETARCH}" in \
         amd64) echo "${CADDY_SHA256_AMD64}  /tmp/caddy.tar.gz" | sha256sum -c - ;; \
         arm64) echo "${CADDY_SHA256_ARM64}  /tmp/caddy.tar.gz" | sha256sum -c - ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && tar -xzf /tmp/caddy.tar.gz caddy \
    && mv caddy /usr/bin/caddy \
    && rm /tmp/caddy.tar.gz

ARG LPROBE_VERSION=v0.2.0
# When upgrading, run
# for arch in amd64 arm64; do printf "LPROBE_SHA256_%s=%s\n" "$(echo $arch | tr a-z A-Z)" "$(wget -qO- "https://github.com/fivexl/lprobe/releases/download/v0.2.0/lprobe-linux-${arch}" | sha256sum | cut -d' ' -f1)"; done
# and update checksums accordingly
ARG LPROBE_SHA256_AMD64=8b55ddb15c2d8c5e1773c73c1413b26c7041e5836dabdbcef5f806ba6b9d17a2
ARG LPROBE_SHA256_ARM64=3f31eee19167f23dc64c645021b75306956da245e5b9763c90abd12797d0a72a
RUN wget -qO /usr/bin/lprobe "https://github.com/fivexl/lprobe/releases/download/${LPROBE_VERSION}/lprobe-linux-${TARGETARCH}" \
    && case "${TARGETARCH}" in \
         amd64) echo "${LPROBE_SHA256_AMD64}  /usr/bin/lprobe" | sha256sum -c - ;; \
         arm64) echo "${LPROBE_SHA256_ARM64}  /usr/bin/lprobe" | sha256sum -c - ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && chmod +x /usr/bin/lprobe

FROM gcr.io/distroless/static-debian13:nonroot AS runtime-prod

COPY --from=tools-download /usr/bin/caddy /usr/bin/caddy
COPY --from=tools-download /usr/bin/lprobe /usr/bin/lprobe
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
