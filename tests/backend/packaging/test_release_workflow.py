from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import ExtendedKeyUsageOID

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/release.yml"
WORKFLOW_TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")
WORKFLOW: dict[str, Any] = yaml.load(WORKFLOW_TEXT, Loader=yaml.BaseLoader)


def steps(job_name: str) -> list[dict[str, Any]]:
    return WORKFLOW["jobs"][job_name]["steps"]


def named_step(job_name: str, name: str) -> dict[str, Any]:
    return next(step for step in steps(job_name) if step.get("name") == name)


def test_release_workflow_parses_and_has_least_privilege_jobs() -> None:
    assert WORKFLOW["name"] == "Stockroom Windows Release"
    assert WORKFLOW["permissions"] == {}
    assert WORKFLOW["on"]["push"] == {"branches": ["main"]}
    assert WORKFLOW["on"]["workflow_dispatch"]["inputs"]["version"]["required"] == "true"

    build = WORKFLOW["jobs"]["build-windows-package"]
    publish = WORKFLOW["jobs"]["publish-github-release"]
    deploy = WORKFLOW["jobs"]["deploy-update-feed"]
    assert build["runs-on"] == "windows-2025"
    assert build["env"]["UV_PYTHON"] == "3.12.13"
    assert build["environment"] == "Windows Release"
    assert build["permissions"] == {"contents": "read"}
    assert publish["runs-on"] == "ubuntu-24.04"
    assert publish["permissions"] == {"actions": "read", "contents": "write"}
    assert publish["name"] == "Publish GitHub Release"
    assert publish["if"] == (
        "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}"
    )
    assert deploy["needs"] == ["build-windows-package", "publish-github-release"]
    assert deploy["environment"]["name"] == "github-pages"
    assert deploy["permissions"] == {
        "actions": "read",
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }

    checkout = named_step("build-windows-package", "Check Out The Exact Release Revision")
    setup_uv = named_step("build-windows-package", "Install Pinned uv")
    assert checkout["with"]["persist-credentials"] == "false"
    assert setup_uv["with"] == {
        "version": "0.11.16",
        "python-version": "3.12.13",
        "enable-cache": "false",
    }


def test_main_push_gets_one_immutable_build_number_release() -> None:
    metadata = named_step("build-windows-package", "Resolve And Validate Release Metadata")
    publish = named_step("publish-github-release", "Publish Signed Windows Release")

    assert metadata["env"]["AUTOMATIC_BASE_VERSION"] == "1.0.0"
    assert metadata["env"]["GITHUB_RUN_NUMBER"] == "${{ github.run_number }}"
    assert (
        '$version = "$($env:AUTOMATIC_BASE_VERSION).$($env:GITHUB_RUN_NUMBER)"' in metadata["run"]
    )
    assert '"release_tag=v$version`n"' in metadata["run"]
    assert publish["env"]["STOCKROOM_RELEASE_TAG"] == (
        "${{ needs.build-windows-package.outputs.release_tag }}"
    )
    assert "gh release create $env:STOCKROOM_RELEASE_TAG" in publish["run"]
    assert "--target $env:GITHUB_SHA" in publish["run"]
    assert "--prerelease=false" in publish["run"]
    assert "--prerelease `" not in publish["run"]
    assert "This release contains Stockroom's stable signed-release broker" in publish["run"]


def test_manual_dispatch_verifies_without_entering_the_publication_path() -> None:
    metadata = named_step("build-windows-package", "Resolve And Validate Release Metadata")
    publish = WORKFLOW["jobs"]["publish-github-release"]

    assert "GITHUB_EVENT_NAME" not in metadata["env"]
    assert '$env:GITHUB_EVENT_NAME -ceq "push"' in metadata["run"]
    assert '$env:GITHUB_EVENT_NAME -ceq "workflow_dispatch"' in metadata["run"]
    assert "$version = $env:MANUAL_VERSION" in metadata["run"]
    assert publish["if"] == (
        "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}"
    )


