# pylint: disable=invalid-sequence-index
"""Unit tests for ApiNotes (Notes API CRUD operations)."""
from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("SOGO_P_REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SOGO_P_VOUCHER_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("SOGO_AES_ENC_KEY", "A9fK2QxM7eR3PZLwH6Jd8sC4T5mNByU")

import pytest
from flask import Flask, g

from app.api.v1.user.ApiNotes import blp
from app.module.user.ModuleUserNotes import ModuleUserNotes


class TestNotesApi:
    """Test suite for Notes API endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures for each test method."""
        # Create mock database
        self.db = mock.MagicMock()
        self.db.connect = mock.MagicMock()
        self.db.select_from_table = mock.MagicMock()
        self.db.insert_in_table = mock.MagicMock()
        self.db.update_in_table = mock.MagicMock()
        self.db.delete_row_in_table = mock.MagicMock()
        
        # Create factory
        class TestFactory:
            def create_user(self):
                """Create a mock test user."""
                user = mock.MagicMock()
                user.uid = "testuser@example.org"
                return user
        
        self.factory = TestFactory()
        
        # Create Flask client
        app = Flask(__name__)
        app.config["TESTING"] = True

        @app.before_request
        def _set_ctx():
            g.process_settings = mock.MagicMock()
            g.system_settings = mock.MagicMock()
            g.user_domain_settings = {}
            g.user = self.factory.create_user()
            g._user_notes_module = ModuleUserNotes(self.db)

        app.register_blueprint(blp)
        self.client = app.test_client()
        
        # Create module instance
        self.module = ModuleUserNotes(self.db)
        
        yield

    def test_create_note(self):
        """Test POST /notes to create a new note."""
        user = self.factory.create_user()
        
        # Mock the module's create_note method
        with mock.patch.object(self.module, 'create_note') as mock_create:
            mock_create.return_value = {
                "id": "note-123",
                "user_uid": user.uid,
                "title": "Test Note",
                "content": "This is a test note",
                "created_at": "2025-01-01T00:00:00",
                "updated_at": "2025-01-01T00:00:00",
            }
            
            resp = self.client.post("/notes", json={
                "title": "Test Note",
                "content": "This is a test note",
            })
            
            assert resp.status_code == 201
            data = resp.get_json()
            assert "id" in data
            assert data["title"] == "Test Note"
            assert data["content"] == "This is a test note"
            assert data["user_uid"] == user.uid

    def test_list_notes(self):
        """Test GET /notes to list all notes."""
        user = self.factory.create_user()
        
        # Mock the module's list_notes method
        with mock.patch.object(self.module, 'list_notes') as mock_list:
            mock_list.return_value = [
                {
                    "id": "note-1",
                    "user_uid": user.uid,
                    "title": "Note 1",
                    "content": "Content 1",
                    "created_at": "2025-01-01T00:00:00",
                    "updated_at": "2025-01-01T00:00:00",
                },
                {
                    "id": "note-2",
                    "user_uid": user.uid,
                    "title": "Note 2",
                    "content": "Content 2",
                    "created_at": "2025-01-02T00:00:00",
                    "updated_at": "2025-01-02T00:00:00",
                },
            ]
            
            resp = self.client.get("/notes")
            
            assert resp.status_code == 200
            data = resp.get_json()
            assert isinstance(data, list)
            assert len(data) == 2
            assert all(isinstance(item, dict) for item in data)
            assert data[0]["id"] == "note-1"
            assert data[1]["id"] == "note-2"

    def test_get_note(self):
        """Test GET /notes/<id> to get a specific note."""
        # Mock the module's get_note method
        with mock.patch.object(self.module, 'get_note') as mock_get:
            mock_get.return_value = {
                "id": "note-123",
                "user_uid": "testuser@example.org",
                "title": "Specific Note",
                "content": "Note content",
                "created_at": "2025-01-01T00:00:00",
                "updated_at": "2025-01-01T00:00:00",
            }
            
            resp = self.client.get("/notes/note-123")
            
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["id"] == "note-123"
            assert data["title"] == "Specific Note"
            assert data["content"] == "Note content"

    def test_update_note(self):
        """Test PUT /notes/<id> to update a note."""
        # Mock the module's update_note method
        with mock.patch.object(self.module, 'update_note') as mock_update:
            mock_update.return_value = {
                "id": "note-123",
                "user_uid": "testuser@example.org",
                "title": "Updated Title",
                "content": "Updated content",
                "created_at": "2025-01-01T00:00:00",
                "updated_at": "2025-01-02T00:00:00",
            }
            
            resp = self.client.put("/notes/note-123", json={
                "title": "Updated Title",
                "content": "Updated content",
            })
            
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["id"] == "note-123"
            assert data["title"] == "Updated Title"
            assert data["content"] == "Updated content"

    def test_delete_note(self):
        """Test DELETE /notes/<id> to delete a note."""
        # Mock the module's delete_note method
        with mock.patch.object(self.module, 'delete_note') as mock_delete:
            mock_delete.return_value = True
            
            resp = self.client.delete("/notes/note-123")
            
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["deleted"] is True
            assert data["note_id"] == "note-123"
