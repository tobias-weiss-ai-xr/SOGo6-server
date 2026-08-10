"""
Module for admin authentication
"""

from __future__ import annotations
import secrets
from typing import TYPE_CHECKING

from app.auth.service.VoucherAdminService import VoucherAdminService
from app.service import sogo_cache
from app.utils.exceptions import RequestException
from app.utils import errors as err
from app.utils.logger.logger import logger

if TYPE_CHECKING:
    from app.config.settings.ProcessSetting import ProcessSetting


class ModuleAdminAuth:
    """
    Module to handle admin authentication.
    Unlike user authentication, admin auth is simple: username/password check against process settings.
    """

    def __init__(self, process: ProcessSetting):
        """
        Initialize the admin authentication module

        :param process: Process settings
        :type process: ProcessSetting
        :raises RequestException: If admin credentials are not configured
        """
        self.process_settings = process
        # Validate that admin credentials are configured
        admin_user = getattr(process, 'SOGO_P_ADMIN', None)
        admin_pwd = getattr(process, 'SOGO_P_ADMIN_PWD', None)
        if not admin_user or not admin_pwd:
            logger.error("Admin authentication not configured. SOGO_P_ADMIN or SOGO_P_ADMIN_PWD is missing.")
            raise RequestException(
                "Admin authentication is not configured properly. Please set SOGO_P_ADMIN and SOGO_P_ADMIN_PWD.",
                err.ERROR_ADMIN_AUTH_NOT_CONFIG
            )

    def check_admin_login(self, username: str, password: str) -> bool:
        """
        Check admin credentials against process settings.
        
        Uses constant-time comparison to prevent timing attacks.

        :param username: Admin username
        :type username: str
        :param password: Admin password
        :type password: str
        :return: True if credentials match
        :rtype: bool
        """
        try:
            admin_user = self.process_settings.SOGO_P_ADMIN
            admin_pwd = self.process_settings.SOGO_P_ADMIN_PWD
            # Use constant-time comparison to prevent timing attacks
            username_ok = secrets.compare_digest(username, admin_user)
            password_ok = secrets.compare_digest(password, admin_pwd)
            return username_ok and password_ok
        except (AttributeError, TypeError):
            return False

    def generate_voucher_from_admin(self, admin_uid: str) -> dict:
        """
        Generate a voucher for an authenticated admin.

        :param admin_uid: Admin username
        :type admin_uid: str
        :return: Dictionary containing the jwt_token
        :rtype: dict
        """
        voucher_admin_service = VoucherAdminService(self.process_settings)
        voucher_data = voucher_admin_service.generate_voucher_from_admin(admin_uid)
        return {"jwt_token": voucher_data}

    def logout_admin(self, voucher_data: str) -> None:
        """
        Revoke the admin session associated with the given voucher.

        :param voucher_data: The raw voucher (JWT token) from the Authorization header
        :type voucher_data: str
        :raises RequestException: If the voucher is invalid or the session cannot be revoked
        """
        voucher_admin_service = VoucherAdminService(self.process_settings)
        _, redis_key = voucher_admin_service.get_redis_session_key_from_voucher(voucher_data)

        cache = sogo_cache()
        cache.revoke_user_sessions_by_key([redis_key])
        cache.close()
