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
    """Reject any non-/health request without a valid bearer token.

    Accepts a single shared token (``expected_token``) AND/OR a per-peer
    token map (``token_map``) keyed by token → peer-name. If a request's
    token matches a peer in the map, :data:`current_peer` (contextvar)
    is set for the duration of the handler so the MCP dispatch layer
    can build a trust-typed :class:`DispatchContext` (v2.7).

    Empty ``expected_token`` AND empty ``token_map`` → permissive
    anonymous + warning (local dev only).
    """

    def __init__(
        self,
        app,
        expected_token: str | None,
        token_map: dict[str, str] | None = None,
    ) -> None:
        super().__init__(app)
        self._expected = expected_token or ""
        self._token_map = dict(token_map or {})
        if not self._expected and not self._token_map:
            logger.warning(
                "%s and CHIMERA_PEER_TOKENS are both empty; HTTP server is "
                "accepting anonymous peers. Set one in production.",
                _TOKEN_ENV,
            )

    async def dispatch(self, request: Request, call_next):
        from .peer_auth import current_peer

        if request.url.path in ("/health", "/healthz"):
            return await call_next(request)
        if not self._expected and not self._token_map:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        peer_name: str | None = None
        if token in self._token_map:
            peer_name = self._token_map[token]
        elif self._expected and token == self._expected:
            peer_name = None  # anonymous-but-authenticated
        else:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        token_ctx = current_peer.set(peer_name)
        try:
            return await call_next(request)
        finally:
            current_peer.reset(token_ctx)


async def _health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("chimera ok\n")


async def _healthz(_: Request) -> JSONResponse:
    """Structured health probe — cycle, trust tier, version, db reachable."""
    from .. import __version__
    from ..a2a import AgentIdentity
    from ..core import LoopConfig, load_heartbeat
    from ..memory import open_and_init

    cfg = LoopConfig.from_env()
    identity = AgentIdentity()
    payload: dict[str, object] = {
        "status": "ok",
        "version": __version__,
        "agent_id": identity.agent_id,
        "capabilities": list(identity.capabilities),
    }
    try:
        state, _ = load_heartbeat(cfg.mind_dir / "HEARTBEAT.md")
        payload["cycle"] = state.cycle
        payload["trust_tier"] = state.trust_tier
        payload["session_started_at"] = state.session_started_at
    except Exception as exc:
        payload["status"] = "degraded"
        payload["heartbeat_error"] = str(exc)
    try:
        conn = open_and_init(cfg.state_dir / "chimera.db")
        conn.execute("SELECT 1").fetchone()
        conn.close()
        payload["db"] = "ok"
    except Exception as exc:
        payload["status"] = "degraded"
        payload["db"] = f"error: {exc}"
    return JSONResponse(payload)


def build_http_app(cms: ChimeraMCPServer) -> Starlette:
    """Construct the Starlette ASGI app: /health + /mcp + bearer auth."""
    session_manager = StreamableHTTPSessionManager(app=cms.server)

    async def _mcp_handler(scope, receive, send):
        await session_manager.handle_request(scope, receive, send)

    async def _emergence_feed(_: Request) -> PlainTextResponse:
        from ..a2a.emergence_sync import serialize_journal
        return PlainTextResponse(serialize_journal(), media_type="application/jsonl")

    routes = [
        Route("/health", _health),
        Route("/healthz", _healthz),
        Route("/emergence-feed", _emergence_feed),
        Mount("/mcp", app=_mcp_handler),
    ]

    @contextlib.asynccontextmanager
    async def _lifespan(app):
        async with session_manager.run():
            yield

    app = Starlette(routes=routes, lifespan=_lifespan)
    expected = os.environ.get(_TOKEN_ENV, "")
    from .peer_auth import load_token_map
    token_map = load_token_map()
    app.add_middleware(
        _BearerAuthMiddleware,
        expected_token=expected,
        token_map=token_map,
    )
    return app


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_loopback(host: str) -> bool:
    """v4.52: a *loopback* bind is safe to run without auth (local-dev
    convenience). Anything else — 0.0.0.0, a public IP, a hostname —
    is treated as network-exposed and requires a bearer token."""
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


class InsecureHttpBindError(RuntimeError):
    """Raised when serve_http is asked to bind to a non-loopback host
    without an auth token configured. Refuses to start rather than
    silently accept anonymous peers from the network."""


def _check_bind_security(host: str) -> None:
    """v4.52 guard, extracted so it's unit-testable without booting
    uvicorn. Raises InsecureHttpBindError on a non-loopback bind that
    has no token set and no explicit insecure override."""
    import os as _os

    if _is_loopback(host):
        return
    has_token = bool(
        _os.environ.get("CHIMERA_PEER_TOKEN")
        or _os.environ.get("CHIMERA_PEER_TOKENS")
    )
    allow_insecure = _os.environ.get("CHIMERA_ALLOW_INSECURE_HTTP") in (
        "1", "true", "yes",
    )
    if has_token or allow_insecure:
        return
    raise InsecureHttpBindError(
        f"refusing to bind chimera serve --http to non-loopback host "
        f"{host!r} without auth. Set CHIMERA_PEER_TOKEN (single token) "
        "or CHIMERA_PEER_TOKENS (JSON map), OR pass --host 127.0.0.1 "
        "for loopback-only, OR set CHIMERA_ALLOW_INSECURE_HTTP=1 to "
        "override (not recommended)."
    )


async def serve_http(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    name: str = "chimera",
) -> int:
    """Run the HTTP MCP server until SIGINT.

    Binds to ``host``:``port``. v4.52: non-loopback binds (``0.0.0.0``
    and any public host) REQUIRE ``CHIMERA_PEER_TOKEN`` or
    ``CHIMERA_PEER_TOKENS`` to be set — the server refuses to start
    otherwise. Loopback binds still allow anonymous (with a warning)
    for local-dev convenience.

    Set ``CHIMERA_ALLOW_INSECURE_HTTP=1`` to bypass the guard if you
    truly mean to expose anonymously (rare; CI / sandboxed networks).
    """
    _check_bind_security(host)
    from ..core import assert_no_errors
    assert_no_errors()
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
