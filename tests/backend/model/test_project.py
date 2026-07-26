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


def test_eda_defaults_to_kicad_and_round_trips():
    # EDA-neutral projects: the record says which EDA owns the files. A record written
    # before the field existed reads as kicad (every registration then WAS KiCad).
    p = ProjectRecord(id="x", name="X", root="/tmp/x")
    assert p.eda == "kicad"
    assert p.to_dict()["eda"] == "kicad"
    assert ProjectRecord.from_dict({"id": "x", "name": "X", "root": "/tmp/x"}).eda == "kicad"
    alt = ProjectRecord(id="y", name="Y", root="/tmp/y", eda="altium")
    assert ProjectRecord.from_dict(alt.to_dict()).eda == "altium"
    assert ProjectRecord.loads(alt.dumps()) == alt


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


# -- durable placement bindings (punch 17) -------------------------------------


def test_bindings_round_trip_per_tool():
    """A project record carries which library part each PLACEMENT is bound to, keyed by the
    EDA tool, so an Altium binding and a KiCad binding can never be confused for each other."""
    p = ProjectRecord(id="p", name="P", root="/tmp/p",
                      bindings={"altium": {"UID-1": "stm32f405", "UID-2": "r10k"}})
    back = ProjectRecord.loads(p.dumps())
    assert back.bindings == {"altium": {"UID-1": "stm32f405", "UID-2": "r10k"}}


def test_bindings_default_to_empty_and_read_from_a_record_written_before_they_existed():
    # Every project record on disk predates this field; reading one must not explode.
    assert ProjectRecord(id="p", name="P", root="/tmp/p").bindings == {}
    old = '{"id": "p", "name": "P", "root": "/tmp/p"}'
    assert ProjectRecord.loads(old).bindings == {}


def test_bindings_are_copied_not_aliased():
    src = {"id": "x", "name": "X", "root": "/tmp/x", "bindings": {"kicad": {"u1": "r10k"}}}
    p = ProjectRecord.from_dict(src)
    p.bindings["kicad"]["u2"] = "r47k"
    assert src["bindings"] == {"kicad": {"u1": "r10k"}}
    out = p.to_dict()
    out["bindings"]["kicad"]["u3"] = "c100n"
    assert p.bindings["kicad"] == {"u1": "r10k", "u2": "r47k"}
