import stat
import zipfile
from pathlib import Path

import pytest

from stockroom.ingest.errors import IngestError
from stockroom.ingest.sandbox import (
    DEFAULT_ARCHIVE_POLICY,
    DEFAULT_LIMITS,
    MAX_COMPRESSION_RATIO,
    MAX_DIRECTORY_DEPTH,
    MAX_MEMBER_EXPANDED_BYTES,
    MAX_MEMBERS,
    MAX_NAME_LENGTH,
    MAX_NESTED_ARCHIVE_DEPTH,
    MAX_PATH_LENGTH,
    MAX_TOTAL_EXPANDED_BYTES,
    ArchiveLimits,
    ArchivePolicy,
    extract_archive,
    inspect_archive,
    sha256_of,
    unpack_inputs,
)


def test_unpack_zip_extracts_into_isolated_root(tmp_path):
    z = tmp_path / "part.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("KiCad/foo.kicad_mod", "(footprint)")
    work = tmp_path / "work"
    [u] = unpack_inputs([z], work)
    assert u.is_zip is True
    assert (u.root / "KiCad" / "foo.kicad_mod").read_text() == "(footprint)"
    assert u.sha256 == sha256_of(z)


def test_unpack_bare_file_copies_into_root(tmp_path):
    f = tmp_path / "sym.kicad_sym"
    f.write_text("(kicad_symbol_lib)")
    [u] = unpack_inputs([f], tmp_path / "work")
    assert u.is_zip is False
    assert (u.root / "sym.kicad_sym").read_text() == "(kicad_symbol_lib)"
    assert u.sha256 == sha256_of(f)


def test_unpack_folder_copies_tree(tmp_path):
    src = tmp_path / "src"
    (src / "KiCAD").mkdir(parents=True)
    (src / "KiCAD" / "a.lib").write_text("x")
    [u] = unpack_inputs([src], tmp_path / "work")
    assert (u.root / "KiCAD" / "a.lib").read_text() == "x"
    assert u.sha256 == ""


def test_unpack_multiple_inputs_get_separate_roots(tmp_path):
    a = tmp_path / "a.kicad_sym"; a.write_text("a")
    b = tmp_path / "b.kicad_sym"; b.write_text("b")
    us = unpack_inputs([a, b], tmp_path / "work")
    assert len(us) == 2
    assert us[0].root != us[1].root


def test_zip_slip_is_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.txt", "pwn")
    with pytest.raises(IngestError):
        unpack_inputs([z], tmp_path / "work")


def test_missing_input_raises(tmp_path):
    with pytest.raises(IngestError):
        unpack_inputs([tmp_path / "nope.zip"], tmp_path / "work")


# --- bounded archive inspection --------------------------------------------
# The sandbox is the only archive walker in the backend, so every bound and every
# refused content class has to be proved HERE. Before this slice the file covered
# zip-slip and nothing else: no bomb, no size, no ratio, no encryption, no nesting.


def _zip(path: Path, members) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)
    return path


def _info(name: str, **fields) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    for key, value in fields.items():
        setattr(info, key, value)
    return info


def test_absolute_member_path_is_rejected(tmp_path):
    z = _zip(tmp_path / "abs.zip", [("/etc/passwd", "x")])
    with pytest.raises(IngestError, match="absolute path"):
        unpack_inputs([z], tmp_path / "work")


def test_windows_drive_qualified_member_is_rejected(tmp_path):
    z = _zip(tmp_path / "drive.zip", [("C:/Windows/System32/config.sam", "x")])
    with pytest.raises(IngestError, match="drive-qualified"):
        unpack_inputs([z], tmp_path / "work")


def test_windows_separator_member_is_rejected(tmp_path):
    """A member written with Windows separators never reaches the filesystem.

    The zip spec allows only forward slashes, so a backslash member is a Windows path
    smuggled through a POSIX-only field. `ZipInfo.__init__` rewrites os.sep, so the name
    is set afterwards -- a hostile writer has no such scruples. CPython's READER then
    normalizes the separators back, which is why this archive is refused as a parent
    reference; the explicit backslash rule guards the same member for any reader that
    does not normalize, and for the loose-file path.
    """
    member = zipfile.ZipInfo("placeholder.txt")
    member.filename = "dir\\..\\..\\escape.txt"
    archive = tmp_path / "back.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(member, "x")
    with pytest.raises(IngestError, match="backslash|parent reference"):
        unpack_inputs([archive], tmp_path / "work")