def test_release_build_cannot_start_before_the_canonical_ci_gate() -> None:
    quality_gate = WORKFLOW["jobs"]["quality-gate"]
    build = WORKFLOW["jobs"]["build-windows-package"]

    assert quality_gate == {
        "name": "Canonical CI Gate",
        "permissions": {"contents": "read"},
        "uses": "./.github/workflows/ci.yml",
    }
    assert build["needs"] == "quality-gate"


def test_every_external_action_is_pinned_to_an_exact_commit() -> None:
    references = [
        reference
        for reference in re.findall(
            r"^\s*uses:\s*([^#\s]+)", WORKFLOW_TEXT, flags=re.MULTILINE
        )
        if not reference.startswith("./")
    ]
    assert set(references) == {
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/configure-pages@983d7736d9b0ae728b81ab479565c72886d7745b",
        "actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e",
        "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
        "actions/setup-dotnet@26b0ec14cb23fa6904739307f278c14f94c95bf1",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa",
        "astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86",
    }
    assert all(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}", reference)
        for reference in references
    )


def test_release_can_only_invoke_the_canonical_production_packager() -> None:
    build = named_step("build-windows-package", "Build Canonical Production Package")["run"]

    assert r"& .\packaging\Build-Windows-Package.ps1" in build
    assert "-Mode Production" in build
    assert "-SigningCertificatePath $pfxPath" in build
    assert "-MinGitRoot" not in build
    assert "-NodeRoot" not in build
    assert "-WebView2BootstrapperPath" not in build
    assert "-TufRootPath $env:STOCKROOM_TUF_ROOT_PATH" in build
    assert "-TufMetadataVersion ([int]$env:STOCKROOM_TUF_METADATA_VERSION)" in build
    assert "-TufTargetsKeyPaths $env:STOCKROOM_TUF_TARGETS_KEY_PATH" in build
    assert "-TufSnapshotKeyPaths $env:STOCKROOM_TUF_SNAPSHOT_KEY_PATH" in build
    assert "-TufTimestampKeyPaths $env:STOCKROOM_TUF_TIMESTAMP_KEY_PATH" in build
    assert "pyinstaller packaging/stockroom.spec" not in WORKFLOW_TEXT.casefold()
    assert "shipping unsigned" not in WORKFLOW_TEXT.casefold()
    assert "exit 0" not in WORKFLOW_TEXT.casefold()
    assert "dist/stockroom.exe" not in WORKFLOW_TEXT.casefold()
    assert "stockroom.exe.sha256" not in WORKFLOW_TEXT.casefold()
    assert "Stockroom.exe" not in WORKFLOW_TEXT


