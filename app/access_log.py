"""Quiet terminal: hide uvicorn's access-log lines for the pages' background polling.

The dashboards poll /api/* every few seconds, and userA's dashboard re-fetches itself with `?live=1`. Logging each
successful poll buries everything else. This filter drops successful (status < 400) GET/HEAD requests to
/api/*, static files, /healthz and `live=1` refreshes. Still shown: page loads, every POST (the real actions:
subscribe, cancel, send...), and every error. `LOG_ALL_REQUESTS=true` turns the filter off.
"""

from __future__ import annotations

import logging

QUIET_PREFIXES = ("/api/", "/static/", "/shop/static/", "/healthz", "/favicon")


class QuietPolling(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True  # not uvicorn's access-log shape: keep it
        _, method, path, _, status = args[:5]
        try:
            ok = int(status) < 400
        except (TypeError, ValueError):
            return True
        path = str(path)
        polling = path.startswith(QUIET_PREFIXES) or "live=1" in path.partition("?")[2]
        return not (ok and str(method) in ("GET", "HEAD") and polling)


def quiet_access_log(enabled: bool) -> None:
    """Add (or remove) the filter on uvicorn's access logger; safe to call more than once."""
    logger = logging.getLogger("uvicorn.access")
    for f in [f for f in logger.filters if isinstance(f, QuietPolling)]:
        logger.removeFilter(f)
    if enabled:
        logger.addFilter(QuietPolling())
