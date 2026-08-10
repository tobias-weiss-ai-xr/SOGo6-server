from typing import Any

from http import HTTPStatus
from marshmallow import Schema, fields

from app.utils.errors import E, ERROR_NO_ERROR

class ApiBaseResponse(Schema):
    """
    Basic response for api
    """
    data : fields.Field = fields.Field(required=True, allow_none=True)
    error_msg = fields.String(required=True)
    error_code = fields.String(required=True)

#def create_api_base_response(data: Any|None = None, error: E = ERROR_NO_ERROR, code: int = 0) -> tuple[dict, int]:

def create_api_base_response(data: Any|None = None, error: E = ERROR_NO_ERROR, code: int = 0, error_code: str | None = None, error_msg: str | None = None, success: bool | None = None, status_code: int | None = None) -> tuple[dict, int]:
    """
    Create the common API response.

    Two conventions are used across the codebase and both are supported:

    * legacy: ``error`` (an ``E`` error object) plus optional ``code``;
      takes ``error.c`` / ``error.m`` for the body fields.
    * new-style (e.g. ``error_code="E000003"``): ``error_code`` with
      ``error_msg`` and optionally ``success`` / ``status_code``.

    Status resolution (first match wins): ``status_code``, ``code``,
    ``success=False`` → 400, else ``error.h``.

    :param error_code: explicit error code string (new-style)
    :type error_code: str, optional
    :param error_msg: explicit error message (new-style)
    :type error_msg: str, optional
    :param success: include a ``success`` bool in the body; ``False`` maps to
        400 when no other status is given
    :type success: bool, optional
    :param status_code: explicit HTTP status
    :type status_code: int, optional
    :return: the common response
    :rtype: tuple[dict, int]
    """
    out_error_code = error_code if error_code is not None else error.c
    out_error_msg = error_msg if error_msg is not None else error.m

    if status_code is not None:
        status = status_code
    elif code:
        status = code
    elif success is False:
        status = HTTPStatus.BAD_REQUEST
    else:
        status = error.h

    payload = {
        "data": data,
        "error_code": out_error_code,
        "error_msg": out_error_msg,
    }
    if success is not None:
        payload["success"] = success
    return payload, status
