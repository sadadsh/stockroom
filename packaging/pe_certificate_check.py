"""Reject malformed PE certificate tables before Microsoft Store signing.

The Store re-signs submitted MSIX packages. A malformed Authenticode table in
any bundled PE makes that signing step fail with ``0x800700C1`` even when the
outer MSIX is intentionally unsigned. This checker uses only the standard
library so the Windows packaging gate can validate the complete staged tree.
"""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path

_PE_SIGNATURE = b"PE\0\0"
_PE32_MAGIC = 0x10B
_PE32_PLUS_MAGIC = 0x20B
_SECURITY_DIRECTORY_INDEX = 4


@dataclass(frozen=True)
class PeCertificateIssue:
    path: Path
    reason: str


def _read_at(path: Path, offset: int, length: int) -> bytes:
    with path.open("rb") as stream:
        stream.seek(offset)
        return stream.read(length)


def _certificate_issue(path: Path) -> str | None:
    file_size = path.stat().st_size
    if file_size < 64:
        return None
    dos_header = _read_at(path, 0, 64)
    if dos_header[:2] != b"MZ":
        return None

    pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
    coff_header = _read_at(path, pe_offset, 24)
    if len(coff_header) != 24 or coff_header[:4] != _PE_SIGNATURE:
        return "MZ file has no complete PE header"

    optional_size = struct.unpack_from("<H", coff_header, 20)[0]
    optional_header = _read_at(path, pe_offset + 24, optional_size)
    if len(optional_header) != optional_size or optional_size < 2:
        return "PE optional header is truncated"

    magic = struct.unpack_from("<H", optional_header, 0)[0]
    if magic == _PE32_MAGIC:
        directory_offset = 96
        directory_count_offset = 92
    elif magic == _PE32_PLUS_MAGIC:
        directory_offset = 112
        directory_count_offset = 108
    else:
        return "PE optional header has an unsupported magic value"

    if optional_size < directory_count_offset + 4:
        return "PE optional header has no data-directory count"
    directory_count = struct.unpack_from("<I", optional_header, directory_count_offset)[0]
    if directory_count <= _SECURITY_DIRECTORY_INDEX:
        return None

    security_offset = directory_offset + (_SECURITY_DIRECTORY_INDEX * 8)
    if optional_size < security_offset + 8:
        return "PE security directory is truncated"
    certificate_offset, certificate_size = struct.unpack_from(
        "<II", optional_header, security_offset
    )
    if certificate_offset == 0 and certificate_size == 0:
        return None
    if certificate_offset == 0 or certificate_size == 0:
        return "certificate table offset and size disagree"
    if certificate_offset % 8:
        return "certificate table offset is not 8-byte aligned"
    if certificate_size < 8:
        return "certificate table is smaller than WIN_CERTIFICATE"
    if certificate_offset + certificate_size > file_size:
        return "certificate table extends beyond the file"

    remaining = certificate_size
    cursor = certificate_offset
    while remaining:
        if remaining < 8:
            return "certificate table ends with a partial WIN_CERTIFICATE header"
        header = _read_at(path, cursor, 8)
        certificate_length = struct.unpack_from("<I", header, 0)[0]
        if certificate_length < 8 or certificate_length > remaining:
            return "WIN_CERTIFICATE length is invalid"
        aligned_length = (certificate_length + 7) & ~7
        if aligned_length > remaining:
            return "WIN_CERTIFICATE alignment extends beyond the table"
        cursor += aligned_length
        remaining -= aligned_length
    return None


def find_invalid_pe_certificates(root: Path) -> tuple[PeCertificateIssue, ...]:
    root = Path(root).resolve(strict=True)
    issues: list[PeCertificateIssue] = []
    for path in sorted(
        (candidate for candidate in root.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        reason = _certificate_issue(path)
        if reason is not None:
            issues.append(PeCertificateIssue(path.relative_to(root), reason))
    return tuple(issues)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    issues = find_invalid_pe_certificates(args.root)
    if not issues:
        return 0
    for issue in issues:
        print(f"{issue.path.as_posix()}: {issue.reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
