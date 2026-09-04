"""Unit tests for CardDavFetcher (SSRF-protected vCard download).

Tests the CardDAV fetcher that downloads vCard data from remote HTTPS URLs
with security protections:
- URL scheme validation (HTTPS only)
- IP address validation (no private/loopback/link-local)
- DNS rebinding protection (IP pinning)
- Size and timeout limits
- vCard format validation
"""
from unittest.mock import MagicMock, patch, mock_open
import socket

import pytest

from app.module.contact.sync.CardDavFetcher import (
    CardDavFetcher,
    FETCH_TIMEOUT_SECONDS,
    MAX_VCARD_BYTES,
    MAX_VCARD_REDIRECTS,
    _ValidatingRedirectHandler,
    _PinnedHTTPSConnection,
    _PinnedHTTPSHandler,
)
from app.utils.exceptions import RequestException


class TestValidateUrl:
    def test_valid_https_url_returns_pinned_ip(self):
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (None, None, None, None, ("8.8.8.8", 443)),
            ]
            with patch("urllib.parse.urlparse") as mock_parse:
                mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
                result = CardDavFetcher._validate_url("https://example.com/card")
                assert result == "8.8.8.8"

    def test_http_url_raises(self):
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (None, None, None, None, ("8.8.8.8", 80)),
            ]
            with patch("urllib.parse.urlparse") as mock_parse:
                mock_parse.return_value = MagicMock(scheme="http", hostname="example.com")
                with pytest.raises(RequestException):
                    CardDavFetcher._validate_url("http://example.com/card")

    def test_invalid_url_raises(self):
        with patch("urllib.parse.urlparse") as mock_parse:
            mock_parse.return_value = MagicMock(scheme="https", hostname=None)
            with pytest.raises(RequestException):
                CardDavFetcher._validate_url("not-a-url")

    def test_unresolvable_hostname_raises(self):
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")
            with patch("urllib.parse.urlparse") as mock_parse:
                mock_parse.return_value = MagicMock(scheme="https", hostname="invalid.example.com")
                with pytest.raises(RequestException):
                    CardDavFetcher._validate_url("https://invalid.example.com/card")

    def test_private_ip_raises(self):
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (None, None, None, None, ("192.168.1.1", 443)),
            ]
            with patch("urllib.parse.urlparse") as mock_parse:
                mock_parse.return_value = MagicMock(scheme="https", hostname="internal.local")
                with pytest.raises(RequestException):
                    CardDavFetcher._validate_url("https://internal.local/card")

    def test_loopback_ip_raises(self):
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (None, None, None, None, ("127.0.0.1", 443)),
            ]
            with patch("urllib.parse.urlparse") as mock_parse:
                mock_parse.return_value = MagicMock(scheme="https", hostname="localhost")
                with pytest.raises(RequestException):
                    CardDavFetcher._validate_url("https://localhost/card")

    def test_link_local_ip_raises(self):
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (None, None, None, None, ("169.254.1.1", 443)),
            ]
            with patch("urllib.parse.urlparse") as mock_parse:
                mock_parse.return_value = MagicMock(scheme="https", hostname="link.local")
                with pytest.raises(RequestException):
                    CardDavFetcher._validate_url("https://link.local/card")



class TestValidateVcardFormat:
    def test_valid_vcard_passes(self):
        text = """BEGIN:VCARD
VERSION:3.0
FN:Test User
END:VCARD"""
        CardDavFetcher._validate_vcard_format(text, "https://example.com/card")

    def test_missing_begin_raises(self):
        text = "VERSION:3.0\nFN:Test User"
        with pytest.raises(RequestException):
            CardDavFetcher._validate_vcard_format(text, "https://example.com/card")

    def test_empty_text_raises(self):
        with pytest.raises(RequestException):
            CardDavFetcher._validate_vcard_format("", "https://example.com/card")


