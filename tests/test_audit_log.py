from __future__ import annotations

import csv
import io
import json

from app.core.audit_log import GENESIS, AuditLog, mask_secrets
from app.store import JsonStore


def _fill(store: JsonStore, n: int = 3) -> None:
    for i in range(n):
        store.audit.append(actor="policy", event="policy_decision", user_id="priya", rule_id="R1",
                           decision="allowed", subscription_id=f"sub-{i}", transport="mock")


def test_entries_chain_and_increment(store: JsonStore) -> None:
    _fill(store)
    entries = store.audit.entries()
    assert [e.seq for e in entries] == [1, 2, 3]
    assert entries[0].prev_hash == GENESIS
    assert entries[1].prev_hash == entries[0].hash
    assert entries[2].prev_hash == entries[1].hash
    assert all(e.sim_day == 0 and e.ts.endswith("Z") for e in entries)
    assert store.audit.verify().ok


def test_tampered_entry_detected(store: JsonStore) -> None:
    _fill(store)
    lines = store.audit.path.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[1])
    data["decision"] = "blocked"
    lines[1] = json.dumps(data)
    store.audit.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = store.audit.verify()
    assert not result.ok and result.broken_at_seq == 2 and "modified" in (result.reason or "")


def test_deleted_entry_detected(store: JsonStore) -> None:
    _fill(store)
    lines = store.audit.path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    store.audit.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = store.audit.verify()
    assert not result.ok and result.broken_at_seq == 3


def test_garbage_line_detected(store: JsonStore) -> None:
    _fill(store, 2)
    with open(store.audit.path, "a", encoding="utf-8") as f:
        f.write("not json\n")
    assert not store.audit.verify().ok


def test_append_only_and_chain_survives_reload(store: JsonStore) -> None:
    _fill(store, 2)
    first_two = store.audit.path.read_text(encoding="utf-8")
    reopened = AuditLog(store.audit.path, store.lock, lambda: 5)
    entry = reopened.append(actor="system", event="startup")
    assert entry.seq == 3 and entry.sim_day == 5
    assert store.audit.path.read_text(encoding="utf-8").startswith(first_two)  # never rewritten
    assert reopened.verify().ok


def test_secrets_and_emails_masked(store: JsonStore) -> None:
    e = store.audit.append(
        actor="system", event="paypal_call", reason="sent to priya@subguard-demo.example",
        details={"access_token": "A21AAsecret", "headers": {"Authorization": "Bearer abc.def"},
                 "note": "Bearer xyz123", "to": "cancel@penwright.example", "api_key": "sk-123"},
    )
    raw = store.audit.path.read_text(encoding="utf-8")
    for secret in ("A21AAsecret", "abc.def", "xyz123", "sk-123", "priya@", "cancel@"):
        assert secret not in raw
    assert e.details["access_token"] == "***"
    assert e.details["to"] == "c***@penwright.example"
    assert e.reason == "sent to p***@subguard-demo.example"


def test_mask_secrets_leaves_plain_values() -> None:
    assert mask_secrets({"plan": "penwright-pro", "n": 3}) == {"plan": "penwright-pro", "n": 3}


def test_query_filters(store: JsonStore) -> None:
    _fill(store, 2)
    store.audit.append(actor="user", event="keep", user_id="intruder")
    assert len(store.audit.query(user="priya")) == 2
    assert len(store.audit.query(event="keep")) == 1
    assert len(store.audit.query(since_day=1)) == 0
    assert len(store.audit.query(subscription_id="sub-1")) == 1


def test_csv_export(store: JsonStore) -> None:
    _fill(store, 2)
    text = store.audit.to_csv(store.audit.entries())
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2 and rows[0]["rule_id"] == "R1" and "hash" in rows[0]
