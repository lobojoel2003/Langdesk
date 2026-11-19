.PHONY: help install test lint format demo run dispatcher docker up down release-check

PY ?= python
VERSION = $(shell $(PY) -c 'from langdesk.version import __version__; print(__version__)')

help:  ## Show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-15s %s\n", $$1, $$2}'

install:  ## Install runtime and development dependencies
	$(PY) -m pip install -r requirements-dev.txt

test:  ## Run the test suite with coverage
	$(PY) -m pytest --cov

lint:  ## Lint and check formatting
	ruff check . && ruff format --check .

format:  ## Format the code
	ruff check --fix . && ruff format .

demo:  ## Create the database and load demo data
	DJANGO_DEBUG=1 $(PY) manage.py migrate
	DJANGO_DEBUG=1 $(PY) manage.py seed_demo

run:  ## Run the development server on :8000
	DJANGO_DEBUG=1 $(PY) manage.py runserver

dispatcher:  ## Run the dispatcher loop without Celery
	DJANGO_DEBUG=1 $(PY) manage.py run_dispatcher --loop

docker:  ## Build the Docker image
	docker build -t ghcr.io/lobojoel2003/langdesk:local --build-arg VERSION=$(VERSION) .

up:  ## Start the full stack with Docker Compose
	docker compose up -d --build

down:  ## Stop the stack
	docker compose down

release-check:  ## Print the tag a release must use
	@echo "Tag to push: v$(VERSION)"