class TestSanitize:
    def test_removes_cr(self):
        result = CardDavFetcher._sanitize("test\rvalue")
        assert "\r" not in result
        assert result == "test value"

    def test_removes_lf(self):
        result = CardDavFetcher._sanitize("test\nvalue")
        assert "\n" not in result
        assert result == "test value"

    def test_removes_both(self):
        result = CardDavFetcher._sanitize("test\r\nvalue")
        assert "\r" not in result
        assert "\n" not in result
        assert result == "test  value"


class TestValidatingRedirectHandler:
    def test_redirect_within_limit(self):
        handler = _ValidatingRedirectHandler(max_redirects=5)
        with patch("urllib.request.HTTPRedirectHandler.redirect_request") as mock_super:
            mock_super.return_value = MagicMock()
            with patch.object(CardDavFetcher, "_validate_url"):
                req = MagicMock()
                result = handler.redirect_request(req, MagicMock(), 302, "Found", MagicMock(), "https://new.url")
                assert handler._count == 1
                assert result is not None

    def test_redirect_exceeds_limit_raises(self):
        handler = _ValidatingRedirectHandler(max_redirects=1)
        handler._count = 1  # Already at limit
        with patch.object(CardDavFetcher, "_validate_url"):
            req = MagicMock()
            with pytest.raises(RequestException):
                handler.redirect_request(req, MagicMock(), 302, "Found", MagicMock(), "https://new.url")


class TestPinnedHTTPSConnection:
    def test_connect_uses_pinned_ip(self):
        conn = _PinnedHTTPSConnection("example.com", "8.8.8.8")
        conn._context = MagicMock()
        mock_sock = MagicMock()
        with patch("socket.create_connection") as mock_create:
            mock_create.return_value = mock_sock
            with patch.object(conn._context, "wrap_socket") as mock_wrap:
                mock_wrap.return_value = MagicMock()
                conn.connect()
                mock_create.assert_called_once_with(("8.8.8.8", 443), timeout=conn.timeout)


class TestPinnedHTTPSHandler:
    def test_https_open_uses_pinned_connection(self):
        handler = _PinnedHTTPSHandler("8.8.8.8", context=MagicMock())
        req = MagicMock()
        with patch.object(handler, "do_open") as mock_do_open:
            mock_do_open.return_value = MagicMock()
            handler.https_open(req)
            assert mock_do_open.called


