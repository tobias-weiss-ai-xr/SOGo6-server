from json import dumps as json_dumps, loads as json_loads
from json.decoder import JSONDecodeError
from typing import cast, Type

from redis import Redis, exceptions as rexc
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from yarl import URL

from app.utils.exceptions import AggravatedException, BugException
from app.utils import errors as err
from app.utils import constants as cs
from app.utils.logger.logger import logger_cache

from functools import wraps
from time import perf_counter


class _ReconnectOnError:
    """
    Decorator that transparently reconnects the Redis client when an operation
    fails because of a stale/closed pooled connection.

    redis-py only retries ``redis.exceptions.ConnectionError`` and
    ``TimeoutError``, but a dead socket can surface as raw ``ValueError``
    ("I/O operation on closed file") or ``OSError`` ("Bad file descriptor",
    ConnectionResetError). When that happens we close the client, re-establish
    the connection and retry the operation exactly once.
    """

    _RETRYABLE = (rexc.ConnectionError, rexc.TimeoutError, rexc.ConnectionError, OSError, ValueError)

    def __init__(self, fn):
        self.fn = fn
        wraps(fn)(self)

    def __call__(self, *args, **kwargs):
        try:
            return self.fn(*args, **kwargs)
        except self._RETRYABLE as exc:
            self_redis = args[0]
            logger_cache.warning(
                "Redis error in %s: %r — reconnecting and retrying once",
                self.fn.__name__, exc,
            )
            try:
                self_redis.close()
            except Exception:
                pass
            self_redis._connect()
            try:
                return self.fn(*args, **kwargs)
            except self._RETRYABLE as exc2:
                logger_cache.error(
                    "Redis still failing after reconnect in %s: %r",
                    self.fn.__name__, exc2,
                )
                raise exc2


def _timed_cache(operation: str):
    """Observe the cache-op duration histogram for *operation* (real measurement)."""

    def _decorator(fn):
        @wraps(fn)
        def _wrapper(self, *args, **kwargs):
            from app.utils.api.prometheus import CACHE_OPERATION_DURATION
            start = perf_counter()
            try:
                return fn(self, *args, **kwargs)
            finally:
                CACHE_OPERATION_DURATION.labels(operation=operation).observe(perf_counter() - start)
        return _wrapper

    return _decorator

# Mapping from hash field name to the sorted set that indexes that field.
# When sort_by matches one of these keys, the corresponding sorted set is
# used directly (redis-side sort + pagination via ZRANGE).
SORT_FIELD_TO_ZSET: dict[str, str] = {
    cs.SESSION_LAST_SEEN: cs.ZSET_USER_SESSIONS_ACTIVITY,
    cs.USER_UID:          cs.ZSET_USER_SESSIONS_UID,
    cs.USER_DOMAIN:       cs.ZSET_USER_SESSIONS_DOMAIN,
}

# redis_logger = logging.getLogger("redis")
# redis_logger.setLevel(logging.DEBUG)

