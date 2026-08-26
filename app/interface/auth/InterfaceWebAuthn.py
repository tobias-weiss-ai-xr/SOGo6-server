from __future__ import annotations

import base64
import time
from typing import TYPE_CHECKING, Any

from app.module.auth.ModuleWebAuthn import ModuleWebAuthn
from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_api

if TYPE_CHECKING:
    from app.auth.User import User
    from app.config.settings.ProcessSetting import ProcessSetting


# Challenge TTL in seconds
_CHALLENGE_TTL = 120


class InterfaceWebAuthn:
    """High-level WebAuthn operations used by the API layer.

    Adapter over :class:`ModuleWebAuthn`. Generation + credential storage are
    delegated to the module; short-lived challenges are tracked in-memory per
    process (acceptable for dev, matching the module's own DB-backed store when
    the complete handshakes are used).
    """

    def __init__(self, process: ProcessSetting) -> None:
        self._process = process
        self._module = ModuleWebAuthn()
        # Challenges are stored in-memory per-process — acceptable for dev;
        # production should use Redis when scaling beyond one worker.
        self._challenges: dict[str, dict[str, Any]] = {}

    # ── Registration ─────────────────────────────────────────────────────

    def registration_begin(
        self,
        user: User,
        rp_id: str,
        rp_name: str = "SOGo 6",
        origin: str | None = None,
    ) -> dict[str, Any]:
        origin = origin or f"https://{rp_id}"
        options = self._module.generate_registration_options(
            user_id=user.uid,
            user_name=user.cn or user.uid,
            user_display_name=user.cn or user.uid,
            rp_id=rp_id,
            rp_name=rp_name,
        )
        challenge = options.get("challenge", "")
        self._challenges[user.uid] = {
            "type": "registration",
            "challenge": challenge,
            "origin": origin,
            "rp_id": rp_id,
            "created_at": time.time(),
        }
        logger_api.debug("WebAuthn registration begin for user=%s", user.uid)
        return {"publicKey": options}

    def registration_complete(
        self,
        user: User,
        credential: dict[str, Any],
        device_name: str = "",
    ) -> dict[str, Any]:
        challenge_data = self._challenges.pop(user.uid, None)
        if not challenge_data or challenge_data["type"] != "registration":
            raise RequestException(
                "No registration challenge in progress",
                err.ERROR_WEBAUTHN_CHALLENGE_EXPIRED,
            )
        if time.time() - challenge_data["created_at"] > _CHALLENGE_TTL:
            raise RequestException(
                "Registration challenge expired",
                err.ERROR_WEBAUTHN_CHALLENGE_EXPIRED,
            )

        try:
            result = self._module.register_credential(
                user_id=user.uid,
                credential=credential,
                name=device_name,
            )
        except Exception as exc:
            logger_api.warning("WebAuthn registration failed for %s: %s", user.uid, exc)
            raise RequestException(
                "WebAuthn registration verification failed",
                err.ERROR_WEBAUTHN_REGISTRATION_FAILED,
            ) from exc

        data = result.to_dict()
        logger_api.info("WebAuthn registration complete for user=%s", user.uid)
        return {
            "credential_id": data.get("id"),
            "device_name": device_name,
        }

    # ── Authentication (login) ────────────────────────────────────────────

    def authentication_begin(
        self,
        rp_id: str,
        user_uid: str | None = None,
        origin: str | None = None,
    ) -> dict[str, Any]:
        origin = origin or f"https://{rp_id}"
        options = self._module.generate_authentication_options(
            user_id=user_uid or "",
            rp_id=rp_id,
        )
        challenge = options.get("challenge", "")
        challenge_key = user_uid or "__anonymous__"
        self._challenges[challenge_key] = {
            "type": "authentication",
            "challenge": challenge,
            "origin": origin,
            "rp_id": rp_id,
            "created_at": time.time(),
        }
        logger_api.debug("WebAuthn authentication begin for user=%s", user_uid or "anonymous")
        return {"publicKey": options}

    def authentication_complete(
        self,
        credential: dict[str, Any],
    ) -> dict[str, Any]:
        # Find the challenge by iterating — the credential may have been
        # preceded by a user-specific or anonymous begin call
        challenge_data: dict[str, Any] | None = None
        challenge_key: str | None = None
        for key, data in list(self._challenges.items()):
            if data["type"] == "authentication":
                challenge_data = data
                challenge_key = key
                break

        if not challenge_data:
            raise RequestException(
                "No authentication challenge in progress",
                err.ERROR_WEBAUTHN_CHALLENGE_EXPIRED,
            )
        if time.time() - challenge_data["created_at"] > _CHALLENGE_TTL:
            self._challenges.pop(challenge_key, None)
            raise RequestException(
                "Authentication challenge expired",
                err.ERROR_WEBAUTHN_CHALLENGE_EXPIRED,
            )
        self._challenges.pop(challenge_key, None)

        try:
            # Migrate the in-memory challenge into the module's DB-backed store
            # so the module verifier can resolve it by id.
            padded = challenge_data["challenge"]
            padded = padded + "=" * ((4 - len(padded) % 4) % 4)
            challenge = ModuleWebAuthn.create_challenge(
                user_id=challenge_key if challenge_key not in (None, "__anonymous__") else None,
                challenge_type="authentication",
                challenge_bytes=base64.urlsafe_b64decode(padded),
                rp_id=challenge_data["rp_id"],
            )
            stored, user_id = ModuleWebAuthn.authenticate(
                challenge.id,
                credential,
            )
        except Exception as exc:
            logger_api.warning("WebAuthn authentication failed: %s", exc)
            raise RequestException(
                "WebAuthn authentication verification failed",
                err.ERROR_WEBAUTHN_AUTHENTICATION_FAILED,
            ) from exc

        logger_api.info("WebAuthn authentication succeeded for user=%s", user_id)
        return {
            "user_uid": user_id,
            "credential_id": stored.id,
        }

    # ── Credential management ─────────────────────────────────────────────

    def get_credentials(self, user_uid: str) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self._module.get_credentials_by_user(user_uid)]

    def delete_credential(self, credential_id: str, user_uid: str) -> None:
        self._module.remove_credential(credential_id, user_uid)

    def has_enabled_credentials(self, user_uid: str) -> bool:
        return self._module.get_user_has_passkeys(user_uid)