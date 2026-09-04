# pylint: disable=invalid-sequence-index
"""Functional tests for the attachment upload/management endpoints.

Tests exercise ApiAttachmentsUpload and ApiAttachmentsDetail view classes
through a real Flask test client with the blueprint registered, mocking
only the lazy-loaded config and Redis client. This gives real code coverage
of the POST/GET/DELETE handlers (previously ~18%).
"""
from __future__ import annotations

import os
import io
import json

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Test client fixture: register Attachments blueprint on a Flask app
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_client(tmp_path):
    """Build a Flask test app with the Attachments blueprint registered."""
    from flask import Flask, g
    from app.api.v1.mail import ApiAttachments

    app = Flask(__name__)
    app.config["TESTING"] = True

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(exist_ok=True)

    # Fake config returned by the lazy _get_config()
    fake_config = MagicMock()
    fake_config.SOGO_UPLOAD_TEMP_PATH = str(upload_dir)
    fake_config.SOGO_MAX_ATTACHMENT_SIZE = 10_000
    fake_config.SOGO_ALLOWED_ATTACHMENT_TYPES = ["text/plain", "image/png", "application/pdf"]

    # Fake Redis client
    from app.utils.api.ApiBaseResponse import create_api_base_response  # noqa

    class FakeCache:
        def __init__(self):
            self._store = {}

        def get(self, key, expected_type=str):
            raw = self._store.get(key)
            if raw is None:
                return None
            if expected_type is dict:
                return json.loads(raw) if isinstance(raw, str) else raw
            return raw

        def set(self, key, val, ttl=None, nx=False):
            if nx and key in self._store:
                return False
            if isinstance(val, (dict, list)):
                val = json.dumps(val)
            self._store[key] = val
            return True

        def delete(self, *keys):
            n = 0
            for key in keys:
                if key in self._store:
                    del self._store[key]
                    n += 1
            return n

        @property
        def redis(self):
            return self

    fake_cache = FakeCache()

    from app.utils.exceptions import RequestException
    from app.utils.api.ApiBaseResponse import create_api_base_response

    def _request_exception_response(_e: RequestException) -> tuple[dict, int]:
        return create_api_base_response(None, error=_e.error, status_code=_e.http_status)

    with (
        patch.object(ApiAttachments, "_get_config", return_value=fake_config),
        patch.object(ApiAttachments, "_get_redis_client", return_value=fake_cache),
    ):
        app.errorhandler(RequestException)(_request_exception_response)
        app.register_blueprint(ApiAttachments.blp)

        @app.before_request
        def _set_user():
            g.user = MagicMock()
            g.user.uid = "test@example.org"

        client = app.test_client()
        client._sogo_cache = fake_cache
        client._sogo_config = fake_config
        yield client
        fake_cache._store.clear()


