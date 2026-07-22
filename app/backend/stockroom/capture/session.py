"""Pure capture-session state for guided capture (no pywebview).

Tracks which Requirements a part still needs and which have landed, gates on a
per-session token, and carries a cooperative stop flag the host poll thread
watches. The host owns one live CaptureSession; starting a new one stops the
prior (fixes wrong-part misattribution, B4).
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.capture.requirements import Requirement

_DEFAULT_TTL = 300.0
_KICAD_REQS = frozenset(
    {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT, Requirement.KICAD_MODEL}
)
_ALTIUM_REQS = frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})


def new_token() -> str:
    return secrets.token_hex(8)


@dataclass
class CaptureSession:
    part_id: str
    token: str
    needs: frozenset[Requirement]
    started_at: float
    ttl: float = _DEFAULT_TTL
    received: dict[Requirement, Path] = field(default_factory=dict)
    stop_flag: dict = field(default_factory=lambda: {"stop": False})
    # The host's scratch dir for this capture (loose Altium libraries extracted from a
    # captured zip land here). Set by the host after start(); cleaned when the session is
    # stopped/replaced or its window closes. Pure data - the capture package never touches it.
    temp_dir: Path | None = None

    @classmethod
    def start(cls, part_id, needs, *, now, token=None, ttl=_DEFAULT_TTL):
        return cls(
            part_id=part_id,
            token=token or new_token(),
            needs=frozenset(needs),
            started_at=now,
            ttl=ttl,
        )

    @property
    def deadline(self) -> float:
        return self.started_at + self.ttl

    def is_expired(self, now: float) -> bool:
        return now >= self.deadline

    def record(self, requirements: Iterable[Requirement], path: Path) -> list[Requirement]:
        newly: list[Requirement] = []
        for req in requirements:
            if req in self.needs and req not in self.received:
                self.received[req] = Path(path)
                newly.append(req)
        return newly

    def remaining(self) -> frozenset[Requirement]:
        return frozenset(self.needs - set(self.received))

    def is_complete(self) -> bool:
        return self.needs <= set(self.received)

    def _subset_complete(self, subset: frozenset[Requirement]) -> bool:
        return (self.needs & subset) <= set(self.received)

    def kicad_complete(self) -> bool:
        return self._subset_complete(_KICAD_REQS)

    def altium_complete(self) -> bool:
        return self._subset_complete(_ALTIUM_REQS)

    def stop(self) -> None:
        self.stop_flag["stop"] = True
