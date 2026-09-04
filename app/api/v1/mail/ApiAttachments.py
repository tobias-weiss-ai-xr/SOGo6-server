"""
API endpoints for attachment upload and management.

Provides endpoints for:
- POST /api/v1/attachments/upload - Upload a file to temporary storage
- DELETE /api/v1/attachments/<upload_id> - Delete a temporary attachment
- GET /api/v1/attachments/<upload_id> - Get metadata for a temporary attachment
"""

from typing import TYPE_CHECKING

import os
import uuid
from datetime import datetime, timezone

from flask import g, request
from flask.views import MethodView
from flask.typing import ResponseReturnValue
from flask_smorest import Blueprint

from app.utils.logger.logger import logger_api
from app.utils.exceptions import RequestException
from app.utils import errors as err
from app.utils.media.MediaType import MediaType
from app.utils.api.ApiBaseResponse import create_api_base_response

if TYPE_CHECKING:
    from werkzeug.datastructures import FileStorage

# Create the blueprint for attachment endpoints
blp = Blueprint("Attachments", __name__, url_prefix="/attachments")

# Redis key prefix for attachment metadata
ATTACHMENT_REDIS_PREFIX: str = "sogo:attachments:"


def _get_redis_client():
    """Lazy import of redis client to avoid circular dependencies."""
    from app.service import sogo_cache
    return sogo_cache()


def _get_config():
    """Lazy import of config to avoid circular dependencies."""
    from app.config.settings.ProcessSetting import process_config
    return process_config


@blp.route("/upload")
class ApiAttachmentsUpload(MethodView):
    """
    Action: Upload an attachment file to temporary storage.
    """
    accepted_content_types = {"multipart/form-data"}

    def post(self) -> ResponseReturnValue:
        """
        Upload a file to temporary storage.
        """
        logger_api.debug("Calling ApiAttachmentsUpload.post")

        # Get the file from the request
        if 'file' not in request.files:
            raise RequestException(err.ERROR_TMP_DRAFT_UPLOAD_NO_FILE.m, error=err.ERROR_TMP_DRAFT_UPLOAD_NO_FILE)
        
        file_storage = request.files['file']
        
        if file_storage is None or file_storage.filename == '':
            raise RequestException(err.ERROR_TMP_DRAFT_UPLOAD_NO_FILE.m, error=err.ERROR_TMP_DRAFT_UPLOAD_NO_FILE)

        # Get current user
        user = g.user

        # Read file data
        filename: str = file_storage.filename or "attachment"
        declared_content_type: str = file_storage.content_type or "application/octet-stream"
        file_data: bytes = file_storage.read()

        # Validate file size
        config = _get_config()
        max_size: int = config.SOGO_MAX_ATTACHMENT_SIZE
        if len(file_data) > max_size:
            logger_api.warning(
                "Attachment upload rejected for user %s: file size %d exceeds max %d",
                user.uid, len(file_data), max_size,
            )
            result, status_code = create_api_base_response(None, err.ERROR_FILE_TOO_LARGE)
            return result, status_code

        # Detect actual MIME type from file content
        detected_mime: str | None = MediaType.get_content_type(file_data)
        
        # If detection fails, use the provided content_type
        if detected_mime is None:
            detected_mime = declared_content_type
            logger_api.debug(
                "Could not detect MIME type from content for user %s, using declared type: %s",
                user.uid, declared_content_type,
            )

        # Validate MIME type against allowed list
        allowed_types: list[str] = config.SOGO_ALLOWED_ATTACHMENT_TYPES
        if detected_mime not in allowed_types:
            logger_api.warning(
                "Attachment upload rejected for user %s: MIME type %s not in allowed list",
                user.uid, detected_mime,
            )
            result, status_code = create_api_base_response(None, err.ERROR_FILE_TYPE_NOT_ALLOWED)
            return result, status_code

        # Generate unique upload ID
        upload_id: str = str(uuid.uuid4())

        # Ensure upload temp directory exists
        temp_path: str = config.SOGO_UPLOAD_TEMP_PATH
        upload_dir: str = os.path.dirname(temp_path) if temp_path.endswith('/') else temp_path
        
        if not os.path.exists(upload_dir):
            try:
                os.makedirs(upload_dir, exist_ok=True)
            except OSError as e:
                logger_api.error(
                    "Failed to create upload temp directory %s for user %s: %s",
                    upload_dir, user.uid, str(e),
                )
                result, status_code = create_api_base_response(
                    None, err.ERROR_TMP_DRAFT_ATTACHMENT_FAILED, error_msg=str(e)
                )
                return result, status_code

        # Construct full file path
        file_path: str = os.path.join(upload_dir, upload_id)

        # Write file to disk
        try:
            with open(file_path, 'wb') as f:
                f.write(file_data)
            logger_api.debug(
                "Attachment uploaded for user %s: %s (%d bytes, type=%s) -> %s",
                user.uid, filename, len(file_data), detected_mime, upload_id,
            )
        except OSError as e:
            logger_api.error(
                "Failed to write attachment file %s for user %s: %s",
                file_path, user.uid, str(e),
            )
            result, status_code = create_api_base_response(
                None, err.ERROR_TMP_DRAFT_ATTACHMENT_FAILED, error_msg=str(e)
            )
            return result, status_code

        # Store metadata in Redis with 24-hour TTL (86400 seconds)
        uploaded_at: str = datetime.now(timezone.utc).isoformat()
        metadata: dict = {
            "upload_id": upload_id,
            "filename": filename,
            "size": len(file_data),
            "mime_type": detected_mime,
            "path": file_path,
            "uploaded_at": uploaded_at,
            "user_uid": user.uid,
        }

        try:
            cache = _get_redis_client()
            redis_key: str = f"{ATTACHMENT_REDIS_PREFIX}{upload_id}"
            cache.set(redis_key, metadata, ttl=86400)
            logger_api.debug(
                "Attachment metadata stored in Redis for user %s: %s",
                user.uid, upload_id,
            )
        except Exception as e:
            # Clean up the file if Redis fails
            try:
                os.remove(file_path)
            except OSError:
                pass
            logger_api.error(
                "Failed to store attachment metadata in Redis for user %s: %s",
                user.uid, str(e),
            )
            result, status_code = create_api_base_response(
                None, err.ERROR_TMP_DRAFT_ATTACHMENT_FAILED, error_msg=str(e)
            )
            return result, status_code

        response_data = {
            "upload_id": upload_id,
            "filename": filename,
            "size": len(file_data),
            "mime_type": detected_mime,
            "uploaded_at": uploaded_at,
        }

        return create_api_base_response(response_data)


