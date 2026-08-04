"""Unpack ingestion inputs (zips, folders, bare files, any mix) into isolated
sandbox roots so the rest of the pipeline works against a plain directory tree,
never the caller's originals (spec section 5, stage 1).

This module owns the ONLY archive walker in the backend. Every bound an untrusted
provider download must satisfy is declared and enforced here, once, so a caller
cannot reach a second, weaker extractor. ``extractall`` is never used: each member
is written individually with the destination re-resolved and containment re-checked,
and the number of bytes actually written is counted rather than trusted from the
central directory (spec section 11).
"""

from __future__ import annotations

import hashlib
import shutil
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from stockroom.ingest.errors import IngestError

# --- Bounds -----------------------------------------------------------------
# Every number below is a measured or platform-derived ceiling, not a taste call.

# The largest real provider CAD bundle measured on this project is a few megabytes
# (Ultra Librarian / SamacSys / SnapMagic downloads). 256 MiB leaves two orders of
# magnitude of headroom for a multi-variant package with several STEP models and
# still refuses a runaway input before a single member is read.
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024

# A real package carries a symbol, one `.pretty` worth of footprint variants, a 3D
# model and its documentation: tens of members, low hundreds at the extreme. 4096
# covers that and refuses a member-count bomb, where a small archive declares
# millions of entries purely to exhaust the walker.
MAX_MEMBERS = 4096

# Expanded output is what actually lands on disk, so it is bounded separately from
# the compressed input. Twice MAX_ARCHIVE_BYTES admits a legitimately compressible
# ASCII STEP/library set while staying far below any decompression-bomb payload.
MAX_TOTAL_EXPANDED_BYTES = 512 * 1024 * 1024

# The largest single legitimate artifact is a 3D model. Every provider STEP measured
# here is under a few megabytes; 64 MiB is well above all of them and still bounds
# one hostile member on its own, before the total bound is reached.
MAX_MEMBER_EXPANDED_BYTES = 64 * 1024 * 1024

# Deflate on real CAD text (STEP, .kicad_sym, P-CAD ASCII) measures below 20:1.
# 100:1 is the ratio `altium/ul_import.py` already proved in production against real
# Ultra Librarian archives, and a bomb needs ratios in the thousands to be useful.
MAX_COMPRESSION_RATIO = 100.0

# Windows' default MAX_PATH is 260 characters and the sandbox root consumes part of
# it. Bounding the member's own relative path at 200 leaves room for the destination
# prefix, so a valid archive can never fail halfway through extraction.
MAX_PATH_LENGTH = 200

# NTFS and every filesystem this ships on cap one path component at 255 characters.
MAX_NAME_LENGTH = 255

# The deepest real provider layout is `KiCADv6/footprints.pretty/part.kicad_mod`:
# two directory levels. 16 is generous for a vendor that nests by tool and version,
# and refuses a directory-recursion bomb.
MAX_DIRECTORY_DEPTH = 16

# Vendors wrap ONE inner archive (typically the Altium set) inside the bundle; that
# single level is the measured shape and is what `capture/classify.py` reads. Deeper
# nesting is a bomb vector, never a real CAD download.
MAX_NESTED_ARCHIVE_DEPTH = 1

# Only the two compression methods a real provider zip uses. Anything else (bzip2,
# lzma, ppmd) cannot be bounded by the ratio check the same way and has never been
# observed in a CAD download.
ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})

ARCHIVE_SUFFIXES = frozenset({".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".cab"})

# Executable, script and shortcut content. A CAD download never needs any of it, and
# a provider that ships it is shipping code, not library data. Extensions are the
# first gate; `prohibited_reason` sniffs the leading bytes for the same classes so a
# renamed payload is caught too.
PROHIBITED_SUFFIXES = frozenset(
    {
        ".exe", ".msi", ".msix", ".appx", ".dll", ".com", ".scr", ".sys", ".cpl", ".pif",
        ".bat", ".cmd", ".ps1", ".psm1", ".ps1xml", ".sh", ".py", ".pyc", ".pyw",
        ".js", ".jse", ".vbs", ".vbe", ".wsf", ".wsh", ".hta", ".jar", ".reg", ".msc",
        ".lnk", ".url", ".scf", ".pas", ".dfm", ".prjscr",
    }
)

# Leading-byte signatures for the same classes, so a `.step` that is really a PE
# binary is refused as a content/extension mismatch rather than extracted.
_EXECUTABLE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"MZ", "a Windows executable"),
    (b"\x7fELF", "an ELF executable"),
    (b"\xfe\xed\xfa", "a Mach-O executable"),
    (b"\xcf\xfa\xed\xfe", "a Mach-O executable"),
    (b"\xca\xfe\xba\xbe", "a Java or fat Mach-O executable"),
    (b"#!", "an interpreter script"),
)
_SHORTCUT_MAGIC = b"L\x00\x00\x00\x01\x14\x02\x00"

