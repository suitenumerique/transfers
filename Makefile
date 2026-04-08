# ==============================================================================
# VARIABLES

BOLD := \033[1m
RESET := \033[0m
GREEN := \033[1;32m
BLUE := \033[1;34m

# -- Docker
# Get the current user ID to use for docker run and docker exec commands
DOCKER_UID          = $(shell id -u)
DOCKER_GID          = $(shell id -g)
DOCKER_USER         = $(DOCKER_UID):$(DOCKER_GID)
COMPOSE             = DOCKER_USER=$(DOCKER_USER) docker compose
COMPOSE_EXEC        = $(COMPOSE) exec
COMPOSE_EXEC_APP    = $(COMPOSE_EXEC) backend-dev
COMPOSE_RUN         = $(COMPOSE) run --rm --build
COMPOSE_RUN_APP     = $(COMPOSE_RUN) backend-dev
COMPOSE_RUN_APP_DB  = $(COMPOSE_RUN) backend-db
COMPOSE_RUN_APP_TOOLS = $(COMPOSE_RUN) --no-deps backend-dev

# -- Backend
MANAGE              = $(COMPOSE_RUN_APP) python manage.py
MANAGE_DB           = $(COMPOSE_RUN_APP_DB) python manage.py


# ==============================================================================
# RULES

default: help

data/media:
	@mkdir -p data/media

data/static:
	@mkdir -p data/static

# -- Project

create-env-files: ## Create empty .local env files for local development
create-env-files: \
	env.d/development/postgresql.local \
	env.d/development/backend.local \
	env.d/development/frontend.local
.PHONY: create-env-files

bootstrap: ## Prepare the project for local development
	@echo "$(BOLD)"
	@echo "╔══════════════════════════════════════════════════════════════════════════════╗"
	@echo "║  Transferts — Service de transfert de fichiers souverain                     ║"
	@echo "║                                                                              ║"
	@echo "║  Services will be available at:                                                                   ║"
	@echo "║  • Frontend: http://localhost:8900                                           ║"
	@echo "║  • API:      http://localhost:8901                                           ║"
	@echo "║  • Admin:    http://localhost:8901/admin                                     ║"
	@echo "╚══════════════════════════════════════════════════════════════════════════════╝"
	@echo "$(RESET)"
	@$(MAKE) update
	@$(MAKE) superuser
	@$(MAKE) start
.PHONY: bootstrap

update: ## Update the project with latest changes
	@$(MAKE) data/media
	@$(MAKE) data/static
	@$(MAKE) create-env-files
	@$(MAKE) build
	@$(MAKE) collectstatic
	@$(MAKE) migrate
	@$(MAKE) install-frozen-front
.PHONY: update

# -- Docker/compose

build: ## build the project containers
	@$(COMPOSE) build
.PHONY: build

down: ## stop and remove containers, networks, images, and volumes
	@$(COMPOSE) down
.PHONY: down

logs: ## display all services logs (follow mode)
	@$(COMPOSE) logs -f
.PHONY: logs

start: ## start all development services
	@$(COMPOSE) up --force-recreate --build -d frontend-dev backend-dev worker-dev --wait
.PHONY: start

start-minimal: ## start minimal services (backend and DB only)
	@$(COMPOSE) up --force-recreate --build -d backend-db --wait
.PHONY: start-minimal

status: ## an alias for "docker compose ps"
	@$(COMPOSE) ps
.PHONY: status

stop: ## stop all development services
	@$(COMPOSE) --profile "*" stop
.PHONY: stop

restart: ## restart all development services
restart: \
	stop \
	start
.PHONY: restart

# -- Linters

lint: ## run all linters
lint: \
  lint-back \
  lint-front \
  typecheck-front
.PHONY: lint

lint-back: ## run back-end linters (with auto-fix)
lint-back: \
  format-back \
  check-back
.PHONY: lint-back

format-back: ## format back-end python sources
	@$(COMPOSE_RUN_APP_TOOLS) ruff format .
.PHONY: format-back

check-back: ## check back-end python sources
	@$(COMPOSE_RUN_APP_TOOLS) ruff check . --fix
.PHONY: check-back

typecheck-front: ## run the frontend type checker
	@$(COMPOSE) run --rm frontend-tools npm run ts:check
.PHONY: typecheck-front

lint-front: ## run the frontend linter
	@$(COMPOSE) run --rm frontend-tools npm run lint
.PHONY: lint-front

# -- Tests

test: ## run all tests
test: \
  test-back \
  test-front
.PHONY: test

test-back: ## run back-end tests
	@args="$(filter-out $@,$(MAKECMDGOALS))" && \
	bin/pytest $${args:-${1}}
.PHONY: test-back

test-front: ## run the frontend tests
	@args="$(filter-out $@,$(MAKECMDGOALS))" && \
	$(COMPOSE) run --rm frontend-tools npm run test -- $${args:-${1}}
.PHONY: test-front

# -- Backend

migrations: ## run django makemigrations
	@echo "$(BOLD)Running makemigrations$(RESET)"
	@$(MANAGE_DB) makemigrations
.PHONY: migrations

migrations-check: ## check that all model changes have corresponding migrations
	@$(COMPOSE_RUN_APP_TOOLS) python manage.py makemigrations --check --dry-run
.PHONY: migrations-check

migrate: ## run django migrations
	@echo "$(BOLD)Running migrations$(RESET)"
	@$(MANAGE_DB) migrate
.PHONY: migrate

superuser: ## Create an admin superuser with password "admin"
	@echo "$(BOLD)Creating a Django superuser$(RESET)"
	@$(MANAGE_DB) createsuperuser --email admin@admin.local --password admin
.PHONY: superuser

shell-back: ## open a shell in the backend container
	@$(COMPOSE) run --rm --build backend-dev /bin/bash
.PHONY: shell-back

exec-back: ## open a shell in the running backend-dev container
	@$(COMPOSE) exec backend-dev /bin/bash
.PHONY: exec-back

deps-lock-back: ## lock the dependencies
	@$(COMPOSE) run --rm --build backend-uv uv lock
.PHONY: deps-lock-back

collectstatic: ## collect static files
	@$(MANAGE_DB) collectstatic --noinput
.PHONY: collectstatic

shell-back-django: ## connect to django shell
	@$(MANAGE) shell
.PHONY: shell-back-django

# -- Database

shell-db: ## connect to database shell
	$(COMPOSE) exec backend-dev python manage.py dbshell
.PHONY: shell-db

reset-db: ## flush database
	@echo "$(BOLD)Flush database$(RESET)"
	@$(MANAGE_DB) flush
.PHONY: reset-db

env.d/development/%.local:
	@echo "# Local development overrides" > $@

# -- Frontend

shell-front: ## open a shell in the frontend container
	@$(COMPOSE) run --rm --build frontend-tools /bin/sh
.PHONY: shell-front

install-front: ## install the frontend locally
	@args="$(filter-out $@,$(MAKECMDGOALS))" && \
	$(COMPOSE) run --rm --build frontend-tools npm install $${args:-${1}}
.PHONY: install-front

install-frozen-front: ## install the frontend locally (frozen lockfile)
	@$(COMPOSE) run --rm --build frontend-tools npm ci
.PHONY: install-frozen-front

build-front: ## build the frontend locally
	@$(COMPOSE) run --rm --build frontend-tools npm run build
.PHONY: build-front

# -- Misc

clean: ## restore repository state as it was freshly cloned
	git clean -idx
.PHONY: clean

help:
	@echo "$(BOLD)Transferts Makefile$(RESET)"
	@echo "Please use 'make $(BOLD)target$(RESET)' where $(BOLD)target$(RESET) is one of:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(firstword $(MAKEFILE_LIST)) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-30s$(RESET) %s\n", $$1, $$2}'
.PHONY: help
