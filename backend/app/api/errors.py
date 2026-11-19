"""Shared HTTP error mapping that adds machine-readable codes.

The response body keeps the legacy ``detail`` string (so existing clients keep
working) and adds a ``code`` field, e.g.::

    {"detail": "No analysis results found for this project.", "code": "analysis_not_found"}
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.errors import ProjectError


class CodedHTTPException(HTTPException):
    def __init__(self, status_code: int, detail: str, code: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def http_error(exc: ProjectError) -> CodedHTTPException:
    return CodedHTTPException(exc.status_code, exc.message, exc.code)


async def coded_http_exception_handler(
    _request: Request, exc: CodedHTTPException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=getattr(exc, "headers", None),
    )
