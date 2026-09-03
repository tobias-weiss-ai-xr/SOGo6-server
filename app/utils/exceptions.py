"""
List of sogo server expetions

SOGo server, being an API, should never raise any exceptions. Instead, it should handles them and
give a proper response to the client's API.
"""

from app.utils.errors import E, ERROR_UNKOWN

class SogoException(Exception):
    """
    Sogo exception with the error
    """
    def __init__(self, message: str = "", error: E = ERROR_UNKOWN,
                 m: str | None = None, error_msg: str | None = None,
                 http_status: int | None = None) -> None:
        # ``message`` is the canonical kwarg; ``m``/``error_msg`` are accepted as
        # historical aliases so every call convention used across the codebase
        # works (several callers pass ``m=...``/``error_msg=...``).
        if not message and m is not None:
            message = m
        if not message and error_msg is not None:
            message = error_msg
        if not message and error is not None:
            message = error.m
        super().__init__(message)
        self.error = error
        # An explicit ``http_status`` overrides the error's own HTTP status so
        # callers can re-purpose a shared error code (e.g. report a 403 while
        # reusing a NOT_FOUND code). Defaults to the error's status.
        self.http_status = http_status if http_status is not None else (error.h if error is not None else ERROR_UNKOWN.h)

    def err(self) -> str:
        """
        Return the code error of this Exception
        """
        return self.error.c

class AggravatedException(SogoException):
    """
    Exception serious enough to stop all operations.

    Example: SOGo can't reach its own database, making him useless.
    Meaning: Something is wrong with process_settings or the database itself
    Remediation: An admin should check the error and the conf
    """

class RequestException(SogoException):
    """
    Exception during a request, mostly unexpected but SOGo can continue to welcome other requests

    Example: Attempting to import an event wich malformed icalender format
    Meaning: Something was wrong with the file, but sogo is still operationnal
    Remediation: An admin should check the log, the input and may report a bug on github if necessary.
    """



class BugException(SogoException):
    """
    Those exceptions should never happen, but as still here in case of bug

    Example: A function was expected a string and got an integger instead.
    Meaning: SOGo miss some robustness 
    Remediation: An admin should report those on github 
    """