_MAGIC_PREFIX_BYTES = 8


def prohibited_reason(head: bytes) -> str:
    """Why these leading bytes are executable/script/shortcut content, or ``""``."""

    if head.startswith(_SHORTCUT_MAGIC):
        return "a Windows shortcut"
    for magic, description in _EXECUTABLE_MAGIC:
        if head.startswith(magic):
            return description
    return ""


def prohibited_file_reason(path: Path) -> str:
    """Why this file is executable/script/shortcut content, or ``""``.

    Judged by extension first and then by leading bytes, so neither a plain `.exe`
    nor a payload renamed to `.step` gets through. An unreadable path is not a
    verdict: callers treat that separately.
    """

    path = Path(path)
    if path.suffix.casefold() in PROHIBITED_SUFFIXES:
        return f"a {path.suffix.casefold()} executable or script"
    try:
        with open(path, "rb") as handle:
            return prohibited_reason(handle.read(_MAGIC_PREFIX_BYTES))
    except OSError:
        return ""


@dataclass(frozen=True)
class ArchiveLimits:
    """The bounds one archive must satisfy. Defaults are the module constants."""

    max_archive_bytes: int = MAX_ARCHIVE_BYTES
    max_members: int = MAX_MEMBERS
    max_total_expanded_bytes: int = MAX_TOTAL_EXPANDED_BYTES
    max_member_expanded_bytes: int = MAX_MEMBER_EXPANDED_BYTES
    max_compression_ratio: float = MAX_COMPRESSION_RATIO
    max_path_length: int = MAX_PATH_LENGTH
    max_name_length: int = MAX_NAME_LENGTH
    max_directory_depth: int = MAX_DIRECTORY_DEPTH
    max_nested_archive_depth: int = MAX_NESTED_ARCHIVE_DEPTH


DEFAULT_LIMITS = ArchiveLimits()


@dataclass(frozen=True)
class ArchivePolicy:
    """Limits plus the content rules for one caller.

    ``reviewed_member_suffixes`` is the ONLY way executable/script content reaches a
    sandbox: `altium/ul_import.py` names the Delphi members it then pins by SHA-256
    before Altium is allowed anywhere near them. It exempts the extension gate only;
    the leading-byte sniff still applies, so a reviewed suffix cannot smuggle a PE.
    """

    limits: ArchiveLimits = DEFAULT_LIMITS
    reject_executable_content: bool = True
    reviewed_member_suffixes: frozenset[str] = frozenset()
    require_non_empty_members: bool = False


DEFAULT_ARCHIVE_POLICY = ArchivePolicy()


@dataclass(frozen=True)
class ArchiveMember:
    """One inspected archive member, already proved safe to write."""

    name: str
    parts: tuple[str, ...]
    suffix: str
    expanded_bytes: int
    is_dir: bool


@dataclass(frozen=True)
class ArchiveInspection:
    """The result of one bounded walk: no bytes written, every bound checked."""

    path: Path
    archive_bytes: int
    total_expanded_bytes: int
    members: tuple[ArchiveMember, ...] = field(default_factory=tuple)

    @property
    def files(self) -> tuple[ArchiveMember, ...]:
        return tuple(member for member in self.members if not member.is_dir)


@dataclass
class Unpacked:
    root: Path
    origin: Path
    is_zip: bool
    sha256: str


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _reject(message: str) -> IngestError:
    return IngestError(message)


def _check_member_name(name: str, limits: ArchiveLimits) -> tuple[str, ...]:
    """Every path-shape rule, returning the member's POSIX parts when it is safe."""

    if not name:
        raise _reject("archive member has an empty name")
    if len(name) > limits.max_path_length:
        raise _reject(f"archive member path is longer than {limits.max_path_length}: {name!r}")
    if "\\" in name:
        raise _reject(f"archive member uses a backslash separator: {name!r}")
    if "\x00" in name:
        raise _reject(f"archive member name contains a null byte: {name!r}")
    pure = PurePosixPath(name)
    parts = pure.parts
    if not parts:
        raise _reject(f"archive member has no usable path: {name!r}")
    if pure.is_absolute() or name.startswith("/"):
        raise _reject(f"archive member is an absolute path: {name!r}")
    if ".." in parts:
        raise _reject(f"archive member escapes the sandbox with a parent reference: {name!r}")
    if ":" in parts[0]:
        raise _reject(f"archive member is drive-qualified: {name!r}")
    for part in parts:
        if len(part) > limits.max_name_length:
            raise _reject(
                f"archive member name is longer than {limits.max_name_length}: {name!r}"
            )
    if len(parts) - 1 > limits.max_directory_depth:
        raise _reject(
            f"archive member is nested deeper than {limits.max_directory_depth} directories: "
            f"{name!r}"
        )
    return parts


