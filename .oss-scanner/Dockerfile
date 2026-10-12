# check=skip=SecretsUsedInArgOrEnv
# Image for Anthropic's OSS Scanner. See .oss-scanner/threat_model.md.
# The scan runs with no network, so this build installs every dependency and
# the services the test suites need: PostgreSQL, Redis and an S3 endpoint.
# Scanner contract: the repository is the build context, the checkout is /src.
# The layout mirrors suitenumerique/messages' .oss-scanner/Dockerfile.
#
# The same Debian release as src/backend/Dockerfile, pinned by digest.
FROM debian:trixie-slim@sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a

# initdb reads the locale when the postgresql package creates its cluster.
# Without a UTF-8 locale the cluster gets the SQL_ASCII encoding.
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1

# policy-rc.d stops the postgresql and redis packages from starting a server:
# a server killed at the end of a layer leaves a stale pid file in the image.
# build-essential and zlib1g-dev compile the C extensions of the lock file, as
# src/backend/Dockerfile does.
RUN <<EOR
set -eux
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod +x /usr/sbin/policy-rc.d
apt-get update
apt-get upgrade -y
apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    libmagic1 \
    libnss-myhostname \
    netcat-openbsd \
    postgresql-17 \
    python3 \
    python3-venv \
    redis-server \
    zlib1g-dev
rm -f /usr/sbin/policy-rc.d
rm -rf /var/lib/apt/lists/*
# settings.py resolves the hostname at import time (Production.ALLOWED_HOSTS).
# With no network and no DNS, only the myhostname NSS module makes that
# lookup succeed.
sed -i 's/^hosts:.*/hosts: files myhostname dns/' /etc/nsswitch.conf
pg_lsclusters
EOR

# The cluster holds test data only. postgresql.conf includes conf.d.
RUN printf '%s\n' \
      "listen_addresses = 'localhost'" \
      "fsync = off" \
      "full_page_writes = off" \
      "synchronous_commit = off" \
      "max_connections = 200" \
      > /etc/postgresql/17/main/conf.d/oss-scanner.conf

# The dev stack uses rustfs for S3. moto is the stand-in here: it is pure Python
# and needs no architecture-specific binary. It runs on the Debian interpreter,
# in a virtual environment of its own, so it never meets the project's pins.
RUN <<EOR
set -eux
python3 -m venv /opt/s3
/opt/s3/bin/pip install --no-cache-dir --disable-pip-version-check \
    "moto[server]==5.2.3" "boto3==1.43.111"
/opt/s3/bin/moto_server --help >/dev/null
EOR

# The scanner replaces ENTRYPOINT and CMD, so the image cannot start the
# services itself. svcctl starts them, and every shell sources the init file.
COPY --chmod=0755 <<'EOF' /usr/local/bin/svcctl
#!/bin/sh
set -eu

pg_ready() {
    pg_isready -q -h 127.0.0.1 -p 5432
}

redis_ready() {
    redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1
}

s3_ready() {
    nc -zw1 127.0.0.1 9000 >/dev/null 2>&1
}

wait_for() {
    i=0
    while [ "$i" -lt 60 ]; do
        if "$1"; then return 0; fi
        sleep 0.5
        i=$((i + 1))
    done
    echo "svcctl: $2 did not become ready" >&2
    return 1
}

start_postgresql() {
    # pg_isready exits 0 when the server accepts connections, 1 while it is
    # still starting, and 2 when nothing answers.
    state=0
    pg_ready || state=$?
    if [ "$state" -eq 0 ]; then return 0; fi
    install -d -o postgres -g postgres -m 2775 /var/run/postgresql
    install -d -o postgres -g postgres -m 1775 /var/log/postgresql
    if [ "$state" -eq 1 ]; then
        # Another shell starts the server now.
        wait_for pg_ready postgresql
        return 0
    fi
    # Nothing answers, so the pid file that the scanner's own layer left
    # behind is stale.
    rm -f /var/lib/postgresql/17/main/postmaster.pid
    pg_ctlcluster 17 main start
    wait_for pg_ready postgresql
}

start_redis() {
    if redis_ready; then return 0; fi
    install -d -o redis -g redis -m 2775 /var/run/redis
    redis-server /etc/redis/redis.conf --daemonize yes --save "" --appendonly no
    wait_for redis_ready redis
}

