# SubGuard. Every target delegates to scripts/tasks.py, which also works on Windows without make.
PYTHON ?= python3

.PHONY: setup dev dev-sandbox seed reset test lint demo-video-check demo-video

setup:
	$(PYTHON) scripts/tasks.py setup

dev:
	$(PYTHON) scripts/tasks.py dev

dev-sandbox:
	$(PYTHON) scripts/tasks.py dev-sandbox

seed:
	$(PYTHON) scripts/tasks.py seed

reset:
	$(PYTHON) scripts/tasks.py reset

test:
	$(PYTHON) scripts/tasks.py test

lint:
	$(PYTHON) scripts/tasks.py lint

demo-video-check:
	$(PYTHON) scripts/tasks.py demo-video-check

demo-video:
	$(PYTHON) scripts/tasks.py demo-video
