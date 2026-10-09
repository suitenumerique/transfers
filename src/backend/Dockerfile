# ---- Base OS ----
FROM debian:trixie-slim AS base

# Bump this to force an update of the apt repositories
ENV MIN_UPDATE_DATE="2026-10-05"

RUN <<EOR
apt-get update
DEBIAN_FRONTEND="noninteractive" apt-get upgrade -y
rm -rf /var/lib/apt/lists/*
EOR

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Where the app keeps what it writes and what was collected for it. Settings
# derive STATIC_ROOT and MEDIA_ROOT from it, so the build and the runtime must
# agree: collectstatic writes the manifest under $DJANGO_DATA_DIR/static, and
# Django looks for it in the same place. Carried as ENV, not ARG, precisely so
# it survives into the running container — an ARG would not, and Django would
# fall back to BASE_DIR/data and raise "Missing staticfiles manifest entry" on
# the first {% static %} it renders, which in practice means every admin page.
# Still a default: compose env files and `-e` override it as usual.
ARG DATA_DIR=/data
ENV DJANGO_DATA_DIR=${DATA_DIR}

WORKDIR /app

# ---- uv + managed Python + build system deps ----
FROM base AS uv

# Pin uv by SHA256 digest for supply chain security
# Verify with: gh attestation verify --owner astral-sh oci://ghcr.io/astral-sh/uv:0.12.24
# https://github.com/astral-sh/uv/releases/tag/0.12.24
#
# uv carries the SHA256 of every Python build it can install, so the Python
# version below cannot move without it: 0.10.4 had no 3.14.7 and failed the
# build with "No download found for request".
COPY --from=ghcr.io/astral-sh/uv@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /uvx /bin/

RUN <<EOR
apt-get update
DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    rdfind \
    libmagic1 \
    build-essential \
    zlib1g-dev
rm -rf /var/lib/apt/lists/*
EOR

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_PREFERENCE=only-managed
ENV UV_PYTHON_INSTALL_DIR=/opt/python
ENV UV_PROJECT_ENVIRONMENT=/venv

# Install Python via uv — integrity verified against SHA256 checksums embedded in the uv binary.
# Uses python-build-standalone: most C deps (ssl, ffi, sqlite, zlib, lzma, bz2) are statically linked.
RUN uv python install 3.14.8

# ---- Production dependencies ----
FROM uv AS base-with-deps

COPY pyproject.toml uv.lock ./

ENV PATH="/venv/bin:$PATH"

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project --no-editable --exact --no-dev

# ---- Development dependencies ----
FROM base-with-deps AS base-with-deps-dev

RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project --no-editable --all-extras

# ---- Static file collector ----
FROM base-with-deps AS link-collector

# Copy application (see .dockerignore)
COPY . /app/

WORKDIR /app

# collectstatic — writes under $DJANGO_DATA_DIR/static, inherited from base.
RUN <<EOR
set -eu
DJANGO_CONFIGURATION=Build python manage.py collectstatic --noinput
# Replace duplicated file by a symlink to decrease the overall size of the final image
rdfind -makesymlinks true -followsymlinks true -makeresultsfile false ${DJANGO_DATA_DIR}/static
EOR

# ---- Strip Python for production (remove pip, idle, tkinter, tcl, headers, tests) ----
FROM uv AS python-runtime
RUN <<EOR
set -e
PYDIR=$(dirname $(dirname $(uv python find 3.14.8)))
rm -rf \
    $PYDIR/bin/idle* $PYDIR/bin/pip* $PYDIR/bin/pydoc* $PYDIR/bin/*-config \
    $PYDIR/include $PYDIR/share \
    $PYDIR/lib/pkgconfig $PYDIR/lib/itcl* $PYDIR/lib/libtcl* \
    $PYDIR/lib/tcl* $PYDIR/lib/tk* $PYDIR/lib/thread* \
    $PYDIR/lib/python3.14/idlelib \
    $PYDIR/lib/python3.14/ensurepip \
    $PYDIR/lib/python3.14/tkinter \
    $PYDIR/lib/python3.14/turtledemo \
    $PYDIR/lib/python3.14/lib-dynload/_tkinter* \
    $PYDIR/lib/python3.14/lib-dynload/_ctypes_test* \
    /opt/python/.gitignore /opt/python/.lock /opt/python/.temp
EOR

# ---- Base runtime image ----
FROM base AS runtime-base

# Give the "root" group the same permissions as the "root" user on /etc/passwd
# to allow a user belonging to the root group to add new users; typically the
# docker user (see entrypoint).
RUN chmod g=u /etc/passwd

# Install required packages
RUN <<EOR
apt-get update
DEBIAN_FRONTEND="noninteractive" apt-get install -y --no-install-recommends \
  libmagic1
rm -rf /var/lib/apt/lists/*
EOR

# Un-privileged user running the application
ARG DOCKER_USER
USER ${DOCKER_USER}

ENV PATH="/venv/bin:$PATH"
ENV VIRTUAL_ENV=/venv
ENV VIRTUAL_ENV_PROMPT=venv

# We wrap commands run in this container by the following entrypoint that
# creates a user on-the-fly with the container user ID (see USER) and root group
# ID.
COPY ./entrypoint /usr/local/bin/entrypoint
ENTRYPOINT [ "/usr/local/bin/entrypoint" ]


# ---- Development runtime ----
FROM runtime-base AS runtime-dev

# Full Python installation (with headers, pip — useful for debugging)
COPY --from=uv /opt/python /opt/python
COPY --from=base-with-deps-dev /venv /venv

# /app will be mounted as a volume in the development container

# Run django development server
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


# ---- Production application source (strip tests, dev tooling, build files) ----
FROM base AS app-prod
COPY . /app/
RUN rm -rf \
    /app/core/tests \
    /app/core/factories.py \
    /app/Dockerfile \
    /app/.pylintrc \
    /app/pyproject.toml \
    /app/uv.lock \
    /app/README.md \
    /app/entrypoint


# ---- Production runtime ----
FROM runtime-base AS runtime-prod

COPY --from=python-runtime /opt/python /opt/python
COPY --from=base-with-deps /venv /venv
COPY --from=link-collector ${DJANGO_DATA_DIR}/static ${DJANGO_DATA_DIR}/static
COPY --from=app-prod /app/ /app/

# The default command runs gunicorn WSGI server
CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "transferts.wsgi:application"]

HEALTHCHECK --interval=30s --timeout=2s --start-period=30s \
  CMD ["python", "-c", "import os; from urllib.request import Request, urlopen; urlopen(Request('http://localhost:8000/__heartbeat__/', headers={'Host': os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost').split(',')[0].strip(), 'X-Forwarded-Proto': 'https'}), timeout=2)"]


# ---- Collect shared libraries for distroless ----
# libmagic + transitive deps (liblzma, libbz2) are the only shared libs needed.
# Python's own deps (ffi, sqlite, ssl, zlib) are statically linked in python-build-standalone.
FROM uv AS shared-libs
RUN mkdir -p /shared-libs/usr/lib /shared-libs/usr/share/misc && \
    for lib in libmagic liblzma libbz2; do \
        cp -L /usr/lib/*/${lib}.so* /shared-libs/usr/lib/; \
    done && \
    cp /usr/share/misc/magic.mgc /shared-libs/usr/share/misc/


