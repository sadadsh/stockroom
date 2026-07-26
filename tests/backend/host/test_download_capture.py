import os
from pathlib import Path

from stockroom.host.download_capture import DownloadsWatch, default_downloads_dir


def _touch(path: Path, mtime: float, content: bytes = b"x") -> None:
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


# -- DownloadsWatch.poll() --


def test_zip_written_after_watch_start_is_returned(tmp_path):
    started_at = 1_000.0
    zip_path = tmp_path / "part-cad.zip"
    _touch(zip_path, started_at + 5)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() == zip_path


def test_zip_present_before_the_watch_is_not_returned(tmp_path):
    started_at = 1_000.0
    zip_path = tmp_path / "old.zip"
    _touch(zip_path, started_at - 50)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() is None


def test_non_zip_file_is_ignored(tmp_path):
    started_at = 1_000.0
    _touch(tmp_path / "notes.pdf", started_at + 1)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() is None


def test_zip_suffix_match_is_case_insensitive(tmp_path):
    started_at = 1_000.0
    zip_path = tmp_path / "PART.ZIP"
    _touch(zip_path, started_at + 1)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() == zip_path


def test_a_directory_named_like_a_zip_is_not_mistaken_for_a_file(tmp_path):
    started_at = 1_000.0
    (tmp_path / "looks-like-a.zip").mkdir()
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() is None


def test_newest_of_several_qualifying_zips_is_chosen(tmp_path):
    started_at = 1_000.0
    older = tmp_path / "a.zip"
    newer = tmp_path / "b.zip"
    _touch(older, started_at + 1)
    _touch(newer, started_at + 5)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() == newer


def test_poll_does_not_return_the_same_zip_twice(tmp_path):
    started_at = 1_000.0
    zip_path = tmp_path / "part.zip"
    _touch(zip_path, started_at + 1)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() == zip_path
    assert watch.poll() is None


def test_a_later_poll_can_surface_a_second_newly_arrived_zip(tmp_path):
    started_at = 1_000.0
    first = tmp_path / "first.zip"
    _touch(first, started_at + 1)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() == first

    second = tmp_path / "second.zip"
    _touch(second, started_at + 2)
    assert watch.poll() == second
    assert watch.poll() is None


def test_poll_returns_none_when_the_downloads_dir_does_not_exist(tmp_path):
    missing = tmp_path / "does-not-exist"
    watch = DownloadsWatch(missing, 0.0)
    assert watch.poll() is None


def test_a_future_dated_mtime_is_treated_as_untrustworthy_and_skipped(tmp_path):
    # A file whose mtime somehow reads AFTER the current `now()` (clock skew on a
    # mapped drive, a corrupted timestamp) is not trustworthy evidence that it "just
    # appeared" - skip it rather than surface it as the definitive newest capture.
    started_at = 1_000.0
    zip_path = tmp_path / "weird.zip"
    _touch(zip_path, started_at + 500)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() is None


# -- widened suffix matching: loose KiCad + Altium asset files, not just *.zip --


def test_loose_altium_schlib_after_start_is_returned(tmp_path):
    started_at = 1_000.0
    schlib = tmp_path / "BQ24074.SchLib"
    _touch(schlib, started_at + 3)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() == schlib


def test_loose_altium_pcblib_and_intlib_after_start_are_returned(tmp_path):
    started_at = 1_000.0
    pcblib = tmp_path / "SOIC8.PcbLib"
    _touch(pcblib, started_at + 2)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() == pcblib

    intlib = tmp_path / "part.IntLib"
    _touch(intlib, started_at + 4)
    assert watch.poll() == intlib


def test_loose_kicad_sym_footprint_and_model_after_start_are_returned(tmp_path):
    started_at = 1_000.0
    for i, name in enumerate(("a.kicad_sym", "a.kicad_mod", "a.step", "a.STP", "a.wrl"), start=1):
        f = tmp_path / name
        _touch(f, started_at + i)
        watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 20)
        # each poll on a fresh watch returns the newest qualifying asset so far
        assert watch.poll() == f


def test_a_non_asset_file_is_still_ignored(tmp_path):
    started_at = 1_000.0
    for name in ("notes.txt", "readme.md", "part.pdf", "image.png"):
        _touch(tmp_path / name, started_at + 1)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() is None


def test_widened_suffix_match_is_case_insensitive(tmp_path):
    started_at = 1_000.0
    schlib = tmp_path / "PART.SCHLIB"
    _touch(schlib, started_at + 1)
    watch = DownloadsWatch(tmp_path, started_at, now=lambda: started_at + 10)
    assert watch.poll() == schlib


# -- DownloadsWatch.start() --


def test_start_classmethod_arms_the_watch_at_the_injected_now(tmp_path):
    clock = {"t": 1_000.0}
    _touch(tmp_path / "already-there.zip", clock["t"] - 1)  # existed strictly before arming

    watch = DownloadsWatch.start(tmp_path, now=lambda: clock["t"])
    assert watch.poll() is None  # pre-existing file is not "after the watch started"

    clock["t"] += 5
    new_zip = tmp_path / "new.zip"
    _touch(new_zip, clock["t"])
    assert watch.poll() == new_zip


# -- default_downloads_dir() --


def test_default_downloads_dir_uses_home_on_posix(monkeypatch):
    monkeypatch.setattr("stockroom.host.download_capture._os_name", lambda: "posix")
    assert default_downloads_dir() == Path.home() / "Downloads"


def test_default_downloads_dir_uses_userprofile_on_windows(monkeypatch, tmp_path):
    # NOTE: faking the WINDOWS branch through _os_name(), never the real os.name -
    # pathlib.Path dispatches its concrete subclass off the REAL os.name at
    # construction time, so patching os.name itself makes Path(...) raise
    # NotImplementedError ("cannot instantiate WindowsPath") on this Linux runner.
    monkeypatch.setattr("stockroom.host.download_capture._os_name", lambda: "nt")
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert default_downloads_dir() == tmp_path / "Downloads"


def test_default_downloads_dir_falls_back_to_home_on_windows_without_userprofile(monkeypatch):
    monkeypatch.setattr("stockroom.host.download_capture._os_name", lambda: "nt")
    monkeypatch.delenv("USERPROFILE", raising=False)
    assert default_downloads_dir() == Path.home() / "Downloads"
