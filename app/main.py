"""FastAPI application with local demo startup and periodic agent work."""

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.config import get_settings
from app.db import make_session_factory
from app.demo import TEAM_ID, seed_demo
from app.outreach.line_bot import router as line_router
from app.redis_client import get_redis

STATIC = Path(__file__).parent / "static"


async def agent_loop(app):
    from app.manager.loop import follow_up, release_themes
    from app.triggers.engine import run_engine

    while True:
        await asyncio.sleep(30)
        # One short transaction per stage so a slow LLM call never holds locks other requests need.
        for stage in (run_engine, release_themes, follow_up):
            try:
                with app.state.session_factory() as session:
                    result = stage(session, app.state.redis, TEAM_ID)
                    if asyncio.iscoroutine(result):
                        await result
                    session.commit()
            except Exception:
                # Retry next tick; model/SDK exceptions can contain sensitive request data.
                continue


def create_app(*, database_url=None, redis=None, background=True):
    @asynccontextmanager
    async def lifespan(application):
        application.state.session_factory = make_session_factory(
            database_url or get_settings().database_url
        )
        application.state.redis = redis if redis is not None else get_redis()
        with application.state.session_factory() as session:
            seed_demo(session)
        task = asyncio.create_task(agent_loop(application)) if background else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            application.state.session_factory.kw["bind"].dispose()

    application = FastAPI(title="Kreng-jai Bridge", lifespan=lifespan)
    application.include_router(api_router)
    application.include_router(line_router)
    application.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")

    @application.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith(("/api/", "/line/")):
            response.headers["Cache-Control"] = "no-store"
        return response

    def page(filename):
        path = STATIC / filename
        if path.is_file():
            return FileResponse(path)
        return HTMLResponse(
            "<!doctype html><html lang='th'><meta charset='utf-8'><title>Kreng-jai Bridge</title><body><h1>Kreng-jai Bridge</h1><p>หน้าสาธิตกำลังเตรียมพร้อม</p></body></html>"
        )

    @application.get("/", include_in_schema=False)
    def index():
        return page("index.html")

    @application.get("/manager", include_in_schema=False)
    def manager():
        return page("manager.html")

    @application.get("/demo", include_in_schema=False)
    def demo():
        return page("demo.html")

    return application


app = create_app()
