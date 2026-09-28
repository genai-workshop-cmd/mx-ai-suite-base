"""FastAPI application hosting the control surface.

Serves a single-page front end from `ui/static` plus the JSON API. No build
step, no npm, no framework - the blueprint asks for a clean control surface,
not a full-stack SPA.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from core import config  # noqa: E402
from core.errors import SuiteError  # noqa: E402
from core.logging import get, setup  # noqa: E402
from ui.api import ROUTERS  # noqa: E402

log = get("suite.ui")

STATIC = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    cfg = config.load()
    setup(cfg.log_level)

    app = FastAPI(
        title=cfg.project_name,
        version=cfg.version,
        description="AI-assisted IBM Maximo delivery: design, build, test, deploy.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    for router in ROUTERS:
        app.include_router(router)

    @app.exception_handler(SuiteError)
    async def suite_error_handler(request: Request, exc: SuiteError) -> JSONResponse:
        log.warning("%s on %s: %s", exc.code, request.url.path, exc.message)
        return JSONResponse(status_code=400, content=exc.as_dict())

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "code": "UNEXPECTED",
                "message": str(exc),
                "remedy": "See the server console for the traceback.",
            },
        )

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        icon = STATIC / "favicon.svg"
        return FileResponse(icon if icon.exists() else STATIC / "index.html")

    log.info("%s v%s ready", cfg.project_name, cfg.version)
    return app


app = create_app()
