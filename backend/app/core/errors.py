from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("datasentry.errors")


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def not_found(entity: str, entity_id: Any = None) -> APIError:
    return APIError(404, "not_found", f"{entity} {entity_id if entity_id is not None else ''} not found".replace("  ", " "))


def conflict(message: str, details: Any = None) -> APIError:
    return APIError(409, "conflict", message, details)


def bad_request(message: str, details: Any = None, code: str = "bad_request") -> APIError:
    return APIError(400, code, message, details)


def forbidden(message: str = "You do not have permission to perform this action.") -> APIError:
    return APIError(403, "forbidden", message)


def _body(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details,
                      "request_id": getattr(request.state, "request_id", None)}}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(_body(request, exc.code, exc.message, exc.details), status_code=exc.status)

    from datasentry_core.io import IngestionError

    @app.exception_handler(IngestionError)
    async def _ingest(request: Request, exc: IngestionError) -> JSONResponse:
        return JSONResponse(_body(request, exc.code, str(exc), exc.details or None), status_code=400)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "message": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(_body(request, "validation_error", "Request validation failed.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
                413: "payload_too_large", 429: "rate_limited"}.get(exc.status_code, "http_error")
        return JSONResponse(_body(request, code, str(exc.detail)), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error request_id=%s path=%s", getattr(request.state, "request_id", None), request.url.path)
        return JSONResponse(_body(request, "internal_error", "An unexpected error occurred. It has been logged."), status_code=500)
