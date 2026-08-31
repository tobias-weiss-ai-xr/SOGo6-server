"""Service interface for attachment cleanup operations.

This interface provides a clean abstraction for triggering and managing
attachment cleanup jobs. It delegates the actual cleanup logic to the
ModuleJobCleanup domain class.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.auth.User import User
    from app.manager.cache.ClientRedis import ClientRedis


class InterfaceJobCleanup:
    """Interface for attachment cleanup operations.
    
    This is a thin facade that provides a consistent interface for cleanup
    operations, suitable for use by both API endpoints and scheduled jobs.
    """

    def __init__(self, cache_client: ClientRedis) -> None:
        """Initialize the cleanup interface.
        
        :param cache_client: Redis client for accessing attachment metadata.
        :type cache_client: ClientRedis
        """
        from app.module.job.ModuleJobCleanup import ModuleJobCleanup
        
        self.cleanup_module = ModuleJobCleanup(cache_client)

    def cleanup_expired_attachments(self) -> dict[str, Any]:
        """Clean up expired temporary attachment files.
        
        :return: Dictionary with cleanup statistics.
        :rtype: dict[str, Any]
        """
        return self.cleanup_module.cleanup_expired_attachments()

    def cleanup_orphaned_redis_keys(self) -> dict[str, Any]:
        """Clean up orphaned Redis keys for missing attachment files.
        
        :return: Dictionary with cleanup statistics.
        :rtype: dict[str, Any]
        """
        return self.cleanup_module.cleanup_orphaned_redis_keys()

    def cleanup_all(self) -> dict[str, Any]:
        """Run both cleanup operations: expired files and orphaned keys.
        
        :return: Combined statistics from both cleanup operations.
        :rtype: dict[str, Any]
        """
        return self.cleanup_module.cleanup_all()
