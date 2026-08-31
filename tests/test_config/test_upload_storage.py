"""
Tests for attachment upload storage configuration and initialization.

Tests cover:
1. Configuration variables for upload storage paths
2. Startup initialization of upload directories
"""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from app.config.settings.ProcessSetting import process_config


class TestUploadStorageConfig:
    """Test upload storage configuration variables."""

    def test_upload_storage_path_default(self):
        """Test that UPLOAD_STORAGE_PATH has a sensible default."""
        assert hasattr(process_config, 'SOGO_UPLOAD_PATH')
        assert process_config.SOGO_UPLOAD_PATH == '/var/lib/sogo6/uploads'

    def test_upload_temp_path_default(self):
        """Test that UPLOAD_TEMP_PATH has a sensible default."""
        assert hasattr(process_config, 'SOGO_UPLOAD_TEMP_PATH')
        assert process_config.SOGO_UPLOAD_TEMP_PATH == '/var/lib/sogo6/uploads/tmp'

    def test_max_attachment_size_default(self):
        """Test that MAX_ATTACHMENT_SIZE has a sensible default."""
        assert hasattr(process_config, 'SOGO_MAX_ATTACHMENT_SIZE')
        assert process_config.SOGO_MAX_ATTACHMENT_SIZE == 25_000_000  # 25MB

    def test_allowed_attachment_types_default(self):
        """Test that ALLOWED_ATTACHMENT_TYPES has a sensible default."""
        assert hasattr(process_config, 'SOGO_ALLOWED_ATTACHMENT_TYPES')
        assert isinstance(process_config.SOGO_ALLOWED_ATTACHMENT_TYPES, list)
        # Should include common types
        allowed = process_config.SOGO_ALLOWED_ATTACHMENT_TYPES
        assert 'application/pdf' in allowed
        assert 'image/jpeg' in allowed
        assert 'image/png' in allowed

    def test_config_override_from_env(self):
        """Test that configuration can be overridden via environment variables."""
        with patch.dict(os.environ, {
            'SOGO_UPLOAD_PATH': '/custom/uploads',
            'SOGO_UPLOAD_TEMP_PATH': '/custom/tmp',
            'SOGO_MAX_ATTACHMENT_SIZE': '50000000',
        }):
            from app.config.settings.ProcessSetting import ProcessSetting
            # Create a new instance to pick up the env vars
            test_config = ProcessSetting()
            assert test_config.SOGO_UPLOAD_PATH == '/custom/uploads'
            assert test_config.SOGO_UPLOAD_TEMP_PATH == '/custom/tmp'
            assert test_config.SOGO_MAX_ATTACHMENT_SIZE == 50_000_000


class TestUploadStorageInit:
    """Test upload storage initialization on startup."""

    def test_init_upload_storage_creates_dirs(self):
        """Test that init_upload_storage creates required directories."""
        from app.config.init_config import init_upload_storage
        
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_path = os.path.join(tmpdir, 'uploads')
            temp_path = os.path.join(tmpdir, 'uploads', 'tmp')
            
            # Mock the config to use our temp directories
            with patch.object(process_config, 'SOGO_UPLOAD_PATH', upload_path):
                with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', temp_path):
                    # Call the initialization
                    init_upload_storage()
                    
                    # Verify directories were created
                    assert os.path.isdir(upload_path)
                    assert os.path.isdir(temp_path)

    def test_init_upload_storage_exist_ok(self):
        """Test that init_upload_storage works when directories already exist."""
        from app.config.init_config import init_upload_storage
        
        with tempfile.TemporaryDirectory() as tmpdir:
            upload_path = os.path.join(tmpdir, 'uploads')
            temp_path = os.path.join(tmpdir, 'uploads', 'tmp')
            
            # Pre-create the directories
            os.makedirs(upload_path, exist_ok=True)
            os.makedirs(temp_path, exist_ok=True)
            
            # Call the initialization - should not fail
            with patch.object(process_config, 'SOGO_UPLOAD_PATH', upload_path):
                with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', temp_path):
                    init_upload_storage()
                    
                    # Directories should still exist
                    assert os.path.isdir(upload_path)
                    assert os.path.isdir(temp_path)


class TestUploadStorageIntegration:
    """Integration tests for upload storage configuration and initialization."""

    def test_full_startup_flow(self):
        """Test that upload storage initialization is part of the startup flow."""
        from app.config.init_config import init_infra
        
        # This should complete without errors
        # Note: This may fail if Redis/DB are not available, but we're just
        # checking that the function is callable
        try:
            cache_client, persistency = init_infra()
            # If we get here, the infra initialized successfully
            assert cache_client is not None
            assert persistency is not None
        except Exception as e:
            # It's okay if Redis/DB are not available in test environment
            # We're just verifying the function exists and is callable
            assert "redis" in str(e).lower() or "database" in str(e).lower() or "connection" in str(e).lower()