start_s3() {
    if s3_ready; then return 0; fi
    nohup /opt/s3/bin/moto_server -H 127.0.0.1 -p 9000 >/var/log/moto_server.log 2>&1 &
    wait_for s3_ready "the s3 endpoint"
    # moto keeps the bucket in memory, so every start creates it again.
    /opt/s3/bin/python - <<'PY'
import os

import boto3
from botocore.exceptions import ClientError

client = boto3.client(
    "s3",
    endpoint_url=os.environ["AWS_S3_ENDPOINT_URL"],
    aws_access_key_id=os.environ["AWS_S3_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_S3_SECRET_ACCESS_KEY"],
    region_name="us-east-1",
)
try:
    client.head_bucket(Bucket=os.environ["AWS_STORAGE_BUCKET_NAME"])
except ClientError:
    client.create_bucket(Bucket=os.environ["AWS_STORAGE_BUCKET_NAME"])
PY
}

case "${1:-start}" in
start)
    start_postgresql
    start_redis
    start_s3
    ;;
stop)
    pg_ctlcluster 17 main stop || true
    redis-cli -h 127.0.0.1 -p 6379 shutdown nosave >/dev/null 2>&1 || true
    pkill -f /opt/s3/bin/moto_server || true
    ;;
status)
    pg_lsclusters
    if redis_ready; then echo "redis: up"; else echo "redis: down"; fi
    if s3_ready; then echo "s3: up"; else echo "s3: down"; fi
    ;;
psql)
    shift
    exec runuser -u postgres -- psql "$@"
    ;;
*)
    echo "usage: svcctl [start|stop|status|psql]" >&2
    exit 2
    ;;
esac
EOF

# Sourced by BASH_ENV, /etc/profile.d and /root/.bashrc. It must stay silent
# and must not change the exit status.
COPY --chmod=0644 <<'EOF' /etc/oss-scanner-shell-init
if [ -z "${OSS_SCANNER_SERVICES_STARTED:-}" ]; then
    if /usr/local/bin/svcctl start >/dev/null 2>&1; then
        OSS_SCANNER_SERVICES_STARTED=1
        export OSS_SCANNER_SERVICES_STARTED
    fi
fi
:
EOF

# Node 22, the major version that engines.node of package.json names.
# src/frontend/Dockerfile builds on node:22-alpine, whose musl binary does not
# run on Debian, so the glibc build of the same major comes from the slim image.
COPY --from=node:22.23.3-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22.23.3-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN <<EOR
set -eux
ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
node --version
npm --version
EOR

# uv and the managed CPython, as in src/backend/Dockerfile.
COPY --from=ghcr.io/astral-sh/uv@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed

RUN uv python install 3.14.8

# The environment sits outside /src, so a search of the checkout does not read
# it. No cache mount: a cache mount is not kept in the image, and the agent
# needs the download caches to install anything with no network.
COPY src/backend/pyproject.toml src/backend/uv.lock /src/src/backend/
RUN cd /src/src/backend \
    && UV_PROJECT_ENVIRONMENT=/opt/venv/backend \
       uv sync --frozen --no-install-project --no-editable --all-extras

COPY src/frontend/package.json src/frontend/package-lock.json /src/src/frontend/
RUN cd /src/src/frontend && npm ci --no-audit --no-fund

COPY . /src
WORKDIR /src

# PYTHONPATH lets a script outside src/backend import the project, the way
# the project's images run from /app.
ENV PATH=/opt/venv/backend/bin:$PATH \
    VIRTUAL_ENV=/opt/venv/backend \
    PYTHONPATH=/src/src/backend