class TestFetch:
    def test_fetch_success(self):
        vcard_content = "BEGIN:VCARD\nVERSION:3.0\nFN:Test\nEND:VCARD"
        with patch("urllib.parse.urlparse") as mock_parse:
            mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (None, None, None, None, ("8.8.8.8", 443)),
                ]
                with patch("urllib.request.build_opener") as mock_opener:
                    mock_response = MagicMock()
                    mock_response.read.return_value = vcard_content.encode("utf-8")
                    mock_opener_instance = MagicMock()
                    mock_opener_instance.open.return_value.__enter__.return_value = mock_response
                    mock_opener.return_value = mock_opener_instance
                    result = CardDavFetcher.fetch("https://example.com/card")
                    assert result == vcard_content

    def test_fetch_with_auth(self):
        vcard_content = "BEGIN:VCARD\nVERSION:3.0\nFN:Test\nEND:VCARD"
        with patch("urllib.parse.urlparse") as mock_parse:
            mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (None, None, None, None, ("8.8.8.8", 443)),
                ]
                with patch("urllib.request.build_opener") as mock_opener:
                    mock_response = MagicMock()
                    mock_response.read.return_value = vcard_content.encode("utf-8")
                    mock_opener_instance = MagicMock()
                    mock_opener_instance.open.return_value.__enter__.return_value = mock_response
                    mock_opener.return_value = mock_opener_instance
                    result = CardDavFetcher.fetch("https://example.com/card", username="user", password="pass")
                    assert result == vcard_content
                    # Verify Authorization header was added
                    mock_opener_instance.open.assert_called_once()
                    call_args = mock_opener_instance.open.call_args
                    assert call_args[0][0].get_header("Authorization") is not None

    def test_fetch_too_large_raises(self):
        large_content = "BEGIN:VCARD\n" + "x" * (MAX_VCARD_BYTES + 1) + "\nEND:VCARD"
        with patch("urllib.parse.urlparse") as mock_parse:
            mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (None, None, None, None, ("8.8.8.8", 443)),
                ]
                with patch("urllib.request.build_opener") as mock_opener:
                    mock_response = MagicMock()
                    mock_response.read.return_value = large_content.encode("utf-8")
                    mock_opener_instance = MagicMock()
                    mock_opener_instance.open.return_value.__enter__.return_value = mock_response
                    mock_opener.return_value = mock_opener_instance
                    with pytest.raises(RequestException):
                        CardDavFetcher.fetch("https://example.com/card")

    def test_fetch_invalid_vcard_raises(self):
        invalid_content = "Not a vCard"
        with patch("urllib.parse.urlparse") as mock_parse:
            mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (None, None, None, None, ("8.8.8.8", 443)),
                ]
                with patch("urllib.request.build_opener") as mock_opener:
                    mock_response = MagicMock()
                    mock_response.read.return_value = invalid_content.encode("utf-8")
                    mock_opener_instance = MagicMock()
                    mock_opener_instance.open.return_value.__enter__.return_value = mock_response
                    mock_opener.return_value = mock_opener_instance
                    with pytest.raises(RequestException):
                        CardDavFetcher.fetch("https://example.com/card")

    def test_fetch_http_error_raises(self):
        with patch("urllib.parse.urlparse") as mock_parse:
            mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (None, None, None, None, ("8.8.8.8", 443)),
                ]
                with patch("urllib.request.build_opener") as mock_opener:
                    mock_opener_instance = MagicMock()
                    mock_opener_instance.open.side_effect = Exception("HTTP Error 404")
                    mock_opener.return_value = mock_opener_instance
                    with pytest.raises(RequestException):
                        CardDavFetcher.fetch("https://example.com/card")

    def test_fetch_timeout_raises(self):
        with patch("urllib.parse.urlparse") as mock_parse:
            mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (None, None, None, None, ("8.8.8.8", 443)),
                ]
                with patch("urllib.request.build_opener") as mock_opener:
                    mock_opener_instance = MagicMock()
                    mock_opener_instance.open.side_effect = Exception("Timeout")
                    mock_opener.return_value = mock_opener_instance
                    with pytest.raises(RequestException):
                        CardDavFetcher.fetch("https://example.com/card")

    def test_fetch_latin1_fallback(self):
        # Content that's not valid UTF-8 but valid Latin-1
        latin1_content = "BEGIN:VCARD\nVERSION:3.0\nFN:T\xE9st\nEND:VCARD"
        with patch("urllib.parse.urlparse") as mock_parse:
            mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
            with patch("socket.getaddrinfo") as mock_getaddrinfo:
                mock_getaddrinfo.return_value = [
                    (None, None, None, None, ("8.8.8.8", 443)),
                ]
                with patch("urllib.request.build_opener") as mock_opener:
                    mock_response = MagicMock()
                    mock_response.read.return_value = latin1_content.encode("latin-1")
                    mock_opener_instance = MagicMock()
                    mock_opener_instance.open.return_value.__enter__.return_value = mock_response
                    mock_opener.return_value = mock_opener_instance
                    result = CardDavFetcher.fetch("https://example.com/card")
                    assert "BEGIN:VCARD" in result

    def test_all_public_ips_succeeds(self):
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (None, None, None, None, ("8.8.8.8", 443)),
                (None, None, None, None, ("8.8.4.4", 443)),
            ]
            with patch("urllib.parse.urlparse") as mock_parse:
                mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
                result = CardDavFetcher._validate_url("https://example.com/card")
                assert result == "8.8.8.8"

    def test_first_ip_private_raises(self):
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (None, None, None, None, ("192.168.1.1", 443)),
                (None, None, None, None, ("8.8.8.8", 443)),
            ]
            with patch("urllib.parse.urlparse") as mock_parse:
                mock_parse.return_value = MagicMock(scheme="https", hostname="example.com")
                with pytest.raises(RequestException):
                    CardDavFetcher._validate_url("https://example.com/card")