def _upload_payload(data: bytes, filename: str = "notes.txt", content_type: str = "text/plain"):
    """Build multipart form data for a file upload."""
    return {
        "file": (io.BytesIO(data), filename, content_type),
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /attachments/upload
# ─────────────────────────────────────────────────────────────────────────────

class TestUpload:
    def test_upload_valid_text_file(self, app_client, tmp_path):
        resp = app_client.post(
            "/attachments/upload",
            data=_upload_payload(b"hello world", "notes.txt", "text/plain"),
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["filename"] == "notes.txt"
        assert body["data"]["size"] == 11
        assert body["data"]["mime_type"] == "text/plain"
        assert body["data"]["upload_id"]
        # File should be written to disk
        files = list((tmp_path / "uploads").iterdir())
        assert len(files) == 1

    def test_upload_valid_png(self, app_client):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        resp = app_client.post(
            "/attachments/upload",
            data=_upload_payload(png, "img.png", "application/octet-stream"),
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["mime_type"] == "image/png"

    def test_upload_valid_pdf(self, app_client):
        pdf = b"%PDF-1.4 hello"
        resp = app_client.post(
            "/attachments/upload",
            data=_upload_payload(pdf, "doc.pdf", "application/pdf"),
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["mime_type"] == "application/pdf"

    def test_upload_unknown_mime_falls_back_to_declared(self, app_client):
        # Content that MediaType cannot detect -> falls back to declared type
        data = b"\x00\x01\x02\x03 unknown binary"
        resp = app_client.post(
            "/attachments/upload",
            data=_upload_payload(data, "blob.bin", "text/plain"),
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["mime_type"] == "text/plain"

    def test_upload_missing_file_rejected(self, app_client):
        resp = app_client.post(
            "/attachments/upload",
            data={},
            content_type="multipart/form-data",
        )
        # ERROR_TMP_DRAFT_UPLOAD_NO_FILE -> RequestException -> 400 via error handler
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["data"] is None

    def test_upload_empty_filename_rejected(self, app_client):
        resp = app_client.post(
            "/attachments/upload",
            data=_upload_payload(b"data", "", "text/plain"),
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["data"] is None

    def test_upload_file_too_large(self, app_client):
        big = b"x" * 20_000  # exceeds fake SOGO_MAX_ATTACHMENT_SIZE=10000
        resp = app_client.post(
            "/attachments/upload",
            data=_upload_payload(big, "huge.bin", "text/plain"),
            content_type="multipart/form-data",
        )
        body = resp.get_json() if resp.is_json else {}
        # ERROR_FILE_TOO_LARGE -> HTTP 413
        assert resp.status_code == 413
        assert body["data"] is None

    def test_upload_disallowed_mime(self, app_client):
        # A .exe-ish content that MediaType can't detect -> declared type not in allowed list
        resp = app_client.post(
            "/attachments/upload",
            data=_upload_payload(b"MZ\x90\x00 exe", "app.exe", "application/octet-stream"),
            content_type="multipart/form-data",
        )
        body = resp.get_json() if resp.is_json else {}
        # ERROR_FILE_TYPE_NOT_ALLOWED -> HTTP 415
        assert resp.status_code == 415
        assert body["data"] is None

    def test_upload_redis_failure_cleans_up_file(self, app_client, tmp_path):
        from app.api.v1.mail import ApiAttachments

        class FailingCache:
            def set(self, key, val, ttl=None, nx=False):
                raise RuntimeError("redis down")

        with patch.object(ApiAttachments, "_get_redis_client", return_value=FailingCache()):
            resp = app_client.post(
                "/attachments/upload",
                data=_upload_payload(b"hello", "notes.txt", "text/plain"),
                content_type="multipart/form-data",
            )
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None
        # File cleaned up after redis failure
        assert list((tmp_path / "uploads").iterdir()) == []

    def test_upload_creates_missing_dir(self, app_client, tmp_path):
        """When the upload temp dir does not exist it is created automatically."""
        from app.api.v1.mail import ApiAttachments

        fresh_dir = tmp_path / "brand-new-uploads"
        assert not fresh_dir.exists()

        config = MagicMock()
        config.SOGO_UPLOAD_TEMP_PATH = str(fresh_dir)
        config.SOGO_MAX_ATTACHMENT_SIZE = 10_000
        config.SOGO_ALLOWED_ATTACHMENT_TYPES = ["text/plain"]

        with patch.object(ApiAttachments, "_get_config", return_value=config):
            resp = app_client.post(
                "/attachments/upload",
                data=_upload_payload(b"hello", "notes.txt", "text/plain"),
                content_type="multipart/form-data",
            )
        assert resp.status_code == 200
        assert fresh_dir.exists()
        assert len(list(fresh_dir.iterdir())) == 1

    def test_upload_dir_create_failure(self, app_client, tmp_path):
        """OSError during directory creation -> ERROR_TMP_DRAFT_ATTACHMENT_FAILED."""
        from app.api.v1.mail import ApiAttachments

        fresh_dir = tmp_path / "cannot-create"
        config = MagicMock()
        config.SOGO_UPLOAD_TEMP_PATH = str(fresh_dir)
        config.SOGO_MAX_ATTACHMENT_SIZE = 10_000
        config.SOGO_ALLOWED_ATTACHMENT_TYPES = ["text/plain"]

        with (
            patch.object(ApiAttachments, "_get_config", return_value=config),
            patch("os.makedirs", side_effect=OSError("permission denied")),
        ):
            resp = app_client.post(
                "/attachments/upload",
                data=_upload_payload(b"hello", "notes.txt", "text/plain"),
                content_type="multipart/form-data",
            )
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None

    def test_upload_write_failure(self, app_client, tmp_path):
        """OSError while writing the file -> ERROR_TMP_DRAFT_ATTACHMENT_FAILED."""
        from app.api.v1.mail import ApiAttachments

        with patch("builtins.open", side_effect=OSError("disk full")):
            resp = app_client.post(
                "/attachments/upload",
                data=_upload_payload(b"hello", "notes.txt", "text/plain"),
                content_type="multipart/form-data",
            )
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None


# ─────────────────────────────────────────────────────────────────────────────
# GET /attachments/<upload_id>
# ─────────────────────────────────────────────────────────────────────────────

class TestGetDetail:
    def _upload_then_get(self, app_client):
        resp = app_client.post(
            "/attachments/upload",
            data=_upload_payload(b"hello world", "notes.txt", "text/plain"),
            content_type="multipart/form-data",
        )
        upload_id = resp.get_json()["data"]["upload_id"]
        return upload_id

    def test_get_existing_attachment(self, app_client):
        upload_id = self._upload_then_get(app_client)
        resp = app_client.get(f"/attachments/{upload_id}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["upload_id"] == upload_id
        assert body["data"]["filename"] == "notes.txt"
        assert body["data"]["user_uid"] == "test@example.org"

    def test_get_missing_attachment(self, app_client):
        resp = app_client.get("/attachments/does-not-exist")
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None

    def test_get_attachment_ownership_mismatch(self, app_client):
        upload_id = self._upload_then_get(app_client)
        # Second client with a different user
        from flask import Flask, g
        from app.api.v1.mail import ApiAttachments

        other = Flask(__name__)
        other.config["TESTING"] = True

        class OtherCache:
            def get(self, key, expected_type=str):
                return app_client._sogo_cache.get(key, dict)

        from app.config.settings.ProcessSetting import process_config  # noqa
        with patch.object(ApiAttachments, "_get_redis_client", return_value=OtherCache()):
            other.register_blueprint(ApiAttachments.blp)

            @other.before_request
            def _set_other_user():
                g.user = MagicMock()
                g.user.uid = "other@example.org"

            resp = other.test_client().get(f"/attachments/{upload_id}")
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None

    def test_get_redis_error_returns_not_found(self, app_client):
        from app.api.v1.mail import ApiAttachments

        class ThrowingCache:
            def get(self, key, expected_type=str):
                raise RuntimeError("boom")

        with patch.object(ApiAttachments, "_get_redis_client", return_value=ThrowingCache()):
            resp = app_client.get("/attachments/some-id")
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /attachments/<upload_id>
# ─────────────────────────────────────────────────────────────────────────────

class TestDeleteDetail:
    def _upload_then_delete(self, app_client, tmp_path):
        resp = app_client.post(
            "/attachments/upload",
            data=_upload_payload(b"hello world", "notes.txt", "text/plain"),
            content_type="multipart/form-data",
        )
        upload_id = resp.get_json()["data"]["upload_id"]
        return upload_id

    def test_delete_existing_attachment(self, app_client, tmp_path):
        upload_id = self._upload_then_delete(app_client, tmp_path)
        resp = app_client.delete(f"/attachments/{upload_id}")
        assert resp.status_code == 200
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None
        # Redis key removed
        assert app_client._sogo_cache.get(f"sogo:attachments:{upload_id}", dict) is None
        # File removed
        assert list((tmp_path / "uploads").iterdir()) == []

    def test_delete_missing_attachment(self, app_client):
        resp = app_client.delete("/attachments/nope")
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None

    def test_delete_ownership_mismatch(self, app_client, tmp_path):
        upload_id = self._upload_then_delete(app_client, tmp_path)
        from flask import Flask, g
        from app.api.v1.mail import ApiAttachments

        other = Flask(__name__)
        other.config["TESTING"] = True

        class OtherCache:
            def get(self, key, expected_type=str):
                return app_client._sogo_cache.get(key, dict)

        with patch.object(ApiAttachments, "_get_redis_client", return_value=OtherCache()):
            other.register_blueprint(ApiAttachments.blp)

            @other.before_request
            def _set_other_user():
                g.user = MagicMock()
                g.user.uid = "other@example.org"

            resp = other.test_client().delete(f"/attachments/{upload_id}")
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None
        # Owner's file should be untouched
        assert app_client._sogo_cache.get(f"sogo:attachments:{upload_id}", dict) is not None

    def test_delete_redis_error(self, app_client):
        from app.api.v1.mail import ApiAttachments

        class ThrowingCache:
            def get(self, key, expected_type=str):
                raise RuntimeError("boom")

        with patch.object(ApiAttachments, "_get_redis_client", return_value=ThrowingCache()):
            resp = app_client.delete("/attachments/some-id")
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None

    def test_delete_file_oserror(self, app_client, tmp_path):
        """OSError while removing the file on disk -> ERROR_TMP_DRAFT_DELETE_ATTACHMENT_FAILED."""
        from app.api.v1.mail import ApiAttachments

        upload_id = self._upload_then_delete(app_client, tmp_path)
        with patch("os.remove", side_effect=OSError("permission denied")):
            resp = app_client.delete(f"/attachments/{upload_id}")
        body = resp.get_json() if resp.is_json else {}
        assert body["data"] is None
