from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api.v1 import auth, datasets, incidents, lineage, models, ops, rules
from app.core.config import get_settings
from app.core.errors import install_handlers
from app.core.logging import configure_logging

log = logging.getLogger("datasentry.api")
API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    for problem in settings.check_production_safety():
        log.error("configuration problem: %s", problem)
        if settings.is_production:
            raise RuntimeError(problem)
    stop = threading.Event()
    if settings.scheduler_mode == "embedded" and settings.environment != "test":
        from app.services.jobs import worker_loop

        threading.Thread(target=worker_loop, args=(stop,), name="scheduler", daemon=True).start()
    yield
    stop.set()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DataSentry API",
        version="0.1.0",
        description="Data quality, drift, lineage impact and safe remediation. Authenticate with `Authorization: Bearer <token>` "
                    "(from /auth/login or /auth/demo) or `X-API-Key: dsk_…`.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    install_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_request_mb * 1024 * 1024:
            return JSONResponse({"error": {"code": "payload_too_large", "message":
                                           f"Request body exceeds {settings.max_request_mb} MB.", "request_id": rid}},
                                status_code=413)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith(API_PREFIX):
            log.info("%s %s %s %.0fms rid=%s", request.method, request.url.path, response.status_code,
                     (time.perf_counter() - started) * 1000, rid)
        return response

    for r in (auth.router, datasets.router, rules.router, models.router, lineage.router, incidents.router, ops.router):
        app.include_router(r, prefix=API_PREFIX)
    app.add_api_route("/health", ops.health, include_in_schema=False)

    static = Path(settings.static_dir) if settings.static_dir else None
    if static and (static / "index.html").exists():
        root = static.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"error": {"code": "not_found", "message": "Not found"}}, status_code=404)
            candidate = (root / path).resolve()
            if path and root in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(root / "index.html")

    return app


app = create_app()
