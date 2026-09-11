"""ApiCardDAV — CardDAV / WebDAV protocol endpoints.

Serves the CardDAV protocol (RFC 6352) and WebDAV (RFC 4918) over a raw Flask
blueprint mounted at /carddav and the /.well-known/carddav discovery redirect.

Route model:
------------

A single catch-all route accepts every WebDAV method and dispatches to the
matching handler by request.method:

* OPTIONS    → capability headers (DAV, Allow, MS-Author-Via)
* PROPFIND   → property discovery (Depth 0/1), multistatus response
* PROPPATCH  → addressbook property updates
* MKCOL      → addressbook collection creation
* PUT        → create/update contact resource (vCard body)
* GET/HEAD   → fetch contact resource
* DELETE     → delete addressbook collection or contact resource
* REPORT     → addressbook-query, addressbook-multiget
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import xml.etree.ElementTree as ET
from flask import Blueprint, Response, current_app, g, request
from werkzeug.exceptions import HTTPException

from app.module.carddav.ModuleCardDAV import (
    CARDDAV_NS,
    DAV_NS,
    ModuleCardDAV,
)
from app.utils import errors as err
from app.utils.exceptions import RequestException

# Apache DAV properties namespace
APACHE_DAV_PROPS_NS = "http://apache.org/dav/props/"

blp = Blueprint("CardDAV", __name__, url_prefix="/carddav")

# DAV capability header (RFC 4918 + CardDAV extensions)
DAV_HEADER = "1, 3, addressbook"

# Methods we advertise on every resource
ALLOW_ALL = (
    "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, PROPPATCH, REPORT, MKCOL"
)
ALLOW_COLLECTION = "OPTIONS, GET, HEAD, PROPFIND, PROPPATCH, REPORT, MKCOL, DELETE"
ALLOW_CONTACT = "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, REPORT"


# ---------------------------------------------------------------------------
# Module access
# ---------------------------------------------------------------------------

def _module() -> ModuleCardDAV:
    """Return the CardDAV engine bound to the Flask app."""
    module = getattr(current_app, "carddav_module", None)
    if module is None:
        module = ModuleCardDAV(base_path="/carddav")
        setattr(current_app, "carddav_module", module)
    return module  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Auth — Basic auth via the same LDAP infrastructure as the REST API
# ---------------------------------------------------------------------------

# Cached InterfaceAuthUser instance (lazy, per-process)
_carddav_auth = None


@blp.before_request
def _carddav_require_auth() -> Response | None:
    """Require Basic auth on all CardDAV endpoints."""
    if request.method == "OPTIONS":
        return None
    auth = request.authorization
    if not auth or auth.type != "basic":
        return Response(
            "Authentication required\n",
            401,
            {"WWW-Authenticate": 'Basic realm="SOGo CardDAV"'},
        )
    global _carddav_auth
    if _carddav_auth is None:
        try:
            from app.config.settings.ProcessSetting import process_config
            from app.config.init_config import init_get_system_and_default_domain_settings
            from app.interface.auth.InterfaceAuthUser import InterfaceAuthUser
            system, default_domain = init_get_system_and_default_domain_settings()
            _carddav_auth = InterfaceAuthUser(process_config, system, default_domain)
        except Exception:
            return Response(
                "Authentication required\n",
                401,
                {"WWW-Authenticate": 'Basic realm="SOGo CardDAV"'},
            )
    try:
        success, user, _ = _carddav_auth._check_login(auth.username, auth.password)
    except Exception:
        success = False
        user = None
    if not success or user is None:
        return Response(
            "Invalid credentials\n",
            401,
            {"WWW-Authenticate": 'Basic realm="SOGo CardDAV"'},
        )
    g.carddav_user = user
    _module().register_user(user.mail or auth.username, user.cn or auth.username)
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xml(tag: str, ns: str = DAV_NS, attrib: dict | None = None, text: str | None = None) -> ET.Element:
    elem = ET.Element(f"{{{ns}}}{tag}" if ns else tag, attrib or {})
    if text is not None:
        elem.text = text
    return elem


def _multistatus() -> ET.Element:
    """<D:multistatus> root with DAV + Apache DAV + CardDAV namespaces."""
    root = ET.Element(f"{{{DAV_NS}}}multistatus")
    ET.register_namespace("D", DAV_NS)
    ET.register_namespace("ap", APACHE_DAV_PROPS_NS)
    ET.register_namespace("card", CARDDAV_NS)
    return root


def _serialize_xml(root: ET.Element) -> bytes:
    """Serialize XML matching SOGo5 format."""
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    body = body.replace(b"<?xml version='1.0' encoding='utf-8'?>", b'<?xml version="1.0" encoding="utf-8"?>')
    body = body.replace(b" />", b"/>")
    return body


def _response_block(parent: ET.Element, href: str) -> ET.Element:
    resp = _xml("response")
    resp.append(_xml("href", text=href))
    parent.append(resp)
    return resp


def _propstat(resp: ET.Element, props: list[ET.Element], status: str = "HTTP/1.1 200 OK") -> None:
    propstat = _xml("propstat")
    propstat.append(_xml("status", text=status))
    prop = _xml("prop")
    for p in props:
        prop.append(p)
    propstat.append(prop)
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
    """Parse request XML safely."""
    if not body:
        return None
    from defusedxml import ElementTree as SafeET
    try:
        return SafeET.fromstring(body)
    except Exception:
        raise RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)


def _rfc1123(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


def _http_error_response(exc: RequestException) -> Response:
    return Response(
        f'<?xml version="1.0"?>\n<D:error xmlns:D="DAV:"><D:response>'
        f"<D:status>HTTP/1.1 {exc.http_status} {exc.error.m}</D:status>"
        f"</D:response></D:error>",
        status=exc.http_status,
        mimetype="application/xml",
    )


# ---------------------------------------------------------------------------
# PROPFIND builders
# ---------------------------------------------------------------------------

def _propfind_props(root: ET.Element) -> tuple[str, list[str]]:
    """Parse a propfind body → (mode, property list)."""
    if root is None:
        return "allprop", []
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


def _build_root_props(resource) -> list[ET.Element]:
    """Root collection properties."""
    return [
        _prop("getlastmodified", text=_rfc1123(datetime.now(timezone.utc))),
        _prop("resourcetype", children=[_prop("collection")]),
        _prop("getcontenttype", text="text/html"),
        _prop("displayname", text="SOGo"),
        _prop("href", text=resource.href),
        _prop("executable", ns=APACHE_DAV_PROPS_NS, text="0"),
    ]


def _build_principals_props(emails: list[str]) -> list[ET.Element]:
    props = [
        _prop("resourcetype", children=[_prop("collection")]),
        _prop("displayname", text="Principals"),
    ]
    for email in emails:
        props.append(
            _prop("principal-URL", children=[_prop("href", text=f"/carddav/principals/user/{email}/")])
        )
    return props


def _build_principal_props(email: str, resource=None) -> list[ET.Element]:
    """User principal properties."""
    displayname = email
    try:
        if hasattr(g, "carddav_user") and g.carddav_user and g.carddav_user.cn:
            displayname = g.carddav_user.cn
    except RuntimeError:
        pass
    href = resource.href if resource else f"/carddav/principals/user/{email}/"
    return [
        _prop("getlastmodified", text=_rfc1123(datetime.now(timezone.utc))),
        _prop("getetag", text='"None"'),
        _prop("resourcetype", children=[_prop("collection"), _prop("principal")]),
        _prop("getcontenttype", text="httpd/unix-directory"),
        _prop("displayname", text=displayname),
        _prop("href", text=href),
        _prop("executable", ns=APACHE_DAV_PROPS_NS, text="0"),
    ]


def _build_collection_props(resource) -> list[ET.Element]:
    """Properties for a sub-collection listed on Depth 1."""
    displayname = "Principals" if resource.kind == "principals" else "Address Books"
    return [
        _prop("getlastmodified", text=_rfc1123(datetime.now(timezone.utc))),
        _prop("getetag", text='"None"'),
        _prop("resourcetype", children=[_prop("collection")]),
        _prop("getcontenttype", text="httpd/unix-directory"),
        _prop("displayname", text=displayname),
        _prop("href", text=resource.href),
        _prop("executable", ns=APACHE_DAV_PROPS_NS, text="0"),
    ]


def _build_addressbook_home_props(addressbooks: list[dict[str, Any]]) -> list[ET.Element]:
    """Addressbook home collection properties."""
    props = [
        _prop("resourcetype", children=[_prop("collection")]),
        _prop("displayname", text="Address Books"),
    ]
    for ab in addressbooks:
        props.append(
            _prop(
                "addressbook-home-set",
                ns=CARDDAV_NS,
                children=[_prop("href", text=f"/carddav/addressbooks/{ab['email']}/")],
            )
        )
        props.append(
            _prop(
                "supported-report-component-set",
                ns=CARDDAV_NS,
                children=[_prop("supported-report", ns=CARDDAV_NS, children=[_prop("report", ns=CARDDAV_NS, attrib={"name": "addressbook"})])],
            )
        )
    return props


def _build_addressbook_props(ab: dict[str, Any]) -> list[ET.Element]:
    """Addressbook collection properties."""
    return [
        _prop(
            "resourcetype",
            children=[_prop("collection"), _prop("addressbook", ns=CARDDAV_NS)],
        ),
        _prop("displayname", text=ab["displayname"]),
        _prop("getetag", text=ab["etag"]),
        _prop("getlastmodified", text=_rfc1123(ab["last_modified"])),
        _prop("description", ns=CARDDAV_NS, text=ab.get("description") or ""),
        _prop(
            "supported-report-component-set",
            ns=CARDDAV_NS,
            children=[_prop("supported-report", ns=CARDDAV_NS, children=[_prop("report", ns=CARDDAV_NS, attrib={"name": "addressbook"})])],
        ),
        _prop("getcontenttype", text="text/vcard"),
    ]


def _build_contact_props(contact: dict[str, Any], include_data: bool = False) -> list[ET.Element]:
    """Contact resource properties."""
    props = [
        _prop("getetag", text=contact["etag"]),
        _prop("getlastmodified", text=_rfc1123(contact["last_modified"])),
        _prop("getsize", text=str(len(contact["vcard"].encode("utf-8")))),
    ]
    if include_data:
        props.append(_prop("address-data", ns=CARDDAV_NS, text=contact["vcard"]))
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

    # Always answer the requested resource itself
    if resource.kind == "root":
        _emit(resource, _build_root_props(resource))
    elif resource.kind == "principals":
        _emit(resource, _build_principals_props(module.list_principal_emails()))
    elif resource.kind == "principal":
        _emit(resource, _build_principal_props(resource.email, resource))
    elif resource.kind == "addressbook_home":
        _emit(resource, _build_addressbook_home_props(module.list_addressbooks(resource.email)))
    elif resource.kind == "addressbook":
        if not module.addressbook_exists(resource.email, resource.addressbook_name or ""):
            return _http_error_response(
                RequestException(error=err.ERROR_CALENDAR_NOT_FOUND)
            )
        ab = module.get_addressbook(resource.email, resource.addressbook_name or "")
        _emit(resource, _build_addressbook_props(ab))
    elif resource.kind == "contact":
        try:
            contact = module.get_contact(
                resource.email or "", resource.addressbook_name or "", resource.uid or ""
            )
        except RequestException as exc:
            return _http_error_response(exc)
        _emit(resource, _build_contact_props(contact, include_data=True))

    # Depth: 1 — enumerate children of collections
    if depth in ("1", "infinity") and resource.is_collection:
        if resource.kind == "root":
            for child_path in ("/carddav/principals/", "/carddav/addressbooks/"):
                child = module.resolve(child_path)
                _emit(child, _build_collection_props(child))
        elif resource.kind == "principals":
            for email in module.list_principal_emails():
                child = module.resolve(f"/carddav/principals/user/{email}/")
                _emit(child, _build_principal_props(email, child))
        elif resource.kind == "addressbook_home":
            for ab in module.list_addressbooks(resource.email):
                child = module.resolve(
                    f"/carddav/addressbooks/{resource.email}/{ab['name']}/"
                )
                _emit(child, _build_addressbook_props(ab))
        elif resource.kind == "addressbook":
            for contact in module.list_contacts(
                resource.email or "", resource.addressbook_name or ""
            ):
                child = module.resolve(
                    f"/carddav/addressbooks/{resource.email}/{resource.addressbook_name}/{contact['uid']}.vcf"
                )
                _emit(child, _build_contact_props(contact, include_data=True))

    body = _serialize_xml(ms)
    return Response(body, status=207, mimetype="application/xml; charset=utf-8")


# ---------------------------------------------------------------------------
# PROPPATCH / MKCOL
# ---------------------------------------------------------------------------

def _prop_patch_request(root: ET.Element) -> dict[str, str]:
    """Extract {propname: value} from a proppatch body."""
    changes: dict[str, str] = {}
    if root is None:
        return changes
    for elem in root.iter():
        tag = elem.tag
        local = tag.rsplit("}", 1)[-1]
        if local in ("displayname", "description"):
            value = elem.text or ""
            changes[local] = value
    return changes


def _proppatch_response(resource, changes: dict[str, str]) -> Response:
    module = _module()
    ms = _multistatus()
    resp = _response_block(ms, resource.href)
    try:
        results = module.update_addressbook_props(
            resource.email or "", resource.addressbook_name or "", changes
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
    body = _serialize_xml(ms)
    return Response(body, status=207, mimetype="application/xml; charset=utf-8")


def _mkcol_request(root: ET.Element) -> dict[str, str]:
    """Extract properties from MKCOL body."""
    props: dict[str, str] = {}
    if root is None:
        return props
    for elem in root.iter():
        local = elem.tag.rsplit("}", 1)[-1]
        if local in ("displayname", "description"):
            props[local] = elem.text or ""
    return props


def _mkcol_response(resource) -> Response:
    module = _module()
    body = _parse_xml(request.get_data(cache=False) if request.get_data else None)
    props = _mkcol_request(body) if body is not None else {}
    try:
        etag = module.create_addressbook(
            resource.email or "",
            resource.addressbook_name or "",
            displayname=props.get("displayname"),
            description=props.get("description"),
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

def _report_addressbook_query(resource, root: ET.Element) -> Response:
    """addressbook-query REPORT — filter contacts."""
    module = _module()
    include_data = False
    if root is not None:
        for elem in root.iter():
            local = elem.tag.rsplit("}", 1)[-1]
            if local == "address-data":
                include_data = True

    ms = _multistatus()
    for contact in module.list_contacts(resource.email or "", resource.addressbook_name or ""):
        resp = _response_block(
            ms,
            f"/carddav/addressbooks/{resource.email}/{resource.addressbook_name}/{contact['uid']}.vcf",
        )
        _propstat(resp, _build_contact_props(contact, include_data=include_data))

    body = _serialize_xml(ms)
    return Response(body, status=207, mimetype="application/xml; charset=utf-8")


def _report_addressbook_multiget(resource, root: ET.Element) -> Response:
    """addressbook-multiget REPORT — fetch a batch of hrefs."""
    module = _module()
    hrefs: list[str] = []
    if root is not None:
        for elem in root.iter():
            if elem.tag == f"{{{DAV_NS}}}href" and elem.text:
                hrefs.append(elem.text.strip())
    ms = _multistatus()
    for href in hrefs:
        # Extract uid from href
        parts = href.rstrip("/").rsplit("/", 1)
        uid = parts[-1].removesuffix(".vcf") if ".vcf" in parts[-1] else parts[-1]
        try:
            contact = module.get_contact(resource.email or "", resource.addressbook_name or "", uid)
            resp = _response_block(ms, href)
            _propstat(resp, _build_contact_props(contact, include_data=True))
        except RequestException:
            resp = _response_block(ms, href)
            _propstat(resp, [], status="HTTP/1.1 404 Not Found")
    body = _serialize_xml(ms)
    return Response(body, status=207, mimetype="application/xml; charset=utf-8")


# ---------------------------------------------------------------------------
# Route (catch-all dispatcher)
# ---------------------------------------------------------------------------

@blp.route("/", methods=["OPTIONS", "PROPFIND", "REPORT", "PROPPATCH", "MKCOL", "GET", "PUT", "DELETE", "HEAD"])
@blp.route("/<path:resource_path>", methods=["OPTIONS", "PROPFIND", "REPORT", "PROPPATCH", "MKCOL", "GET", "PUT", "DELETE", "HEAD"])
def carddav_dispatch(resource_path: str = "") -> Response:
    """Catch-all CardDAV endpoint dispatching by HTTP method."""
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

    # HEAD / GET — contact retrieval
    if method in ("GET", "HEAD"):
        if resource.kind != "contact":
            response = Response(status=200)
            response.headers["DAV"] = DAV_HEADER
            response.headers["Allow"] = ALLOW_COLLECTION
            return response
        try:
            contact = module.get_contact(resource.email or "", resource.addressbook_name or "", resource.uid or "")
        except RequestException as exc:
            return _http_error_response(exc)
        body = contact["vcard"].encode("utf-8")
        response = Response(body if method == "GET" else b"", status=200)
        response.headers["Content-Type"] = "text/vcard; charset=utf-8"
        response.headers["ETag"] = contact["etag"]
        response.headers["Last-Modified"] = _rfc1123(contact["last_modified"])
        return response

    # PUT — contact create/update
    if method == "PUT":
        if resource.kind != "contact":
            return _http_error_response(
                RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
            )
        body = request.get_data(cache=False)
        if_match = request.headers.get("If-Match")
        if_none_match = request.headers.get("If-None-Match")
        try:
            etag, created = module.put_contact(
                resource.email or "",
                resource.addressbook_name or "",
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

    # DELETE — addressbook or contact
    if method == "DELETE":
        if_match = request.headers.get("If-Match")
        try:
            if resource.kind == "contact":
                module.delete_contact(
                    resource.email or "",
                    resource.addressbook_name or "",
                    resource.uid or "",
                    if_match=if_match,
                )
            elif resource.kind == "addressbook":
                module.delete_addressbook(resource.email or "", resource.addressbook_name or "")
            else:
                return _http_error_response(
                    RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
                )
        except RequestException as exc:
            return _http_error_response(exc)
        return Response(status=204)

    # MKCOL — addressbook creation
    if method == "MKCOL":
        if resource.kind != "addressbook":
            return _http_error_response(
                RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
            )
        return _mkcol_response(resource)

    # PROPFIND — property discovery
    if method == "PROPFIND":
        body = _parse_xml(request.get_data(cache=False))
        mode, props = _propfind_props(body)
        depth = request.headers.get("Depth", "0")
        return _propfind_response(resource, depth, mode, props)

    # PROPPATCH — property updates
    if method == "PROPPATCH":
        if resource.kind != "addressbook":
            return _http_error_response(
                RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND)
            )
        body = _parse_xml(request.get_data(cache=False))
        changes = _prop_patch_request(body) if body is not None else {}
        return _proppatch_response(resource, changes)

    # REPORT — query / multiget
    if method == "REPORT":
        body = _parse_xml(request.get_data(cache=False))
        report_name = ""
        if body is not None:
            report_name = body.tag.rsplit("}", 1)[-1]
        try:
            if report_name == "addressbook-query":
                return _report_addressbook_query(resource, body)
            if report_name == "addressbook-multiget":
                return _report_addressbook_multiget(resource, body)
            return _http_error_response(
                RequestException(error=err.ERROR_CALDAV_REPORT_UNSUPPORTED)
            )
        except RequestException as exc:
            return _http_error_response(exc)
        except HTTPException:
            raise

    return _http_error_response(RequestException(error=err.ERROR_CALDAV_PATH_NOT_FOUND))