# ---- Distroless production runtime ----
# Uses cc-debian13 (C runtime only) + python-build-standalone from uv.
# Debug with: docker run --entrypoint='' gcr.io/distroless/cc-debian13:debug-nonroot sh
FROM gcr.io/distroless/cc-debian13:nonroot AS runtime-distroless-prod
# Not derived from ``base``, so it does not inherit the variable above.
ARG DATA_DIR=/data
ENV DJANGO_DATA_DIR=${DATA_DIR}

WORKDIR /app

# Stripped Python installation (python-build-standalone via uv)
COPY --from=python-runtime /opt/python /opt/python
# Python dependencies
COPY --from=base-with-deps /venv /venv
# libmagic shared library + magic database
COPY --from=shared-libs /shared-libs/ /
# Static files
COPY --from=link-collector ${DJANGO_DATA_DIR}/static ${DJANGO_DATA_DIR}/static
# Application code
COPY --from=app-prod /app/ /app/

ENV PATH="/venv/bin:$PATH"
ENV VIRTUAL_ENV=/venv
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Distroless has no ldconfig — tell the dynamic linker where to find libmagic
ENV LD_LIBRARY_PATH=/usr/lib

CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "transferts.wsgi:application"]

HEALTHCHECK --interval=30s --timeout=2s --start-period=30s \
  CMD ["python", "-c", "import os; from urllib.request import Request, urlopen; urlopen(Request('http://localhost:8000/__heartbeat__/', headers={'Host': os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost').split(',')[0].strip(), 'X-Forwarded-Proto': 'https'}), timeout=2)"]
