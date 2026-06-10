"""Web tools — `http_fetch` and `web_search`.

Per ADR 0001 §"Concentric tool surface" (ring 2) and the user's research
playbook (use Exa for web work).

- :data:`HTTP_FETCH_SCHEMA` — generic GET with size/timeout caps; rejects
  loopback + RFC1918 addresses by default. Always available.
- :data:`WEB_SEARCH_SCHEMA` — Exa search if ``EXA_API_KEY`` is set;
  Tavily as a fallback if ``TAVILY_API_KEY`` is set. Otherwise the tool
  is registered but ``check_fn`` reports unavailable.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from .dispatch import DispatchContext
from .registry import ToolRegistry, default_registry


_DEFAULT_FETCH_TIMEOUT = 15.0
_MAX_FETCH_BYTES = 1_000_000


def _is_private_address(host: str) -> bool:
    """Reject loopback + RFC1918 + link-local. Resolves the hostname."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # If we can't resolve, the fetch will fail anyway — let it through.
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
            return True
    return False


HTTP_FETCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "http_fetch",
        "description": (
            "Fetch a public URL and return the response body as text. Loopback "
            "and private network addresses are rejected. Response is capped at "
            f"{_MAX_FETCH_BYTES // 1000} KB and {_DEFAULT_FETCH_TIMEOUT}s timeout."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute URL to fetch (http/https only)."},
                "max_chars": {
                    "type": "integer",
                    "description": "Truncate the response text to this many characters (default 16000).",
                },
            },
            "required": ["url"],
        },
    },
}


async def http_fetch_handler(args: dict[str, Any], context: DispatchContext) -> str:
    url = args.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("url must be a non-empty string")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL is missing a host")
    if _is_private_address(host):
        raise PermissionError(f"refusing to fetch private address: {host}")

    max_chars = int(args.get("max_chars") or 16_000)

    async with httpx.AsyncClient(
        timeout=_DEFAULT_FETCH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "chimera/0.0 (+research)"},
    ) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            return f"http_fetch: error fetching {url}: {exc}"
    body = resp.text
    if len(body) > _MAX_FETCH_BYTES:
        body = body[:_MAX_FETCH_BYTES]
    if len(body) > max_chars:
        body = body[:max_chars] + f"\n[truncated; full response was {len(resp.text)} chars]"
    return (
        f"GET {url}\n"
        f"status={resp.status_code} content-type={resp.headers.get('content-type', '?')}\n"
        f"---\n{body}"
    )


# ── web_search ───────────────────────────────────────────────


WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web. Backend selected by env: EXA_API_KEY (preferred), "
            "BRAVE_SEARCH_API_KEY, then TAVILY_API_KEY. Returns title + URL + "
            "snippet per result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."},
                "num_results": {
                    "type": "integer",
                    "description": "How many results to return (default 5, max 10).",
                },
            },
            "required": ["query"],
        },
    },
}


def web_search_available() -> bool:
    return bool(
        os.environ.get("EXA_API_KEY")
        or os.environ.get("BRAVE_SEARCH_API_KEY")
        or os.environ.get("TAVILY_API_KEY")
    )


async def _exa_search(query: str, num_results: int) -> str:
    api_key = os.environ["EXA_API_KEY"]
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.exa.ai/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "numResults": num_results, "contents": {"text": True}},
        )
        if resp.status_code >= 400:
            return f"web_search (Exa): error {resp.status_code}: {resp.text[:300]}"
        data = resp.json()

    results = data.get("results") or []
    lines: list[str] = [f"web_search (Exa): {len(results)} result(s) for {query!r}"]
    for i, r in enumerate(results, start=1):
        title = r.get("title") or "(no title)"
        url = r.get("url") or ""
        text = (r.get("text") or "")[:300]
        lines.append(f"\n[{i}] {title}\n    {url}\n    {text.strip()}")
    return "\n".join(lines)


async def _brave_search(query: str, num_results: int) -> str:
    api_key = os.environ["BRAVE_SEARCH_API_KEY"]
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            params={"q": query, "count": num_results},
        )
        if resp.status_code >= 400:
            return f"web_search (Brave): error {resp.status_code}: {resp.text[:300]}"
        data = resp.json()

    results = (data.get("web") or {}).get("results") or []
    lines: list[str] = [f"web_search (Brave): {len(results)} result(s) for {query!r}"]
    for i, r in enumerate(results, start=1):
        title = r.get("title") or "(no title)"
        url = r.get("url") or ""
        snippet = (r.get("description") or "")[:300]
        lines.append(f"\n[{i}] {title}\n    {url}\n    {snippet.strip()}")
    return "\n".join(lines)


async def _tavily_search(query: str, num_results: int) -> str:
    api_key = os.environ["TAVILY_API_KEY"]
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": num_results,
                "search_depth": "basic",
            },
        )
        if resp.status_code >= 400:
            return f"web_search (Tavily): error {resp.status_code}: {resp.text[:300]}"
        data = resp.json()

    results = data.get("results") or []
    lines: list[str] = [f"web_search (Tavily): {len(results)} result(s) for {query!r}"]
    for i, r in enumerate(results, start=1):
        title = r.get("title") or "(no title)"
        url = r.get("url") or ""
        snippet = (r.get("content") or "")[:300]
        lines.append(f"\n[{i}] {title}\n    {url}\n    {snippet.strip()}")
    return "\n".join(lines)


async def web_search_handler(args: dict[str, Any], context: DispatchContext) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    num_results = max(1, min(int(args.get("num_results") or 5), 10))
    if os.environ.get("EXA_API_KEY"):
        return await _exa_search(query, num_results)
    if os.environ.get("BRAVE_SEARCH_API_KEY"):
        return await _brave_search(query, num_results)
    if os.environ.get("TAVILY_API_KEY"):
        return await _tavily_search(query, num_results)
    raise RuntimeError(
        "web_search: no backend configured (set EXA_API_KEY, BRAVE_SEARCH_API_KEY, or TAVILY_API_KEY)"
    )


# ── registration ─────────────────────────────────────────────


def register_web_tools(registry: ToolRegistry | None = None) -> None:
    """Idempotent: register both web tools against the given (or default) registry."""
    reg = registry or default_registry()
    reg.register(
        name="http_fetch",
        toolset="core",
        schema=HTTP_FETCH_SCHEMA,
        handler=http_fetch_handler,
        description="Generic HTTP GET for public URLs.",
        override=True,
    )
    reg.register(
        name="web_search",
        toolset="core",
        schema=WEB_SEARCH_SCHEMA,
        handler=web_search_handler,
        check_fn=web_search_available,
        description="Search the web via Exa or Tavily.",
        override=True,
    )
