"""Library profiles: each libraries/<Name>/ is a complete, self-contained set.

Create/switch/delete in-app; the active profile is per-machine state. Delete
removes the folder in a scoped commit; git history preserves everything (spec
section 3).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from stockroom.model.category import category_footprint_lib, category_symbol_lib
from stockroom.vcs.repo import GitRepo

_SUBDIRS = ("parts", "symbols", "footprints", "models", "datasheets")


def _validate_name(name: str) -> None:
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"unsafe profile name: {name!r}")


class ProfileLibrary:
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def parts_dir(self) -> Path:
        return self.root / "parts"

    @property
    def symbols_dir(self) -> Path:
        return self.root / "symbols"

    @property
    def footprints_dir(self) -> Path:
        return self.root / "footprints"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def datasheets_dir(self) -> Path:
        return self.root / "datasheets"

    def symbol_lib_path(self, category: str) -> Path:
        return self.symbols_dir / category_symbol_lib(category)

    def footprint_lib_path(self, category: str) -> Path:
        return self.footprints_dir / category_footprint_lib(category)

    def ensure_layout(self) -> list[Path]:
        keeps: list[Path] = []
        for sub in _SUBDIRS:
            d = self.root / sub
            d.mkdir(parents=True, exist_ok=True)
            keep = d / ".gitkeep"
            if not keep.exists():
                keep.write_text("")
            keeps.append(keep)
        return keeps


class Profile:
    def __init__(self, name: str, root: Path):
        self.name = name
        self.root = Path(root)
        self.library = ProfileLibrary(self.root)

    @property
    def is_archive(self) -> bool:
        """A grandfathered archive profile (spec section 7): holds the imported legacy
        library and is exempt from the complete-to-add gate. Marked by an `.archive`
        sentinel in the profile root."""
        return (self.root / ".archive").exists()


class ProfileStore:
    def __init__(self, libraries_root: Path, repo: GitRepo):
        self.libraries_root = Path(libraries_root)
        self.repo = repo

    def list(self) -> list[str]:
        if not self.libraries_root.exists():
            return []
        return sorted(p.name for p in self.libraries_root.iterdir() if p.is_dir())

    def exists(self, name: str) -> bool:
        return (self.libraries_root / name).is_dir()

    def get(self, name: str) -> Profile:
        _validate_name(name)
        if not self.exists(name):
            raise ValueError(f"profile does not exist: {name}")
        return Profile(name, self.libraries_root / name)

    def create(self, name: str, archive: bool = False) -> Profile:
        _validate_name(name)
        if self.exists(name):
            raise ValueError(f"profile already exists: {name}")
        profile = Profile(name, self.libraries_root / name)
        tracked = list(profile.library.ensure_layout())
        if archive:
            marker = profile.root / ".archive"
            marker.write_text("")
            tracked.append(marker)
        self.repo.commit(f"Create {'archive ' if archive else ''}profile {name}", tracked)
        return profile

    def delete(self, name: str) -> None:
        _validate_name(name)
        if not self.exists(name):
            raise ValueError(f"profile does not exist: {name}")
        if self.list() == [name]:
            raise ValueError("refusing to delete the last profile")
        target = self.libraries_root / name
        # remove from the working tree; the scoped commit stages the deletion of the
        # now-missing tracked files (git add -A records removals) as one commit.
        shutil.rmtree(target)
        self.repo.commit(f"Delete profile {name}", [target])
