"""Applying workspace hygiene to a real git repo (Batch 2, the measured cause of the owner's
KiCad peer-sync failures).

The operation is deliberately TWO-part and atomic: refresh the managed block in `.gitignore` /
`.gitattributes`, AND untrack every already-committed path those rules now cover. Verified against
git: an ignore rule has no effect on a tracked file, so writing the file alone would have committed
something and changed nothing the owner can observe.
"""

from __future__ import annotations

import shutil

import pytest

from stockroom.eda import workspace
from stockroom.mutation.hygiene import apply_hygiene, hygiene_preview
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _repo(tmp_path, files):
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    repo.init()
    written = []
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        written.append(p)
    repo.commit("seed", written)
    return root, repo


def test_the_per_user_files_a_peer_conflicts_on_are_untracked_and_kept_on_disk(tmp_path):
    root, repo = _repo(tmp_path, {
        "board.kicad_sch": "(kicad_sch)\n",
        "board.kicad_prl": '{"window": {}}\n',
        "fp-info-cache": "cache\n",
    })
    result = apply_hygiene(root, ["kicad"], repo=repo)

    tracked = set(repo._run("ls-files").stdout.split())
    assert "board.kicad_prl" not in tracked
    assert "fp-info-cache" not in tracked
    # the DESIGN source is untouched, which is the one mistake that would be unrecoverable
    assert "board.kicad_sch" in tracked
    # untracking leaves the user's local state alone
    assert (root / "board.kicad_prl").exists()
    assert sorted(result["untracked"]) == ["board.kicad_prl", "fp-info-cache"]
    assert result["committed"]


def test_the_rules_actually_take_effect_for_a_peer(tmp_path):
    """The end the owner cares about: after this, touching the per-user file produces NOTHING for
    git to conflict on. Asserted through git's own status, not through our own belief."""
    root, repo = _repo(tmp_path, {"board.kicad_sch": "(kicad_sch)\n",
                                  "board.kicad_prl": "before\n"})
    apply_hygiene(root, ["kicad"], repo=repo)
    (root / "board.kicad_prl").write_text("a peer's window layout\n", encoding="utf-8")
    assert repo.status_porcelain() == []


def test_an_existing_user_gitignore_survives(tmp_path):
    root, repo = _repo(tmp_path, {"board.kicad_sch": "(kicad_sch)\n",
                                  ".gitignore": "# mine\nsecrets.env\n"})
    apply_hygiene(root, ["kicad"], repo=repo)
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("# mine\nsecrets.env\n")
    assert "*.kicad_prl" in text
    assert workspace.BEGIN in text


def test_running_it_twice_changes_nothing_and_commits_nothing(tmp_path):
    root, repo = _repo(tmp_path, {"board.kicad_sch": "(kicad_sch)\n",
                                  "board.kicad_prl": "x\n"})
    apply_hygiene(root, ["kicad"], repo=repo)
    head = repo.head()
    before = (root / ".gitignore").read_text(encoding="utf-8")
    again = apply_hygiene(root, ["kicad"], repo=repo)
    assert repo.head() == head
    assert again["committed"] is None
    assert again["untracked"] == []
    assert (root / ".gitignore").read_text(encoding="utf-8") == before


def test_a_preview_reports_the_same_work_without_touching_anything(tmp_path):
    root, repo = _repo(tmp_path, {"board.kicad_sch": "(kicad_sch)\n",
                                  "board.kicad_prl": "x\n", "fp-info-cache": "c\n"})
    head = repo.head()
    preview = hygiene_preview(root, ["kicad"], repo=repo)
    assert sorted(preview["untracked"]) == ["board.kicad_prl", "fp-info-cache"]
    assert preview["writes"] == [".gitattributes", ".gitignore"]
    assert repo.head() == head
    assert not (root / ".gitignore").exists()
    # and what it PROMISED is what applying then does
    applied = apply_hygiene(root, ["kicad"], repo=repo)
    assert sorted(applied["untracked"]) == sorted(preview["untracked"])


