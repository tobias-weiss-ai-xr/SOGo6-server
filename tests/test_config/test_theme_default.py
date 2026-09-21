# pylint: disable=invalid-sequence-index
"""Unit tests for THEME-1: SOGO_DEFAULT_THEME read-time fallback in get_all_preferences."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByUv")

import pytest


def make_interface(stored: dict):
    """Build an InterfaceUserPreferences with a mocked module returning *stored*."""
    from app.interface.user.InterfaceUserPreferences import InterfaceUserPreferences

    with mock.patch(
        "app.interface.user.InterfaceUserPreferences.ModuleUserProfile"
    ) as mod_cls:
        iface = InterfaceUserPreferences(
            process_settings=mock.MagicMock(),
            user_domain={},
            user=mock.MagicMock(),
        )
        iface.module_user_profile.get_user_preferences.return_value = stored
    return iface


class TestDefaultUserThemeReadFallback:
    def test_env_unset_fills_default(self, monkeypatch):
        monkeypatch.delenv("SOGO_DEFAULT_THEME", raising=False)
        iface = make_interface({"USER_GENERAL": {"SOGO_U_LANGUAGE": "German"}})
        resp, code = iface.get_all_preferences()
        assert code == 200
        assert resp["data"]["USER_GENERAL"]["SOGO_U_THEME"] == "default"
        assert resp["data"]["USER_GENERAL"]["SOGO_U_LANGUAGE"] == "German"

    def test_env_sogo5_classic_served(self, monkeypatch):
        monkeypatch.setenv("SOGO_DEFAULT_THEME", "sogo5-classic")
        iface = make_interface({"USER_GENERAL": {}})
        resp, code = iface.get_all_preferences()
        assert code == 200
        assert resp["data"]["USER_GENERAL"]["SOGO_U_THEME"] == "sogo5-classic"

    def test_stored_theme_not_overwritten(self, monkeypatch):
        monkeypatch.setenv("SOGO_DEFAULT_THEME", "sogo5-classic")
        iface = make_interface(
            {"USER_GENERAL": {"SOGO_U_THEME": "default", "SOGO_U_LANGUAGE": "French"}}
        )
        resp, code = iface.get_all_preferences()
        assert code == 200
        assert resp["data"]["USER_GENERAL"]["SOGO_U_THEME"] == "default"
        assert resp["data"]["USER_GENERAL"]["SOGO_U_LANGUAGE"] == "French"

    def test_helper_reads_env_at_call_time(self, monkeypatch):
        from app.config.settings.UserSettings import default_user_theme

        monkeypatch.delenv("SOGO_DEFAULT_THEME", raising=False)
        assert default_user_theme() == "default"
        monkeypatch.setenv("SOGO_DEFAULT_THEME", "sogo5-classic")
        assert default_user_theme() == "sogo5-classic"

    def test_missing_user_general_ignored(self):
        iface = make_interface({})
        resp, code = iface.get_all_preferences()
        assert code == 200
        assert resp["data"] == {}
