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
import hmac
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

        # Constant-time matching. A plain ``==`` (or ``token in dict``) leaks
        # the token byte-by-byte through response-time variation, letting an
        # attacker recover it via a timing side-channel. ``hmac.compare_digest``
        # compares in time independent of where the first mismatch is. We must
        # avoid the dict's hash lookup for the per-peer map too, so we walk it
        # and compare each candidate in constant time.
        peer_name: str | None = None
        matched = False
        for candidate, name in self._token_map.items():
            if hmac.compare_digest(token, candidate):
                peer_name = name
                matched = True
                break
        if not matched and self._expected and hmac.compare_digest(token, self._expected):
            peer_name = None  # anonymous-but-authenticated
            matched = True
        if not matched:
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
    without auth + TLS configured. Refuses to start rather than
    silently accept anonymous peers or transmit bearer tokens in
    cleartext on the network."""


class TlsConfigError(RuntimeError):
    """Raised when CHIMERA_TLS_CERT / CHIMERA_TLS_KEY are misconfigured
    (one without the other, or a path that doesn't exist)."""


def _tls_config() -> tuple[str | None, str | None]:
    """Read CHIMERA_TLS_CERT + CHIMERA_TLS_KEY (ADR 0178).

    Returns ``(certfile, keyfile)`` — both ``None`` when TLS is not
    configured. Raises :class:`TlsConfigError` on a half-configured pair
    or a missing file, because a typo'd cert path silently falling back
    to cleartext would defeat the point.
    """
    import os as _os
    from pathlib import Path as _Path

    cert = (_os.environ.get("CHIMERA_TLS_CERT") or "").strip() or None
    key = (_os.environ.get("CHIMERA_TLS_KEY") or "").strip() or None
    if cert is None and key is None:
        return None, None
    if cert is None or key is None:
        raise TlsConfigError(
            "CHIMERA_TLS_CERT and CHIMERA_TLS_KEY must be set together "
            f"(got cert={'set' if cert else 'unset'}, "
            f"key={'set' if key else 'unset'})"
        )
    for label, path in (("CHIMERA_TLS_CERT", cert), ("CHIMERA_TLS_KEY", key)):
        if not _Path(path).is_file():
            raise TlsConfigError(f"{label}={path!r} does not exist or is not a file")
    return cert, key


def _check_bind_security(host: str, *, tls_enabled: bool | None = None) -> None:
    """v4.52 guard, tightened by ADR 0178; extracted so it's unit-testable
    without booting uvicorn.

    Loopback: always allowed (anonymous + cleartext are fine on-host).
    Non-loopback: requires BOTH a bearer token (CHIMERA_PEER_TOKEN /
    CHIMERA_PEER_TOKENS) AND TLS (CHIMERA_TLS_CERT + CHIMERA_TLS_KEY) —
    a token over cleartext HTTP can be sniffed in one request, making the
    auth requirement theatre. CHIMERA_ALLOW_INSECURE_HTTP=1 overrides
    both requirements (CI / sandboxed networks).
    """
    import os as _os

    if _is_loopback(host):
        return
    allow_insecure = _os.environ.get("CHIMERA_ALLOW_INSECURE_HTTP") in (
        "1", "true", "yes",
    )
    if allow_insecure:
        return
    has_token = bool(
        _os.environ.get("CHIMERA_PEER_TOKEN")
        or _os.environ.get("CHIMERA_PEER_TOKENS")
    )
    if tls_enabled is None:
        cert, _key = _tls_config()
        tls_enabled = cert is not None
    if has_token and tls_enabled:
        return
    missing = []
    if not has_token:
        missing.append("a bearer token (CHIMERA_PEER_TOKEN or CHIMERA_PEER_TOKENS)")
    if not tls_enabled:
        missing.append("TLS (CHIMERA_TLS_CERT + CHIMERA_TLS_KEY)")
    raise InsecureHttpBindError(
        f"refusing to bind chimera serve --http to non-loopback host "
        f"{host!r} without {' and '.join(missing)}. Bearer tokens over "
        "cleartext HTTP are sniffable in transit (ADR 0178). Either "
        "configure what's missing, pass --host 127.0.0.1 for "
        "loopback-only, or set CHIMERA_ALLOW_INSECURE_HTTP=1 to override "
        "(not recommended)."
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
    certfile, keyfile = _tls_config()
    _check_bind_security(host, tls_enabled=certfile is not None)
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
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )
    server = uvicorn.Server(config)
    scheme = "https" if certfile else "http"
    logger.info("chimera serve --http listening on %s://%s:%d", scheme, host, port)
    await server.serve()
    return 0