def test_symlink_member_is_rejected(tmp_path):
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            _info("link.kicad_sym", create_system=3, external_attr=(stat.S_IFLNK | 0o777) << 16),
            "/etc/passwd",
        )
    with pytest.raises(IngestError, match="symbolic link"):
        unpack_inputs([archive], tmp_path / "work")


def test_device_and_fifo_members_are_rejected(tmp_path):
    for label, mode, expected in (
        ("chr", stat.S_IFCHR, "character device"),
        ("blk", stat.S_IFBLK, "block device"),
        ("fifo", stat.S_IFIFO, "FIFO"),
    ):
        archive = tmp_path / f"{label}.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(
                _info(f"{label}.dat", create_system=3, external_attr=(mode | 0o666) << 16),
                "x",
            )
        with pytest.raises(IngestError, match=expected):
            unpack_inputs([archive], tmp_path / f"work-{label}")


def _mark_encrypted(path: Path) -> None:
    """Set general-purpose bit 0 on every header. Python cannot write an encrypted zip,
    and `_open_to_write` clears the flag, so the bytes are patched after the fact."""
    data = bytearray(path.read_bytes())
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        index = data.find(signature)
        while index != -1:
            data[index + offset] |= 0x01
            index = data.find(signature, index + 1)
    path.write_bytes(bytes(data))


def test_encrypted_member_is_rejected(tmp_path):
    # The general-purpose flag is what a reader trusts: a member claiming encryption
    # cannot be inspected, so it is refused rather than extracted unexamined.
    archive = _zip(tmp_path / "encrypted.zip", [("secret.kicad_sym", "x")])
    _mark_encrypted(archive)
    with pytest.raises(IngestError, match="encrypted"):
        unpack_inputs([archive], tmp_path / "work")


def test_corrupt_archive_is_rejected(tmp_path):
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    with pytest.raises(IngestError, match="corrupt"):
        inspect_archive(broken)


def test_compression_ratio_bomb_is_rejected_at_the_default_limits(tmp_path):
    # A real decompression bomb: 8 MiB of zeros deflates to a few kilobytes, far past
    # the 100:1 ratio real CAD text ever reaches. No reduced limits, no fixture tricks.
    archive = _zip(tmp_path / "bomb.zip", [("payload.kicad_sym", b"\0" * (8 * 1024 * 1024))])
    with pytest.raises(IngestError, match="compression ratio"):
        unpack_inputs([archive], tmp_path / "work")


def test_total_expanded_bytes_is_bounded(tmp_path):
    tiny = ArchivePolicy(
        limits=ArchiveLimits(max_total_expanded_bytes=64, max_compression_ratio=10_000)
    )
    archive = _zip(
        tmp_path / "big.zip",
        [(f"part{index}.kicad_sym", "x" * 32) for index in range(4)],
    )
    with pytest.raises(IngestError, match="expands past 64 bytes"):
        unpack_inputs([archive], tmp_path / "work", policy=tiny)


def test_per_member_expanded_bytes_is_bounded(tmp_path):
    tiny = ArchivePolicy(
        limits=ArchiveLimits(max_member_expanded_bytes=16, max_compression_ratio=10_000)
    )
    archive = _zip(tmp_path / "member.zip", [("part.kicad_sym", "x" * 64)])
    with pytest.raises(IngestError, match="expands past 16 bytes"):
        unpack_inputs([archive], tmp_path / "work", policy=tiny)


def test_member_count_is_bounded(tmp_path):
    archive = _zip(
        tmp_path / "many.zip",
        [(f"m{index}.txt", "x") for index in range(MAX_MEMBERS + 1)],
    )
    with pytest.raises(IngestError, match="more than"):
        unpack_inputs([archive], tmp_path / "work")


def test_directory_depth_is_bounded(tmp_path):
    deep = "/".join(f"d{index}" for index in range(MAX_DIRECTORY_DEPTH + 1)) + "/x.kicad_sym"
    archive = _zip(tmp_path / "deep.zip", [(deep, "x")])
    with pytest.raises(IngestError, match="nested deeper"):
        unpack_inputs([archive], tmp_path / "work")


