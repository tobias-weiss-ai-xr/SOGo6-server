# pylint: disable=invalid-sequence-index
"""Unit tests for the attachment cleanup job (F2: Send Attachment, subsection 5).

Tests cover the hourly cleanup job that:
1. Deletes expired temporary attachment files (>24h)
2. Removes orphaned Redis keys for attachments not in the filesystem

Tests run WITHOUT a live stack: Redis connections are mocked,
mirroring the rest of the suite.
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, mock_open

import pytest

# Set required environment variables for ProcessSetting
os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_cache():
    """Create a fake cache that stores in memory."""
    import json as _json

    class FakeRedis:
        """Fake redis-py client for testing."""
        def __init__(self, cache):
            self._cache = cache
        
        def scan_iter(self, match=None, count=None):
            """Return an iterator of keys matching the pattern."""
            if match is None:
                keys = list(self._cache._store.keys())
            else:
                if match.endswith("*"):
                    prefix = match[:-1]
                    keys = [k for k in self._cache._store.keys() if k.startswith(prefix)]
                else:
                    keys = [k for k in self._cache._store.keys() if k == match]
            return iter(keys)
        
        def keys(self, pattern=None):
            """Return all keys matching the pattern."""
            if pattern is None:
                return list(self._cache._store.keys())
            else:
                if pattern.endswith("*"):
                    prefix = pattern[:-1]
                    return [k for k in self._cache._store.keys() if k.startswith(prefix)]
                else:
                    return [k for k in self._cache._store.keys() if k == pattern]

    class FakeCache:
        def __init__(self):
            self._store: dict = {}
            self.redis = FakeRedis(self)

        def get(self, key, expected_type=str):
            raw = self._store.get(key)
            if raw is None:
                return None
            if expected_type == str:
                return raw
            try:
                return _json.loads(raw)
            except (TypeError, _json.JSONDecodeError):
                return raw

        def set(self, key, val, ttl=None, nx=False):
            if nx and key in self._store:
                return False
            if not isinstance(val, str):
                val = _json.dumps(val)
            self._store[key] = val
            return True

        def delete(self, *keys):
            removed = 0
            for key in keys:
                if key in self._store:
                    del self._store[key]
                    removed += 1
            return removed

        def scan(self, match=None, count=100, cursor=0):
            """Return all keys matching the pattern (compatibility)."""
            if cursor == 0:
                if match is None:
                    matching = list(self._store.keys())
                else:
                    if match.endswith("*"):
                        prefix = match[:-1]
                        matching = [k for k in self._store.keys() if k.startswith(prefix)]
                    else:
                        matching = [k for k in self._store.keys() if k == match]
                return (0, matching)
            return (0, [])

        def flushdb(self):
            self._store.clear()

        def ping(self):
            return True

    cache = FakeCache()
    yield cache
    cache.flushdb()


@pytest.fixture
def temp_upload_dir(tmp_path):
    """Create a temporary upload directory for testing."""
    upload_dir = tmp_path / "uploads" / "tmp"
    upload_dir.mkdir(parents=True)
    return upload_dir


# ─────────────────────────────────────────────────────────────────────────────
# Tests for ModuleJobCleanup
# ─────────────────────────────────────────────────────────────────────────────


class TestModuleJobCleanup:
    """Test the domain logic for attachment cleanup."""

    def test_cleanup_deletes_expired_files(self, fake_cache, temp_upload_dir):
        """Test that expired files are deleted."""
        from app.config.settings.ProcessSetting import process_config
        from app.module.job.ModuleJobCleanup import ModuleJobCleanup

        # Patch the config to use our temp directory
        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', str(temp_upload_dir)):
            # Create test files with different ages
            old_file = temp_upload_dir / "old_upload"
            recent_file = temp_upload_dir / "recent_upload"
            
            # Create files
            old_file.write_bytes(b"old content")
            recent_file.write_bytes(b"recent content")
            
            # Set old file's modification time to 25 hours ago
            old_time = time.time() - (25 * 3600)
            os.utime(old_file, (old_time, old_time))
            
            # Run cleanup
            cleanup = ModuleJobCleanup(fake_cache)
            result = cleanup.cleanup_expired_attachments()
            
            # Old file should be deleted
            assert not old_file.exists()
            # Recent file should still exist
            assert recent_file.exists()
            assert result["files_deleted"] == 1
            assert result["status"] == "ok"

    def test_cleanup_preserves_recent_files(self, fake_cache, temp_upload_dir):
        """Test that recent files are not deleted."""
        from app.config.settings.ProcessSetting import process_config
        from app.module.job.ModuleJobCleanup import ModuleJobCleanup

        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', str(temp_upload_dir)):
            # Create a recent file
            recent_file = temp_upload_dir / "recent_upload"
            recent_file.write_bytes(b"recent content")
            
            # Run cleanup
            cleanup = ModuleJobCleanup(fake_cache)
            result = cleanup.cleanup_expired_attachments()
            
            # Recent file should still exist
            assert recent_file.exists()
            assert result["files_deleted"] == 0

    def test_cleanup_deletes_redis_keys(self, fake_cache, temp_upload_dir):
        """Test that Redis keys for expired files are deleted."""
        from app.config.settings.ProcessSetting import process_config
        from app.module.job.ModuleJobCleanup import ModuleJobCleanup

        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', str(temp_upload_dir)):
            # Create an old file and its Redis key
            old_file = temp_upload_dir / "old_upload"
            old_file.write_bytes(b"old content")
            
            old_time = time.time() - (25 * 3600)
            os.utime(old_file, (old_time, old_time))
            
            # Add Redis key
            redis_key = "sogo:attachments:old_upload"
            fake_cache.set(redis_key, {"upload_id": "old_upload", "filename": "test.txt"})
            
            # Run cleanup
            cleanup = ModuleJobCleanup(fake_cache)
            result = cleanup.cleanup_expired_attachments()
            
            # File and Redis key should be deleted
            assert not old_file.exists()
            assert fake_cache.get(redis_key, str) is None
            assert result["files_deleted"] == 1
            assert result["keys_deleted"] == 1

    def test_cleanup_handles_missing_directory(self, fake_cache):
        """Test that cleanup handles missing temp directory gracefully."""
        from app.config.settings.ProcessSetting import process_config
        from app.module.job.ModuleJobCleanup import ModuleJobCleanup

        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', "/nonexistent/path"):
            cleanup = ModuleJobCleanup(fake_cache)
            result = cleanup.cleanup_expired_attachments()
            
            assert result["files_deleted"] == 0
            assert result["keys_deleted"] == 0
            assert result["status"] == "ok"

    def test_cleanup_orphaned_redis_keys(self, fake_cache, temp_upload_dir):
        """Test that orphaned Redis keys are deleted."""
        from app.config.settings.ProcessSetting import process_config
        from app.module.job.ModuleJobCleanup import ModuleJobCleanup

        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', str(temp_upload_dir)):
            # Add Redis keys without corresponding files
            redis_key1 = "sogo:attachments:orphan1"
            redis_key2 = "sogo:attachments:orphan2"
            
            fake_cache.set(redis_key1, {"upload_id": "orphan1"})
            fake_cache.set(redis_key2, {"upload_id": "orphan2"})
            
            # Run cleanup
            cleanup = ModuleJobCleanup(fake_cache)
            result = cleanup.cleanup_orphaned_redis_keys()
            
            # Both orphaned keys should be deleted
            assert fake_cache.get(redis_key1, str) is None
            assert fake_cache.get(redis_key2, str) is None
            assert result["keys_deleted"] == 2

    def test_cleanup_preserves_valid_redis_keys(self, fake_cache, temp_upload_dir):
        """Test that Redis keys with existing files are preserved."""
        from app.config.settings.ProcessSetting import process_config
        from app.module.job.ModuleJobCleanup import ModuleJobCleanup

        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', str(temp_upload_dir)):
            # Create a file and its Redis key
            valid_file = temp_upload_dir / "valid_upload"
            valid_file.write_bytes(b"valid content")
            
            redis_key = "sogo:attachments:valid_upload"
            fake_cache.set(redis_key, {"upload_id": "valid_upload"})
            
            # Add an orphaned key
            orphan_key = "sogo:attachments:orphan"
            fake_cache.set(orphan_key, {"upload_id": "orphan"})
            
            # Run cleanup
            cleanup = ModuleJobCleanup(fake_cache)
            result = cleanup.cleanup_orphaned_redis_keys()
            
            # Valid key should be preserved, orphan should be deleted
            assert fake_cache.get(redis_key, str) is not None
            assert fake_cache.get(orphan_key, str) is None
            assert result["keys_deleted"] == 1

    def test_cleanup_all(self, fake_cache, temp_upload_dir):
        """Test that cleanup_all runs both operations."""
        from app.config.settings.ProcessSetting import process_config
        from app.module.job.ModuleJobCleanup import ModuleJobCleanup

        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', str(temp_upload_dir)):
            # Create expired file with Redis key
            old_file = temp_upload_dir / "old_upload"
            old_file.write_bytes(b"old content")
            old_time = time.time() - (25 * 3600)
            os.utime(old_file, (old_time, old_time))
            
            redis_key = "sogo:attachments:old_upload"
            fake_cache.set(redis_key, {"upload_id": "old_upload"})
            
            # Add orphaned key
            orphan_key = "sogo:attachments:orphan"
            fake_cache.set(orphan_key, {"upload_id": "orphan"})
            
            # Run cleanup_all
            cleanup = ModuleJobCleanup(fake_cache)
            result = cleanup.cleanup_all()
            
            # Both should be cleaned up
            assert not old_file.exists()
            assert fake_cache.get(redis_key, str) is None
            assert fake_cache.get(orphan_key, str) is None
            assert result["files_deleted"] == 1
            assert result["keys_deleted"] == 2
            assert result["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Tests for InterfaceJobCleanup
# ─────────────────────────────────────────────────────────────────────────────


class TestInterfaceJobCleanup:
    """Test the interface layer for attachment cleanup."""

    def test_interface_delegates_to_module(self, fake_cache, temp_upload_dir):
        """Test that the interface properly delegates to the module."""
        from app.config.settings.ProcessSetting import process_config
        from app.interface.job.InterfaceJobCleanup import InterfaceJobCleanup

        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', str(temp_upload_dir)):
            interface = InterfaceJobCleanup(fake_cache)
            
            # Create a file that should be cleaned up
            old_file = temp_upload_dir / "old_upload"
            old_file.write_bytes(b"old content")
            old_time = time.time() - (25 * 3600)
            os.utime(old_file, (old_time, old_time))
            
            # Add Redis key
            redis_key = "sogo:attachments:old_upload"
            fake_cache.set(redis_key, {"upload_id": "old_upload"})
            
            # Run cleanup through interface
            result = interface.cleanup_all()
            
            assert result["files_deleted"] == 1
            assert result["keys_deleted"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests for JobRequestCleanupAttachments
# ─────────────────────────────────────────────────────────────────────────────


class TestJobRequestCleanupAttachments:
    """Test the job request for attachment cleanup."""

    def test_request_name(self):
        """Test that the request has the correct name."""
        from app.module.job.jobs.JobRequestCleanupAttachments import JobRequestCleanupAttachments

        assert JobRequestCleanupAttachments.name == "cleanup_attachments"

    def test_request_cron(self):
        """Test that the request has the correct cron expression."""
        from app.module.job.jobs.JobRequestCleanupAttachments import JobRequestCleanupAttachments

        assert JobRequestCleanupAttachments.cron == "0 * * * *"

    def test_request_payload(self):
        """Test that the request payload is empty."""
        from app.module.job.jobs.JobRequestCleanupAttachments import JobRequestCleanupAttachments

        req = JobRequestCleanupAttachments()
        payload = req.payload()
        
        assert payload == {}

    def test_request_execution_metadata(self):
        """Test the execution metadata for the request."""
        from app.module.job.jobs.JobRequestCleanupAttachments import JobRequestCleanupAttachments

        assert JobRequestCleanupAttachments.max_try == 1
        assert JobRequestCleanupAttachments.soft_timeout_seconds == 300
        assert JobRequestCleanupAttachments.max_concurrent == 1
        assert JobRequestCleanupAttachments.resume == False
        assert JobRequestCleanupAttachments.retry_for == ()


# ─────────────────────────────────────────────────────────────────────────────
# Tests for JobCleanupAttachments
# ─────────────────────────────────────────────────────────────────────────────


class TestJobCleanupAttachments:
    """Test the job implementation for attachment cleanup."""

    def test_job_has_correct_request_class(self):
        """Test that the job has the correct request class."""
        from app.module.job.jobs.JobCleanupAttachments import JobCleanupAttachments
        from app.module.job.jobs.JobRequestCleanupAttachments import JobRequestCleanupAttachments

        assert JobCleanupAttachments.request_class == JobRequestCleanupAttachments

    def test_job_process_runs_cleanup(self, fake_cache, temp_upload_dir):
        """Test that the job process method runs the cleanup."""
        from app.config.settings.ProcessSetting import process_config
        from app.module.job.jobs.JobCleanupAttachments import JobCleanupAttachments

        # Patch the cache service at the module where it's used
        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', str(temp_upload_dir)):
            with patch('app.module.job.jobs.JobCleanupAttachments.sogo_cache', return_value=fake_cache):
                # Create expired file
                old_file = temp_upload_dir / "old_upload"
                old_file.write_bytes(b"old content")
                old_time = time.time() - (25 * 3600)
                os.utime(old_file, (old_time, old_time))
                
                redis_key = "sogo:attachments:old_upload"
                fake_cache.set(redis_key, {"upload_id": "old_upload"})
                
                # Create and run the job
                job = JobCleanupAttachments()
                result = job.process({}, user_uid=None, job_id="test-job-id")
                
                # Verify cleanup happened
                assert result["files_deleted"] == 1
                assert result["keys_deleted"] == 1
                assert result["status"] == "ok"
                assert not old_file.exists()

    def test_job_handles_empty_directory(self, fake_cache, temp_upload_dir):
        """Test that the job handles an empty directory gracefully."""
        from app.config.settings.ProcessSetting import process_config
        from app.module.job.jobs.JobCleanupAttachments import JobCleanupAttachments

        with patch.object(process_config, 'SOGO_UPLOAD_TEMP_PATH', str(temp_upload_dir)):
            with patch('app.module.job.jobs.JobCleanupAttachments.sogo_cache', return_value=fake_cache):
                job = JobCleanupAttachments()
                result = job.process({}, user_uid=None, job_id="test-job-id")
                
                assert result["files_deleted"] == 0
                assert result["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAttachmentCleanupIntegration:
    """Integration tests for the attachment cleanup feature."""

    def test_job_is_registered(self):
        """Test that the cleanup job is registered with the agent."""
        # Import the job module to trigger registration
        from app.module.job.jobs import JobCleanupAttachments  # noqa: F401
        from app.agent.jobs.Job import collected_agent_class_jobs
        
        job_classes = collected_agent_class_jobs()
        class_names = [cls.__name__ for cls in job_classes]
        
        assert "JobCleanupAttachments" in class_names

    def test_job_discovery(self):
        """Test that the job module is discovered and imported."""
        from app.module.job.jobs import JobCleanupAttachments
        from app.module.job.jobs import JobRequestCleanupAttachments
        
        # These should be importable
        assert JobCleanupAttachments is not None
        assert JobRequestCleanupAttachments is not None

    def test_interface_available(self):
        """Test that the interface is available and functional."""
        from app.interface.job.InterfaceJobCleanup import InterfaceJobCleanup
        
        # Should be importable
        assert InterfaceJobCleanup is not None

    def test_module_available(self):
        """Test that the module is available."""
        from app.module.job.ModuleJobCleanup import ModuleJobCleanup
        
        # Should be importable
        assert ModuleJobCleanup is not None
