from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

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
    assert WORKFLOW["on"]["push"]["tags"] == ["v*"]
    assert WORKFLOW["on"]["workflow_dispatch"]["inputs"]["version"]["required"] == "true"

    build = WORKFLOW["jobs"]["build-windows-package"]
    publish = WORKFLOW["jobs"]["publish-github-release"]
    assert build["runs-on"] == "windows-2025"
    assert build["env"]["UV_PYTHON"] == "3.12.13"
    assert build["environment"] == "Windows Release"
    assert build["permissions"] == {"contents": "read"}
    assert publish["runs-on"] == "ubuntu-24.04"
    assert publish["permissions"] == {"actions": "read", "contents": "write"}
    assert "github.ref_type == 'tag'" in publish["if"]

    checkout = named_step("build-windows-package", "Check Out The Exact Release Revision")
    setup_uv = named_step("build-windows-package", "Install Pinned uv")
    assert checkout["with"]["persist-credentials"] == "false"
    assert setup_uv["with"] == {
        "version": "0.11.16",
        "python-version": "3.12.13",
        "enable-cache": "false",
    }


def test_every_external_action_is_pinned_to_an_exact_commit() -> None:
    references = re.findall(r"^\s*uses:\s*([^#\s]+)", WORKFLOW_TEXT, flags=re.MULTILINE)
    assert set(references) == {
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
            "actions/setup-dotnet@26b0ec14cb23fa6904739307f278c14f94c95bf1",
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
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
    assert "-MinGitRoot $env:STOCKROOM_MINGIT_ROOT" in build
    assert "-WebView2BootstrapperPath $env:STOCKROOM_WEBVIEW2_BOOTSTRAPPER" in build
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
    build = named_step("build-windows-package", "Build Canonical Production Package")
    cleanup = named_step("build-windows-package", "Destroy Ephemeral Signing Material")
    build_steps = steps("build-windows-package")

    assert WORKFLOW_TEXT.count("${{ secrets.WINDOWS_CERT_BASE64 }}") == 1
    assert WORKFLOW_TEXT.count("${{ secrets.WINDOWS_CERT_PASSWORD }}") == 1
    assert materialize["env"] == {
        "WINDOWS_CERT_BASE64": "${{ secrets.WINDOWS_CERT_BASE64 }}",
        "STOCKROOM_TUF_TARGETS_KEY_BASE64": (
            "${{ secrets.STOCKROOM_TUF_TARGETS_KEY_BASE64 }}"
        ),
        "STOCKROOM_TUF_SNAPSHOT_KEY_BASE64": (
            "${{ secrets.STOCKROOM_TUF_SNAPSHOT_KEY_BASE64 }}"
        ),
        "STOCKROOM_TUF_TIMESTAMP_KEY_BASE64": (
            "${{ secrets.STOCKROOM_TUF_TIMESTAMP_KEY_BASE64 }}"
        ),
    }
    for role in ("TARGETS", "SNAPSHOT", "TIMESTAMP"):
        secret = f"${{{{ secrets.STOCKROOM_TUF_{role}_KEY_BASE64 }}}}"
        assert WORKFLOW_TEXT.count(secret) == 1
    assert build["env"]["STOCKROOM_SIGNING_CERT_PASSWORD"] == (
        "${{ secrets.WINDOWS_CERT_PASSWORD }}"
    )
    assert cleanup["if"] == "${{ always() }}"
    assert "[IO.FileAccess]::Write" in cleanup["run"]
    assert "$stream.Write($buffer, 0, $count)" in cleanup["run"]
    assert "Remove-Item -LiteralPath $path -Force" in cleanup["run"]
    assert build_steps.index(cleanup) < build_steps.index(
        named_step("build-windows-package", "Upload Verified Release Assets")
    )


def test_launcher_inputs_are_https_host_restricted_and_digest_pinned() -> None:
    metadata = named_step("build-windows-package", "Resolve And Validate Release Metadata")["run"]
    fetch = named_step("build-windows-package", "Fetch And Verify Pinned Launcher Inputs")["run"]

    for name in (
        "STOCKROOM_MINGIT_URL",
        "STOCKROOM_MINGIT_SHA256",
        "STOCKROOM_WEBVIEW2_BOOTSTRAPPER_URL",
        "STOCKROOM_WEBVIEW2_BOOTSTRAPPER_SHA256",
    ):
        assert name in metadata
        assert name in fetch
    assert '$parsed.Scheme -cne "https"' in fetch
    assert "$parsed.UserInfo" in fetch
    assert '"github.com"' in fetch
    assert '"go.microsoft.com"' in fetch
    assert "Get-FileHash -LiteralPath $Destination -Algorithm SHA256" in fetch
    assert "Release input SHA-256 verification failed." in fetch
    assert "STOCKROOM_TUF_ROOT_BASE64" in metadata
    assert "STOCKROOM_TUF_ROOT_BASE64" in fetch
    assert "[Convert]::FromBase64String($env:STOCKROOM_TUF_ROOT_BASE64)" in fetch
    assert "STOCKROOM_TUF_ROOT_PATH=$tufRoot" in fetch
    assert "STOCKROOM_TUF_METADATA_VERSION=$tufMetadataVersion" in metadata
    assert "Release version is older than an existing canonical release tag." in metadata


def test_only_the_exact_verified_release_asset_set_can_be_published() -> None:
    verify = named_step("build-windows-package", "Verify And Stage Exact Release Assets")["run"]
    upload = named_step("build-windows-package", "Upload Verified Release Assets")
    publish = named_step("publish-github-release", "Publish Signed Windows Prerelease")["run"]

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
    assert "gh release upload $env:GITHUB_REF_NAME @assets" in publish
    assert "--clobber" not in publish
    assert "Published release assets are immutable" in publish
    assert "asset outside the release allowlist" in publish
    assert "Published GitHub prerelease assets differ from the exact release allowlist." in publish


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
        '$evidence.managed_runtime.service_mode -cne "coordinator"',
        '$evidence.managed_runtime.coordinator_state -cne "running"',
        '$evidence.managed_runtime.update_channel -cne "production"',
        "$evidence.tools.bundled_mingit.git_executable_sha256",
        "$evidence.tools.webview2_bootstrapper.sha256",
        "$evidence.reproducibility.pyinstaller_payloads_match",
        "Get-AuthenticodeSignature -LiteralPath $packagePath",
        "Release output digest does not match Build Evidence.json.",
    ):
        assert required in verify
