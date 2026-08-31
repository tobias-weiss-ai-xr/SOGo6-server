"""Domain logic for attachment cleanup jobs.

This module provides the core business logic for cleaning up expired temporary
attachment files and their associated Redis metadata.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.config.settings.ProcessSetting import process_config
from app.utils.logger.logger import logger_agent

if TYPE_CHECKING:
    from app.manager.cache.ClientRedis import ClientRedis


class ModuleJobCleanup:
    """Cleans up expired temporary attachment files and orphaned Redis metadata.
    
    The cleanup job performs two main operations:
    1. Deletes temporary attachment files older than 24 hours
    2. Removes orphaned Redis keys for attachments that no longer exist on disk
    
    This is a system-level job (user_uid=None) that runs periodically via Celery Beat.
    """

    # Redis key prefix for attachment metadata
    ATTACHMENT_REDIS_PREFIX: str = "sogo:attachments:"
    
    # Maximum age for temp files in seconds (24 hours)
    MAX_AGE_SECONDS: int = 86400

    def __init__(self, cache_client: ClientRedis) -> None:
        """Initialize the cleanup module.
        
        :param cache_client: Redis client for accessing attachment metadata.
        :type cache_client: ClientRedis
        """
        self.cache_client = cache_client
        self.temp_path = process_config.SOGO_UPLOAD_TEMP_PATH
        self.upload_path = process_config.SOGO_UPLOAD_PATH

    def cleanup_expired_attachments(self) -> dict[str, Any]:
        """Clean up expired temporary attachment files and their Redis metadata.
        
        Scans the temporary upload directory for files older than MAX_AGE_SECONDS
        and removes both the files and their corresponding Redis keys.
        
        :return: Dictionary with cleanup statistics (files_deleted, keys_deleted, errors).
        :rtype: dict[str, Any]
        """
        files_deleted: int = 0
        keys_deleted: int = 0
        errors: list[str] = []
        
        now = time.time()
        max_age = self.MAX_AGE_SECONDS
        
        # Ensure temp directory exists
        if not os.path.exists(self.temp_path):
            logger_agent.info(
                "Attachment cleanup: temp directory %s does not exist, nothing to clean",
                self.temp_path,
            )
            return {
                "files_deleted": 0,
                "keys_deleted": 0,
                "errors": [],
                "status": "ok",
            }
        
        # Scan the temp directory for old files
        try:
            for filename in os.listdir(self.temp_path):
                filepath = os.path.join(self.temp_path, filename)
                
                # Skip directories
                if not os.path.isfile(filepath):
                    continue
                
                # Check file age
                try:
                    file_mtime = os.path.getmtime(filepath)
                    file_age = now - file_mtime
                    
                    if file_age >= max_age:
                        # File is expired, delete it
                        try:
                            os.remove(filepath)
                            files_deleted += 1
                            logger_agent.debug(
                                "Attachment cleanup: deleted expired file %s (age %.1fh)",
                                filepath, file_age / 3600,
                            )
                        except OSError as e:
                            errors.append(f"Failed to delete file {filepath}: {e}")
                            logger_agent.error(
                                "Attachment cleanup: failed to delete file %s: %s",
                                filepath, e,
                            )
                        
                        # Delete corresponding Redis key
                        redis_key = f"{self.ATTACHMENT_REDIS_PREFIX}{filename}"
                        try:
                            self.cache_client.delete(redis_key)
                            keys_deleted += 1
                            logger_agent.debug(
                                "Attachment cleanup: deleted Redis key %s",
                                redis_key,
                            )
                        except Exception as e:
                            errors.append(f"Failed to delete Redis key {redis_key}: {e}")
                            logger_agent.error(
                                "Attachment cleanup: failed to delete Redis key %s: %s",
                                redis_key, e,
                            )
                except OSError as e:
                    errors.append(f"Failed to get mtime for {filepath}: {e}")
                    logger_agent.warning(
                        "Attachment cleanup: could not get mtime for %s: %s",
                        filepath, e,
                    )
        except OSError as e:
            errors.append(f"Failed to list directory {self.temp_path}: {e}")
            logger_agent.error(
                "Attachment cleanup: failed to list directory %s: %s",
                self.temp_path, e,
            )
        
        logger_agent.info(
            "Attachment cleanup: deleted %d files, %d Redis keys, %d errors",
            files_deleted, keys_deleted, len(errors),
        )
        
        return {
            "files_deleted": files_deleted,
            "keys_deleted": keys_deleted,
            "errors": errors,
            "status": "ok" if not errors else "partial",
        }

    def cleanup_orphaned_redis_keys(self) -> dict[str, Any]:
        """Clean up Redis keys for attachments that no longer exist on disk.
        
        Uses the underlying Redis client to scan for keys with the attachment prefix
        and removes those whose corresponding files don't exist in the temp directory.
        
        Note: This uses Redis KEYS command which may block the server for large
        databases. However, since attachment keys have a 24-hour TTL and are expected
        to be relatively few, this should be safe for the cleanup job.
        
        :return: Dictionary with cleanup statistics (keys_deleted, errors).
        :rtype: dict[str, Any]
        """
        keys_deleted: int = 0
        errors: list[str] = []
        
        # Access the underlying redis-py client to use scan_iter
        # which is more efficient than KEYS for large datasets
        try:
            redis_client = self.cache_client.redis
            pattern = f"{self.ATTACHMENT_REDIS_PREFIX}*"
            
            # Use scan_iter for non-blocking iteration
            # This may not be available in all redis-py versions, fall back to keys
            try:
                all_keys = [key.decode('utf-8') if isinstance(key, bytes) else key
                           for key in redis_client.scan_iter(match=pattern)]
            except AttributeError:
                # Fall back to KEYS if scan_iter is not available
                # KEYS can block the server, but is acceptable for small datasets
                raw_keys = redis_client.keys(pattern)
                all_keys = [key.decode('utf-8') if isinstance(key, bytes) else key
                           for key in raw_keys]
            
            # Check each key for orphaned metadata
            for redis_key in all_keys:
                if not redis_key.startswith(self.ATTACHMENT_REDIS_PREFIX):
                    continue
                
                # Extract the upload_id from the key
                # Key format: sogo:attachments:<upload_id>
                key_parts = redis_key.split(":")
                if len(key_parts) < 3:
                    continue
                upload_id = key_parts[-1]
                
                # Check if the file exists
                filepath = os.path.join(self.temp_path, upload_id)
                if not os.path.exists(filepath):
                    # File doesn't exist, delete the Redis key
                    try:
                        self.cache_client.delete(redis_key)
                        keys_deleted += 1
                        logger_agent.debug(
                            "Attachment cleanup: deleted orphaned Redis key %s (file %s missing)",
                            redis_key, filepath,
                        )
                    except Exception as e:
                        errors.append(f"Failed to delete orphaned Redis key {redis_key}: {e}")
                        logger_agent.error(
                            "Attachment cleanup: failed to delete orphaned Redis key %s: %s",
                            redis_key, e,
                        )
            
            logger_agent.info(
                "Orphaned Redis keys cleanup: deleted %d keys, %d errors",
                keys_deleted, len(errors),
            )
        except Exception as e:
            # If Redis is not available or doesn't support scan, log but don't fail
            # The main cleanup (expired files) will still work
            errors.append(f"Failed to scan Redis keys: {e}")
            logger_agent.warning(
                "Attachment cleanup: failed to scan Redis keys for orphaned entries: %s",
                e,
            )
        
        return {
            "keys_deleted": keys_deleted,
            "errors": errors,
            "status": "ok" if not errors else "partial",
        }

    def cleanup_all(self) -> dict[str, Any]:
        """Run both cleanup operations: expired files and orphaned keys.
        
        :return: Combined statistics from both cleanup operations.
        :rtype: dict[str, Any]
        """
        result_expired = self.cleanup_expired_attachments()
        result_orphaned = self.cleanup_orphaned_redis_keys()
        
        all_errors = (
            result_expired.get("errors", []) + 
            result_orphaned.get("errors", [])
        )
        
        return {
            "files_deleted": result_expired.get("files_deleted", 0),
            "keys_deleted": (
                result_expired.get("keys_deleted", 0) +
                result_orphaned.get("keys_deleted", 0)
            ),
            "errors": all_errors,
            "status": "ok" if not all_errors else "partial",
        }
