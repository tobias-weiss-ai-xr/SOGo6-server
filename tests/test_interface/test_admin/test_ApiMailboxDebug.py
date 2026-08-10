"""Tests for Mailbox Debug Panel (#35)."""
import pytest


class TestMailboxDebug:
    def test_debug_raw_endpoint_exists(self):
        from app.api.v1.admin.ApiMailboxDebug import ApiMailboxDebugRaw
        view = ApiMailboxDebugRaw()
        assert hasattr(view, 'get')
    
    def test_debug_headers_endpoint_exists(self):
        from app.api.v1.admin.ApiMailboxDebug import ApiMailboxDebugHeaders
        view = ApiMailboxDebugHeaders()
        assert hasattr(view, 'get')

    def test_anonymous_user_fallback(self):
        from app.api.v1.admin.ApiMailboxDebug import AnonymousUser
        user = AnonymousUser()
        assert user.uid == ""
        assert user.authenticated is False
        assert user.domain == ""
