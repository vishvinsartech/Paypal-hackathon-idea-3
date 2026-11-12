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
from tests.story_helpers import TEST_PASSWORD, sign_in  # noqa: E402

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
    return Settings(_env_file=None, app_mode="mock", data_dir=data_dir, demo_seed=False,  # type: ignore[call-arg]
                    demo_password=TEST_PASSWORD)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Signed in as Priya (Phase 7: every non-public route needs a session)."""
    with TestClient(create_app(settings)) as c:
        yield sign_in(c)


@pytest.fixture
def anon_client(settings: Settings) -> Iterator[TestClient]:
    """Signed out: the same app as `client`, no session cookie."""
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def demo_client(data_dir: Path) -> Iterator[TestClient]:
    """Mock mode with the demo seed: Priya's scripted Penwright usage (no subscriptions yet). Signed in as Priya."""
    settings = Settings(_env_file=None, app_mode="mock", data_dir=data_dir, demo_seed=True,  # type: ignore[call-arg]
                        demo_password=TEST_PASSWORD)
    with TestClient(create_app(settings)) as c:
        yield sign_in(c)
