"""D-172: Priya's Activity is ONE chronological timeline; one Penwright per run; one calendar per run."""

from __future__ import annotations

import os
import re
from html import unescape
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import fsutil
from app.core.sub_dates import day_text
from tests.story_helpers import advance_to, alerts, allow_many, cancel_via_alert, on, subscribe

SYSTEM = re.compile(r"sub-I-|\bI-[A-Z0-9]{6,}|ACTIVE|CANCELLED|\bR[1-7]\b|edited:|outbox|Day \d|✗")


def plain(s: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", s)).strip()


def entries(html: str) -> list[dict[str, str]]:
    """Each Activity entry: kind, key, day, its line (with the answer) and its grey detail, as plain text."""
    act = html.split('id="live-timeline"', 1)[1].split('data-testid="activity-raw-log"', 1)[0]
    out = []
    for chunk in act.split('data-testid="tl-entry"')[1:]:
        chunk = chunk.split("</li>", 1)[0]
        meta = re.match(r' data-kind="([^"]+)" data-key="([^"]+)" data-day="(\d+)"', chunk)
        assert meta, chunk[:120]
        line = re.search(r'<span class="ac-text">(.*?)</span>(?=<span class="ac-detail">|</span>)', chunk, re.S)
        detail = re.search(r'<span class="ac-detail">(.*?)</span>', chunk, re.S)
        out.append({"kind": meta.group(1), "key": meta.group(2), "day": meta.group(3),
                    "line": plain(line.group(1)) if line else "", "detail": plain(detail.group(1)) if detail else "",
                    "html": chunk})
    return out


def check_shape(rows: list[dict[str, str]], html: str) -> None:
    keys = [r["key"] for r in rows]
    assert len(keys) == len(set(keys)), keys  # no event twice
    days = [int(r["day"]) for r in rows]
    assert days == sorted(days, reverse=True), days  # newest day first
    heads = [int(d) for d in re.findall(r'data-testid="tl-day" data-day="(\d+)"', html)]
    assert heads == sorted(set(heads), reverse=True), heads  # one heading per day, in order
    for r in rows:
        assert len(r["line"].split(" · You chose")[0]) <= 70, r["line"]
        assert not SYSTEM.search(r["line"]) and not SYSTEM.search(r["detail"]), r
        assert "rule-chip" not in r["html"]


def test_cancel_story_is_one_timeline(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    check = alerts(c, kind="reminder")[0]
    c.post(f"/api/alerts/{check['id']}/act", json={"user_id": "priya", "action": "cancel"})  # a tap she closed
    cancel_via_alert(c, check)
    n = c.get("/api/notices?user=priya").json()[0]
    c.post(f"/api/notices/{n['id']}/send", json={"user_id": "priya", "to": n["to"], "subject": n["subject"],
                                                  "body": n["body"]})
    advance_to(c, 11)
    html = c.get("/").text
    rows = entries(html)
    check_shape(rows, html)
    assert [r["kind"] for r in rows] == ["charge_blocked", "email_sent", "cancel", "checkin", "timer", "signup",
                                         "review"]
    by = {r["kind"]: r for r in rows}
    assert by["checkin"]["line"] == "Asked you: keep Penwright or cancel? · You chose: Cancel"
    assert by["checkin"]["detail"].startswith("Sent by App")
    assert by["review"]["detail"].endswith("hidden AI instructions on the page ignored")  # folded in
    assert by["signup"]["detail"] == f"Free until {on(10)}, then $24.99/month"
    assert by["cancel"]["detail"] == f"You confirmed. No $24.99 charge on {on(11)}."
    proof = by["cancel"]["html"]
    assert "Proof" in proof and "ACTIVE → CANCELLED" in proof and "(rule R1)" in proof and "<q>" in proof
    assert 'data-email-open="' in by["email_sent"]["html"] and "View email" in by["email_sent"]["html"]
    assert html.count("Read the fine print") == 0 and 'data-testid="activity-raw-log"' in html
    did = html.split('data-testid="audit-summary"', 1)[1].split("</ol>", 1)[0]
    assert re.findall(r'data-kind="(\w+)"', did) == ["charge_blocked", "email_sent", "cancel"]


def test_keep_story_is_one_timeline(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    check = alerts(c, kind="reminder")[0]
    assert c.post(f"/api/alerts/{check['id']}/act", json={"user_id": "priya", "action": "keep"}).status_code == 200
    advance_to(c, 11)
    html = c.get("/").text
    rows = entries(html)
    check_shape(rows, html)
    assert [r["kind"] for r in rows] == ["charge_due", "checkin", "timer", "signup", "review"]
    assert rows[1]["line"].endswith("· You chose: Keep")
    assert rows[3]["detail"] == f"Free until {on(10)}, then $24.99/month"  # the FIRST charge, not the next one


def test_open_check_in_needs_her_answer(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    advance_to(c, 5)
    html = c.get("/").text
    (check,) = [r for r in entries(html) if r["kind"] == "checkin"]
    assert 'aria-label="Needs your answer"' in check["html"] and "You chose" not in check["line"]


def test_one_penwright_per_run(demo_client: TestClient) -> None:
    c = demo_client
    subscribe(c)
    again = c.post("/api/checkout/create", json={"merchant_id": "penwright", "plan_key": "penwright-pro",
                                                 "user_id": "priya"})
    assert again.status_code == 409 and "Reset" in again.json()["detail"]
    assert c.post("/api/demo/reset").status_code == 200
    assert c.get("/api/subscriptions?user=priya").json() == []  # earlier runs don't show up
    subscribe(c)
    assert len(c.get("/api/subscriptions?user=priya").json()) == 1


def test_reset_survives_a_reader_holding_the_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Why earlier runs showed up: on Windows a page poll reading the audit log made Reset's rename fail
    (WinError 32), so Reset stopped before wiping the subscriptions. Renames/deletes now retry briefly."""
    src, dst = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    src.write_text("x", encoding="utf-8")
    real, calls = os.replace, {"n": 0}

    def busy(a: object, b: object) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(32, "The process cannot access the file because it is being used")
        real(a, b)  # type: ignore[arg-type]

    monkeypatch.setattr(fsutil, "WAIT_S", 0)
    monkeypatch.setattr(os, "replace", busy)
    fsutil.replace(src, dst)
    assert calls["n"] == 3 and dst.read_text(encoding="utf-8") == "x" and not src.exists()


def test_one_calendar_per_run(demo_client: TestClient) -> None:
    """The bug behind "kept on Nov 12" before the Nov 17 check-in: a trial started on sim Day 5 used its own
    sign-up moment as Day 5. Every subscription now reads Day N as the same date."""
    c = allow_many(demo_client)
    first = subscribe(c)
    advance_to(c, 5)
    second = subscribe(c, review=False)
    svc = c.app.state.services  # type: ignore[attr-defined]
    a, b = svc.sub(first["id"]), svc.sub(second["id"])
    assert day_text(a, 5) == day_text(b, 5) == on(5)