def test_altium_binaries_are_marked_so_git_refuses_to_auto_merge_them(tmp_path):
    root, repo = _repo(tmp_path, {"Amp.SchDoc": "binary-ish\n"})
    apply_hygiene(root, ["altium"], repo=repo)
    attrs = (root / ".gitattributes").read_text(encoding="utf-8")
    assert "*.SchDoc binary" in attrs
    assert "*.PcbLib binary" in attrs
    # the DbLib is INI text and must stay diffable; marking it binary would destroy review
    assert "*.DbLib binary" not in attrs
    assert "*.DbLib text eol=lf" in attrs


def test_a_repo_with_an_unterminated_block_refuses_rather_than_guessing(tmp_path):
    root, repo = _repo(tmp_path, {
        "board.kicad_sch": "(kicad_sch)\n",
        ".gitignore": "# mine\n" + workspace.BEGIN + "\nhalf\n",
    })
    with pytest.raises(ValueError, match="managed block"):
        apply_hygiene(root, ["kicad"], repo=repo)
    # nothing half-applied
    assert (root / ".gitignore").read_text(encoding="utf-8").endswith("half\n")


def test_foreign_STAGED_work_is_refused_before_anything_is_written(tmp_path):
    """`commit_staged` commits the whole index, so anything already staged would be swept into the
    hygiene commit. That is the real hazard and it is refused."""
    root, repo = _repo(tmp_path, {"board.kicad_sch": "(kicad_sch)\n", "board.kicad_prl": "x\n"})
    (root / "board.kicad_sch").write_text("(kicad_sch (edited))\n", encoding="utf-8")
    repo._run("add", "--", str(root / "board.kicad_sch"))
    with pytest.raises(ValueError, match="staged"):
        apply_hygiene(root, ["kicad"], repo=repo)
    assert not (root / ".gitignore").exists()


def test_an_uncommitted_edit_to_a_hygiene_FILE_is_refused(tmp_path):
    """Our merge reads the file's current text, so committing it would carry the user's unfinished
    edit into a Stockroom commit they did not make."""
    root, repo = _repo(tmp_path, {"board.kicad_sch": "(kicad_sch)\n",
                                  ".gitignore": "# mine\n"})
    (root / ".gitignore").write_text("# mine\n# half-written thought\n", encoding="utf-8")
    with pytest.raises(ValueError, match="uncommitted"):
        apply_hygiene(root, ["kicad"], repo=repo)


def test_UNRELATED_uncommitted_work_does_not_block_the_sync(tmp_path):
    """The library repo always has in-progress and regenerated files lying around. Refusing on any
    dirt at all would mean hygiene could never run on a real library, and none of that dirt can
    reach the commit: untracked files are not in the index, and only our own paths get staged."""
    root, repo = _repo(tmp_path, {"board.kicad_sch": "(kicad_sch)\n", "board.kicad_prl": "x\n"})
    (root / "board.kicad_sch").write_text("(kicad_sch (mid-edit))\n", encoding="utf-8")
    (root / "scratch.txt").write_text("untracked\n", encoding="utf-8")

    result = apply_hygiene(root, ["kicad"], repo=repo)
    assert result["untracked"] == ["board.kicad_prl"]
    # the user's in-progress edit is STILL uncommitted, exactly as they left it
    assert " M board.kicad_sch" in repo.status_porcelain()
    assert "(mid-edit)" in (root / "board.kicad_sch").read_text(encoding="utf-8")
    show = repo._run("show", "--stat", "--name-only", "--format=", "HEAD").stdout
    assert "board.kicad_sch" not in show
    assert "scratch.txt" not in show


# -- wired into the project surface -------------------------------------------


