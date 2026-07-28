"""
Structured JSON logging for the SOGo API server.

Provides a ``JsonFormatter`` that outputs structured JSON lines instead of the
default text format.  Auto-enabled when ``SOGO_JSON_LOG=1`` or when the
``FLASK_ENV`` is ``production`` (can be overridden by setting ``SOGO_JSON_LOG=0``).

Each log line contains:
  - ``timestamp`` (ISO-8601)
  - ``level``
  - ``logger`` (logger name, e.g. ``sogolog.api``)
  - ``pid``
  - ``file``, ``func``, ``line``
  - ``request_id``  (from Flask ``g.request_id``, or ``"-"``)
  - ``user``        (user UID, or ``"-"``)
  - ``domain``      (user domain, or ``"-"``)
  - ``message``
  - optional extra fields passed as keyword arguments to the log call
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Log formatter that emits structured JSON lines with request context."""

    # Fields on LogRecord that are *not* extra keyword arguments
    _SKIP_KEYS: frozenset[str] = frozenset({
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module",
        "msecs", "message", "msg", "name", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "thread",
        "threadName",
    })

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "pid": record.process,
            "file": record.pathname,
            "func": record.funcName,
            "line": record.lineno,
            "request_id": getattr(record, "request_id", "-"),
            "user": getattr(record, "user_uid", "-"),
            "domain": getattr(record, "user_domain", "-"),
            "message": record.getMessage(),
        }

        # Add any extra custom fields (passed as kwargs to the log call)
        for key, value in record.__dict__.items():
            if key not in self._SKIP_KEYS:
                payload[key] = value

        if record.exc_info and record.exc_info[0]:
            payload["exception"] = {
                "type": record.exc_info[0].__name__,
                "value": str(record.exc_info[1]),
            }

        return json.dumps(payload, default=str, ensure_ascii=False)


def enable_json_logging() -> None:
    """Patch the root sogolog logger and its children to use ``JsonFormatter``.

    Auto-enabled when ``SOGO_JSON_LOG=1`` or ``FLASK_ENV=production``.
    Explicitly disable with ``SOGO_JSON_LOG=0``.
    """
    env = os.environ.get("SOGO_JSON_LOG", "")
    if env == "1":
        pass  # explicit opt-in
    elif env == "0":
        return  # explicit opt-out
    elif os.environ.get("FLASK_ENV", "") == "production":
        pass  # auto-enable in production
    else:
        return  # development → keep console format

    json_handler = logging.StreamHandler()
    json_handler.setFormatter(JsonFormatter())

    root = logging.getLogger("sogolog")
    # Remove existing handlers
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(json_handler)
    root.propagate = False

    # Ensure all child loggers use the same handler (no duplicate propagation)
    for name in list(logging.root.manager.loggerDict):  # type: ignore[attr-defined]
        if name.startswith("sogolog."):
            child = logging.getLogger(name)
            child.handlers.clear()
            child.propagate = False


# Auto-enable on import (after logger.py has run)
enable_json_logging()
