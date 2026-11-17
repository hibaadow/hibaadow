"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import get_settings
from ..db import init_db, session_scope
from ..events import get_bus
from ..logging import get_logger, setup_logging
from ..security import COOKIE, client_ip, ensure_admin, limiter, user_from_token
from . import backtests, routes

log = get_logger("atlas.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    with session_scope() as db:
        msg = ensure_admin(db)
        if msg:
            log.warning(msg)
    app.state.history = None
    s = get_settings()
    if s.data_source in ("oanda", "mt5", "metaapi"):
        from ..agent import make_source
        try:
            app.state.history = make_source(s.data_source)
        except Exception as e:  # noqa: BLE001 — misconfiguration is reported via integrations, not a crash
            log.warning("history source unavailable", extra={"data": {"error": str(e)[:200]}})
    app.state.agent = None
    if get_settings().embedded_worker and not getattr(app.state, "disable_agent", False):
        from ..agent import TradingAgent

        app.state.agent = TradingAgent()
        await app.state.agent.start()
    yield
    if app.state.agent:
        await app.state.agent.stop()
    if app.state.history is not None:
        await app.state.history.close()


def create_app(disable_agent: bool = False) -> FastAPI:
    s = get_settings()
    app = FastAPI(title="ATLAS AI", version="1.0.0", lifespan=lifespan,
                  docs_url=None if s.is_production else "/api/docs", openapi_url=None if s.is_production else "/api/openapi.json")
    app.state.disable_agent = disable_agent
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["content-type", "x-atlas-client"])

    @app.middleware("http")
    async def security_mw(request: Request, call_next):
        if request.url.path.startswith("/api/") and not limiter.allow(f"api:{client_ip(request)}", 600, 60):
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        if request.headers.get("content-length") and int(request.headers["content-length"]) > 1_000_000:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' "
                                                   "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
                                                   "connect-src 'self' ws: wss:; frame-ancestors 'none'")
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"data": {"path": request.url.path}})
        return JSONResponse({"detail": "internal error"}, status_code=500)

    app.include_router(backtests.router)
    app.include_router(routes.router)

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket):
        with session_scope() as db:
            user = user_from_token(db, websocket.cookies.get(COOKIE))
        origin = websocket.headers.get("origin")
        if user is None or (origin and origin not in s.cors_origins and not _same_origin(origin, websocket)):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        bus = get_bus()

        async def pump():
            async for ev in bus.subscribe():
                await websocket.send_json(ev)

        task = asyncio.create_task(pump())
        try:
            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            task.cancel()

    dist = s.frontend_dist
    if dist and os.path.isdir(dist):
        app.mount("/_next", StaticFiles(directory=os.path.join(dist, "_next")), name="next")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            safe = os.path.normpath(path).lstrip("/.")
            for cand in (safe, f"{safe}.html", os.path.join(safe, "index.html")):
                full = os.path.realpath(os.path.join(dist, cand))
                if full.startswith(os.path.realpath(dist)) and os.path.isfile(full):
                    return FileResponse(full)
            return FileResponse(os.path.join(dist, "index.html"))

    return app


def _same_origin(origin: str, ws: WebSocket) -> bool:
    host = ws.headers.get("host", "")
    return origin.split("://", 1)[-1] == host


app = create_app()
