# pylint: disable=invalid-sequence-index
"""Unit tests for PREF-1: Stop preferences default-injection stomping stored user settings on PATCH"""
from __future__ import annotations

import os

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
from marshmallow import fields
from app.config.settings.SogoSchema import SogoSchema, check_data_for_sogo_schemas
from app.config.settings.UserSettings import get_all_user_settings_schema


class TestPreferencesNoStomp: 
    """Tests to ensure PATCH operations don't stomp stored user preferences with defaults."""

    def test_check_data_for_sogo_schemas_preserves_existing_fields(self):
        """Test that check_data_for_sogo_schemas preserves existing fields without adding defaults."""
        from app.config.settings.UserSettings import UserGeneralSettings
        
        # Simulate user has stored only 2 out of many fields in USER_GENERAL
        stored_data = {
            "USER_GENERAL": {
                "SOGO_U_LANGUAGE": "French",
                "SOGO_U_TIMEZONE": "Europe/Paris"
                # Other fields like SOGO_U_TIME_FORMAT, SOGO_U_THEME, etc. are NOT stored
            }
        }
        
        # This should preserve the existing fields and NOT add defaults for missing ones
        result = check_data_for_sogo_schemas(stored_data, get_all_user_settings_schema, inject_defaults=False)
        
        # Check that existing fields are preserved
        assert result["USER_GENERAL"]["SOGO_U_LANGUAGE"] == "French"
        assert result["USER_GENERAL"]["SOGO_U_TIMEZONE"] == "Europe/Paris"
        
        # Check that other USER_GENERAL fields were NOT added with defaults
        # The user never set these, so they shouldn't be in the result
        # Note: If the user explicitly wants defaults, they should be set during creation
        # But PATCH operations should not add them
        general_schema = UserGeneralSettings()
        all_fields = set(general_schema.fields.keys())
        stored_fields = set(stored_data["USER_GENERAL"].keys())
        result_fields = set(result["USER_GENERAL"].keys())
        
        # With partial=True, only the stored fields should be in the result
        # (assuming no new fields were added via PATCH)
        # But wait - the user might have other fields stored that we didn't include in our test
        # So we should at least check that we didn't add any fields that weren't in the input
        assert result_fields == stored_fields, f"Expected {stored_fields}, got {result_fields}"

    def test_check_data_for_sogo_schemas_with_patch_simulation(self):
        """Test that after merge_patch and check_data_for_sogo_schemas, no defaults are added."""
        from app.config.settings.UserSettings import UserGeneralSettings
        from app.utils.dict import merge_patch
        from copy import deepcopy
        
        # Simulate user has stored preferences with custom values
        stored_data = {
            "USER_GENERAL": {
                "SOGO_U_LANGUAGE": "French",
                "SOGO_U_TIMEZONE": "Europe/Paris"
            }
        }
        
        # Simulate a PATCH request
        patch = {
            "USER_GENERAL": {
                "SOGO_U_LANGUAGE": "German"
            }
        }
        
        # Merge the patch (simulating what update_user_preferences does)
        current_data = deepcopy(stored_data)
        merge_patch(patch, current_data)
        
        # Check the data after merge
        assert current_data["USER_GENERAL"]["SOGO_U_LANGUAGE"] == "German"
        assert current_data["USER_GENERAL"]["SOGO_U_TIMEZONE"] == "Europe/Paris"
        
        # Now call check_data_for_sogo_schemas
        result = check_data_for_sogo_schemas(current_data, get_all_user_settings_schema, inject_defaults=False)
        
        # Check that the patched field was updated
        assert result["USER_GENERAL"]["SOGO_U_LANGUAGE"] == "German"
        
        # Check that the other field was preserved
        assert result["USER_GENERAL"]["SOGO_U_TIMEZONE"] == "Europe/Paris"
        
        # Check that no additional fields were added with defaults
        # The result should only have the fields that were in the merged data
        expected_fields = {"SOGO_U_LANGUAGE", "SOGO_U_TIMEZONE"}
        result_fields = set(result["USER_GENERAL"].keys())
        assert result_fields == expected_fields, f"Expected {expected_fields}, got {result_fields}"

    def test_check_data_for_sogo_schemas_with_new_subparent(self):
        """Test that when a new subparent is added, only the provided fields are present."""
        from app.config.settings.UserSettings import UserGeneralSettings, UserSecuritySettings
        
        # User has no preferences stored
        stored_data = {}
        
        # Simulate a PATCH that adds a new subparent with one field
        patch = {
            "USER_GENERAL": {
                "SOGO_U_LANGUAGE": "German"
            }
        }
        
        # Merge the patch
        from app.utils.dict import merge_patch
        from copy import deepcopy
        current_data = deepcopy(stored_data)
        merge_patch(patch, current_data)
        
        # Now call check_data_for_sogo_schemas
        result = check_data_for_sogo_schemas(current_data, get_all_user_settings_schema, inject_defaults=False)
        
        # Check that only the patched field is present
        assert result["USER_GENERAL"]["SOGO_U_LANGUAGE"] == "German"
        
        # With partial=True, other USER_GENERAL fields should NOT be added
        # This is different from the creation path where defaults ARE added
        assert "SOGO_U_TIMEZONE" not in result["USER_GENERAL"], "Default should not be added during PATCH"
        assert "SOGO_U_TIME_FORMAT" not in result["USER_GENERAL"], "Default should not be added during PATCH"
        
        # But other subparents should still be processed (they'll be empty)
        assert "USER_SECURITY" in result, "Other subparents should be processed"


    def test_check_data_defaults_still_injected_on_creation(self):
        """inject_defaults=True (creation path) must still fill load_default values."""
        stored_data = {"USER_GENERAL": {"SOGO_U_LANGUAGE": "German"}}
        result = check_data_for_sogo_schemas(
            stored_data, get_all_user_settings_schema, inject_defaults=True
        )
        assert result["USER_GENERAL"]["SOGO_U_LANGUAGE"] == "German"
        assert result["USER_GENERAL"]["SOGO_U_THEME"] == "default"  # load_default filled
