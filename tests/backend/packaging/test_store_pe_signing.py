from __future__ import annotations

import struct
from pathlib import Path

from packaging.pe_certificate_check import find_invalid_pe_certificates

ROOT = Path(__file__).resolve().parents[3]


def _write_pe(
    path: Path,
    *,
    certificate_offset: int,
    certificate_size: int,
    file_size: int,
) -> None:
    pe_offset = 0x80
    optional_offset = pe_offset + 24
    data = bytearray(file_size)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset : pe_offset + 4] = b"PE\0\0"
    struct.pack_into("<H", data, pe_offset + 4, 0x8664)
    struct.pack_into("<H", data, pe_offset + 20, 0xF0)
    struct.pack_into("<H", data, optional_offset, 0x20B)
    struct.pack_into("<I", data, optional_offset + 108, 16)
    struct.pack_into(
        "<II",
        data,
        optional_offset + 112 + (4 * 8),
        certificate_offset,
        certificate_size,
    )
    if certificate_offset and certificate_offset + 8 <= file_size:
        struct.pack_into(
            "<IHH",
            data,
            certificate_offset,
            certificate_size,
            0x0200,
            0x0002,
        )
    path.write_bytes(data)


def test_store_signability_rejects_a_truncated_pe_certificate(tmp_path: Path) -> None:
    broken = tmp_path / "Runtime" / "broken.dll"
    broken.parent.mkdir()
    _write_pe(
        broken,
        certificate_offset=512,
        certificate_size=128,
        file_size=512,
    )

    issues = find_invalid_pe_certificates(tmp_path)

    assert [(issue.path, issue.reason) for issue in issues] == [
        (Path("Runtime/broken.dll"), "certificate table extends beyond the file")
    ]


def test_store_signability_accepts_unsigned_and_complete_pe_files(tmp_path: Path) -> None:
    unsigned = tmp_path / "unsigned.exe"
    signed = tmp_path / "signed.dll"
    _write_pe(unsigned, certificate_offset=0, certificate_size=0, file_size=512)
    _write_pe(signed, certificate_offset=512, certificate_size=64, file_size=576)

    assert find_invalid_pe_certificates(tmp_path) == ()


def test_packaged_worker_excludes_the_unused_tk_runtime() -> None:
    spec = (ROOT / "packaging" / "stockroom.spec").read_text(encoding="utf-8")

    assert '"tkinter"' in spec
    assert '"_tkinter"' in spec


def test_windows_package_build_fails_closed_on_invalid_pe_certificates() -> None:
    build = (ROOT / "packaging" / "Build-Windows-Package.ps1").read_text(encoding="utf-8")

    assert '$PeCertificateCheck = Join-Path $PackagingRoot "pe_certificate_check.py"' in build
    assert '"python", $PeCertificateCheck, "--root", $stage' in build
