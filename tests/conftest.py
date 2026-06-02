"""Shared pytest fixtures and suite-wide hygiene.

Hermetic enforcement env (the char-2026-06-02 root cause): the in-loop critic
gate activates on ``CHIMERA_CRITIC_ENFORCE=1`` (and the operator override
``CHIMERA_ALLOW_CRITIC_REJECT=1``). Those are OPERATIONAL knobs, not test
conditions. When the enforced self-determined soak runs ``chimera verify`` as its
acceptance gate, the verify pytest subprocess INHERITS the soak's
``CHIMERA_CRITIC_ENFORCE=1`` — which silently flipped commit-path tests
(test_soak_autocommit, test_git_commit_tool) from ``committed`` to
``critic_blocked``, turning a green suite red out from under a correct change.
CI never saw it because CI doesn't set the var; the soak does.

Scrub both knobs from the environment for every test by default, so the suite is
deterministic regardless of the ambient shell. A test that specifically wants
enforcement opts in explicitly via ``monkeypatch.setenv`` in its own body — which
is already how the critic-gate tests drive it. Production behaviour is untouched:
the real in-loop gate reads the live process env at commit time, not this fixture.
"""

from __future__ import annotations

import pytest

# Operational enforcement knobs that must never leak into a test from the ambient
# shell (mirrors critic_gate._ENFORCE_ENV / _OVERRIDE_ENV).
_ENFORCEMENT_ENV_VARS = ("CHIMERA_CRITIC_ENFORCE", "CHIMERA_ALLOW_CRITIC_REJECT")


@pytest.fixture(autouse=True)
def _hermetic_enforcement_env(monkeypatch):
    """Default every test to the un-enforced baseline (matches green CI).

    Autouse so no test has to remember; opt back in with ``monkeypatch.setenv``.
    """
    for var in _ENFORCEMENT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
