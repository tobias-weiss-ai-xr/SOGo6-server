"""
Interface layer for application-password management.

Wraps ModuleAppPassword with API-friendly methods, ownership guards,
and integration with the authenticated user context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module.auth.ModuleAppPassword import ModuleAppPassword
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User
    from app.manager.db.ClientSQL import ClientSQL


class InterfaceAppPassword:
    """High-level app-password operations used by the API layer."""

    def __init__(self, db: ClientSQL) -> None:
        self._module = ModuleAppPassword(db)

    def create(self, user_uid: str, label: str) -> dict[str, Any]:
        """Create a new app password for the given user.

        :param user_uid: The user's email / UID.
        :param label: Human-readable description (e.g. "Thunderbird").
        :returns: Dict with 'token' (shown once) and 'app_password' metadata.
        :raises RequestException: On validation or DB errors.
        """
        try:
            raw_token, record = self._module.create(user_uid, label)
        except RequestException:
            raise
        except Exception as exc:
            logger_api.error("Failed to create app password for %s: %s", user_uid, exc)
            raise RequestException(
                "Failed to create app password",
                err.ERROR_SERVER,
            ) from exc

        return {
            "token": raw_token,
            "app_password": record,
        }

    def list(self, user_uid: str) -> list[dict[str, Any]]:
        """List all app passwords for a user (metadata only, no tokens)."""
        return self._module.list_for_user(user_uid)

    def delete(self, record_id: int, user_uid: str) -> None:
        """Revoke an app password by its ID, with ownership guard.

        :raises RequestException: If not found or not owned.
        """
        try:
            self._module.delete(record_id, user_uid)
        except RequestException:
            raise
        except Exception as exc:
            logger_api.error("Failed to revoke app password %d for %s: %s", record_id, user_uid, exc)
            raise RequestException(
                "Failed to revoke app password",
                err.ERROR_SERVER,
            ) from exc