@blp.route("/<string:upload_id>")
class ApiAttachmentsDetail(MethodView):
    """
    Action: Get metadata or delete a temporary attachment.
    """

    def get(self, upload_id: str) -> ResponseReturnValue:
        """
        Get metadata for a temporary attachment.
        """
        logger_api.debug("Calling ApiAttachmentsDetail.get for upload_id: %s", upload_id)
        
        user = g.user
        
        try:
            cache = _get_redis_client()
            redis_key: str = f"{ATTACHMENT_REDIS_PREFIX}{upload_id}"
            metadata: dict | None = cache.get(redis_key, dict)
            
            if metadata is None:
                logger_api.debug("Attachment %s not found for user %s", upload_id, user.uid)
                result, status_code = create_api_base_response(None, err.ERROR_TMP_DRAFT_ATTACHMENT_NOT_FOUND)
                return result, status_code

            # Verify ownership
            if metadata.get("user_uid") != user.uid:
                logger_api.warning(
                    "User %s attempted to access attachment %s owned by %s",
                    user.uid, upload_id, metadata.get("user_uid"),
                )
                result, status_code = create_api_base_response(None, err.ERROR_TMP_DRAFT_ATTACHMENT_NOT_FOUND)
                return result, status_code

            return create_api_base_response(metadata)

        except Exception as e:
            logger_api.error(
                "Failed to retrieve attachment metadata %s for user %s: %s",
                upload_id, user.uid, str(e),
            )
            return create_api_base_response(None, err.ERROR_MAIL_ATTACHMENT_NOT_FOUND, error_msg=str(e))

    def delete(self, upload_id: str) -> ResponseReturnValue:
        """
        Delete a temporary attachment.
        """
        logger_api.debug("Calling ApiAttachmentsDetail.delete for upload_id: %s", upload_id)
        
        user = g.user
        
        try:
            cache = _get_redis_client()
            redis_key: str = f"{ATTACHMENT_REDIS_PREFIX}{upload_id}"
            metadata: dict | None = cache.get(redis_key, dict)
            
            if metadata is None:
                logger_api.warning("Attempt to delete non-existent attachment %s by user %s", upload_id, user.uid)
                result, status_code = create_api_base_response(None, err.ERROR_TMP_DRAFT_ATTACHMENT_NOT_FOUND)
                return result, status_code

            # Verify ownership
            if metadata.get("user_uid") != user.uid:
                logger_api.warning(
                    "User %s attempted to delete attachment %s owned by %s",
                    user.uid, upload_id, metadata.get("user_uid"),
                )
                result, status_code = create_api_base_response(None, err.ERROR_TMP_DRAFT_ATTACHMENT_NOT_FOUND)
                return result, status_code

            file_path: str = metadata.get("path", "")
            
            # Delete the file
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger_api.debug("Attachment file deleted for user %s: %s", user.uid, file_path)
                except OSError as e:
                    logger_api.error("Failed to delete attachment file %s for user %s: %s", file_path, user.uid, str(e))
                    result, status_code = create_api_base_response(
                        None, err.ERROR_TMP_DRAFT_DELETE_ATTACHMENT_FAILED, error_msg=str(e)
                    )
                    return result, status_code

            # Delete Redis metadata
            cache.delete(redis_key)
            logger_api.debug("Attachment metadata deleted from Redis for user %s: %s", user.uid, upload_id)

            return create_api_base_response(None)

        except Exception as e:
            logger_api.error("Failed to delete attachment %s for user %s: %s", upload_id, user.uid, str(e))
            return create_api_base_response(
                None, err.ERROR_TMP_DRAFT_DELETE_ATTACHMENT_FAILED, error_msg=str(e)
            )