def test_signing_secrets_are_step_scoped_and_always_destroyed() -> None:
    materialize = named_step("build-windows-package", "Materialize Ephemeral Signing Material")
    trust = named_step("build-windows-package", "Trust Pinned GitHub Signing Certificate")
    build = named_step("build-windows-package", "Build Canonical Production Package")
    cleanup = named_step("build-windows-package", "Destroy Ephemeral Signing Material")
    trust_cleanup = named_step(
        "build-windows-package", "Remove Ephemeral Verification Trust"
    )
    verify = named_step("build-windows-package", "Verify And Stage Exact Release Assets")
    build_steps = steps("build-windows-package")

    assert WORKFLOW_TEXT.count("${{ secrets.WINDOWS_CERT_BASE64 }}") == 1
    assert WORKFLOW_TEXT.count("${{ secrets.WINDOWS_CERT_PASSWORD }}") == 1
    assert materialize["env"] == {
        "WINDOWS_CERT_BASE64": "${{ secrets.WINDOWS_CERT_BASE64 }}",
        "STOCKROOM_TUF_TARGETS_KEY_BASE64": ("${{ secrets.STOCKROOM_TUF_TARGETS_KEY_BASE64 }}"),
        "STOCKROOM_TUF_SNAPSHOT_KEY_BASE64": ("${{ secrets.STOCKROOM_TUF_SNAPSHOT_KEY_BASE64 }}"),
        "STOCKROOM_TUF_TIMESTAMP_KEY_BASE64": ("${{ secrets.STOCKROOM_TUF_TIMESTAMP_KEY_BASE64 }}"),
    }
    for role in ("TARGETS", "SNAPSHOT", "TIMESTAMP"):
        secret = f"${{{{ secrets.STOCKROOM_TUF_{role}_KEY_BASE64 }}}}"
        assert WORKFLOW_TEXT.count(secret) == 1
    assert build["env"]["STOCKROOM_SIGNING_CERT_PASSWORD"] == (
        "${{ secrets.WINDOWS_CERT_PASSWORD }}"
    )
    assert trust["run"].count("packaging/Stockroom GitHub Signing.cer") == 1
    assert "Cert:\\LocalMachine\\TrustedPeople" in trust["run"]
    assert "Cert:\\CurrentUser\\TrustedPeople" not in trust["run"]
    assert "STOCKROOM_SIGNING_CERT_THUMBPRINT" in trust["run"]
    assert "-SigningCertificateTrustedForVerification" in build["run"]
    assert cleanup["if"] == "${{ always() }}"
    assert "[IO.FileAccess]::Write" in cleanup["run"]
    assert "$stream.Write($buffer, 0, $count)" in cleanup["run"]
    assert "Remove-Item -LiteralPath $path -Force" in cleanup["run"]
    assert "Cert:\\LocalMachine\\TrustedPeople" not in cleanup["run"]
    assert trust_cleanup["if"] == "${{ always() }}"
    assert "STOCKROOM_SIGNING_CERT_THUMBPRINT" in trust_cleanup["run"]
    assert "Cert:\\LocalMachine\\TrustedPeople" in trust_cleanup["run"]
    assert build_steps.index(trust) < build_steps.index(build) < build_steps.index(cleanup)
    assert build_steps.index(cleanup) < build_steps.index(verify)
    assert build_steps.index(verify) < build_steps.index(trust_cleanup)
    assert build_steps.index(trust_cleanup) < build_steps.index(
        named_step("build-windows-package", "Upload Verified Release Assets")
    )


def test_github_signing_certificate_is_public_and_pinned() -> None:
    certificate = REPOSITORY_ROOT / "packaging" / "Stockroom GitHub Signing.cer"

    assert certificate.is_file()
    parsed = x509.load_der_x509_certificate(certificate.read_bytes())
    assert parsed.subject.rfc4514_string() == "CN=6586C41B-410B-4C94-8631-F025DB362E47"
    assert parsed.fingerprint(hashes.SHA256()).hex() == (
        "8cce8e310de3de9823f5a54a33b2adfc4a9f00673df4679172f37500cc2dc066"
    )
    assert parsed.not_valid_before_utc <= datetime.now(UTC) <= parsed.not_valid_after_utc
    assert ExtendedKeyUsageOID.CODE_SIGNING in parsed.extensions.get_extension_for_class(
        x509.ExtendedKeyUsage
    ).value


def test_release_materializes_only_the_pinned_tuf_root() -> None:
    metadata = named_step("build-windows-package", "Resolve And Validate Release Metadata")["run"]
    materialize = named_step("build-windows-package", "Materialize Pinned TUF Root")["run"]

    assert "STOCKROOM_TUF_ROOT_BASE64" in metadata
    assert "[Convert]::FromBase64String($env:STOCKROOM_TUF_ROOT_BASE64)" in materialize
    assert "STOCKROOM_TUF_ROOT_PATH=$tufRoot" in materialize
    assert "STOCKROOM_TUF_METADATA_VERSION=$tufMetadataVersion" in metadata
    assert "Release version is older than an existing canonical release tag." in metadata
    for obsolete in ("MINGIT", "NODE_ROOT", "WEBVIEW2_BOOTSTRAPPER"):
        assert obsolete not in WORKFLOW_TEXT


