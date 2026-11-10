"""Quiet terminal: background polling is hidden from uvicorn's access log; actions, pages and errors are not."""

from __future__ import annotations

import logging

import pytest

from app.access_log import QuietPolling, quiet_access_log


def record(method: str, path: str, status: int) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:5000", method, path, "1.1", status), None)


@pytest.mark.parametrize(("method", "path", "status", "shown"), [
    ("GET", "/api/alerts?user=usera", 200, False),
    ("GET", "/api/audit-log/verify", 200, False),
    ("GET", "/static/app.js", 304, False),
    ("GET", "/shop/static/checkout.js", 200, False),
    ("GET", "/healthz", 200, False),
    ("GET", "/user?user=usera&live=1", 200, False),
    ("GET", "/", 200, True),                             # a page load
    ("GET", "/user", 200, True),
    ("POST", "/api/checkout/demo-paypal-window", 200, True),  # an action
    ("POST", "/api/demo/advance?to_day=5", 200, True),
    ("GET", "/api/subscriptions/x/paypal", 403, True),   # an error
    ("GET", "/api/alerts", 500, True),
])
def test_filter(method: str, path: str, status: int, shown: bool) -> None:
    assert QuietPolling().filter(record(method, path, status)) is shown


def test_other_records_pass_and_setting_turns_it_off() -> None:
    plain = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "hello", None, None)
    assert QuietPolling().filter(plain)
    logger = logging.getLogger("uvicorn.access")
    quiet_access_log(True)
    quiet_access_log(True)
    assert sum(isinstance(f, QuietPolling) for f in logger.filters) == 1  # idempotent
    quiet_access_log(False)
    assert not any(isinstance(f, QuietPolling) for f in logger.filters)


def test_live_refresh_is_marked() -> None:
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "app" / "static" / "user.js").read_text(encoding="utf-8")
    assert 'url.searchParams.set("live", "1")' in js
