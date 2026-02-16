"""FastAPI application factory and entry point.

Creates the application instance, registers all middleware, mounts route
routers (including FastAPI-Users auth routers), and configures the Jinja2
template engine.

Usage::

    # Development server (from project root)
    uvicorn issue_observatory.api.main:app --reload

    # Production (via Docker / Gunicorn + Uvicorn workers)
    gunicorn issue_observatory.api.main:app -k uvicorn.workers.UvicornWorker
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from issue_observatory.config.settings import get_settings
from issue_observatory.core.logging_config import configure_logging, request_id_var

# ---------------------------------------------------------------------------
# Logging configuration — applied once at module import time so that log
# records emitted during app construction are captured correctly.
# The log level is re-applied inside create_app() after settings are loaded.
# ---------------------------------------------------------------------------

configure_logging("INFO")

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_PACKAGE_DIR = Path(__file__).parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Separated from the module-level ``app`` singleton so that tests can
    call ``create_app()`` with a patched settings environment before the
    singleton is created.

    Returns:
        A fully configured ``FastAPI`` instance.
    """
    settings = get_settings()

    # Re-apply logging configuration with the correct level from settings.
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        description=(
            "A modular platform for systematic collection and analysis of "
            "public discourse across digital media arenas."
        ),
        version="0.1.0",
        debug=settings.debug,
        # Disable automatic redirect for paths with trailing slashes.
        redirect_slashes=False,
    )

    # ---- Middleware --------------------------------------------------------

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,  # required for cookie-based auth
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- Request logging middleware ----------------------------------------

    @application.middleware("http")
    async def request_logging_middleware(
        request: Request, call_next: Callable
    ) -> Response:
        """Log every incoming request and its response status + duration.

        Attaches a unique ``request_id`` to the structlog context so that all
        log lines emitted during a request can be correlated.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler in the chain.

        Returns:
            The HTTP response from the handler.
        """
        request_id = str(uuid.uuid4())
        # Populate the ContextVar so stdlib logging records also carry the ID.
        request_id_var.set(request_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("unhandled_exception", exc_info=exc)
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            status_code = getattr(response, "status_code", 500)
            log_fn = logger.warning if status_code >= 400 else logger.info
            log_fn(
                "request_complete",
                status_code=status_code,
                elapsed_ms=elapsed_ms,
            )

        response.headers["X-Request-ID"] = request_id
        return response

    # ---- Static files & templates -----------------------------------------

    if _STATIC_DIR.exists():
        application.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # ---- Auth routers (FastAPI-Users) -------------------------------------

    from issue_observatory.api.routes.auth import auth_router, users_router  # noqa: PLC0415

    application.include_router(auth_router, prefix="/auth")
    application.include_router(users_router, prefix="/users")

    # ---- Arena routers -------------------------------------------------------
    # Each arena exposes a standalone FastAPI router.  All are mounted under
    # the /arenas prefix so arena endpoints are grouped in the OpenAPI docs.

    from issue_observatory.arenas.google_search.router import (  # noqa: PLC0415
        router as google_search_router,
    )
    from issue_observatory.arenas.google_autocomplete.router import (  # noqa: PLC0415
        router as google_autocomplete_router,
    )
    from issue_observatory.arenas.bluesky.router import (  # noqa: PLC0415
        router as bluesky_router,
    )
    from issue_observatory.arenas.reddit.router import (  # noqa: PLC0415
        router as reddit_router,
    )
    from issue_observatory.arenas.youtube.router import (  # noqa: PLC0415
        router as youtube_router,
    )
    from issue_observatory.arenas.rss_feeds.router import (  # noqa: PLC0415
        router as rss_feeds_router,
    )
    from issue_observatory.arenas.gdelt.router import (  # noqa: PLC0415
        router as gdelt_router,
    )
    from issue_observatory.arenas.telegram.router import (  # noqa: PLC0415
        router as telegram_router,
    )
    from issue_observatory.arenas.tiktok.router import (  # noqa: PLC0415
        router as tiktok_router,
    )
    from issue_observatory.arenas.ritzau_via.router import (  # noqa: PLC0415
        router as ritzau_via_router,
    )
    from issue_observatory.arenas.gab.router import (  # noqa: PLC0415
        router as gab_router,
    )
    from issue_observatory.arenas.event_registry.router import (  # noqa: PLC0415
        router as event_registry_router,
    )
    from issue_observatory.arenas.x_twitter.router import (  # noqa: PLC0415
        router as x_twitter_router,
    )
    from issue_observatory.arenas.threads.router import (  # noqa: PLC0415
        router as threads_router,
    )
    from issue_observatory.arenas.web.common_crawl.router import (  # noqa: PLC0415
        router as common_crawl_router,
    )
    from issue_observatory.arenas.web.wayback.router import (  # noqa: PLC0415
        router as wayback_router,
    )
    from issue_observatory.arenas.majestic.router import (  # noqa: PLC0415
        router as majestic_router,
    )
    from issue_observatory.arenas.facebook.router import (  # noqa: PLC0415
        router as facebook_router,
    )
    from issue_observatory.arenas.instagram.router import (  # noqa: PLC0415
        router as instagram_router,
    )

    application.include_router(google_search_router, prefix="/arenas")
    application.include_router(google_autocomplete_router, prefix="/arenas")
    application.include_router(bluesky_router, prefix="/arenas")
    application.include_router(reddit_router, prefix="/arenas")
    application.include_router(youtube_router, prefix="/arenas")
    application.include_router(rss_feeds_router, prefix="/arenas")
    application.include_router(gdelt_router, prefix="/arenas")
    application.include_router(telegram_router, prefix="/arenas")
    application.include_router(tiktok_router, prefix="/arenas")
    application.include_router(ritzau_via_router, prefix="/arenas")
    application.include_router(gab_router, prefix="/arenas")
    application.include_router(event_registry_router, prefix="/arenas")
    application.include_router(x_twitter_router, prefix="/arenas")
    application.include_router(threads_router, prefix="/arenas")
    application.include_router(common_crawl_router, prefix="/arenas")
    application.include_router(wayback_router, prefix="/arenas")
    application.include_router(majestic_router, prefix="/arenas")
    application.include_router(facebook_router, prefix="/arenas")
    application.include_router(instagram_router, prefix="/arenas")

    # ---- Application routers ----------------------------------------------
    # Each stub module is imported lazily.  As routes are fleshed out these
    # imports will populate with real route handlers.

    from issue_observatory.api.routes import (  # noqa: PLC0415
        actors,
        analysis,
        collections,
        content,
        credits,
        health as health_routes,
        imports,
        pages,
        query_designs,
        users,
    )

    # Health endpoints (/api/health, /api/arenas/health)
    application.include_router(health_routes.router)

    application.include_router(query_designs.router, prefix="/query-designs", tags=["query-designs"])
    application.include_router(collections.router, prefix="/collections", tags=["collections"])
    application.include_router(content.router, prefix="/content", tags=["content"])
    application.include_router(actors.router, prefix="/actors", tags=["actors"])
    application.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
    application.include_router(credits.router, prefix="/credits", tags=["credits"])
    application.include_router(imports.router, prefix="/api", tags=["imports"])
    # Admin user management (activation, role changes, API key management)
    application.include_router(users.router, prefix="/admin/users", tags=["admin:users"])
    # HTML page routes (Jinja2 templates, no API prefix)
    application.include_router(pages.router)

    # ---- Lifecycle events -------------------------------------------------

    @application.on_event("startup")
    async def on_startup() -> None:
        """Log application startup information.

        Also stores the Jinja2 templates engine on ``app.state`` so that
        HTML page route handlers can resolve it via ``request.app.state.templates``
        without importing the module-level singleton directly.

        Future: run Alembic migration check, warm Redis connection pool.
        """
        application.state.templates = templates
        logger.info(
            "application_startup",
            app_name=settings.app_name,
            debug=settings.debug,
            log_level=settings.log_level,
        )

    @application.on_event("shutdown")
    async def on_shutdown() -> None:
        """Log clean shutdown."""
        logger.info("application_shutdown")

    # ---- Health endpoint --------------------------------------------------

    @application.get("/health", tags=["system"], include_in_schema=True)
    async def health() -> JSONResponse:
        """Return a minimal process-level liveness status.

        Used by Docker health checks and load balancers that need a fast
        ``200 OK`` without performing any I/O.  Deep infrastructure checks
        (DB, Redis) are at ``/api/health``.  Arena-level checks are at
        ``/api/arenas/health``.

        Returns:
            JSON response with ``{"status": "ok"}``.
        """
        return JSONResponse({"status": "ok"})

    return application


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

app = create_app()
"""The FastAPI application instance.

This is the ASGI callable passed to Uvicorn / Gunicorn.
"""

# ---------------------------------------------------------------------------
# Jinja2 template engine (module-level for reuse in route modules)
# ---------------------------------------------------------------------------

templates: Jinja2Templates | None = None
if _TEMPLATES_DIR.exists():
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    """Jinja2 template engine pointed at ``api/templates/``.

    Import this in route modules that render HTML responses::

        from issue_observatory.api.main import templates

        @router.get("/login")
        async def login_page(request: Request):
            return templates.TemplateResponse("auth/login.html", {"request": request})
    """
