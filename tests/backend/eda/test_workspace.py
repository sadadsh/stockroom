"""Workspace hygiene: putting the EDA registry's ignore/attributes rules into a REAL repo.

The registry has produced this content since `01fd28f` and nothing wrote it anywhere, which made it
the measured-but-unfixed cause of the owner's KiCad peer-sync failures. Two properties decide whether
writing it is safe, and both are tested here rather than assumed:

  1. Stockroom does not own the user's project files, so an existing `.gitignore` must SURVIVE. The
     generated content lives in a delimited managed block that is rewritten in place.
  2. A `.gitignore` rule does nothing to an already-TRACKED file (verified against git itself), and in
     the owner's repos those files are already committed. Untracking is part of the operation, not a
     follow-up.
"""

from __future__ import annotations

from stockroom.eda import workspace


def test_a_fresh_file_is_just_the_block():
    out = workspace.merge_block("", "alpha\nbeta\n")
    assert workspace.BEGIN in out and workspace.END in out
    assert "alpha" in out and "beta" in out
    assert out.endswith("\n")


def test_existing_user_content_is_preserved_verbatim():
    """The property that makes writing into someone else's project defensible at all."""
    existing = "# my own rules\n*.log\nbuild/\n"
    out = workspace.merge_block(existing, "*.kicad_prl\n")
    assert out.startswith(existing)
    assert "*.kicad_prl" in out


def test_rewriting_the_block_replaces_it_in_place_and_is_idempotent():
    once = workspace.merge_block("# mine\n*.log\n", "*.kicad_prl\n")
    twice = workspace.merge_block(once, "*.kicad_prl\n")
    assert twice == once
    # a CHANGED rule set replaces the old block rather than appending a second one
    changed = workspace.merge_block(once, "*.kicad_prl\nfp-info-cache\n")
    assert changed.count(workspace.BEGIN) == 1
    assert changed.count(workspace.END) == 1
    assert "fp-info-cache" in changed
    assert changed.startswith("# mine\n*.log\n")


def test_content_after_the_block_survives_a_rewrite():
    seeded = workspace.merge_block("# top\n", "old-rule\n") + "# bottom kept\n"
    out = workspace.merge_block(seeded, "new-rule\n")
    assert out.startswith("# top\n")
    assert out.rstrip().endswith("# bottom kept")
    assert "old-rule" not in out and "new-rule" in out


def test_an_unterminated_block_is_left_ALONE_rather_than_guessed():
    """A half-written marker means a previous run died or a human edited it. Appending a second block
    would be wrong and deleting to end-of-file would destroy user content, so the honest move is to
    refuse and say so."""
    broken = "# mine\n" + workspace.BEGIN + "\nstuff\n"
    try:
        workspace.merge_block(broken, "x\n")
    except ValueError as err:
        assert "block" in str(err).lower()
    else:
        raise AssertionError("an unterminated managed block must not be silently repaired")


def test_the_block_says_what_it_is_and_that_it_is_generated():
    out = workspace.merge_block("", "x\n")
    assert "Stockroom" in out
    # A human opening the file has to know an edit inside the markers will be overwritten.
    assert "regenerat" in out.lower() or "do not" in out.lower()


# -- which paths a rule set covers -------------------------------------------


def test_ignored_matches_are_found_for_directory_and_glob_rules():
    rules = ["*.kicad_prl", "fp-info-cache", "*-backups/"]
    paths = [
        "board.kicad_prl", "sub/other.kicad_prl", "fp-info-cache",
        "board-backups/x.zip", "board.kicad_sch", "notes.md",
    ]
    hit = set(workspace.matching(paths, rules))
    assert hit == {"board.kicad_prl", "sub/other.kicad_prl", "fp-info-cache",
                   "board-backups/x.zip"}


def test_a_design_SOURCE_is_never_matched():
    """The one mistake that would be unrecoverable: untracking a user's actual design."""
    rules = ["*.kicad_prl", "fp-info-cache", "*.lck", "*-backups/", "*.kicad_sch-bak"]
    sources = ["board.kicad_sch", "board.kicad_pcb", "sym.kicad_sym", "fp.kicad_mod",
               "board.kicad_pro", "Amp.SchDoc", "Amp.PcbLib"]
    assert workspace.matching(sources, rules) == []