def _check_member_mode(item: zipfile.ZipInfo) -> None:
    """Refuse anything that is not a plain file or directory entry.

    Unix-created archives carry the mode in the high half of ``external_attr``;
    a symlink, device node, FIFO or socket entry is rejected by its file type
    rather than by name, because the name of a symlink is indistinguishable from
    a regular file's.
    """

    if item.create_system != 3:
        return
    unix_mode = item.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if file_type in {0, stat.S_IFREG, stat.S_IFDIR}:
        return
    kind = {
        stat.S_IFLNK: "symbolic link",
        stat.S_IFBLK: "block device",
        stat.S_IFCHR: "character device",
        stat.S_IFIFO: "FIFO",
        stat.S_IFSOCK: "socket",
    }.get(file_type, "non-regular entry")
    raise _reject(f"archive member is a {kind}: {item.filename!r}")


def inspect_archive(
    path: Path,
    *,
    policy: ArchivePolicy = DEFAULT_ARCHIVE_POLICY,
    depth: int = 0,
) -> ArchiveInspection:
    """Walk one archive against `policy` without writing a byte.

    Raises ``IngestError`` naming the exact bound or content rule that failed. The
    returned inspection is the only member list any caller needs: extraction and the
    Ultra Librarian script-shape check both read it rather than re-walking the zip.
    """

    path = Path(path)
    limits = policy.limits
    try:
        archive_bytes = path.stat().st_size
    except OSError as exc:
        raise _reject(f"archive cannot be read: {path.name}") from exc
    if archive_bytes > limits.max_archive_bytes:
        raise _reject(
            f"archive is larger than {limits.max_archive_bytes} bytes: {path.name}"
        )
    if depth > limits.max_nested_archive_depth:
        raise _reject(
            f"archive nests deeper than {limits.max_nested_archive_depth} levels: {path.name}"
        )

    members: list[ArchiveMember] = []
    folded: set[str] = set()
    total_expanded = 0
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_members:
                raise _reject(
                    f"archive declares more than {limits.max_members} members: {path.name}"
                )
            for item in infos:
                name = item.filename
                parts = _check_member_name(name, limits)
                key = name.rstrip("/").casefold()
                if key in folded:
                    raise _reject(f"archive has duplicate or case-colliding members: {name!r}")
                folded.add(key)
                _check_member_mode(item)
                if item.flag_bits & 0x1:
                    raise _reject(f"archive member is encrypted and cannot be inspected: {name!r}")
                is_dir = item.is_dir()
                suffix = PurePosixPath(name).suffix.casefold()
                if not is_dir:
                    if item.compress_type not in ALLOWED_COMPRESSION:
                        raise _reject(
                            f"archive member uses unsupported compression: {name!r}"
                        )
                    if item.file_size > limits.max_member_expanded_bytes:
                        raise _reject(
                            f"archive member expands past {limits.max_member_expanded_bytes} "
                            f"bytes: {name!r}"
                        )
                    if policy.require_non_empty_members and item.file_size <= 0:
                        raise _reject(f"archive member is empty: {name!r}")
                    if (
                        item.compress_size
                        and item.file_size / item.compress_size > limits.max_compression_ratio
                    ):
                        raise _reject(
                            f"archive member exceeds a {limits.max_compression_ratio:g}:1 "
                            f"compression ratio: {name!r}"
                        )
                    total_expanded += item.file_size
                    if total_expanded > limits.max_total_expanded_bytes:
                        raise _reject(
                            f"archive expands past {limits.max_total_expanded_bytes} bytes: "
                            f"{path.name}"
                        )
                    if suffix in ARCHIVE_SUFFIXES and depth + 1 > limits.max_nested_archive_depth:
                        raise _reject(
                            f"archive nests deeper than {limits.max_nested_archive_depth} "
                            f"levels: {name!r}"
                        )
                    if policy.reject_executable_content:
                        _check_member_content(archive, item, name, suffix, policy)
                members.append(
                    ArchiveMember(
                        name=name,
                        parts=parts,
                        suffix=suffix,
                        expanded_bytes=0 if is_dir else item.file_size,
                        is_dir=is_dir,
                    )
                )
    except zipfile.BadZipFile as exc:
        raise _reject(f"archive is corrupt: {path.name}") from exc
    except OSError as exc:
        raise _reject(f"archive cannot be read: {path.name}") from exc
    return ArchiveInspection(
        path=path,
        archive_bytes=archive_bytes,
        total_expanded_bytes=total_expanded,
        members=tuple(members),
    )