def test_project_ops_syncs_hygiene_for_the_projects_own_eda(tmp_path):
    """Registry-generic by construction: the rules written are the ones the project's OWN tool
    declares, so an Altium project never inherits KiCad's per-user rules and vice versa."""
    from stockroom.mutation.project_ops import ProjectOps
    from stockroom.store.project_store import ProjectStore

    lib = tmp_path / "lib"
    lib.mkdir()
    librepo = GitRepo(lib)
    librepo.init()
    (lib / "seed.txt").write_text("s", encoding="utf-8")
    librepo.commit("seed", [lib / "seed.txt"])
    ops = ProjectOps(ProjectStore(lib / ".projects", librepo))

    root, _prepo = _repo(tmp_path, {
        "board.kicad_pro": "{}\n",
        "board.kicad_sch": "(kicad_sch)\n",
        "board.kicad_prl": "state\n",
    })
    rec = ops.register(root)

    preview = ops.hygiene_read(rec.id)
    assert preview["untracked"] == ["board.kicad_prl"]
    assert preview["eda"] == "kicad"

    result = ops.hygiene_apply(rec.id)
    assert result["untracked"] == ["board.kicad_prl"]
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert "*.kicad_prl" in text
    # KiCad's rules only; an Altium rule here would be a leak from the wrong adapter.
    assert "History/" not in text


def test_hygiene_on_a_project_with_no_git_is_an_honest_refusal(tmp_path):
    from stockroom.mutation.project_ops import ProjectOps
    from stockroom.store.project_store import ProjectStore

    lib = tmp_path / "lib"
    lib.mkdir()
    librepo = GitRepo(lib)
    librepo.init()
    (lib / "seed.txt").write_text("s", encoding="utf-8")
    librepo.commit("seed", [lib / "seed.txt"])
    ops = ProjectOps(ProjectStore(lib / ".projects", librepo))

    plain = tmp_path / "nogit"
    plain.mkdir()
    (plain / "board.kicad_pro").write_text("{}\n", encoding="utf-8")
    (plain / "board.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")
    rec = ops.register(plain)
    with pytest.raises(ValueError, match="git"):
        ops.hygiene_apply(rec.id)


def test_the_LIBRARY_repo_gets_every_registered_tools_rules(tmp_path):
    """The library holds assets for every EDA tool at once, so it takes the union rather than one
    tool's set. A per-project sync would never cover it, and a peer cloning the library is exactly
    who inherits a committed `fp-info-cache`."""
    from stockroom.eda.registry import all_tools

    root, repo = _repo(tmp_path, {
        "Stockroom/symbols/SR-Resistors.kicad_sym": "(kicad_symbol_lib)\n",
        "Stockroom/altium/Stockroom.DbLib": "[DatabaseLinks]\n",
        "Stockroom/fp-info-cache": "cache\n",
    })
    result = apply_hygiene(root, [t.key for t in all_tools()], repo=repo)
    assert result["untracked"] == ["Stockroom/fp-info-cache"]
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    attrs = (root / ".gitattributes").read_text(encoding="utf-8")
    assert "*.kicad_prl" in ignore and "History/" in ignore      # both adapters contributed
    assert "*.PcbLib binary" in attrs and "*.kicad_sch text eol=lf" in attrs
    # the library's real assets stay tracked
    tracked = set(repo._run("ls-files").stdout.split())
    assert "Stockroom/symbols/SR-Resistors.kicad_sym" in tracked
    assert "Stockroom/altium/Stockroom.DbLib" in tracked


def test_library_ops_exposes_the_same_two_step(tmp_path):
    from stockroom.mutation.library_ops import LibraryOps
    from stockroom.store.profile import Profile

    root, repo = _repo(tmp_path, {"Stockroom/parts/.gitkeep": "",
                                  "Stockroom/fp-info-cache": "cache\n"})
    ops = LibraryOps(Profile("Stockroom", root / "Stockroom"), repo)
    assert ops.hygiene_read()["untracked"] == ["Stockroom/fp-info-cache"]
    assert ops.hygiene_apply()["untracked"] == ["Stockroom/fp-info-cache"]
    assert ops.hygiene_apply()["committed"] is None  # idempotent
