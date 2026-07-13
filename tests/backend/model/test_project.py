import json

from stockroom.model.project import ProjectRecord, new_project_id


def _sample() -> ProjectRecord:
    return ProjectRecord(
        id="netdeck-main",
        name="NETDECK Main",
        root="/home/sadad/git/NETDECK/main",
        pro_path="main.kicad_pro",
        board_paths=["main.kicad_pcb"],
        sheet_paths=["main.kicad_sch", "power.kicad_sch"],
        git_root="/home/sadad/git/NETDECK",
        audit_digest={"components": 566, "healthy": 480, "inputs_sha": "abc123"},
        registered_at="2026-07-13T00:00:00Z",
    )


def test_round_trip_preserves_every_field():
    p = _sample()
    again = ProjectRecord.from_dict(p.to_dict())
    assert again == p


def test_dumps_is_canonical_json():
    text = _sample().dumps()
    assert text.endswith("\n")
    parsed = json.loads(text)
    # sort_keys => top-level keys alphabetical, so a one-field edit stays a minimal diff.
    assert list(parsed.keys()) == sorted(parsed.keys())
    assert parsed["name"] == "NETDECK Main"
    assert parsed["board_paths"] == ["main.kicad_pcb"]
    assert parsed["audit_digest"]["components"] == 566


def test_loads_is_the_inverse_of_dumps():
    p = _sample()
    assert ProjectRecord.loads(p.dumps()) == p


def test_defaults_are_honest_empties():
    p = ProjectRecord(id="x", name="X", root="/tmp/x")
    d = p.to_dict()
    assert d["pro_path"] == ""
    assert d["board_paths"] == []
    assert d["sheet_paths"] == []
    assert d["git_root"] is None
    assert d["audit_digest"] is None
    # from_dict tolerates a record written before optional keys existed.
    assert ProjectRecord.from_dict({"id": "x", "name": "X", "root": "/tmp/x"}) == p


def test_from_dict_copies_mutable_containers():
    # A record built from a dict must not alias the caller's lists/dicts.
    src = {"id": "x", "name": "X", "root": "/tmp/x", "board_paths": ["a.kicad_pcb"], "audit_digest": {"n": 1}}
    p = ProjectRecord.from_dict(src)
    p.board_paths.append("b.kicad_pcb")
    p.audit_digest["n"] = 2
    assert src["board_paths"] == ["a.kicad_pcb"]
    assert src["audit_digest"] == {"n": 1}


def test_new_project_id_slugifies_the_base(tmp_path):
    # slugify collapses non-alphanumeric runs to underscores; the dedup suffix is -N.
    assert new_project_id(tmp_path, "NETDECK Main") == "netdeck_main"


def test_new_project_id_dedups_against_existing(tmp_path):
    (tmp_path / "netdeck_main.json").write_text("{}", encoding="utf-8")
    assert new_project_id(tmp_path, "NETDECK Main") == "netdeck_main-2"
    (tmp_path / "netdeck_main-2.json").write_text("{}", encoding="utf-8")
    assert new_project_id(tmp_path, "NETDECK Main") == "netdeck_main-3"


def test_new_project_id_falls_back_when_base_slugifies_empty(tmp_path):
    assert new_project_id(tmp_path, "!!!") == "project"
