# pylint: disable=invalid-sequence-index
"""Unit tests for SnoozeJob (44% -> high)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")


from app.agent.jobs.SnoozeJob import SnoozeCheckRequest, SnoozeJob


def make_patches(due=None):
    db = mock.MagicMock()
    module = mock.MagicMock()
    module.list_due.return_value = due or []
    patches = [
        mock.patch(
            "app.utils.module.importManager.import_and_instantiate_manager",
            return_value=db,
        ),
        mock.patch("app.module.mail.ModuleSnooze.ModuleSnooze", return_value=module),
    ]
    return db, module, patches


class TestRequest:
    def test_meta(self):
        assert SnoozeCheckRequest.name == "snooze_check"
        assert SnoozeCheckRequest.max_try == 3
        assert SnoozeCheckRequest.max_concurrent == 1

    def test_job_registered(self):
        assert SnoozeJob.request_class is SnoozeCheckRequest


class TestProcess:
    def test_no_due(self):
        _, module, patches = make_patches(due=[])
        with mock.patch(
            "app.config.settings.ProcessSetting.process_config"
        ) as proc:
            proc.SOGO_P_DB_TYPE = "MySQL"
            proc.get_db_settings.return_value = {"host": "db"}
            for p in patches:
                p.start()
            try:
                out = SnoozeJob().process({})
            finally:
                for p in patches:
                    p.stop()
        assert out["processed"] == 0
        assert "checked_at" in out
        module.remove_record.assert_not_called()

    def test_processes_due(self):
        db, module, patches = make_patches(due=[
            {"id": 1, "mail_uid": "M1", "user_uid": "u1", "snooze_until": "2024-01-01"},
            {"id": 2, "mail_uid": "M2", "user_uid": "u2", "snooze_until": "2024-01-01"},
        ])
        with mock.patch(
            "app.config.settings.ProcessSetting.process_config"
        ) as proc:
            proc.SOGO_P_DB_TYPE = "MySQL"
            proc.get_db_settings.return_value = {"host": "db"}
            for p in patches:
                p.start()
            try:
                out = SnoozeJob().process({})
            finally:
                for p in patches:
                    p.stop()
        assert out["processed"] == 2
        assert module.remove_record.call_count == 2
        db.connect.assert_called_once()

    def test_skips_failed_record(self):
        db, module, patches = make_patches(due=[
            {"id": 9, "mail_uid": "M9", "user_uid": "u9", "snooze_until": "2024-01-01"},
        ])
        module.remove_record.side_effect = RuntimeError("db down")
        with mock.patch(
            "app.config.settings.ProcessSetting.process_config"
        ) as proc:
            proc.SOGO_P_DB_TYPE = "MySQL"
            proc.get_db_settings.return_value = {"host": "db"}
            with mock.patch(
                "app.agent.jobs.SnoozeJob.logger_agent"
            ) as logger_mock:
                for p in patches:
                    p.start()
                try:
                    out = SnoozeJob().process({})
                finally:
                    for p in patches:
                        p.stop()
        assert out["processed"] == 0
        logger_mock.error.assert_called()