# The Test configuration of src/backend/transfers/settings.py, with every
# service on the loopback address. The values mirror
# env.d/development/backend.defaults: they are the public development values,
# not secrets. The OIDC endpoints are never called, but RS256 refuses to load
# without a JWKS endpoint.
ENV DJANGO_SETTINGS_MODULE=transfers.settings \
    DJANGO_CONFIGURATION=Test \
    DJANGO_SECRET_KEY=ThisIsAnExampleKeyForDevPurposeOnly \
    DJANGO_ALLOWED_HOSTS=* \
    DJANGO_DATA_DIR=/data \
    DB_HOST=127.0.0.1 \
    DB_PORT=5432 \
    DB_NAME=transfers \
    DB_USER=user \
    DB_PASSWORD=pass \
    REDIS_URL=redis://127.0.0.1:6379 \
    CELERY_BROKER_URL=redis://127.0.0.1:6379 \
    AWS_S3_ENDPOINT_URL=http://127.0.0.1:9000 \
    AWS_S3_ACCESS_KEY_ID=transfers \
    AWS_S3_SECRET_ACCESS_KEY=password \
    AWS_S3_SIGNATURE_VERSION=s3v4 \
    AWS_STORAGE_BUCKET_NAME=transfers \
    OIDC_OP_JWKS_ENDPOINT=http://keycloak:8802/realms/transfers/protocol/openid-connect/certs \
    OIDC_OP_AUTHORIZATION_ENDPOINT=http://localhost:8902/realms/transfers/protocol/openid-connect/auth \
    OIDC_OP_TOKEN_ENDPOINT=http://keycloak:8802/realms/transfers/protocol/openid-connect/token \
    OIDC_OP_USER_ENDPOINT=http://keycloak:8802/realms/transfers/protocol/openid-connect/userinfo \
    OIDC_OP_LOGOUT_ENDPOINT=http://localhost:8902/realms/transfers/protocol/openid-connect/logout \
    OIDC_RP_CLIENT_ID=transfers \
    OIDC_RP_CLIENT_SECRET=transfers-dev-secret \
    OIDC_RP_SIGN_ALGO=RS256 \
    OIDC_RP_SCOPES="openid email profile" \
    OIDC_REDIRECT_ALLOWED_HOSTS=http://localhost:8980,http://localhost:8981 \
    LOGIN_REDIRECT_URL=http://localhost:8980 \
    LOGIN_REDIRECT_URL_FAILURE=http://localhost:8980/errors \
    LOGOUT_REDIRECT_URL=http://localhost:8980

# "user" needs the quotes: it is a reserved word in SQL. pytest-django creates
# the test database, so the role needs CREATEDB.
RUN <<EOR
set -eux
install -d -m 0777 /data /data/static /data/media
svcctl start
test "$(runuser -u postgres -- psql -tAXc 'show server_encoding')" = UTF8
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -X \
    -c "CREATE ROLE \"${DB_USER}\" LOGIN SUPERUSER CREATEDB PASSWORD '${DB_PASSWORD}';"
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -X \
    -c "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";"
cd /src/src/backend
python manage.py migrate --noinput
python manage.py collectstatic --noinput
svcctl stop
EOR

# A failing test must not fail the build, and each run has a time limit. -k
# kills a worker that ignores the first signal. --reuse-db keeps the migrated
# test databases in the image for the agent's first `pytest --reuse-db`.
RUN <<EOR
set -eux
svcctl start
cd /src/src/backend
timeout -k 30 720 pytest --reuse-db -q -p no:cacheprovider --no-cov -n auto \
    || echo "WARNING: the parallel test run did not finish cleanly (exit $?)"
timeout -k 30 240 pytest --reuse-db -q -p no:cacheprovider --no-cov core/tests/test_api_config.py \
    || echo "WARNING: the serial test run did not finish cleanly (exit $?)"
svcctl stop
EOR

RUN <<EOR
set -eux
cd /src/src/frontend
timeout -k 30 420 npm run test \
    || echo "WARNING: the frontend test run did not finish cleanly (exit $?)"
EOR

RUN <<EOR
set -eux
echo '. /etc/oss-scanner-shell-init' > /etc/profile.d/oss-scanner.sh
echo '. /etc/oss-scanner-shell-init' >> /root/.bashrc
git config --system --add safe.directory /src
python -c 'import socket; socket.gethostbyname(socket.gethostname())'
EOR

# From here on every tool reads the caches in this image and fails fast
# instead of waiting for a network that is not there.
ENV BASH_ENV=/etc/oss-scanner-shell-init \
    NO_UPDATE_NOTIFIER=1 \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_OFFLINE=true \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    PIP_NO_INDEX=1 \
    UV_FROZEN=1 \
    UV_NO_SYNC=1 \
    UV_OFFLINE=1
