from __future__ import annotations

import base64
import http.client
import ipaddress
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, cast

from app.utils import errors as err
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_contact

FETCH_TIMEOUT_SECONDS: int = 30
MAX_VCARD_BYTES: int = 50 * 1024 * 1024  # 50 MB
MAX_VCARD_REDIRECTS: int = 5


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """HTTPS redirect handler that re-validates each redirect target and caps redirects."""

    def __init__(self, max_redirects: int) -> None:
        super().__init__()
        self._max = max_redirects
        self._count = 0

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: Any, headers: Any, newurl: str,
    ) -> urllib.request.Request | None:
        self._count += 1
        if self._count > self._max:
            logger_contact.error("CardDAV feed exceeded max redirects (%d)", self._max)
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)
        CardDavFetcher._validate_url(newurl)  # pylint: disable=protected-access
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to a pre-validated IP (anti DNS-rebinding)."""

    def __init__(self, host: str, pinned_ip: str, **kwargs: Any) -> None:
        super().__init__(host, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """urllib HTTPS handler routing through _PinnedHTTPSConnection."""

    def __init__(self, pinned_ip: str, context: ssl.SSLContext) -> None:
        super().__init__(context=context)
        self._pinned_ip = pinned_ip
        self._context = context

    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(
            lambda host, **kw: _PinnedHTTPSConnection(host, self._pinned_ip, **kw),
            req,
            context=self._context,
        )


class CardDavFetcher:
    """Downloads vCard data from a remote HTTPS URL with SSRF protection.

    Validates URL scheme (https only), rejects private/loopback/link-local IPs,
    pins the resolved IP to prevent DNS rebinding, enforces size/timeout limits.
    """

    @staticmethod
    def fetch(url: str, username: str | None = None, password: str | None = None) -> str:
        """Download and return the raw vCard content as a string.

        Supports HTTP Basic auth. Expects the URL to point to a CardDAV address book
        that returns one or more vCard entries (BEGIN:VCARD ... END:VCARD).
        """
        pinned_ip: str = CardDavFetcher._validate_url(url)
        logger_contact.debug("Fetching CardDAV from %s", url)
        try:
            request = urllib.request.Request(url)
            request.add_header("Accept", "text/vcard")
            if username and password:
                credentials: str = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
                request.add_header("Authorization", f"Basic {credentials}")

            opener = urllib.request.build_opener(
                _PinnedHTTPSHandler(pinned_ip, context=ssl.create_default_context()),
                _ValidatingRedirectHandler(max_redirects=MAX_VCARD_REDIRECTS),
            )
            with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                raw: bytes = response.read(MAX_VCARD_BYTES + 1)
                if len(raw) > MAX_VCARD_BYTES:
                    logger_contact.error("CardDAV feed from %s exceeds size limit (%d bytes)", url, MAX_VCARD_BYTES)
                    raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)
                try:
                    text: str = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1")

            CardDavFetcher._validate_vcard_format(text, url)
            return text
        except RequestException:
            raise
        except urllib.error.HTTPError as exc:
            logger_contact.error("HTTP %s fetching CardDAV from %s: %s", exc.code, url, CardDavFetcher._sanitize(exc.reason))
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED) from exc
        except urllib.error.URLError as exc:
            logger_contact.error("Failed to fetch CardDAV from %s: %s", url, CardDavFetcher._sanitize(str(exc)))
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED) from exc
        except Exception as exc:
            logger_contact.exception("Unexpected error fetching CardDAV from %s", url)
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED) from exc

    @staticmethod
    def _validate_vcard_format(text: str, url: str) -> None:
        """Validate that the content looks like vCard data (contains at least one VCARD block)."""
        if "BEGIN:VCARD" not in text:
            logger_contact.error("CardDAV feed from %s is not valid vCard (missing BEGIN:VCARD)", url)
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)

    @staticmethod
    def _sanitize(value: str) -> str:
        """Strip CR/LF to prevent log injection."""
        return str(value).replace("\r", " ").replace("\n", " ")

    @staticmethod
    def _validate_url(url: str) -> str:
        """Reject URLs that could enable SSRF attacks and return the validated IP to pin."""
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception as exc:
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED) from exc

        if parsed.scheme != "https":
            logger_contact.error("Rejected CardDAV URL with disallowed scheme: %s", parsed.scheme)
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)

        hostname: str | None = parsed.hostname
        if not hostname:
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)

        try:
            resolved = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            logger_contact.error("Cannot resolve CardDAV hostname %s: %s", hostname, exc)
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED) from exc

        pinned_ip: str | None = None
        for info in resolved:
            ip_str: str = cast(str, info[4][0]).split("%")[0]
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
                logger_contact.error("Rejected CardDAV URL resolving to non-public address: %s", ip_str)
                raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)
            if pinned_ip is None:
                pinned_ip = ip_str

        if pinned_ip is None:
            raise RequestException(error=err.ERROR_CONTACT_ADDRESSBOOK_SYNC_FAILED)
        return pinned_ip
