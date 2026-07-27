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
from app.utils.logger.logger import logger_calendar

FETCH_TIMEOUT_SECONDS: int = 30
MAX_ICS_BYTES: int = 10 * 1024 * 1024  # 10 MB
MAX_REDIRECTS: int = 5

# CalDAV XML namespaces
NS_DAV = "DAV:"
NS_CALDAV = "urn:ietf:params:xml:ns:caldav"
NS_CALENDARSERVER = "http://calendarserver.org/ns/"


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
            logger_calendar.error("CalDAV feed exceeded max redirects (%d)", self._max)
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED)
        CalDavFetcher._validate_url(newurl)  # pylint: disable=protected-access
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


class CalDavFetcher:
    """Downloads calendar data from a remote CalDAV or HTTPS ICS URL with SSRF protection.

    Supports:
    - Direct ICS URLs (single .ics file download)
    - CalDAV calendar URLs (PROPFIND + GET for event collection)
    - HTTP Basic auth
    """

    @staticmethod
    def fetch_ics(url: str, username: str | None = None, password: str | None = None) -> str:
        """Download and return the raw iCalendar data as a string.

        For direct ICS URLs this performs a simple GET.
        For CalDAV calendar home URLs this performs PROPFIND to discover
        the calendar URL, then GET to retrieve the data.
        """
        pinned_ip: str = CalDavFetcher._validate_url(url)
        logger_calendar.debug("Fetching calendar from %s", url)

        try:
            # Try simple GET first (works for direct ICS feeds)
            result = CalDavFetcher._http_get(url, pinned_ip, username, password)
            if CalDavFetcher._looks_like_icalendar(result):
                logger_calendar.debug("Direct ICS fetch succeeded for %s", url)
                return result

            # If it doesn't look like iCalendar, try CalDAV PROPFIND
            logger_calendar.debug("Direct GET did not return iCalendar, trying CalDAV PROPFIND for %s", url)
            calendar_url = CalDavFetcher._discover_calendar_url(url, pinned_ip, username, password)
            if calendar_url:
                result = CalDavFetcher._http_get(calendar_url, pinned_ip, username, password)
                if CalDavFetcher._looks_like_icalendar(result):
                    return result

            # If we got here, the response wasn't iCalendar and we couldn't discover
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED)

        except RequestException:
            raise
        except urllib.error.HTTPError as exc:
            logger_calendar.error("HTTP %s fetching calendar from %s: %s",
                                  exc.code, url, CalDavFetcher._sanitize(str(exc.reason)))
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED) from exc
        except urllib.error.URLError as exc:
            logger_calendar.error("Failed to fetch calendar from %s: %s",
                                  url, CalDavFetcher._sanitize(str(exc)))
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED) from exc
        except Exception as exc:
            logger_calendar.exception("Unexpected error fetching calendar from %s", url)
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED) from exc

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
            _ValidatingRedirectHandler(max_redirects=MAX_REDIRECTS),
        )
        with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            raw: bytes = response.read(MAX_ICS_BYTES + 1)
            if len(raw) > MAX_ICS_BYTES:
                logger_calendar.error("Calendar feed from %s exceeds size limit (%d bytes)",
                                      url, MAX_ICS_BYTES)
                raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED)
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
        """
        propfind_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="{NS_DAV}" xmlns:c="{NS_CALDAV}">
  <d:prop>
    <d:resourcetype/>
    <d:displayname/>
    <c:supported-calendar-component-set/>
    <c:calendar-home-set/>
  </d:prop>
</d:propfind>"""

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
            _ValidatingRedirectHandler(max_redirects=MAX_REDIRECTS),
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

        # Parse the response to find calendar URLs
        calendar_urls = CalDavFetcher._parse_propfind_response(body,
                                                                urllib.parse.urlparse(url))
        if calendar_urls:
            # Return the first VEVENT-capable calendar
            for cal_url in calendar_urls:
                if "VEVENT" in cal_url.get("components", []):
                    return cal_url["href"]
            return calendar_urls[0]["href"]

        return None

    @staticmethod
    def _parse_propfind_response(xml_body: str, base_parsed: urllib.parse.ParseResult) -> list[dict[str, Any]]:
        """Minimal XML parser for PROPFIND responses.

        Extracts href, displayname, and supported calendar components
        without external XML library dependencies.
        """
        calendars: list[dict[str, Any]] = []
        # Simple tag extraction
        current = {}
        in_response = False
        in_href = False
        in_displayname = False
        in_component = False
        tag_content = ""

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

            if line.startswith("d:href") or line.startswith("href"):
                in_href = True
                tag_content = ""
                # Extract content after >
                if ">" in line:
                    tag_content = line.split(">", 1)[1]
                    if "<" in tag_content:
                        tag_content = tag_content.split("<", 1)[0]
                        in_href = False
                continue
            if (line.startswith("/d:href") or line.startswith("/href")):
                if tag_content:
                    current["href"] = tag_content
                in_href = False
                tag_content = ""
                continue

            if line.startswith("d:displayname") or line.startswith("displayname"):
                in_displayname = True
                tag_content = ""
                if ">" in line:
                    tag_content = line.split(">", 1)[1]
                    if "<" in tag_content:
                        tag_content = tag_content.split("<", 1)[0]
                        in_displayname = False
                continue
            if (line.startswith("/d:displayname") or line.startswith("/displayname")):
                if tag_content:
                    current["displayname"] = tag_content
                in_displayname = False
                tag_content = ""
                continue

            if "calendar-component" in line or "supported-calendar-component" in line:
                in_component = True
                if ">" in line:
                    comp = line.split(">", 1)[1].split("<", 1)[0].strip()
                    if comp:
                        current.setdefault("components", []).append(comp)
                continue
            if in_component and ">" in line:
                comp = line.split(">", 0)[0].strip() if ">" in line else ""
                if comp and comp[0].isalpha():
                    current.setdefault("components", []).append(comp)

            # Handle content between tags
            if in_href and ">" in line:
                content = line.split(">", 1)[1]
                if "<" in content:
                    tag_content = content.split("<", 1)[0]
                    in_href = False
                else:
                    tag_content = content
            elif in_displayname and ">" in line:
                content = line.split(">", 1)[1]
                if "<" in content:
                    tag_content = content.split("<", 1)[0]
                    in_displayname = False
                else:
                    tag_content = content

        # Resolve relative hrefs
        resolved = []
        for cal in calendars:
            href = cal.get("href", "")
            if href.startswith("/"):
                cal["href"] = f"{base_parsed.scheme}://{base_parsed.netloc}{href}"
            elif not href.startswith("http"):
                # Relative URL
                base = f"{base_parsed.scheme}://{base_parsed.netloc}"
                if base_parsed.path:
                    base_path = base_parsed.path.rstrip("/")
                    cal["href"] = f"{base}{base_path}/{href.lstrip('/')}"
                else:
                    cal["href"] = f"{base}/{href.lstrip('/')}"
            resolved.append(cal)

        return resolved

    @staticmethod
    def _looks_like_icalendar(text: str) -> bool:
        """Check if the response looks like iCalendar data."""
        return "BEGIN:VCALENDAR" in text and "END:VCALENDAR" in text

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
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED) from exc

        if parsed.scheme not in ("https", "http"):
            logger_calendar.error("Rejected calendar URL with disallowed scheme: %s", parsed.scheme)
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED)

        hostname: str | None = parsed.hostname
        if not hostname:
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED)

        try:
            resolved = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            logger_calendar.error("Cannot resolve calendar hostname %s: %s", hostname, exc)
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED) from exc

        pinned_ip: str | None = None
        for info in resolved:
            ip_str: str = cast(str, info[4][0]).split("%")[0]
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
                logger_calendar.error("Rejected calendar URL resolving to non-public address: %s", ip_str)
                raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED)
            if pinned_ip is None:
                pinned_ip = ip_str

        if pinned_ip is None:
            raise RequestException(error=err.ERROR_CALENDAR_SYNC_FAILED)
        return pinned_ip
