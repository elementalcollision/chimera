"""Trust-tier system — Steiner-style developmental gating.

Per Reggio's TrustManager + ADR 0003 deferred-list.

Tiers (lowest → highest):

  T0 LOCKED        — observer only; no tool dispatch.
  T1 SUPERVISED    — tools dispatch; writes need operator approval.
  T2 UNLOCKED      — basic autonomy; non-destructive tools auto-fire.
  T3 TRUSTED       — broader autonomy; can spawn sub-agents freely.
  T4 ADAPTIVE      — can activate validated skills without approval.
  T5 AUTONOMOUS    — full autonomy; only drift lockdown demotes.

State persists in ``state/trust_state.json``. The auto-promotion check
runs each cycle; demotion fires on drift lockdown.
"""

from .manager import (
    TrustEvent,
    TrustManager,
    TrustState,
    TrustTier,
)

__all__ = ["TrustEvent", "TrustManager", "TrustState", "TrustTier"]
