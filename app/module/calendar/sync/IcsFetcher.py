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

from app.module.calendar.CalendarConst import FETCH_TIMEOUT_SECONDS, MAX_ICS_BYTES, MAX_ICS_REDIRECTS
from app.utils.errors import ERROR_CALENDAR_ICS_FETCH_FAILED, ERROR_CALENDAR_ICS_PARSE_FAILED
from app.utils.exceptions import RequestException
from app.utils.logger.logger import logger_calendar


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """HTTPS redirect handler that re-validates each redirect target and caps the number of redirects.

    Re-validation is essential: a remote server can return a 302 toward a private/loopback IP
    (e.g. https://169.254.169.254/) and a naive handler would follow it, defeating the initial check.
    """

    def __init__(self, max_redirects: int) -> None:
        super().__init__()
        self._max = max_redirects
        self._count = 0

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: Any, headers: Any, newurl: str,
    ) -> urllib.request.Request | None:
        self._count += 1
        if self._count > self._max:
            logger_calendar.error("ICS feed exceeded max redirects (%d)", self._max)
            raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED)
        IcsFetcher._validate_url(newurl)  # pylint: disable=protected-access
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# DNS rebinding protection - why these two classes exist:
#
# _validate_url() resolves the hostname once and checks that every returned IP is public.
# A naive follow-up call to urllib.request.urlopen() would re-resolve the same hostname
# independently, giving an attacker who controls a low-TTL DNS zone the opportunity to
# return a public IP at validation time and a private IP (e.g. 169.254.169.254 cloud
# metadata, 127.0.0.1, RFC 1918) when urllib actually connects.
#
# We close the window by passing the already-validated IP through the urllib stack: the
# Connection opens the TCP socket on the pinned IP, the Handler routes urlopen() through
# this Connection. The hostname is still carried for TLS SNI / certificate validation.
#
# HTTPS-only: ICS over plain HTTP is rejected by _validate_url, so we don't need an HTTP
# variant of these classes.


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that opens the TCP socket on a pinned IP.

    The hostname passed as `host` is kept for two purposes that must not change after
    DNS validation:
      * TLS SNI (`server_hostname=` in wrap_socket) - lets the remote serve the right
        certificate when multiple sites share an IP.
      * Certificate validation - the CN/SAN is matched against the hostname, not the IP,
        so plugging the IP here would break verification for any real HTTPS endpoint.
    Only the address used by `socket.create_connection` is swapped for the pinned IP.
    """

    def __init__(self, host: str, pinned_ip: str, **kwargs: Any) -> None:
        super().__init__(host, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, self.port), timeout=self.timeout)
        # _context is set by http.client.HTTPSConnection but absent from typeshed stubs.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """urllib HTTPS handler that routes every request through _PinnedHTTPSConnection.

    Installed in the opener so that urlopen() never falls back to the stdlib default
    HTTPSHandler - which would resolve the hostname again and undo the IP pinning.
    Forwards the SSLContext so certificate verification stays enabled.
    """

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


class IcsFetcher:
    """Downloads ICS/CalDAV content from a remote HTTPS URL with SSRF protection.

    Supports:
    - Direct ICS URLs (single .ics file download)
    - CalDAV calendar URLs (PROPFIND discovery + GET for event collection)

    Validates the URL scheme (https only) and rejects private/loopback/link-local IPs.
    The hostname is resolved once and the connection is pinned to that IP (anti DNS-rebinding).
    Redirects are re-validated against the same rules.
    Enforces a size limit, timeout, and redirect limit on the download.
    Supports HTTP Basic authentication for htaccess-protected feeds.
    """

    # CalDAV XML namespaces for PROPFIND discovery
    NS_DAV: str = "DAV:"
    NS_CALDAV: str = "urn:ietf:params:xml:ns:caldav"

    @staticmethod
    def fetch(url: str, username: str | None = None, password: str | None = None) -> str:
        """Download and return the ICS content as a string.

        For direct ICS URLs this performs a simple GET.
        For CalDAV URLs this attempts GET first, and if the response is not
        iCalendar data, performs a PROPFIND to discover the calendar URL.

        :param url: The remote ICS or CalDAV URL to fetch (https only).
        :param username: Optional HTTP Basic auth username.
        :param password: Optional HTTP Basic auth password.
        :raises RequestException: On network error, invalid URL, SSRF attempt, size limit exceeded, or invalid ICS format.
        """
        pinned_ip: str = IcsFetcher._validate_url(url)
        logger_calendar.debug("Fetching calendar from %s", url)
        try:
            # First try: direct GET (works for plain ICS feeds)
            result: str = IcsFetcher._http_get(url, pinned_ip, username, password)
            if IcsFetcher._looks_like_icalendar(result):
                return result

            # Second try: CalDAV PROPFIND to discover calendar URL
            logger_calendar.debug(
                "Direct GET did not return iCalendar, trying CalDAV PROPFIND for %s", url
            )
            calendar_url: str | None = IcsFetcher._discover_calendar_url(
                url, pinned_ip, username, password,
            )
            if calendar_url:
                result = IcsFetcher._http_get(
                    calendar_url, pinned_ip, username, password,
                )
                if IcsFetcher._looks_like_icalendar(result):
                    return result

            # If neither succeeded, the content is not valid ICS
            raise RequestException(error=ERROR_CALENDAR_ICS_PARSE_FAILED)

        except RequestException:
            raise
        except urllib.error.HTTPError as exc:
            logger_calendar.error("HTTP %s fetching calendar from %s: %s",
                                  exc.code, url, IcsFetcher._sanitize(str(exc.reason)))
            raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED) from exc
        except urllib.error.URLError as exc:
            logger_calendar.error("Failed to fetch calendar from %s: %s",
                                  url, IcsFetcher._sanitize(str(exc)))
            raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED) from exc
        except Exception as exc:
            logger_calendar.exception("Unexpected error fetching calendar from %s", url)
            raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED) from exc

    @staticmethod
    def _http_get(url: str, pinned_ip: str, username: str | None = None,
                  password: str | None = None) -> str:
        """Perform an HTTP GET request with SSRF protection."""
        request = urllib.request.Request(url)
        request.add_header("Accept", "text/calendar, application/calendar+json, */*")
        if username and password:
            credentials: str = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            request.add_header("Authorization", f"Basic {credentials}")

        opener = urllib.request.build_opener(
            _PinnedHTTPSHandler(pinned_ip, context=ssl.create_default_context()),
            _ValidatingRedirectHandler(max_redirects=MAX_ICS_REDIRECTS),
        )
        with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            raw: bytes = response.read(MAX_ICS_BYTES + 1)
            if len(raw) > MAX_ICS_BYTES:
                logger_calendar.error("Calendar feed from %s exceeds size limit (%d bytes)",
                                      url, MAX_ICS_BYTES)
                raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED)
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1")

    @staticmethod
    def _discover_calendar_url(url: str, pinned_ip: str, username: str | None = None,
                                password: str | None = None) -> str | None:
        """Discover the calendar URL via CalDAV PROPFIND.

        Sends a PROPFIND to the URL to discover calendar-home-set or
        directly listed calendar URLs. Returns the first calendar URL found.
        Returns None if PROPFIND is not supported (HTTP 405).
        """
        propfind_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '  <d:prop>'
            '    <d:resourcetype/>'
            '    <d:displayname/>'
            '    <c:supported-calendar-component-set/>'
            '  </d:prop>'
            '</d:propfind>'
        )

        request = urllib.request.Request(
            url,
            data=propfind_xml.encode("utf-8"),
            method="PROPFIND",
        )
        request.add_header("Content-Type", "application/xml; charset=utf-8")
        request.add_header("Depth", "1")
        if username and password:
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            request.add_header("Authorization", f"Basic {credentials}")

        opener = urllib.request.build_opener(
            _PinnedHTTPSHandler(pinned_ip, context=ssl.create_default_context()),
            _ValidatingRedirectHandler(max_redirects=MAX_ICS_REDIRECTS),
        )

        try:
            with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_ICS_BYTES + 1)
                body = raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 405:
                # Method not allowed -> not a CalDAV server
                logger_calendar.debug("PROPFIND not supported at %s (HTTP 405), treating as ICS URL", url)
                return None
            raise

        # Parse the XML response to find calendar URLs
        parsed = urllib.parse.urlparse(url)
        calendar_urls = IcsFetcher._parse_propfind_response(body, parsed)

        if calendar_urls:
            # Return the first VEVENT-capable calendar
            for cal_url in calendar_urls:
                if "VEVENT" in cal_url.get("components", []):
                    return cal_url["href"]
            return calendar_urls[0]["href"]

        return None

    @staticmethod
    def _parse_propfind_response(
        xml_body: str, base_parsed: urllib.parse.ParseResult
    ) -> list[dict[str, object]]:
        """Minimal XML parser for PROPFIND responses.

        Extracts href, displayname, and supported calendar components
        without external XML library dependencies.
        """
        calendars: list[dict[str, object]] = []
        current: dict[str, object] = {}
        in_response = False
        _ = ""

        for line in xml_body.split("<"):
            if not line:
                continue

            if line.startswith("d:response") or line.startswith("response"):
                if in_response and current:
                    calendars.append(current)
                current = {}
                in_response = True
                continue

            if (line.startswith("/d:response") or line.startswith("/response")):
                if in_response and current:
                    calendars.append(current)
                in_response = False
                current = {}
                continue

            if not in_response:
                continue

            # href
            if line.startswith("d:href") or line.startswith("href"):
                if ">" in line:
                    content = line.split(">", 1)[1]
                    if "<" in content:
                        content = content.split("<", 1)[0]
                        if content:
                            current["href"] = content
                continue

            # displayname
            if line.startswith("d:displayname") or line.startswith("displayname"):
                if ">" in line:
                    content = line.split(">", 1)[1]
                    if "<" in content:
                        content = content.split("<", 1)[0]
                        if content:
                            current["displayname"] = content
                continue

            # calendar component (VEVENT, VTODO, etc.)
            if "calendar-component" in line or "supported-calendar-component" in line:
                if ">" in line:
                    comp = line.split(">", 1)[1].split("<", 1)[0].strip()
                    if comp:
                        components = current.get("components", [])
                        if isinstance(components, list):
                            components.append(comp)
                            current["components"] = components
                continue

        # Resolve relative hrefs
        base_scheme = base_parsed.scheme
        base_netloc = base_parsed.netloc
        base_path = base_parsed.path.rstrip("/") if base_parsed.path else ""

        resolved: list[dict[str, object]] = []
        for cal in calendars:
            href = cal.get("href", "")
            if isinstance(href, str):
                if href.startswith("/"):
                    cal["href"] = f"{base_scheme}://{base_netloc}{href}"
                elif not href.startswith("http"):
                    cal["href"] = f"{base_scheme}://{base_netloc}{base_path}/{href.lstrip('/')}"
            resolved.append(cal)

        return resolved

    @staticmethod
    def _looks_like_icalendar(text: str) -> bool:
        """Check if the response looks like iCalendar data."""
        return "BEGIN:VCALENDAR" in text and "END:VCALENDAR" in text

    @staticmethod
    def _validate_ics_format(text: str, url: str) -> None:
        """Validate that the content looks like a valid iCalendar feed."""
        if "BEGIN:VCALENDAR" not in text:
            logger_calendar.error("ICS feed from %s is not a valid iCalendar (missing BEGIN:VCALENDAR)", url)
            raise RequestException(error=ERROR_CALENDAR_ICS_PARSE_FAILED)

    @staticmethod
    def _sanitize(value: str) -> str:
        """Strip CR/LF to prevent log injection."""
        return str(value).replace("\r", " ").replace("\n", " ")

    @staticmethod
    def _validate_url(url: str) -> str:
        """Reject URLs that could enable SSRF attacks and return the validated IP to pin.

        Only the https scheme is allowed (plain HTTP is refused - ICS feeds without TLS have
        no business being subscribed to in 2026). The hostname must resolve to a public IP:
        private, loopback, link-local, reserved and multicast ranges are all rejected (covers
        RFC 1918, ::1, 169.254.x.x, etc.). All resolved addresses must be public; otherwise
        the URL is rejected.

        :return: The first resolved public IP, used to pin the subsequent connection.
        """
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception as exc:
            raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED) from exc

        if parsed.scheme != "https":
            logger_calendar.error("Rejected ICS URL with disallowed scheme: %s", parsed.scheme)
            raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED)

        hostname: str | None = parsed.hostname
        if not hostname:
            raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED)

        try:
            resolved = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            logger_calendar.error("Cannot resolve ICS hostname %s: %s", hostname, exc)
            raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED) from exc

        pinned_ip: str | None = None
        for info in resolved:
            ip_str: str = cast(str, info[4][0]).split("%")[0]
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
                logger_calendar.error("Rejected ICS URL resolving to non-public address: %s", ip_str)
                raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED)
            if pinned_ip is None:
                pinned_ip = ip_str

        if pinned_ip is None:
            raise RequestException(error=ERROR_CALENDAR_ICS_FETCH_FAILED)
        return pinned_ip
