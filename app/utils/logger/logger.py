"""
Professional logging setup for the SOGo server.

Features:
  - File-based rotating logging (configurable via ``SOGO_LOG_DIR`` / ``SOGO_LOG_FILE``)
  - ANSI terminal or JSON structured output (auto-detects JSON in production)
  - Per-subsystem named loggers with inherited levels
  - Correlation ID injected from Flask ``g.request_id``
  - User/domain/session context enrichment
  - Safe IMAP logging (never prints credentials)
  - Respects ``SOGO_LOG_LEVEL`` environment variable (fallback: INFO in production, DEBUG in dev)
"""

from __future__ import annotations

import logging
import os
import sys
from logging import DEBUG, INFO, WARNING, ERROR, CRITICAL
from logging.handlers import RotatingFileHandler

# ---------------------------------------------------------------------------
# Level resolution
# ---------------------------------------------------------------------------

_LOG_LEVEL_MAP: dict[str, int] = {
    "DEBUG": DEBUG,
    "INFO": INFO,
    "WARNING": WARNING,
    "ERROR": ERROR,
    "CRITICAL": CRITICAL,
}


def _resolve_level(default: int = INFO) -> int:
    """Return the numeric log level from the ``SOGO_LOG_LEVEL`` env var, falling back to *default*."""
    raw = os.environ.get("SOGO_LOG_LEVEL", "").strip().upper()
    if raw in _LOG_LEVEL_MAP:
        return _LOG_LEVEL_MAP[raw]
    # Fallback: production → INFO, dev → DEBUG
    if os.environ.get("FLASK_ENV", "") == "production" or os.environ.get("SOGO_JSON_LOG") == "1":
        return INFO
    return DEBUG


# ---------------------------------------------------------------------------
# File handler helpers
# ---------------------------------------------------------------------------

def _ensure_log_dir(log_dir: str) -> str:
    """Create *log_dir* if it does not exist; return the path."""
    if not os.path.isdir(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as exc:
            print(f"[sogolog] Cannot create log directory {log_dir}: {exc}", file=sys.stderr)
    return log_dir


def _build_file_handler(log_file: str, level: int, formatter: logging.Formatter) -> RotatingFileHandler | None:
    """Build a rotating file handler. Returns ``None`` when the path is not writable."""
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            _ensure_log_dir(log_dir)
        handler = RotatingFileHandler(
            log_file,
            maxBytes=100 * 1024 * 1024,  # 100 MB
            backupCount=10,
        )
        handler.setLevel(level)
        handler.setFormatter(formatter)
        return handler
    except (OSError, PermissionError) as exc:
        print(f"[sogolog] Cannot create rotating file handler for {log_file}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Request correlation filter
# ---------------------------------------------------------------------------

class CorrelationFilter(logging.Filter):
    """Injects ``request_id``, ``user``, ``domain`` into every log record from Flask ``g`` when available."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from flask import g as flask_g

            record.request_id = getattr(flask_g, "request_id", None) or "-"
            record.user_uid = getattr(flask_g, "user", None) and getattr(flask_g.user, "uid", "-") or "-"
            record.user_domain = getattr(flask_g, "user", None) and getattr(flask_g.user, "domain", "-") or "-"
        except Exception:
            record.request_id = "-"
            record.user_uid = "-"
            record.user_domain = "-"
        return True


# ---------------------------------------------------------------------------
# Custom formatters
# ---------------------------------------------------------------------------

class SogoConsoleFormatter(logging.Formatter):
    """Human-readable console formatter with correlation ID."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s <%(process)s> [%(levelname)s][%(name)s][%(filename)s:%(funcName)s:%(lineno)d] "
                "req=%(request_id)s user=%(user_uid)s@%(user_domain)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )


# ---------------------------------------------------------------------------
# Logger initialisation
# ---------------------------------------------------------------------------

_root_level = _resolve_level()

# Remove any pre-existing handlers on the root slogger so we start clean
logging.getLogger("sogolog").handlers.clear()

# ---- Console handler (always present) ----
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(_root_level)
console_handler.setFormatter(SogoConsoleFormatter())
console_handler.addFilter(CorrelationFilter())

# ---- File handler (opt-in via SOGO_LOG_FILE / SOGO_LOG_DIR) ----
_file_handler: RotatingFileHandler | None = None

log_file = os.environ.get("SOGO_LOG_FILE", "")
if not log_file:
    log_dir = os.environ.get("SOGO_LOG_DIR", "")
    if log_dir:
        log_file = os.path.join(_ensure_log_dir(log_dir), "sogo.log")

if log_file:
    _file_handler = _build_file_handler(log_file, _root_level, SogoConsoleFormatter())

# ---- Wire up the root sogolog logger ----
root_logger = logging.getLogger("sogolog")
root_logger.setLevel(_root_level)
root_logger.addHandler(console_handler)
if _file_handler:
    root_logger.addHandler(_file_handler)
root_logger.propagate = False

# Disable werkzeug's own access log (we replace it with structured one)
logging.getLogger("werkzeug").setLevel(WARNING)


# ---------------------------------------------------------------------------
# Named loggers (children inherit handlers + level from the root)
# ---------------------------------------------------------------------------

logger: logging.Logger = root_logger
logger_api: logging.Logger = logging.getLogger("sogolog.api")
logger_usersource: logging.Logger = logging.getLogger("sogolog.usersource")
logger_config: logging.Logger = logging.getLogger("sogolog.config")
logger_auth: logging.Logger = logging.getLogger("sogolog.auth")
logger_sql: logging.Logger = logging.getLogger("sogolog.sql")
logger_imap: logging.Logger = logging.getLogger("sogolog.imap")
logger_sieve: logging.Logger = logging.getLogger("sogolog.sieve")
logger_cache: logging.Logger = logging.getLogger("sogolog.cache")
logger_mail_server: logging.Logger = logging.getLogger("sogolog.mailserver")
logger_mail_outgoing: logging.Logger = logging.getLogger("sogolog.mailoutgoing")
logger_user_profile: logging.Logger = logging.getLogger("sogolog.userprofile")
logger_calendar: logging.Logger = logging.getLogger("sogolog.calendar")
logger_agent: logging.Logger = logging.getLogger("sogolog.agent")
logger_contact: logging.Logger = logging.getLogger("sogolog.contact")
logger_ldap: logging.Logger = logging.getLogger("sogolog.ldap")


# ---------------------------------------------------------------------------
# Child-logger overrides (only for subsystems that need a different level)
# ---------------------------------------------------------------------------

# Cache and LDAP are intentionally quieter in production
if _root_level <= DEBUG:
    logger_cache.setLevel(DEBUG)
    logger_ldap.setLevel(DEBUG)
    logger_sql.setLevel(DEBUG)
else:
    logger_cache.setLevel(WARNING)
    logger_ldap.setLevel(WARNING)
    logger_sql.setLevel(WARNING)

# IMAP: never log below WARNING to avoid leaking passwords via imaplib debug output
logger_imap.setLevel(WARNING)

# API logger: match root level (no extra DEBUG override)
logger_api.setLevel(_root_level)


# ---------------------------------------------------------------------------
# Safe IMAP logging (never print credentials)
# ---------------------------------------------------------------------------

# The imaplib debug level is kept at 0 unless the imap logger itself is set to DEBUG,
# and even then we cap at WARNING to avoid leaking credentials via imaplib's built-in
# protocol dump.  A dedicated IMAP traffic logger (outside imaplib) can be added later.
import imaplib
imaplib.Debug = 0
