from __future__ import annotations


def test_local_cad_inspect_is_not_a_public_activation_lane(client, tmp_path):
    response = client.post(
        "/api/parts/any-part/assets/inspect",
        json={"paths": [str(tmp_path / "vendor.zip")]},
    )

    assert response.status_code == 422
    assert "local CAD files cannot be inspected" in response.json()["detail"]
    assert "KiCad, Altium, and STEP" in response.json()["detail"]


def test_single_tool_local_commit_is_not_a_public_activation_lane(client):
    response = client.post(
        "/api/parts/any-part/assets/commit",
        json={
            "vendor": "snapeda",
            "symbol_lib_path": r"C:\Downloads\Part.kicad_sym",
            "symbol_name": "Part",
            "footprint_variants": [r"C:\Downloads\Part.kicad_mod"],
            "model_path": r"C:\Downloads\Part.step",
            "category": "ICs",
        },
    )

    assert response.status_code == 422
    assert "single-tool CAD attachment is disabled" in response.json()["detail"]
    assert "activate atomically" in response.json()["detail"]
