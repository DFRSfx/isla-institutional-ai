import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, agent, audit, auth, data, imports, reports, sync
from app.core.config import get_settings
from app.services.scheduler import portal_auto_sync_loop


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    sync_task: asyncio.Task[None] | None = None
    if settings.portal_auto_sync_enabled:
        sync_task = asyncio.create_task(portal_auto_sync_loop(settings=settings))
    try:
        yield
    finally:
        if sync_task is not None:
            sync_task.cancel()
            with suppress(asyncio.CancelledError):
                await sync_task


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description="Backend API do ISLA Institutional AI Agent (MVP v1.0)",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(sync.router, prefix="/api/v1")
    app.include_router(imports.router, prefix="/api/v1")
    app.include_router(data.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(reports.router, prefix="/api/v1")
    app.include_router(audit.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    return app


app = create_app()
