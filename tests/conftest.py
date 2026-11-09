from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Make importing app.main safe: mock mode, throwaway data dir, ignore the developer's .env values.
os.environ["APP_MODE"] = "mock"
os.environ["LLM_PROVIDER"] = "anthropic"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="subguard-import-")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import ROOT_DIR, Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import JsonStore  # noqa: E402

SEED_DIR = ROOT_DIR / "data" / "seed"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    (tmp_path / "seed").mkdir()
    for f in SEED_DIR.glob("*.json"):
        (tmp_path / "seed" / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


@pytest.fixture
def store(data_dir: Path) -> JsonStore:
    return JsonStore(data_dir / "runtime", data_dir / "seed")


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    return Settings(_env_file=None, app_mode="mock", data_dir=data_dir)  # type: ignore[call-arg]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c
