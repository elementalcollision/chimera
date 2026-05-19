"""HTTP/SSE transport for Chimera's MCP server (v2.6).

Per ADR 0011: a Starlette ASGI app wraps the existing MCP ``Server``
via :class:`StreamableHTTPSessionManager`, plus a bearer-token
middleware. Multiple concurrent peers can connect over HTTP; stdio
remains the default for the single-peer subprocess case.

Auth: env ``CHIMERA_PEER_TOKEN`` is the required bearer. If unset, the
server logs a loud warning and allows anonymous (intended for local dev
only). For real deployments set the token and configure each peer to
send it as ``Authorization: Bearer <token>``.
"""

from __future__ import annotations

import contextlib
import logging
import os

import uvicorn
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from .mcp_server import ChimeraMCPServer

logger = logging.getLogger(__name__)


_TOKEN_ENV = "CHIMERA_PEER_TOKEN"


class _BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject any non-/health request without the expected bearer token.

    If ``expected_token`` is empty, the middleware is permissive (anonymous
    allowed). The constructor logs a warning in that case.
    """

    def __init__(self, app, expected_token: str | None) -> None:
        super().__init__(app)
        self._expected = expected_token or ""
        if not self._expected:
            logger.warning(
                "%s is empty; HTTP server is accepting anonymous peers. "
                "Set the env var in production.",
                _TOKEN_ENV,
            )

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if not self._expected:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or token != self._expected:
            return JSONResponse(
                {"error": "unauthorized"}, status_code=401
            )
        return await call_next(request)


async def _health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("chimera ok\n")


def build_http_app(cms: ChimeraMCPServer) -> Starlette:
    """Construct the Starlette ASGI app: /health + /mcp + bearer auth."""
    session_manager = StreamableHTTPSessionManager(app=cms.server)

    async def _mcp_handler(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    routes = [
        Route("/health", _health),
        Mount("/mcp", app=_mcp_handler),
    ]

    @contextlib.asynccontextmanager
    async def _lifespan(app):
        async with session_manager.run():
            yield

    app = Starlette(routes=routes, lifespan=_lifespan)
    expected = os.environ.get(_TOKEN_ENV, "")
    app.add_middleware(_BearerAuthMiddleware, expected_token=expected)
    return app


async def serve_http(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    name: str = "chimera",
) -> int:
    """Run the HTTP MCP server until SIGINT.

    Binds to ``host``:``port``. ``host=0.0.0.0`` exposes to the
    network — make sure ``CHIMERA_PEER_TOKEN`` is set first.
    """
    cms = ChimeraMCPServer.from_env(name=name)
    if not cms.exposed:
        logger.warning(
            "no tools exposed to peers; set CHIMERA_PEER_EXPOSED_TOOLS"
        )
    app = build_http_app(cms)
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info("chimera serve --http listening on http://%s:%d", host, port)
    await server.serve()
    return 0
