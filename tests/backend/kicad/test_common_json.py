import json
import shutil

from stockroom.kicad.common_json import read_env_var, write_env_var


def _load(fixtures_dir, tmp_path):
    dst = tmp_path / "kicad_common.json"
    shutil.copyfile(fixtures_dir / "kicad_common.sample.json", dst)
    return dst


def test_sets_var_when_vars_is_null(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    changed = write_env_var(p, "SR_LIB", "/home/sadad/git/stockroom/libraries/Main")
    assert changed is True
    data = json.loads(p.read_text())
    assert data["environment"]["vars"]["SR_LIB"] == "/home/sadad/git/stockroom/libraries/Main"
    # every other key survives
    assert data["meta"]["version"] == 6
    assert data["system"]["working_dir"] == "/home/sadad/git/stockroom"


def test_read_back(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    write_env_var(p, "SR_LIB", "/x")
    assert read_env_var(p, "SR_LIB") == "/x"
    assert read_env_var(p, "MISSING") is None


def test_preserves_other_env_vars(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    data = json.loads(p.read_text())
    data["environment"]["vars"] = {"KIPRJMOD": "/somewhere"}
    p.write_text(json.dumps(data))
    write_env_var(p, "SR_LIB", "/x")
    out = json.loads(p.read_text())
    assert out["environment"]["vars"]["KIPRJMOD"] == "/somewhere"
    assert out["environment"]["vars"]["SR_LIB"] == "/x"


def test_idempotent_no_backup_when_already_correct(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    assert write_env_var(p, "SR_LIB", "/x") is True
    # a backup exists from the first real write
    backups_after_first = list(tmp_path.glob("kicad_common.json.*.bak"))
    assert len(backups_after_first) == 1
    assert write_env_var(p, "SR_LIB", "/x") is False  # no change
    # no second backup taken
    assert list(tmp_path.glob("kicad_common.json.*.bak")) == backups_after_first


def test_takes_backup_before_writing(fixtures_dir, tmp_path):
    p = _load(fixtures_dir, tmp_path)
    original = p.read_text()
    write_env_var(p, "SR_LIB", "/x")
    backups = list(tmp_path.glob("kicad_common.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