class ClientRedis():
    """
    Client for redis, the cache system
    
    Features:
    - Timeout handling via Redis URL query parameters (socket_timeout, connect_timeout)
    - Automatic reconnection with exponential backoff (configurable retries)
    - Fallback handled at application level with try/except blocks
    - Connection pooling for efficiency
    """


    def __init__(self, url_str:str, resp3: bool = True, max_retries: int = 3):
        """
        Initialize the client.
        It's initiated with a url to avoid having a lof of parameters.
        That wats all parameters are in the query

        Features:
        - Automatic reconnection on connection errors (configurable via max_retries)
        - Fallback handled at application level with try/except blocks

        SOGo force the decode_responses=True.
        SOGo will use RESP3 that allow caching (needs REDIS 6.0)
        SOGo greatly encourages the use of username/password with that can only access one redis db
        Such db being only for this user/SOGo.

        SOGo use json to serialize data. The library pickle is not safe as it will execute code.

        :param redis_url: Url for redis
        :type redis_url: str
        :param resp3: Whether to use RESP3 protocol (enables server-side caching)
        :type resp3: bool
        :param max_retries: Maximum number of reconnection attempts before giving up
        :type max_retries: int
        """
        super().__init__()
        
        self.url_str = url_str
        self.resp3 = resp3
        self.max_retries = max_retries
        self._connection_attempts = 0

        # Establish the Redis connection eagerly so that ping()/set()/get()
        # work right after construction (regression fix: _connect() was
        # extracted but never called from __init__).
        self._connect()

        
    def _connect(self) -> None:
        """
        Establish connection to Redis server.
        Configures automatic retry on connection errors.
        :raises AggravatedException: If connection cannot be established after max_retries
        """
        redis_url = URL(self.url_str)
        redis_url = redis_url.update_query(decode_responses="Yes")
        self.cache = False
        
        # Configure retry: retry on connection errors with exponential backoff
        # base=0.5s, cap=2s → delays 0.5s, 1s, 2s between attempts
        retry = Retry(
            backoff=ExponentialBackoff(base=0.5, cap=2.0),
            retries=3  # Max 3 retry attempts
        )
        
        if self.resp3:
            redis_url = redis_url.update_query(protocol=3)
            redis_connstring = str(redis_url)
            logger_cache.info("Setting Redis client with retry for %s", redis_connstring)
            # NOTE: redis-py's client-side caching (CacheConfig) is intentionally
            # NOT enabled. With it on, the client serves STALE ZRANGE/ZSET reads
            # from its local cache after writes on the same connection (verified:
            # zadd is not invalidating a previously cached zrange). That silently
            # corrupts every zset flow in this app — session activity indices and
            # the audit-log hash chain (audit() reads the newest member before
            # linking the next entry). Correctness over latency: all reads hit the
            # server. The resp3 (protocol 3) toggle remains for the wire protocol.
            self.redis = Redis.from_url(
                redis_connstring,
                retry=retry,
                retry_on_error=[rexc.ConnectionError, rexc.TimeoutError],
                # Drop pooled connections idle for more than 30s instead of
                # handing out a stale socket (avoids intermittent
                # "I/O operation on closed file" / "Bad file descriptor").
                health_check_interval=30,
            )
        else:
            redis_connstring = str(redis_url)
            logger_cache.info("Setting Redis client with retry for %s", redis_connstring)
            self.redis = Redis.from_url(
                redis_connstring,
                retry=retry,
                retry_on_error=[rexc.ConnectionError, rexc.TimeoutError],
                health_check_interval=30,
            )

    @_timed_cache("ping")
    @_ReconnectOnError
    def ping(self) -> None:
        """
        Ping to check the availability of the redis server
        """
        try:
            self.redis.ping()
        except rexc.AuthenticationError as e:
            logger_cache.error("Redis server authentication failed %s", repr(e))
            raise AggravatedException("Redis server authentication failed", err.ERROR_CACHE_AUTH_FAILED) from e
        except rexc.ConnectionError as e:
            logger_cache.error("Redis server is unavailable %s", repr(e))
            raise AggravatedException("Redis server is unavailable", err.ERROR_CACHE_NOT_REACHABLE) from e



    @_timed_cache("set")
    @_ReconnectOnError
    def set(self, key: str, value: str|list|dict, ttl: int, nx: bool = False) -> bool:
        """
        Set a key/value in the redis server.

        :param key: key of the value
        :type key: str
        :param value: value to store, if not a string, will be serialize as a json before
        :type value: str | list | dict
        :param ttl: time to live of this key/value, in seconds
        :type ttl: int
        :param nx: when True, only set if the key does not already exist (SET NX). Returns False if the key was already held.
        :type nx: bool
        :raises BugException: Value given is not a string nor json serializable
        :return: True if the value has been successfully stored, False if nx=True and key already exists
        :rtype: bool
        """
        if not isinstance(value, str):
            try:
                value = json_dumps(value)
            except TypeError as e:
                logger_cache.error("Data to store in cache not jsonable: %s", e)
                raise BugException("Data to store in cache not jsonable", err.ERROR_CACHE_DATA_NOT_JSON) from e

        if ttl < 1:
            #redis.set() raise redis.exceptions.ResponseError if time is 0 or less
            logger_cache.error("TTL for redis is below 1")
            raise BugException("TTL for redis is below 1", err.ERROR_CACHE_TTL_BELOW_0)

        try:
            result = self.redis.set(name=key, value=value, ex=ttl, nx=nx)
        except rexc.ResponseError as e:
            logger_cache.error("Error when setting data in redis: %s", e)
            raise BugException("Error when setting data in redis", err.ERROR_CACHE_RESPONSE_ERROR) from e

        if nx and result is None:
            logger_cache.info("Key '%s' already exists (nx=True), not set", key)
            return False

        # Don't log full cache value at INFO level - could contain sensitive data
        logger_cache.debug("Set cached value for key '%s' (value length: %d)", key, len(value))
        return True

    @_timed_cache("get")
    @_ReconnectOnError
    def get(self, key: str, expected_type: Type[str]|Type[list]|Type[dict]) -> str|list|dict|None:
        """
        Get the value stored in redis. The type of value expected must be given to be sure
        to return the correct data.

        :param key: key name of the value
        :type key: str
        :param expected_type: type of value expected
        :type expected_type: Type[str] | Type[list] | Type[dict]
        :raises BugException: If expecting a list or dict but the value is not a json
        :return: The value or None if the key does not exist.
        :rtype: str|list|dict|None
        """

        result_str = cast(str|None, self.redis.get(key))
        if result_str is not None:
            # Don't log full cache value at INFO level - could contain sensitive data
            logger_cache.debug("Get cached value for key '%s' (value length: %d)", key, len(result_str))
            #If we expect a string directly return it
            if expected_type == str:
                return result_str

            #If we expect a list or dict, the result_str is a json
            try:
                result: list|dict = json_loads(result_str)
            except (TypeError, JSONDecodeError) as e:
                raise BugException("list/dict stored in redis is not a Json", err.ERROR_CACHE_DATA_NOT_JSON) from e
            return result
        logger_cache.info("Get no value for key '%s'", key)
        return None

    @_timed_cache("hashset")
    @_ReconnectOnError
    def hashset(self, key:str, data: dict, ttl: int) -> bool:
        """
        Create or update a hash in redis.
        A hash contains a dict where value can be updated without
        giving the whole dict, only the key/value needed.
        
        (e.g. update the key last_connection for user session).

        If your dict data won't be modified, prefered set() method

        If ttl is 0 or less, the expiration will not be set or updated.

        :param key: _description_
        :type key: str
        :param data: _description_
        :type data: dict
        :param ttl: _description_
        :type ttl: int
        """
        logger_cache.info("Hashset cached for key '%s'", key)
        self.redis.hset(key, mapping=data)
        if ttl > 0:
            self.redis.expire(key, ttl)
        # Don't log full hash data at INFO level - could contain sensitive data
        logger_cache.debug("Hashset cached for key '%s' (data length: %d)", key, len(data))
        return True

    @_timed_cache("hashget")
    @_ReconnectOnError
    def hashget(self, key:str) -> dict|None:
        """
        Return the whole dict of a hash

        :param key: _description_
        :type key: str
        :return: _description_
        :rtype: dict|None
        """
        logger_cache.info("Hashget cached for key '%s'", key)
        ret = cast(dict|None, self.redis.hgetall(key))
        if ret:
            # Don't log full hash data at INFO level - could contain sensitive data
            logger_cache.debug("Hashget cached value for key '%s' (data length: %d)", key, len(ret))
        else:
            logger_cache.debug("Hashget no cached value for key '%s'", key)
        return ret


    # -- Sorted-set helpers --------------------------------------------------

    @_timed_cache("zset_add")
    @_ReconnectOnError
    def zset_add(self, zset_key: str, member: str, score: float) -> None:
        """
        Add (or update) a member in a sorted set with the given score.

        :param zset_key: name of the sorted set
        :param member: member value (e.g. "user_session:<uuid>")
        :param score: score used for ordering (e.g. a Unix timestamp)
        """
        self.redis.zadd(zset_key, {member: score})
        logger_cache.debug("zadd %s -> member=%s score=%s", zset_key, member, score)

    @_timed_cache("zset_remove")
    @_ReconnectOnError
    def zset_remove(self, zset_key: str, *members: str) -> int:
        """
        Remove one or more members from a sorted set.

        :return: number of members actually removed
        """
        removed = cast(int, self.redis.zrem(zset_key, *members))
        logger_cache.debug("zrem %s -> members=%s removed=%d", zset_key, members, removed)
        return removed

    @_timed_cache("zset_count")
    @_ReconnectOnError
    def zset_count(self, zset_key: str) -> int:
        """
        Return the total number of members in a sorted set
        """
        return cast(int, self.redis.zcard(zset_key))

    @_timed_cache("zset_revrange")
    @_ReconnectOnError
    def zset_revrange(self, zset_key: str, start: int, stop: int) -> list[str]:
        """
        Return members of a sorted set by descending score, between ranks start and stop.

        Members are normalised to ``str`` (the underlying client may return bytes).

        :param zset_key: name of the sorted set
        :param start: first rank to return (0-based, inclusive)
        :param stop: last rank to return (inclusive; -1 for the end)
        :return: members ordered by descending score
        """
        raw = cast(list, self.redis.zrevrange(zset_key, start, stop))
        return [m.decode("utf-8") if isinstance(m, bytes) else str(m) for m in raw]

    def zset_paginate_hashes(
        self,
        first: int = 0,
        last: int = 0,
        sort_by: str | None = None,
        sort_order: str | None = None
    ) -> tuple[int, list[dict]]:
        """
        Paginate through hash keys referenced in a sorted set.

        When *sort_by* matches a field that has a dedicated sorted-set
        index (see :pyattr:`SORT_FIELD_TO_ZSET`), that index is used
        instead — still fully redis-side, no Python sort needed.

        Only when *sort_by* has **no** matching sorted-set index does
        the method fall back to fetching all hashes and sorting in memory.

        :param first: offset of the first item to return
        :param last: index of the last item (inclusive).
        :param sort_by: hash field to sort on.  None means use the
            sorted-set score (fast path).  Any other value triggers the
            in-memory fallback only if no dedicated index exists.
        :param sort_order: "asc" or "desc" (default "desc")
        :param include_fields: comma-separated list of hash fields to keep
            in each returned dict (None = return all fields)
        :return: (total_count, page_items)
        """
        logger_cache.info("zset_paginate_hashes first=%s last=%s sort_by=%s sort_order=%s", first, last, sort_by, sort_order)
        # set default zset key
        zset_key_default = cs.ZSET_USER_SESSIONS_ACTIVITY
        total_count = cast(int, self.redis.zcard(zset_key_default))

        if total_count == 0:
            return 0, []
        if sort_order is None:
            sort_order = "desc"

        reverse = sort_order == "desc"

        # Resolve which sorted set to query for ordering.
        # If sort_by matches a dedicated index, use it (redis-side fast path).
        resolved_zset: str | None = None
        if sort_by is not None:
            resolved_zset = SORT_FIELD_TO_ZSET.get(sort_by)

        # ----- Fast path: sort by sorted-set score (redis-side) -----
        if sort_by is None or resolved_zset is not None:
            effective_zset = resolved_zset if resolved_zset is not None else zset_key_default

            if last:
                count = last - first + 1
            else:
                count = total_count

            sorted_keys: list[str] = cast(
                list[str],
                self.redis.zrange(
                    effective_zset,
                    start=first,
                    end=first + count - 1,
                    desc=reverse,
                ),
            )
            if not sorted_keys:
                return total_count, []
            items = self._pipeline_hgetall(sorted_keys)

        else:
            # ----- Slow path: no dedicated index, in-memory fallback -----
            # This path is used when no sorted-set index exists for the query field.
            # For large datasets, ensure you create indexes via zset_add_index().
            # Retrieve ALL member keys from the sorted set
            all_keys: list[str] = cast(
                list[str],
                self.redis.zrange(zset_key_default, start=0, end=-1),
            )

            if not all_keys:
                return total_count, []

            # Retrieve ALL corresponding hashes in a single pipeline round-trip
            items = self._pipeline_hgetall(all_keys)

            # Sort in memory on the requested field
            items.sort(key=lambda d: d.get(sort_by, ""), reverse=reverse)

            # Paginate
            if last:
                items = items[first:last + 1]

        logger_cache.info(
            "zset_paginate_hashes: total=%d page_size=%d", total_count, len(items),
        )
        return total_count, items

    def _pipeline_hgetall(self, keys: list[str]) -> list[dict]:
        """
        Fetch multiple hashes in a single Redis round-trip.

        Keys whose hash no longer exists (e.g. expired) are silently
        skipped **and their orphaned entries are removed from the
        sorted-set indexes** (lazy cleanup).  The Redis key itself is
        injected into each returned dict under the
        :pyattr:`cs.SESSION_KEY` field.

        :param keys: list of Redis hash keys
        :return: list of non-empty hash dicts
        """
        pipe = self.redis.pipeline(transaction=False)
        for key in keys:
            pipe.hgetall(key)
        raw_results = pipe.execute()

        items: list[dict] = []
        orphaned_keys: list[str] = []
        data: dict
        for key, data in zip(keys, raw_results):
            if data:
                data.pop(cs.SESSION_SENSITIVE)
                data[cs.SESSION_KEY] = key
                items.append(data)
            else:
                orphaned_keys.append(key)

        # Lazy cleanup: remove sorted-set entries whose hash has expired
        if orphaned_keys:
            cleanup_pipe = self.redis.pipeline(transaction=False)
            for key in orphaned_keys:
                cleanup_pipe.zrem(cs.ZSET_USER_SESSIONS_ACTIVITY, key)
                cleanup_pipe.zrem(cs.ZSET_USER_SESSIONS_UID, key)
                cleanup_pipe.zrem(cs.ZSET_USER_SESSIONS_DOMAIN, key)
            cleanup_pipe.execute()
            logger_cache.info(
                "_pipeline_hgetall: cleaned up %d orphaned sorted-set entries",
                len(orphaned_keys),
            )
        return items

    @_timed_cache("delete")
    @_ReconnectOnError
    def delete(self, *keys: str) -> int:
        """
        Delete all the key given

        :return: the number of deletion made
        :rtype: int
        """

        ret = cast(int, self.redis.delete(*keys))
        logger_cache.info("Delete cached value for keys '%s'", keys)

        return ret


    def revoke_user_sessions_by_uid(self, uids: list[str]) -> int:
        """
        Revoke all cache sessions that belong to the given UIDs.
        Not using delete because we need to remove the session keys from the sorted-set indexes as well.

        For each member of every session sorted-set, the corresponding hash is
        inspected.  When its uid field matches one of the requested UIDs the
        hash key is collected.  Then all matching hash keys are deleted and removed
        from every sorted-set index in a single pipeline round-trip.

        :param uids: list of user UIDs whose sessions must be revoked
        :type uids: list[str]
        :return: number of session hashes deleted
        :rtype: int
        """
        uid_set = set(uids)

        # Retrieve all session keys from the activity sorted-set (canonical index)
        all_keys: list[str] = cast(
            list[str],
            self.redis.zrange(cs.ZSET_USER_SESSIONS_ACTIVITY, start=0, end=-1),
        )

        if not all_keys:
            logger_cache.info("revoke_user_sessions_by_uid: no active sessions found")
            return 0

        # Fetch all hashes in one pipeline round-trip
        pipe = self.redis.pipeline(transaction=False)
        for key in all_keys:
            pipe.hget(key, cs.USER_UID)
        uid_values: list[str | None] = pipe.execute()

        # Collect keys whose uid matches the requested set
        keys_to_revoke: list[str] = [
            key
            for key, uid_val in zip(all_keys, uid_values)
            if uid_val in uid_set
        ]

        if not keys_to_revoke:
            logger_cache.info("revoke_user_sessions_by_uid: no sessions found for uids %s", uids)
            return 0

        # Delete hash keys and remove from all sorted-set indexes in one pipeline
        pipe = self.redis.pipeline(transaction=False)
        for key in keys_to_revoke:
            pipe.delete(key)
            pipe.zrem(cs.ZSET_USER_SESSIONS_ACTIVITY, key)
            pipe.zrem(cs.ZSET_USER_SESSIONS_UID, key)
            pipe.zrem(cs.ZSET_USER_SESSIONS_DOMAIN, key)
        pipe.execute()

        logger_cache.info(
            "revoke_user_sessions_by_uid: revoked %d session(s) for uids %s",
            len(keys_to_revoke), uids,
        )
        return len(keys_to_revoke)

    def revoke_user_sessions_by_key(self, redis_keys: list[str]) -> int:
        """
        Revoke cache sessions identified by their Redis keys directly.

        Each key is deleted along with its entry in every sorted-set index
        in a single pipeline round-trip.

        :param redis_keys: list of Redis hash keys to revoke (e.g. ``user_session:<uuid>``)
        :type redis_keys: list[str]
        :return: number of session hashes deleted
        :rtype: int
        """
        if not redis_keys:
            logger_cache.info("revoke_user_sessions_by_key: no keys provided")
            return 0

        # Delete hash keys and remove from all sorted-set indexes in one pipeline
        # Each key produces 4 commands: delete, zrem×3
        pipe = self.redis.pipeline(transaction=False)
        for key in redis_keys:
            pipe.delete(key)
            pipe.zrem(cs.ZSET_USER_SESSIONS_ACTIVITY, key)
            pipe.zrem(cs.ZSET_USER_SESSIONS_UID, key)
            pipe.zrem(cs.ZSET_USER_SESSIONS_DOMAIN, key)
        results = pipe.execute()

        # Count actually deleted keys by inspecting the delete result
        # (every 4th result starting at index 0)
        revoked_count = sum(
            1 for i in range(0, len(results), 4) if results[i]
        )

        logger_cache.info(
            "revoke_user_sessions_by_key: revoked %d session(s) for keys %s",
            revoked_count, redis_keys,
        )
        return revoked_count

    def revoke_user_sessions_by_activity(self, timestamp: int) -> int:
        """
        Revoke all cache sessions whose last activity score is older than
        (i.e. less than or equal to) the given Unix timestamp.

        Uses ``ZRANGEBYSCORE`` on the activity sorted set to find members
        with a score between ``-inf`` and *timestamp* (inclusive).
        Then deletes the corresponding hash keys and removes the members
        from every sorted-set index in a single pipeline round-trip.

        :param timestamp: Unix timestamp.  Sessions with a
            last-activity score ≤ this value are considered inactive.
        :type timestamp: int
        :return: number of session hashes deleted
        :rtype: int
        """
        # Find all session keys whose activity score <= timestamp
        keys_to_revoke: list[str] = cast(
            list[str],
            self.redis.zrangebyscore(
                cs.ZSET_USER_SESSIONS_ACTIVITY,
                min="-inf",
                max=timestamp,
            ),
        )

        if not keys_to_revoke:
            logger_cache.info(
                "revoke_user_sessions_by_activity: no sessions older than %d",
                timestamp,
            )
            return 0

        # Delete hash keys and remove from all sorted-set indexes in one pipeline.
        # zremrangebyscore handles the activity set in bulk; the UID and domain
        # sets are cleaned up per-key since they share the same member names.
        pipe = self.redis.pipeline(transaction=False)
        for key in keys_to_revoke:
            pipe.delete(key)
            pipe.zrem(cs.ZSET_USER_SESSIONS_UID, key)
            pipe.zrem(cs.ZSET_USER_SESSIONS_DOMAIN, key)
        pipe.zremrangebyscore(cs.ZSET_USER_SESSIONS_ACTIVITY, "-inf", timestamp)
        results = pipe.execute()

        # Count actually deleted keys by inspecting the delete result
        # (every 3rd result starting at index 0, one delete + two zrem per key)
        revoked_count = sum(
            1 for i in range(0, len(results) - 1, 3) if results[i]
        )

        logger_cache.info(
            "revoke_user_sessions_by_activity: revoked %d session(s) older than %d",
            revoked_count, timestamp,
        )
        return revoked_count

    @_timed_cache("incr")
    @_ReconnectOnError
    def incr(self, key: str) -> int:
        """
        Atomically increment the integer stored at *key* (creating it as 0 first).

        Provides the monotonic sequence numbers used by the tamper-evident
        audit log.

        :param key: name of the counter key
        :type key: str
        :return: the new value
        :rtype: int
        """
        return cast(int, self.redis.incr(key))

    @_timed_cache("zset_trim")
    def zset_trim(self, zset_key: str, keep: int) -> int:
        """
        Trim a sorted set to its *keep* highest-scoring members.

        Removes the lowest-ranked members (i.e. the oldest for a
        timestamp/sequence ordering). Returns the number of removed members.

        :param zset_key: name of the sorted set
        :param keep: number of members to keep (highest scores)
        :return: number of members removed
        """
        if keep <= 0:
            raise ValueError("keep must be > 0")
        total = self.zset_count(zset_key)
        if total <= keep:
            return 0
        removed = cast(int, self.redis.zremrangebyrank(zset_key, 0, total - keep - 1))
        logger_cache.info("zset_trim %s -> kept=%d removed=%d", zset_key, keep, removed)
        return removed


    def close(self) -> None:
        """
        _summary_
        """
        self.redis.close()
