# SubGuard. The standard way to run the server is the uvicorn command in `dev` (README "Quick start").
# The other targets delegate to scripts/tasks.py, which also works on Windows without make.
PYTHON ?= python3
# The venv's Python if `make setup` created it, so `make dev` works without activating the venv.
VENV_PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
SERVE := -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

.PHONY: setup dev dev-sandbox seed sandbox-check sandbox-ui-check reset test lint ui-check shots zapier-check demo-video-check demo-video

setup:
	$(PYTHON) scripts/tasks.py setup

# One worker only (JSON store lock, DECISIONS D-020): uvicorn's default, and --reload never forks workers.
dev:
	$(VENV_PY) $(SERVE)

dev-sandbox:
	APP_MODE=sandbox $(VENV_PY) $(SERVE)

seed:
	$(PYTHON) scripts/tasks.py seed $(ARGS)

sandbox-check:
	$(PYTHON) scripts/tasks.py sandbox-check $(ARGS)

sandbox-ui-check:
	$(PYTHON) scripts/tasks.py sandbox-ui-check $(ARGS)

reset:
	$(PYTHON) scripts/tasks.py reset

test:
	$(PYTHON) scripts/tasks.py test

lint:
	$(PYTHON) scripts/tasks.py lint

ui-check:
	$(PYTHON) scripts/tasks.py ui-check $(ARGS)

shots:
	$(PYTHON) scripts/tasks.py shots $(ARGS)

zapier-check:
	$(PYTHON) scripts/tasks.py zapier-check $(ARGS)

demo-video-check:
	$(PYTHON) scripts/tasks.py demo-video-check

demo-video:
	$(PYTHON) scripts/tasks.py demo-video