def _check_member_content(
    archive: zipfile.ZipFile,
    item: zipfile.ZipInfo,
    name: str,
    suffix: str,
    policy: ArchivePolicy,
) -> None:
    """Extension gate, then the leading-byte sniff for a renamed payload."""

    if suffix in PROHIBITED_SUFFIXES and suffix not in policy.reviewed_member_suffixes:
        raise _reject(f"archive member is executable or script content: {name!r}")
    if item.file_size <= 0:
        return
    with archive.open(item) as handle:
        head = handle.read(_MAGIC_PREFIX_BYTES)
    reason = prohibited_reason(head)
    if reason:
        raise _reject(f"archive member is {reason} regardless of its name: {name!r}")


def extract_archive(
    path: Path,
    dst: Path,
    *,
    policy: ArchivePolicy = DEFAULT_ARCHIVE_POLICY,
) -> ArchiveInspection:
    """Inspect, then write each member individually into `dst`.

    ``extractall`` is deliberately absent: it resolves the destination once and
    trusts the central directory's sizes. Here the destination is re-resolved and
    containment re-checked per member, and the written byte count is enforced
    against the same bounds, so a member that lies about its size is truncated into
    a rejection rather than filling the disk.
    """

    inspection = inspect_archive(path, policy=policy)
    limits = policy.limits
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    written_total = 0
    with zipfile.ZipFile(path) as archive:
        for member in inspection.members:
            root = dst.resolve()
            target = (dst / PurePosixPath(member.name)).resolve()
            if target != root and root not in target.parents:
                raise _reject(f"archive member escapes the sandbox: {member.name!r}")
            if member.is_dir:
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(member.name) as source, open(target, "wb") as sink:
                while True:
                    chunk = source.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    written_total += len(chunk)
                    if written > limits.max_member_expanded_bytes:
                        raise _reject(
                            f"archive member wrote past {limits.max_member_expanded_bytes} "
                            f"bytes: {member.name!r}"
                        )
                    if written_total > limits.max_total_expanded_bytes:
                        raise _reject(
                            f"archive wrote past {limits.max_total_expanded_bytes} bytes: "
                            f"{Path(path).name}"
                        )
                    sink.write(chunk)
    return inspection


def unpack_inputs(
    inputs: list[Path],
    workdir: Path,
    *,
    policy: ArchivePolicy = DEFAULT_ARCHIVE_POLICY,
) -> list[Unpacked]:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out: list[Unpacked] = []
    for n, raw in enumerate(inputs):
        origin = Path(raw)
        if not origin.exists():
            raise IngestError(f"input does not exist: {origin}")
        root = workdir / str(n)
        root.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(origin, root, dirs_exist_ok=True)
            out.append(Unpacked(root=root, origin=origin, is_zip=False, sha256=""))
        elif zipfile.is_zipfile(origin):
            extract_archive(origin, root, policy=policy)
            out.append(Unpacked(root=root, origin=origin, is_zip=True, sha256=sha256_of(origin)))
        else:
            # A loose selected file is held to the same content rule as a member: a
            # download named `datasheet.pdf` that is really a PE must not be copied
            # into a sandbox the rest of the pipeline treats as inert data.
            if policy.reject_executable_content:
                suffix = origin.suffix.casefold()
                reason = ""
                if suffix in PROHIBITED_SUFFIXES and suffix not in policy.reviewed_member_suffixes:
                    reason = f"a {suffix} executable or script"
                else:
                    try:
                        with open(origin, "rb") as handle:
                            reason = prohibited_reason(handle.read(_MAGIC_PREFIX_BYTES))
                    except OSError as exc:
                        raise IngestError(f"input cannot be read: {origin}") from exc
                if reason:
                    raise IngestError(f"input is {reason}: {origin.name}")
            shutil.copyfile(origin, root / origin.name)
            out.append(Unpacked(root=root, origin=origin, is_zip=False, sha256=sha256_of(origin)))
    return out


__all__ = [
    "ALLOWED_COMPRESSION",
    "ARCHIVE_SUFFIXES",
    "ArchiveInspection",
    "ArchiveLimits",
    "ArchiveMember",
    "ArchivePolicy",
    "DEFAULT_ARCHIVE_POLICY",
    "DEFAULT_LIMITS",
    "MAX_ARCHIVE_BYTES",
    "MAX_COMPRESSION_RATIO",
    "MAX_DIRECTORY_DEPTH",
    "MAX_MEMBERS",
    "MAX_MEMBER_EXPANDED_BYTES",
    "MAX_NAME_LENGTH",
    "MAX_NESTED_ARCHIVE_DEPTH",
    "MAX_PATH_LENGTH",
    "MAX_TOTAL_EXPANDED_BYTES",
    "PROHIBITED_SUFFIXES",
    "Unpacked",
    "extract_archive",
    "inspect_archive",
    "prohibited_file_reason",
    "prohibited_reason",
    "sha256_of",
    "unpack_inputs",
]
