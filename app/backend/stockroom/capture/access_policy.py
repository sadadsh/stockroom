"""Explicit machine-access policy for provider-controlled browser automation.

An implemented adapter is not permission to operate a commercial website.  This registry records
the narrower exception that makes a reviewed adapter eligible, while the per-machine flag records
that the current account and installation are actually covered by that exception.  The default is
therefore always assisted capture.

No credential, cookie, account identifier, or manager identity belongs here.  Those are either
machine secrets in Windows Credential Manager or external authorization evidence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class MachineAccessPolicy:
    """A reviewed, bounded exception to a provider's normal assisted-only access policy."""

    provider_key: str
    exception_code: str
    authorization_flag: str
    provider_kill_switch: str
    max_concurrency: int
    starts_per_window: int
    window_seconds: float
    scope: str


_GLOBAL_KILL_SWITCH = "STOCKROOM_DISABLE_PROVIDER_AUTOMATION"
_POLICIES = {
    "ultralibrarian": MachineAccessPolicy(
        provider_key="ultralibrarian",
        exception_code="UL-PRIVATE-EVALUATION-2026-07-28",
        authorization_flag="ul_private_evaluation_automation",
        provider_kill_switch="STOCKROOM_DISABLE_ULTRALIBRARIAN_AUTOMATION",
        max_concurrency=1,
        starts_per_window=1,
        window_seconds=2.0,
        scope=(
            "Private evaluation through the user's own Ultra Librarian account for ordinary, "
            "exact-part CAD retrieval only; no bulk catalogue scraping and no CAPTCHA, 2FA, or "
            "security-control bypass."
        ),
    ),
}
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class MachineAccessDecision:
    """Why this installation may or may not run one provider adapter unattended.

    ``authorized`` is the whole decision; ``signal`` and ``detail`` exist so the capture trace can
    say WHICH policy row, flag, or environment kill switch settled it. Nothing here names a
    credential: the only per-machine state consulted is a public boolean flag.
    """

    provider_key: str
    authorized: bool
    signal: str
    detail: str
    policy: MachineAccessPolicy | None = None

    @property
    def exception_code(self) -> str:
        return self.policy.exception_code if self.policy is not None else ""


def machine_access_policy(provider_key: str) -> MachineAccessPolicy | None:
    """Return the reviewed policy row for ``provider_key``, if one exists."""

    return _POLICIES.get((provider_key or "").strip().casefold())


def machine_access_decision(
    provider_key: str,
    *,
    config: object | None = None,
    environ: Mapping[str, str] | None = None,
) -> MachineAccessDecision:
    """The authorization verdict WITH the exact reason that produced it.

    Same three facts, same order, same fail-closed behaviour as ``machine_access_authorized``,
    which is implemented in terms of this. Splitting them would let the trace describe a decision
    the run did not actually make.
    """

    key = (provider_key or "").strip().casefold()
    policy = machine_access_policy(key)
    if policy is None:
        return MachineAccessDecision(
            provider_key=key,
            authorized=False,
            signal="no-reviewed-policy",
            detail=(
                "no reviewed machine-access exception exists for this provider; "
                "it stays assisted-only"
            ),
        )
    environment = os.environ if environ is None else environ
    if _environment_flag(environment, _GLOBAL_KILL_SWITCH):
        return MachineAccessDecision(
            provider_key=key,
            authorized=False,
            signal="global-kill-switch",
            detail=f"{_GLOBAL_KILL_SWITCH} is set",
            policy=policy,
        )
    if _environment_flag(environment, policy.provider_kill_switch):
        return MachineAccessDecision(
            provider_key=key,
            authorized=False,
            signal="provider-kill-switch",
            detail=f"{policy.provider_kill_switch} is set",
            policy=policy,
        )
    if config is None:
        try:
            from stockroom.store.machine_config import MachineConfig

            config = MachineConfig.load()
        except Exception:  # noqa: BLE001 - unreadable authorization state is not authorization
            return MachineAccessDecision(
                provider_key=key,
                authorized=False,
                signal="config-unreadable",
                detail="the per-machine configuration could not be read; failing closed",
                policy=policy,
            )
    if getattr(config, policy.authorization_flag, None) is True:
        return MachineAccessDecision(
            provider_key=key,
            authorized=True,
            signal="authorized",
            detail=(
                f"{policy.authorization_flag} is enabled under {policy.exception_code}"
            ),
            policy=policy,
        )
    return MachineAccessDecision(
        provider_key=key,
        authorized=False,
        signal="flag-not-enabled",
        detail=(
            f"the per-machine {policy.authorization_flag} authorization flag is not enabled"
        ),
        policy=policy,
    )


def machine_access_authorized(
    provider_key: str,
    *,
    config: object | None = None,
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Whether this installation may run the provider adapter automatically.

    Eligibility requires all three independent facts:

    * a reviewed policy exception exists in this registry;
    * the non-secret, per-machine authorization flag is explicitly ``True``;
    * neither the global nor provider-specific emergency kill switch is active.

    A malformed or unreadable machine configuration fails closed.
    """

    return machine_access_decision(
        provider_key,
        config=config,
        environ=environ,
    ).authorized


def _environment_flag(environment: Mapping[str, str], name: str) -> bool:
    return str(environment.get(name, "") or "").strip().casefold() in _TRUE_VALUES


__all__ = [
    "MachineAccessDecision",
    "MachineAccessPolicy",
    "machine_access_authorized",
    "machine_access_decision",
    "machine_access_policy",
]
