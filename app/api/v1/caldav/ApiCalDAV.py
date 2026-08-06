"""ApiCalDAV — CalDAV / WebDAV protocol endpoints.

Serves the CalDAV protocol (RFC 4791), WebDAV (RFC 4918) and CalDAV sync
(RFC 6578) over a raw Flask blueprint mounted at ``/caldav`` and the
``/.well-known/caldav`` discovery redirect.

Route model
-----------

A single catch-all route accepts every WebDAV method and dispatches to the
matching handler by ``request.method``:

* OPTIONS    → capability headers (DAV, Allow, MS-Author-Via)
* PROPFIND   → property discovery (Depth 0/1), multistatus response
* PROPPATCH  → calendar property updates
* MKCALENDAR → calendar collection creation
* MKCOL      → extended MKCOL calendar creation
* PUT        → create/update event resource (iCalendar body)
* GET/HEAD   → fetch event resource
* DELETE     → delete calendar collection or event resource
* REPORT     → sync-collection (RFC 6578), calendar-query, calendar-multiget,
               free-busy-query

The blueprint is registered directly on the Flask app (outside the smorest
``/api`` tree) so the CalDAV XML/iCalendar media types and WebDAV methods are
not constrained by the JSON content-type middleware.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import xml.etree.ElementTree as ET
from flask import Blueprint, Response, current_app, g, request
from werkzeug.exceptions import HTTPException

from app.module.caldav.ModuleCalDAV import (
    CALDAV_NS,
    CALENDAR_SERVER_NS,
    DAV_NS,
    MAX_SYNC_LIMIT,
    ModuleCalDAV,
)
from app.utils import errors as err
from app.utils.exceptions import RequestException

blp = Blueprint("CalDAV", __name__, url_prefix="/caldav")

# DAV capability header (RFC 4918 §18.1 + CalDAV extensions)
DAV_HEADER = "1, 2, 3, calendar-access, calendar-schedule, extended-mkcol"

# Methods we advertise on every resource
ALLOW_ALL = (
    "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, PROPPATCH, REPORT, "
    "MKCALENDAR, MKCOL"
)
ALLOW_COLLECTION = "OPTIONS, GET, HEAD, PROPFIND, PROPPATCH, REPORT, MKCALENDAR, MKCOL, DELETE"
ALLOW_EVENT = "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, REPORT"


# ---------------------------------------------------------------------------
# Module access
# ---------------------------------------------------------------------------

def _module() -> ModuleCalDAV:
    """Return the CalDAV engine bound to the Flask app (created on demand).

    Stored on the app (not ``g``) so the in-memory resource store survives
    across requests within a single server process.
    """
    module = getattr(current_app, "caldav_module", None)
    if module is None:
        module = ModuleCalDAV(base_path="/caldav")
        setattr(current_app, "caldav_module", module)
    return module  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xml(tag: str, ns: str = DAV_NS, attrib: dict | None = None, text: str | None = None) -> ET.Element:
    elem = ET.Element(f"{{{ns}}}{tag}" if ns else tag, attrib or {})
    if text is not None:
        elem.text = text
    return elem


def _multistatus() -> ET.Element:
    """<d:multistatus> root with CalDAV + calendarserver namespaces."""
    root = ET.Element(f"{{{DAV_NS}}}multistatus")
    ET.register_namespace("d", DAV_NS)
    ET.register_namespace("c", CALDAV_NS)
    ET.register_namespace("cs", CALENDAR_SERVER_NS)
    return root


def _response_block(parent: ET.Element, href: str) -> ET.Element:
    resp = _xml("response")
    resp.append(_xml("href", text=href))
    parent.append(resp)
    return resp


def _propstat(resp: ET.Element, props: list[ET.Element], status: str = "HTTP/1.1 200 OK") -> None:
    propstat = _xml("propstat")
    prop = _xml("prop")
    for p in props:
        prop.append(p)
    propstat.append(prop)
    propstat.append(_xml("status", text=status))
    resp.append(propstat)


def _prop(name: str, ns: str = DAV_NS, children: list[ET.Element] | None = None, text: str | None = None, attrib: dict | None = None) -> ET.Element:
    elem = _xml(name, ns=ns, attrib=attrib)
    if children:
        for c in children:
            elem.append(c)
    if text is not None:
        elem.text = text
    return elem


def _parse_xml(body: bytes | None) -> ET.Element | None:
    """Parse request XML safely (defusedxml), return None on empty body."""
    if not body:
        return None
    from defusedxml import ElementTree as SafeET
    try:
        return SafeET.fromstring(body)
    except Exception as exc:  # XML parse error → 400
        raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND) from exc  # reused as generic 4xx


def _rfc1123(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def _http_error_response(exc: RequestException) -> Response:
    return Response(
        f'<?xml version="1.0"?>\n<d:error xmlns:d="DAV:"><d:response>'
        f"<d:status>HTTP/1.1 {exc.http_status} {exc.error.m}</d:status>"
        f"</d:response></d:error>",
        status=exc.http_status,
        mimetype="application/xml",
    )


# ---------------------------------------------------------------------------
# PROPFIND builders
# ---------------------------------------------------------------------------

def _propfind_props(root: ET.Element) -> tuple[str, list[str]]:
    """Parse a propfind body → (mode, property list).

    mode ∈ {"allprop", "propname", "prop"}; list is empty for allprop/propname.
    """
    if root is None:
        return "allprop", []
    # find the d:propfind element (root or its child)
    propfind = root
    for child in root.iter():
        if child.tag == f"{{{DAV_NS}}}propfind":
            propfind = child
            break
    for child in propfind:
        if child.tag == f"{{{DAV_NS}}}allprop":
            return "allprop", []
        if child.tag == f"{{{DAV_NS}}}propname":
            return "propname", []
        if child.tag == f"{{{DAV_NS}}}prop":
            props = [c.tag for c in child]
            return "prop", props
    return "allprop", []


def _build_root_props() -> list[ET.Element]:
    return [
        _prop("resourcetype", children=[_prop("collection")]),
        _prop("displayname", text="SOGo 6 CalDAV"),
        _prop("current-user-principal", children=[_prop("href", text="/caldav/principals/user/")]),
    ]


def _build_principals_props(emails: list[str]) -> list[ET.Element]:
    props = [
        _prop("resourcetype", children=[_prop("collection")]),
        _prop("displayname", text="Principals"),
    ]
    for email in emails:
        props.append(
            _prop("principal-URL", children=[_prop("href", text=f"/caldav/principals/user/{email}/")])
        )
    return props


def _build_principal_props(email: str) -> list[ET.Element]:
    return [
        _prop("resourcetype", children=[_prop("principal")]),
        _prop("displayname", text=email),
        _prop("principal-URL", children=[_prop("href", text=f"/caldav/principals/user/{email}/")]),
        _prop(
            "calendar-home-set",
            ns=CALDAV_NS,
            children=[_prop("href", text=f"/caldav/calendars/{email}/")],
        ),
        _prop(
            "calendar-user-address-set",
            ns=CALDAV_NS,
            children=[_prop("href", text=f"mailto:{email}")],
        ),
        _prop(
            "calendar-user-type",
            ns=CALDAV_NS,
            children=[_prop("value", text="INDIVIDUAL")],
        ),
    ]


def _build_calendar_home_props(calendars: list[dict[str, Any]]) -> list[ET.Element]:
    props = [
        _prop("resourcetype", children=[_prop("collection")]),
        _prop("displayname", text="Calendars"),
    ]
    for cal in calendars:
        props.append(
            _prop(
                "calendar-home-set",
                ns=CALDAV_NS,
                children=[_prop("href", text=f"/caldav/calendars/{cal['user']}/{cal['name']}/")],
            )
        )
    return props


def _build_calendar_props(cal: dict[str, Any]) -> list[ET.Element]:
    return [
        _prop(
            "resourcetype",
            children=[_prop("collection"), _prop("calendar", ns=CALDAV_NS)],
        ),
        _prop("displayname", text=cal["displayname"]),
        _prop("getetag", text=cal["etag"]),
        _prop("getlastmodified", text=_rfc1123(cal["last_modified"])),
        _prop("calendar-description", ns=CALDAV_NS, text=cal.get("description") or ""),
        _prop("calendar-timezone", ns=CALDAV_NS, text=cal.get("timezone") or "UTC"),
        _prop("calendar-color", ns=CALENDAR_SERVER_NS, text=cal.get("color") or "#3B82F6"),
        _prop(
            "supported-calendar-component-set",
            ns=CALDAV_NS,
            children=[_prop("comp", ns=CALDAV_NS, attrib={"name": c}) for c in ("VEVENT", "VTODO")],
        ),
        _prop("sync-token", text=_module().sync_token(cal["user"], cal["name"])),
    ]


def _build_event_props(event, include_data: bool = False) -> list[ET.Element]:
    props = [
        _prop("getetag", text=event.etag),
        _prop("getlastmodified", text=_rfc1123(event.last_modified)),
    ]
    if include_data:
        props.append(_prop("calendar-data", ns=CALDAV_NS, text=event.ical))
    return props


# ---------------------------------------------------------------------------
# PROPFIND
# ---------------------------------------------------------------------------

def _propfind_response(resource, depth: str, mode: str, props: list[str]) -> Response:
    module = _module()
    ms = _multistatus()

    def _emit(res, props_list: list[ET.Element]) -> None:
        resp = _response_block(ms, res.href)
        _propstat(resp, props_list)

    # always answer the requested resource itself (Depth 0 / default)
    if resource.kind == "root":
        _emit(resource, _build_root_props())
    elif resource.kind == "principals":
        _emit(resource, _build_principals_props(module.list_principal_emails()))
    elif resource.kind == "principal":
        _emit(resource, _build_principal_props(resource.email))
    elif resource.kind == "calendar_home":
        _emit(resource, _build_calendar_home_props(module.list_calendars(resource.email)))
    elif resource.kind == "calendar":
        if not module.calendar_exists(resource.email, resource.calendar_name or ""):
            return _http_error_response(
                RequestException(error=err.ERROR_CALENDAR_NOT_FOUND)
            )
        cal = module.get_calendar(resource.email, resource.calendar_name or "")
        _emit(resource, _build_calendar_props(cal))
    elif resource.kind == "event":
        try:
            event = module.get_event(
                resource.email or "", resource.calendar_name or "", resource.uid or ""
            )
        except RequestException as exc:
            return _http_error_response(exc)
        _emit(resource, _build_event_props(event, include_data=True))

    # Depth: 1 — enumerate children of collections
    if depth in ("1", "infinity") and resource.is_collection:
        if resource.kind == "principals":
            for email in module.list_principal_emails():
                child = module.resolve(f"/caldav/principals/user/{email}/")
                _emit(child, _build_principal_props(email))
        elif resource.kind == "calendar_home":
            for cal in module.list_calendars(resource.email):
                child = module.resolve(
                    f"/caldav/calendars/{resource.email}/{cal['name']}/"
                )
                _emit(child, _build_calendar_props(cal))
        elif resource.kind == "calendar":
            for event in module.list_events(
                resource.email or "", resource.calendar_name or ""
            ):
                child = module.resolve(
                    f"/caldav/calendars/{resource.email}/{resource.calendar_name}/{event.uid}.ics"
                )
                _emit(child, _build_event_props(event, include_data=True))

    body = ET.tostring(ms, encoding="utf-8", xml_declaration=True)
    return Response(body, status=207, mimetype="application/xml; charset=utf-8")


# ---------------------------------------------------------------------------
# PROPPATCH / MKCALENDAR / MKCOL
# ---------------------------------------------------------------------------

def _prop_patch_request(root: ET.Element) -> dict[str, str]:
    """Extract {propname: value} from a proppatch body."""
    changes: dict[str, str] = {}
    if root is None:
        return changes
    for elem in root.iter():
        tag = elem.tag
        local = tag.rsplit("}", 1)[-1]
        if local in ("displayname", "description", "timezone", "color", "calendar-description", "calendar-timezone", "calendar-color"):
            value = elem.text or ""
            # normalize caldav-specific names to engine prop names
            if local == "calendar-description":
                local = "description"
            elif local == "calendar-timezone":
                local = "timezone"
            elif local == "calendar-color":
                local = "color"
            changes[local] = value
    return changes


def _proppatch_response(resource, changes: dict[str, str]) -> Response:
    module = _module()
    ms = _multistatus()
    resp = _response_block(ms, resource.href)
    try:
        results = module.update_calendar_props(
            resource.email or "", resource.calendar_name or "", changes
        )
    except RequestException as exc:
        return _http_error_response(exc)
    for prop, status_text in results:
        propstat = _xml("propstat")
        prop_el = _xml("prop")
        value = changes.get(prop, "")
        prop_el.append(_prop(prop, text=value if value else None))
        propstat.append(prop_el)
        propstat.append(_xml("status", text=f"HTTP/1.1 {status_text}"))
        resp.append(propstat)
    body = ET.tostring(ms, encoding="utf-8", xml_declaration=True)
    return Response(body, status=207, mimetype="application/xml; charset=utf-8")


def _mkcalendar_request(root: ET.Element) -> dict[str, str]:
    props: dict[str, str] = {}
    if root is None:
        return props
    for elem in root.iter():
        local = elem.tag.rsplit("}", 1)[-1]
        if local in ("displayname", "calendar-description", "calendar-timezone", "calendar-color"):
            value = elem.text or ""
            key = {
                "displayname": "displayname",
                "calendar-description": "description",
                "calendar-timezone": "timezone",
                "calendar-color": "color",
            }[local]
            props[key] = value
    return props


def _mkcalendar_response(resource) -> Response:
    module = _module()
    body = _parse_xml(request.get_data(cache=False) if request.get_data else None)
    props = _mkcalendar_request(body) if body is not None else {}
    try:
        etag = module.create_calendar(
            resource.email or "",
            resource.calendar_name or "",
            display_name=props.get("displayname"),
            description=props.get("description"),
            timezone=props.get("timezone"),
            color=props.get("color"),
        )
    except RequestException as exc:
        return _http_error_response(exc)
    response = Response(status=201)
    response.headers["Location"] = resource.href
    response.headers["ETag"] = etag
    return response


# ---------------------------------------------------------------------------
# REPORT handlers
# ---------------------------------------------------------------------------

def _report_sync_collection(resource, root: ET.Element) -> Response:
    module = _module()
    sync_token: str | None = None
    limit = MAX_SYNC_LIMIT
    include_data = False
    if root is not None:
        for elem in root.iter():
            local = elem.tag.rsplit("}", 1)[-1]
            if local == "sync-token" and elem.text:
                sync_token = elem.text.strip()
            elif local == "limit":
                for child in elem.iter():
                    if child.tag.rsplit("}", 1)[-1] == "nresults" and child.text:
                        try:
                            limit = min(int(child.text.strip()), MAX_SYNC_LIMIT)
                        except ValueError:
                            pass
            elif local == "calendar-data":
                include_data = True

    changed, deleted, next_token = module.sync_changes(
        resource.email or "", resource.calendar_name or "", sync_token
    )
    ms = _multistatus()
    ms.append(_xml("sync-token", text=next_token))

    # deleted resources: response with 404 status (RFC 6578 §3.2)
    for uid in deleted[:limit]:
        resp = _response_block(
            ms,
            f"/caldav/calendars/{resource.email}/{resource.calendar_name}/{uid}.ics",
        )
        _propstat(resp, [], status="HTTP/1.1 404 Not Found")

    remaining = limit - len(deleted)
    for event in changed[: max(remaining, 0)]:
        resp = _response_block(
            ms,
            f"/caldav/calendars/{resource.email}/{resource.calendar_name}/{event.uid}.ics",
        )
        _propstat(resp, _build_event_props(event, include_data=include_data))

    body = ET.tostring(ms, encoding="utf-8", xml_declaration=True)
    return Response(body, status=207, mimetype="application/xml; charset=utf-8")


def _report_calendar_query(resource, root: ET.Element) -> Response:
    """calendar-query REPORT — time-range filtered listing (RFC 4791 §7.8)."""
    module = _module()
    include_data = False
    time_range: tuple[datetime, datetime] | None = None
    if root is not None:
        for elem in root.iter():
            local = elem.tag.rsplit("}", 1)[-1]
            if local == "calendar-data":
                include_data = True
            elif local == "time-range":
                for attr_name, attr_val in elem.attrib.items():
                    if attr_name.rsplit("}", 1)[-1] == "start":
                        time_range = (datetime.fromisoformat(attr_val.replace("Z", "+00:00")), time_range[1] if time_range else None)  # type: ignore[index]
                    elif attr_name.rsplit("}", 1)[-1] == "end":
                        time_range = (time_range[0] if time_range else None, datetime.fromisoformat(attr_val.replace("Z", "+00:00")))  # type: ignore[index]

    ms = _multistatus()
    for event in module.list_events(resource.email or "", resource.calendar_name or ""):
        if time_range is not None:
            start, end = time_range
            from datetime import timedelta, timezone as _tz
            periods = module._event_periods_in_range(event, start or datetime.min.replace(tzinfo=_tz.utc), end or datetime.max.replace(tzinfo=_tz.utc))
            if not periods:
                continue
        resp = _response_block(
            ms,
            f"/caldav/calendars/{resource.email}/{resource.calendar_name}/{event.uid}.ics",
        )
        _propstat(resp, _build_event_props(event, include_data=include_data))
    body = ET.tostring(ms, encoding="utf-8", xml_declaration=True)
    return Response(body, status=207, mimetype="application/xml; charset=utf-8")


def _report_calendar_multiget(resource, root: ET.Element) -> Response:
    """calendar-multiget REPORT — fetch a batch of hrefs (RFC 4791 §7.9)."""
    module = _module()
    hrefs: list[str] = []
    if root is not None:
        for elem in root.iter():
            if elem.tag == f"{{{DAV_NS}}}href" and elem.text:
                hrefs.append(elem.text.strip())
    ms = _multistatus()
    for href in hrefs:
        uid = href.rsplit("/", 1)[-1].removesuffix(".ics")
        try:
            event = module.get_event(resource.email or "", resource.calendar_name or "", uid)
            resp = _response_block(ms, href)
            _propstat(resp, _build_event_props(event, include_data=True))
        except RequestException:
            resp = _response_block(ms, href)
            _propstat(resp, [], status="HTTP/1.1 404 Not Found")
    body = ET.tostring(ms, encoding="utf-8", xml_declaration=True)
    return Response(body, status=207, mimetype="application/xml; charset=utf-8")


def _report_free_busy(resource, root: ET.Element) -> Response:
    """free-busy-query REPORT (RFC 4791 §7.10) → iCalendar VFREEBUSY."""
    module = _module()
    start: datetime | None = None
    end: datetime | None = None
    if root is not None:
        for elem in root.iter():
            local = elem.tag.rsplit("}", 1)[-1]
            if local == "time-range":
                for attr_name, attr_val in elem.attrib.items():
                    if attr_name.rsplit("}", 1)[-1] == "start":
                        start = datetime.fromisoformat(attr_val.replace("Z", "+00:00"))
                    elif attr_name.rsplit("}", 1)[-1] == "end":
                        end = datetime.fromisoformat(attr_val.replace("Z", "+00:00"))
    if start is None or end is None:
        raise RequestException(error=err.ERROR_CALENDAR_FREEBUSY_INVALID_REQUEST)

    periods = module.free_busy_report(resource.email or "", resource.calendar_name or "", start, end)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SOGo//SOGo 6//EN",
        "BEGIN:VFREEBUSY",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
    ]
    for period in periods:
        lines.append(
            f"FREEBUSY;FBTYPE=BUSY:{period['start'].replace('-', '').replace(':', '').replace('+00:00', 'Z')}/{period['end'].replace('-', '').replace(':', '').replace('+00:00', 'Z')}"
        )
    lines.append("END:VFREEBUSY")
    lines.append("END:VCALENDAR")
    return Response("\r\n".join(lines) + "\r\n", status=200, mimetype="text/calendar; charset=utf-8")


# ---------------------------------------------------------------------------
# Route (catch-all dispatcher)
# ---------------------------------------------------------------------------

@blp.route("/", methods=["OPTIONS", "PROPFIND", "REPORT", "PROPPATCH", "MKCALENDAR", "MKCOL", "GET", "PUT", "DELETE", "HEAD"])
@blp.route("/<path:resource_path>", methods=["OPTIONS", "PROPFIND", "REPORT", "PROPPATCH", "MKCALENDAR", "MKCOL", "GET", "PUT", "DELETE", "HEAD"])
def caldav_dispatch(resource_path: str = "") -> Response:
    """Catch-all CalDAV endpoint dispatching by HTTP method."""
    path = request.path
    module = _module()
    try:
        resource = module.resolve(path)
    except RequestException as exc:
        return _http_error_response(exc)

    method = request.method

    # OPTIONS — capability discovery
    if method == "OPTIONS":
        response = Response(status=200)
        response.headers["DAV"] = DAV_HEADER
        response.headers["Allow"] = ALLOW_ALL
        response.headers["MS-Author-Via"] = "DAV"
        response.headers["Content-Length"] = "0"
        return response

    # HEAD / GET — event retrieval
    if method in ("GET", "HEAD"):
        if resource.kind != "event":
            # collection GET → 200 (empty body, or redirect to web UI)
            response = Response(status=200)
            response.headers["DAV"] = DAV_HEADER
            response.headers["Allow"] = ALLOW_COLLECTION
            return response
        try:
            event = module.get_event(resource.email or "", resource.calendar_name or "", resource.uid or "")
        except RequestException as exc:
            return _http_error_response(exc)
        body = event.ical.encode("utf-8")
        response = Response(body if method == "GET" else b"", status=200)
        response.headers["Content-Type"] = "text/calendar; charset=utf-8"
        response.headers["ETag"] = event.etag
        response.headers["Last-Modified"] = _rfc1123(event.last_modified)
        return response

    # PUT — event create/update
    if method == "PUT":
        if resource.kind != "event":
            return _http_error_response(
                RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
            )
        body = request.get_data(cache=False)
        if_match = request.headers.get("If-Match")
        if_none_match = request.headers.get("If-None-Match")
        try:
            etag, created = module.put_event(
                resource.email or "",
                resource.calendar_name or "",
                resource.uid or "",
                body.decode("utf-8", errors="replace"),
                if_match=if_match,
                if_none_match=if_none_match,
            )
        except RequestException as exc:
            return _http_error_response(exc)
        response = Response(status=201 if created else 204)
        response.headers["ETag"] = etag
        response.headers["Last-Modified"] = _rfc1123(module._now_utc())
        return response

    # DELETE — calendar or event
    if method == "DELETE":
        if_match = request.headers.get("If-Match")
        try:
            if resource.kind == "event":
                module.delete_event(
                    resource.email or "",
                    resource.calendar_name or "",
                    resource.uid or "",
                    if_match=if_match,
                )
            elif resource.kind == "calendar":
                module.delete_calendar(resource.email or "", resource.calendar_name or "")
            else:
                return _http_error_response(
                    RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
                )
        except RequestException as exc:
            return _http_error_response(exc)
        return Response(status=204)

    # MKCALENDAR / MKCOL — calendar creation
    if method in ("MKCALENDAR", "MKCOL"):
        if resource.kind != "calendar":
            return _http_error_response(
                RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
            )
        return _mkcalendar_response(resource)

    # PROPFIND — property discovery
    if method == "PROPFIND":
        body = _parse_xml(request.get_data(cache=False))
        mode, props = _propfind_props(body)
        depth = request.headers.get("Depth", "0")
        return _propfind_response(resource, depth, mode, props)

    # PROPPATCH — property updates
    if method == "PROPPATCH":
        if resource.kind != "calendar":
            return _http_error_response(
                RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
            )
        body = _parse_xml(request.get_data(cache=False))
        changes = _prop_patch_request(body) if body is not None else {}
        return _proppatch_response(resource, changes)

    # REPORT — sync / query / multiget / free-busy
    if method == "REPORT":
        body = _parse_xml(request.get_data(cache=False))
        report_name = ""
        if body is not None:
            report_name = body.tag.rsplit("}", 1)[-1]
        try:
            if report_name == "sync-collection":
                return _report_sync_collection(resource, body)
            if report_name == "calendar-query":
                return _report_calendar_query(resource, body)
            if report_name == "calendar-multiget":
                return _report_calendar_multiget(resource, body)
            if report_name == "free-busy-query":
                return _report_free_busy(resource, body)
            return _http_error_response(
                RequestException(error=err.ERROR_CALDAV_REPORT_UNSUPPORTED)
            )
        except RequestException as exc:
            return _http_error_response(exc)
        except HTTPException:
            raise

    return _http_error_response(RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND))