def test_member_path_length_is_bounded(tmp_path):
    long_path = "/".join(["dir"] * ((MAX_PATH_LENGTH // 4) + 2)) + "/x.kicad_sym"
    archive = _zip(tmp_path / "long.zip", [(long_path, "x")])
    with pytest.raises(IngestError, match="path is longer"):
        unpack_inputs([archive], tmp_path / "work")


def test_single_filename_length_is_bounded(tmp_path):
    # Isolated from the path bound so the FILENAME rule is the one that fires.
    roomy = ArchivePolicy(limits=ArchiveLimits(max_path_length=4096))
    archive = _zip(tmp_path / "name.zip", [("a" * (MAX_NAME_LENGTH + 10) + ".kicad_sym", "x")])
    with pytest.raises(IngestError, match="name is longer"):
        unpack_inputs([archive], tmp_path / "work", policy=roomy)


def test_nested_archive_depth_is_bounded(tmp_path):
    strict = ArchivePolicy(limits=ArchiveLimits(max_nested_archive_depth=0))
    inner = _zip(tmp_path / "inner.zip", [("a.kicad_sym", "x")])
    archive = _zip(tmp_path / "outer.zip", [("altium/inner.zip", inner.read_bytes())])
    with pytest.raises(IngestError, match="nests deeper"):
        unpack_inputs([archive], tmp_path / "work", policy=strict)
    # One level is the measured real shape and stays allowed.
    [unpacked] = unpack_inputs([archive], tmp_path / "work-ok")
    assert (unpacked.root / "altium" / "inner.zip").is_file()


def test_archive_input_size_is_bounded(tmp_path):
    tiny = ArchivePolicy(limits=ArchiveLimits(max_archive_bytes=16))
    archive = _zip(tmp_path / "size.zip", [("a.kicad_sym", "x" * 512)])
    with pytest.raises(IngestError, match="larger than 16 bytes"):
        unpack_inputs([archive], tmp_path / "work", policy=tiny)


def test_executable_member_is_rejected(tmp_path):
    archive = _zip(tmp_path / "exe.zip", [("KiCad/a.kicad_sym", "x"), ("setup.exe", "x")])
    with pytest.raises(IngestError, match="executable or script"):
        unpack_inputs([archive], tmp_path / "work")


def test_script_member_is_rejected(tmp_path):
    archive = _zip(tmp_path / "ps1.zip", [("install.ps1", "Write-Host hi")])
    with pytest.raises(IngestError, match="executable or script"):
        unpack_inputs([archive], tmp_path / "work")


def test_shortcut_member_is_rejected_by_name_and_by_content(tmp_path):
    named = _zip(tmp_path / "lnk.zip", [("open me.lnk", "x")])
    with pytest.raises(IngestError, match="executable or script"):
        unpack_inputs([named], tmp_path / "work-a")
    disguised = _zip(
        tmp_path / "disguised.zip",
        [("notes.txt", b"L\x00\x00\x00\x01\x14\x02\x00rest")],
    )
    with pytest.raises(IngestError, match="Windows shortcut"):
        unpack_inputs([disguised], tmp_path / "work-b")


def test_extension_content_mismatch_is_rejected(tmp_path):
    # A `.step` whose leading bytes are a PE image cannot be safely identified as CAD.
    archive = _zip(tmp_path / "mismatch.zip", [("model.step", b"MZ\x90\x00payload")])
    with pytest.raises(IngestError, match="Windows executable"):
        unpack_inputs([archive], tmp_path / "work")


def test_a_loose_executable_input_is_rejected_too(tmp_path):
    payload = tmp_path / "datasheet.pdf"
    payload.write_bytes(b"MZ\x90\x00still a binary")
    with pytest.raises(IngestError, match="Windows executable"):
        unpack_inputs([payload], tmp_path / "work")


def test_reviewed_member_suffixes_are_the_only_script_exemption(tmp_path):
    archive = _zip(tmp_path / "ul.zip", [("AltiumDesigner/UL_Import.pas", "Begin End.")])
    with pytest.raises(IngestError, match="executable or script"):
        unpack_inputs([archive], tmp_path / "work-default")
    reviewed = ArchivePolicy(reviewed_member_suffixes=frozenset({".pas"}))
    [unpacked] = unpack_inputs([archive], tmp_path / "work-reviewed", policy=reviewed)
    assert (unpacked.root / "AltiumDesigner" / "UL_Import.pas").is_file()
    # The exemption covers the EXTENSION only: a reviewed suffix carrying a PE is still refused.
    smuggled = _zip(tmp_path / "smuggled.zip", [("AltiumDesigner/UL_Import.pas", b"MZ\x90\x00")])
    with pytest.raises(IngestError, match="Windows executable"):
        unpack_inputs([smuggled], tmp_path / "work-smuggled", policy=reviewed)


def test_a_pretty_directory_and_its_members_survive_extraction(tmp_path):
    archive = _zip(
        tmp_path / "vendor.zip",
        [
            ("KiCADv6/2026-01-01.kicad_sym", "(kicad_symbol_lib)"),
            ("KiCADv6/MyPart.pretty/VarA.kicad_mod", "(footprint)"),
            ("KiCADv6/MyPart.pretty/VarB.kicad_mod", "(footprint)"),
            ("MyPart.step", "ISO-10303-21;"),
            ("MyPart.pdf", "%PDF-1.4"),
            ("README.txt", "supporting"),
        ],
    )
    [unpacked] = unpack_inputs([archive], tmp_path / "work")
    pretty = unpacked.root / "KiCADv6" / "MyPart.pretty"
    assert pretty.is_dir()
    assert sorted(path.name for path in pretty.iterdir()) == ["VarA.kicad_mod", "VarB.kicad_mod"]
    assert (unpacked.root / "MyPart.pdf").is_file()


def test_inspection_reports_the_members_without_writing_anything(tmp_path):
    archive = _zip(tmp_path / "look.zip", [("KiCad/a.kicad_sym", "x" * 10)])
    inspection = inspect_archive(archive)
    assert [member.name for member in inspection.files] == ["KiCad/a.kicad_sym"]
    assert inspection.total_expanded_bytes == 10
    assert not (tmp_path / "look").exists()


def test_extraction_writes_each_member_and_returns_the_inspection(tmp_path):
    archive = _zip(tmp_path / "one.zip", [("KiCad/a.kicad_sym", "sym")])
    inspection = extract_archive(archive, tmp_path / "out")
    assert (tmp_path / "out" / "KiCad" / "a.kicad_sym").read_text() == "sym"
    assert inspection.archive_bytes == archive.stat().st_size


def test_the_default_policy_wires_the_named_limits():
    limits = DEFAULT_ARCHIVE_POLICY.limits
    assert limits == DEFAULT_LIMITS
    assert limits.max_members == MAX_MEMBERS
    assert limits.max_member_expanded_bytes == MAX_MEMBER_EXPANDED_BYTES
    assert limits.max_total_expanded_bytes == MAX_TOTAL_EXPANDED_BYTES
    assert limits.max_compression_ratio == MAX_COMPRESSION_RATIO
    assert limits.max_path_length == MAX_PATH_LENGTH
    assert limits.max_name_length == MAX_NAME_LENGTH
    assert limits.max_directory_depth == MAX_DIRECTORY_DEPTH
    assert limits.max_nested_archive_depth == MAX_NESTED_ARCHIVE_DEPTH
    assert DEFAULT_ARCHIVE_POLICY.reject_executable_content is True
    assert DEFAULT_ARCHIVE_POLICY.reviewed_member_suffixes == frozenset()


def test_extractall_is_never_called_on_untrusted_input():
    """One bounded extractor, and no way around it.

    `extractall` resolves the destination once and trusts the central directory's
    sizes, which is exactly what the bounds above exist to stop. If it reappears
    anywhere in the backend, those bounds are decoration.
    """
    backend = Path(__file__).resolve().parents[3] / "app" / "backend" / "stockroom"
    offenders = [
        path.relative_to(backend).as_posix()
        for path in backend.rglob("*.py")
        if "extractall(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_sandbox_is_the_only_module_that_walks_an_archive_for_safety():
    """Archive-safety fields belong to one implementation.

    `capture/classify.py` reads member NAMES to classify a bundle and is allowed to.
    What must not exist twice is the safety walk itself: the code reasoning about
    encryption flags, compression methods and unix mode bits.
    """
    backend = Path(__file__).resolve().parents[3] / "app" / "backend" / "stockroom"
    markers = ("flag_bits", "compress_type", "external_attr", "create_system")
    offenders = sorted(
        path.relative_to(backend).as_posix()
        for path in backend.rglob("*.py")
        if any(marker in path.read_text(encoding="utf-8") for marker in markers)
    )
    assert offenders == ["ingest/sandbox.py"]
