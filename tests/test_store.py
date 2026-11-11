from __future__ import annotations

import asyncio
import json
import os
import threading
from decimal import Decimal

import pytest

from app import models as m
from app.store import JsonStore, atomic_write_text, utcnow


def test_missing_files_created_from_defaults_and_seeds(store: JsonStore) -> None:
    users = store.load("users")
    assert [u.id for u in users.items] == ["priya"]
    assert store.load("state").sim_day == 0
    assert not store.path("subscriptions").exists()
    store.ensure_all()
    assert all(store.path(name).exists() for name in store.files)
    merchants = {mc.id: mc for mc in store.load("merchants").items}
    assert set(merchants) == {"penwright"}


def test_money_round_trips_as_string_decimal(store: JsonStore) -> None:
    snap = m.ConsentSnapshot(taken_at=utcnow(), sim_day=0, price=Decimal("24.99"))
    sub = m.Subscription(id="s1", paypal_id="I-1", plan_key="penwright-pro", plan_id="P-1",
                         merchant_id="penwright", owner_id="priya", consent_snapshot=snap)
    with store.edit("subscriptions") as subs:
        subs.items.append(sub)
    raw = json.loads(store.path("subscriptions").read_text(encoding="utf-8"))
    assert raw["items"][0]["consent_snapshot"]["price"] == "24.99"  # string, not float
    loaded = store.load("subscriptions").items[0].consent_snapshot
    assert loaded.price == Decimal("24.99") and isinstance(loaded.price, Decimal)


def test_atomic_write_crash_before_replace_keeps_old_file(store: JsonStore, monkeypatch) -> None:
    with store.edit("state") as st:
        st.sim_day = 3
    path = store.path("state")
    before = path.read_text(encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError("simulated crash before os.replace")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        with store.edit("state") as st:
            st.sim_day = 99
    monkeypatch.undo()
    assert path.read_text(encoding="utf-8") == before
    assert store.load("state").sim_day == 3
    assert not path.with_name(path.name + ".tmp").exists()


def test_atomic_write_text_replaces_content(tmp_path) -> None:
    p = tmp_path / "x.json"
    atomic_write_text(p, "one")
    atomic_write_text(p, "two")
    assert p.read_text() == "two"


def test_edit_does_not_save_when_block_raises(store: JsonStore) -> None:
    with pytest.raises(RuntimeError):
        with store.edit("state") as st:
            st.sim_day = 42
            raise RuntimeError("nope")
    assert store.load("state").sim_day == 0


@pytest.mark.parametrize("garbage", ["{not json", '{"sim_day": "not-a-number"}', ""])
def test_corrupt_file_recovered(store: JsonStore, garbage: str) -> None:
    store.ensure_all()
    store.path("state").write_text(garbage, encoding="utf-8")
    state = store.load("state")
    assert state.sim_day == 0
    corrupt = list(store.dir.glob("state.corrupt-*.json"))
    assert len(corrupt) == 1 and corrupt[0].read_text(encoding="utf-8") == garbage
    assert any("state.json was corrupt" in w for w in store.warnings)
    events = [e.event for e in store.audit.entries()]
    assert "store_corrupt_recovered" in events
    assert store.audit.verify().ok


def test_corrupt_users_file_reseeds(store: JsonStore) -> None:
    store.ensure_all()
    store.path("users").write_text("[[[", encoding="utf-8")
    assert [u.id for u in store.load("users").items] == ["priya"]


def test_concurrent_thread_edits_are_serialised(store: JsonStore) -> None:
    store.ensure_all()

    def bump() -> None:
        for _ in range(20):
            with store.edit("state") as st:
                st.sim_day += 1

    threads = [threading.Thread(target=bump) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.load("state").sim_day == 100


def test_concurrent_async_edits_are_serialised(store: JsonStore) -> None:
    store.ensure_all()

    async def bump() -> None:
        for _ in range(10):
            async with store.aedit("state") as st:
                current = st.sim_day
                await asyncio.sleep(0)  # yield mid-edit: another coroutine must not interleave
                st.sim_day = current + 1

    async def main() -> None:
        await asyncio.gather(*(bump() for _ in range(5)))

    asyncio.run(main())
    assert store.load("state").sim_day == 50


def test_save_rejects_wrong_model(store: JsonStore) -> None:
    with pytest.raises(TypeError):
        store.save("state", m.UserList())


def test_reset_keeps_sandbox_ids_and_archives_audit_log(store: JsonStore) -> None:
    store.ensure_all()
    with store.edit("sandbox_ids") as ids:
        ids.plans["penwright-pro"] = "P-123"
    with store.edit("state") as st:
        st.sim_day = 21
    store.audit.append(actor="user", event="something")
    (store.dir / "outbox").mkdir()
    (store.dir / "outbox" / "mail.json").write_text("{}")

    store.reset()
    store.reset()  # idempotent

    assert store.load("sandbox_ids").plans == {"penwright-pro": "P-123"}
    assert store.load("state").sim_day == 0
    assert not (store.dir / "outbox").exists()
    archives = list(store.dir.glob("audit_log.*.jsonl"))
    assert len(archives) == 2
    fresh = store.audit.entries()
    assert [e.event for e in fresh] == ["demo_reset"] and fresh[0].seq == 1
    assert store.audit.verify().ok