def test_only_the_exact_verified_release_asset_set_can_be_published() -> None:
    verify = named_step("build-windows-package", "Verify And Stage Exact Release Assets")["run"]
    upload = named_step("build-windows-package", "Upload Verified Release Assets")
    publish_step = named_step("publish-github-release", "Publish Signed Windows Release")
    publish = publish_step["run"]

    assert publish_step["env"]["GH_REPO"] == "${{ github.repository }}"
    assert upload["with"]["path"] == "${{ runner.temp }}\\Stockroom.Release.Publish"
    assert upload["with"]["if-no-files-found"] == "error"
    assert "Copy-Item -LiteralPath $packagePath -Destination $publishRoot" in verify
    assert "Copy-Item -LiteralPath $appInstallerPath -Destination $publishRoot" in verify
    assert "Copy-Item -LiteralPath $evidencePath -Destination $publishRoot" in verify
    assert "Copy-Item -LiteralPath $feedPath -Destination $publishRoot" in verify
    assert "Copy-Item -LiteralPath $feedEvidencePath -Destination $publishRoot" in verify
    assert "Stockroom_TUF_Feed_$($env:STOCKROOM_PACKAGE_VERSION).zip" in publish
    assert "Copy-Item" not in "\n".join(
        line for line in verify.splitlines() if "Stockroom.exe" in line
    )
    assert "Release staging contains a file outside the exact publication allowlist." in verify
    assert "gh release upload $env:STOCKROOM_RELEASE_TAG @assets" in publish
    assert "--clobber" not in publish
    assert "Published release assets are immutable" in publish
    assert "asset outside the release allowlist" in publish
    assert "Published GitHub release assets differ from the exact release allowlist." in publish


def test_main_release_atomically_deploys_the_verified_update_feed() -> None:
    deploy = WORKFLOW["jobs"]["deploy-update-feed"]
    stage = named_step("deploy-update-feed", "Assemble Verified Pages Site")["run"]

    assert deploy["if"] == (
        "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}"
    )
    assert "Copy-Item -Recurse -Force store-site/* pages-root" in stage
    assert "Stockroom GitHub Signing.cer" in stage
    assert "pages-root/downloads/Stockroom-GitHub-Signing.cer" in stage
    assert "packaging/deploy_release_feed.py" in stage
    assert "--previous-feed" in stage
    assert "pages-root/windows/x64" in stage
    assert "STOCKROOM_WINDOWS_FEED_BASE_URI" in stage
    assert named_step("deploy-update-feed", "Deploy Public Site And Update Feed")[
        "uses"
    ] == "actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e"


def test_release_requires_complete_signed_canonical_evidence() -> None:
    verify = named_step("build-windows-package", "Verify And Stage Exact Release Assets")["run"]

    for required in (
        '$evidence.schema -cne "stockroom-windows-package-build/3"',
        '$evidence.runtime_status -cne "stable-managed-release-runtime"',
        '$evidence.mode -cne "production"',
        '$evidence.signing.state -cne "authenticode-signed"',
        '$evidence.signing.executable_signature_status -cne "Valid"',
        '$evidence.signing.msix_signature_status -cne "Valid"',
        "$evidence.validation.makeappx_semantic_validation",
        "$evidence.validation.makeappx_round_trip",
        "$evidence.validation.immutable_release_bundle_round_trip",
        "$evidence.validation.managed_host_launch",
        "$evidence.validation.managed_service_authority",
        "$evidence.validation.workflow_coordinator_running",
        "$evidence.validation.packaged_frontend_served",
        "$evidence.validation.packaged_worker_handoff",
        "$evidence.validation.signed_tuf_release_feed",
        '$evidence.release_feed.schema -cne "stockroom-release-feed/1"',
        "$evidence.release_feed.trusted_updater_round_trip",
        '$evidence.release_feed.deployment_state -cne "staged-not-deployed"',
        "-not $evidence.managed_runtime.native_host",
        "-not $evidence.managed_runtime.packaged_worker",
        '$evidence.managed_runtime.update_channel -cne "production"',
        "$evidence.tools.cad_converter.tree_sha256",
        "$evidence.tools.cad_converter.executable_sha256",
        "$evidence.reproducibility.pyinstaller_payloads_match",
        "Get-AuthenticodeSignature -LiteralPath $packagePath",
        "Release output digest does not match Build Evidence.json.",
    ):
        assert required in verify
