"""RFC 9116 security.txt endpoint (CRA Art. 14(2) — coordinated disclosure).

Serves the machine-readable vulnerability disclosure policy at both
``/.well-known/security.txt`` (on the API host) and ``/security.txt``.
"""

from __future__ import annotations

from flask import Response
from flask.views import MethodView
from flask_smorest import Blueprint

blp = Blueprint("SecurityTxt", __name__)
blp.public_access = True  # type: ignore[attr-defined]

SECURITY_TXT = """# CRA Art. 14(2) — Coordinated vulnerability disclosure (RFC 9116)
# See SECURITY.md in the repository root for the full policy.

Contact: https://github.com/tobias-weiss-ai-xr/SOGo6-dockerized/security/advisories/new
Expires: 2027-12-31T23:59:59Z
Preferred-Languages: en, de
Policy: https://github.com/tobias-weiss-ai-xr/SOGo6-dockerized/blob/main/SECURITY.md
"""


class SecurityTxtResource(MethodView):
    """Serve the security.txt content."""

    public_access = True  # type: ignore[attr-defined]


    def get(self) -> Response:
        return Response(
            SECURITY_TXT,
            status=200,
            mimetype="text/plain",
            headers={"Cache-Control": "no-store"},
        )


blp.add_url_rule("/.well-known/security.txt", view_func=SecurityTxtResource.as_view("security_txt"))
blp.add_url_rule("/security.txt", view_func=SecurityTxtResource.as_view("security_txt_alt"))
