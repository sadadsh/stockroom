"""One per-machine Primary CAD Tool policy.

The registry owns tool facts. This module owns the machine choice and every transition around it:
recommendation without consent, default capture requirements, promoted setup, and deferred switching
while old-tool work finishes. Callers receive one DTO instead of scattering tool-key branches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from stockroom.eda.registry import EdaTool, all_tools, get_tool
from stockroom.store.machine_config import MachineConfig


@dataclass(frozen=True)
class PrimaryEdaState:
    primary_key: str | None
    pending_key: str | None
    recommended_key: str | None
    confirmation_required: bool


class PrimaryEdaPolicy:
    """Deep interface over the machine choice and the EDA registry.

    Methods mutate only the supplied in-memory ``MachineConfig``. The caller owns persistence so a
    settings request, onboarding transition, or future Assets operation can include the choice in
    its own transaction boundary.
    """

    def __init__(self, config: MachineConfig) -> None:
        self._config = config

    @staticmethod
    def _registered(key: str) -> EdaTool | None:
        candidate = str(key or "").strip().casefold()
        if not candidate:
            return None
        try:
            return get_tool(candidate)
        except KeyError:
            return None

    @staticmethod
    def _require_registered(key: str) -> EdaTool:
        candidate = str(key or "").strip().casefold()
        try:
            return get_tool(candidate)
        except KeyError as exc:
            raise ValueError(f"unknown primary CAD tool: {key!r}") from exc

    @property
    def primary_tool(self) -> EdaTool | None:
        return self._registered(self._config.primary_eda)

    @property
    def pending_tool(self) -> EdaTool | None:
        pending = self._registered(self._config.primary_eda_pending)
        primary = self.primary_tool
        if primary is None or pending is None or pending.key == primary.key:
            return None
        return pending

    def recommendation(self, detected_keys: Iterable[str] = ()) -> EdaTool | None:
        primary = self.primary_tool
        if primary is not None:
            return primary
        detected = {
            tool.key
            for key in detected_keys
            if (tool := self._registered(key)) is not None
        }
        for tool in all_tools():
            if tool.key in detected:
                return tool
        return None

    def snapshot(self, detected_keys: Iterable[str] = ()) -> PrimaryEdaState:
        primary = self.primary_tool
        pending = self.pending_tool
        recommendation = self.recommendation(detected_keys)
        return PrimaryEdaState(
            primary_key=primary.key if primary else None,
            pending_key=pending.key if pending else None,
            recommended_key=recommendation.key if recommendation else None,
            confirmation_required=primary is None,
        )

    def requirements(self) -> tuple[str, ...]:
        tool = self.primary_tool
        return tool.closable_assets() if tool else ()

    def setup_checks(self) -> tuple[str, ...]:
        tool = self.primary_tool
        return tool.setup_checks if tool else ()

    def promoted_settings_target(self) -> str:
        tool = self.primary_tool
        return tool.settings_target if tool else ""

    def retained_optional_tool_keys(self) -> tuple[str, ...]:
        """Other-tool assets retained when one tool controls defaults and readiness."""

        primary = self.primary_tool
        return tuple(
            tool.key
            for tool in all_tools()
            if primary is None or tool.key != primary.key
        )

    def request_switch(
        self,
        key: str,
        *,
        active_tool: str | None = None,
    ) -> PrimaryEdaState:
        """Confirm or request a tool without changing an active operation mid-flight.

        ``active_tool`` names the tool captured by running work. When it is the current primary,
        the request is persisted as pending and the old tool remains authoritative. With no active
        work, the choice activates immediately. Selecting the current tool cancels a pending switch.
        """

        target = self._require_registered(key)
        current = self.primary_tool
        active = self._require_registered(active_tool) if active_tool else None

        if current is None:
            if active is not None:
                raise ValueError("cannot defer a Primary CAD Tool choice without a current tool")
            self._config.primary_eda = target.key
            self._config.primary_eda_pending = ""
        elif target.key == current.key:
            self._config.primary_eda_pending = ""
        elif active is not None:
            if active.key != current.key:
                raise ValueError("active CAD work does not belong to the current Primary CAD Tool")
            self._config.primary_eda_pending = target.key
        else:
            self._config.primary_eda = target.key
            self._config.primary_eda_pending = ""
        return self.snapshot()

    def activate_pending(self, completed_tool: str) -> bool:
        """Activate a queued switch only after work owned by the old primary finishes."""

        pending = self.pending_tool
        current = self.primary_tool
        if pending is None or current is None:
            return False
        completed = self._require_registered(completed_tool)
        if completed.key != current.key:
            return False
        self._config.primary_eda = pending.key
        self._config.primary_eda_pending = ""
        return True

    def dto(self, detected_keys: Iterable[str] = ()) -> dict[str, object]:
        detected = {
            tool.key
            for key in detected_keys
            if (tool := self._registered(key)) is not None
        }
        state = self.snapshot(detected)
        return {
            "primary_eda": state.primary_key,
            "primary_eda_pending": state.pending_key,
            "primary_eda_confirmation_required": state.confirmation_required,
            "recommended_primary_eda": state.recommended_key,
            "primary_eda_requirements": list(self.requirements()),
            "retained_optional_eda": list(self.retained_optional_tool_keys()),
            "eda_tools": [
                {
                    "key": tool.key,
                    "label": tool.label,
                    "detected": tool.key in detected,
                    "selected": tool.key == state.primary_key,
                    "pending": tool.key == state.pending_key,
                    "setup_checks": list(tool.setup_checks),
                    "settings_target": tool.settings_target,
                }
                for tool in all_tools()
            ],
        }


def machine_detected_tool_keys(ctx) -> tuple[str, ...]:
    """Read installed-tool facts without selecting one or launching either application."""

    detected: list[str] = []
    if bool(getattr(getattr(ctx, "cli", None), "available", False)):
        detected.append("kicad")
    try:
        from stockroom.altium.driver import AltiumDriver

        if AltiumDriver().installed:
            detected.append("altium")
    except (OSError, RuntimeError):
        # Detection is a recommendation aid, never a setup blocker. An explicit choice will run
        # the selected tool's proper readiness checks and report the actionable failure there.
        pass
    return tuple(detected)
