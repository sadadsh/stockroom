"""Seamless, health-gated backend process handoff for the persistent WebView host."""

from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from stockroom.update.releases import GitReleaseStore, ReleaseCandidate

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


class CandidateProcess(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def kill(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BackendEndpoint:
    revision: str
    base_url: str
    process: CandidateProcess | None = None
    candidate: ReleaseCandidate | None = None


@dataclass(frozen=True, slots=True)
class ActivationOutcome:
    ok: bool
    revision: str
    detail: str = ""
    rolled_back: bool = False


def health_probe(base_url: str, timeout_seconds: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(
            f"{base_url.rstrip('/')}/api/health",
            timeout=timeout_seconds,
        ) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def spawn_candidate_backend(
    candidate: ReleaseCandidate,
    token: str,
    *,
    convergence_status_path: Path | None = None,
    checkout_inventory_path: Path | None = None,
    public_base_url: str | None = None,
) -> BackendEndpoint:
    """Start the candidate's windowless backend using its own frozen environment."""
    port = _free_port()
    if os.name == "nt":
        python = candidate.root / ".venv" / "Scripts" / "python.exe"
    else:
        python = candidate.root / ".venv" / "bin" / "python"
    if not python.is_file():
        raise RuntimeError("candidate environment has no Python interpreter after dependency sync")
    env = os.environ.copy()
    env["STOCKROOM_HANDOFF_TOKEN"] = token
    if convergence_status_path is not None:
        env["STOCKROOM_CONVERGENCE_STATUS"] = str(convergence_status_path)
    if checkout_inventory_path is not None:
        env["STOCKROOM_CHECKOUT_INVENTORY"] = str(checkout_inventory_path)
    if public_base_url is not None:
        env["STOCKROOM_PUBLIC_BASE_URL"] = public_base_url
    process = subprocess.Popen(
        [
            str(python),
            "-m",
            "stockroom.host.worker",
            "--port",
            str(port),
        ],
        cwd=str(candidate.root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )
    return BackendEndpoint(
        revision=candidate.revision,
        base_url=f"http://127.0.0.1:{port}",
        process=process,
        candidate=candidate,
    )


class SeamlessBackendHandoff:
    """Keep one native window while verified loopback backends are exchanged."""

    def __init__(
        self,
        store: GitReleaseStore,
        *,
        original_revision: str,
        original_base_url: str,
        prepare: Callable[[Path], None],
        spawn: Callable[[ReleaseCandidate], BackendEndpoint],
        adopt: Callable[[str], None],
        probe: Callable[[str], bool] = health_probe,
        startup_timeout_seconds: float = 30.0,
        post_adoption_probes: int = 3,
        probe_interval_seconds: float = 0.25,
    ) -> None:
        self.store = store
        self._prepare = prepare
        self._spawn = spawn
        self._adopt = adopt
        self._probe = probe
        self._startup_timeout = startup_timeout_seconds
        self._post_adoption_probes = max(1, post_adoption_probes)
        self._probe_interval = max(0.0, probe_interval_seconds)
        self._active = BackendEndpoint(original_revision, original_base_url)
        self._fallback: BackendEndpoint | None = None
        self._failed_revisions: set[str] = set()

    @property
    def active_revision(self) -> str:
        return self._active.revision

    @property
    def active_base_url(self) -> str:
        return self._active.base_url

    def _stop(self, endpoint: BackendEndpoint | None) -> None:
        process = endpoint.process if endpoint is not None else None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _prune_releases(self) -> None:
        keep = {
            endpoint.revision
            for endpoint in (self._active, self._fallback)
            if endpoint is not None and endpoint.candidate is not None
        }
        self.store.prune(keep)

    def _wait_healthy(self, endpoint: BackendEndpoint) -> bool:
        deadline = time.monotonic() + self._startup_timeout
        while time.monotonic() < deadline:
            if endpoint.process is not None and endpoint.process.poll() is not None:
                return False
            if self._probe(endpoint.base_url):
                return True
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        return False

    def activate(self, revision: str) -> ActivationOutcome:
        """Stage, prepare, health-check, and adopt; any failure leaves the old backend live."""
        if revision == self._active.revision:
            return ActivationOutcome(True, revision, "The requested release is already active.")
        if revision in self._failed_revisions:
            return ActivationOutcome(
                False,
                self._active.revision,
                (
                    f"Release {revision[:12]} previously failed activation and is quarantined "
                    "until a different revision is published."
                ),
            )
        candidate_endpoint: BackendEndpoint | None = None
        navigated = False
        prior = self._active
        try:
            candidate = self.store.stage(revision)
            self._prepare(candidate.root)
            # Dependency setup is not trusted to preserve the checkout.  Verify again.
            candidate = self.store.verify(candidate)
            candidate_endpoint = self._spawn(candidate)
            if candidate_endpoint.revision != candidate.revision:
                raise RuntimeError("candidate process revision does not match the staged release")
            if not self._wait_healthy(candidate_endpoint):
                raise RuntimeError("candidate backend did not become healthy before the deadline")
            self._adopt(candidate_endpoint.base_url)
            navigated = True
            for _ in range(self._post_adoption_probes):
                if (
                    candidate_endpoint.process is not None
                    and candidate_endpoint.process.poll() is not None
                ):
                    raise RuntimeError("candidate backend exited during adoption")
                if not self._probe(candidate_endpoint.base_url):
                    raise RuntimeError("candidate backend failed its post-adoption health gate")
                if self._probe_interval:
                    time.sleep(self._probe_interval)
            self.store.promote(candidate, candidate_endpoint.base_url)
        except Exception as exc:
            self._failed_revisions.add(revision)
            if candidate_endpoint is not None:
                # Navigation may already have happened.  Re-adopt the known-good
                # endpoint before terminating the failed process.
                try:
                    if navigated:
                        self._adopt(prior.base_url)
                finally:
                    self._stop(candidate_endpoint)
            self._prune_releases()
            return ActivationOutcome(
                False,
                prior.revision,
                f"Candidate activation failed; the previous release remains active: {exc}",
                rolled_back=navigated,
            )

        obsolete = self._fallback
        self._fallback = prior
        self._active = candidate_endpoint
        # Keep exactly one known-good fallback.  The original in-process endpoint
        # has no child process and therefore remains available until window close.
        if obsolete is not None and obsolete is not prior:
            self._stop(obsolete)
        self._prune_releases()
        return ActivationOutcome(
            True,
            revision,
            "The verified backend was adopted without closing the application window.",
        )

    def restore_last_active(self) -> ActivationOutcome:
        """Start the persisted last-known-good release before the window opens.

        No remote access is involved, so an offline launch runs the same verified
        revision that was active when Stockroom last closed.
        """
        try:
            candidate = self.store.active_candidate()
            if candidate is None:
                return ActivationOutcome(True, self._active.revision)
            self._prepare(candidate.root)
            candidate = self.store.verify(candidate)
            endpoint = self._spawn(candidate)
            if not self._wait_healthy(endpoint):
                self._stop(endpoint)
                raise RuntimeError("the persisted backend did not become healthy")
        except Exception as exc:
            self.store.record_rollback(
                self._active.revision,
                self._active.base_url,
                "unverified-persisted-release",
            )
            self._prune_releases()
            return ActivationOutcome(
                False,
                self._active.revision,
                f"The last active release could not be restored; using the bundled backend: {exc}",
                rolled_back=True,
            )
        self._fallback = self._active
        self._active = endpoint
        self._prune_releases()
        return ActivationOutcome(
            True,
            endpoint.revision,
            "The last verified release was restored before the window opened.",
        )

    def verify_active(self) -> ActivationOutcome:
        """Health-check the adopted worker and roll back in the same window if it failed."""
        process_failed = (
            self._active.process is not None and self._active.process.poll() is not None
        )
        if not process_failed and self._probe(self._active.base_url):
            return ActivationOutcome(True, self._active.revision)
        failed = self._active
        self._failed_revisions.add(failed.revision)
        fallback = self._fallback
        if fallback is None:
            return ActivationOutcome(
                False,
                failed.revision,
                "The active backend is unhealthy and no verified fallback is available.",
            )
        if fallback.process is not None and fallback.process.poll() is not None:
            return ActivationOutcome(
                False,
                failed.revision,
                "The active backend and its retained fallback are both unavailable.",
            )
        # The bundled fallback is served through the same stable public URL as
        # the proxy. While a candidate is active that URL still points at the
        # candidate, so probing it first only probes the failed backend again.
        # Re-select the in-process app before its health check. Child-process
        # fallbacks have their own private URL and can still be checked before
        # adoption.
        fallback_is_bundled = fallback.process is None
        if fallback_is_bundled:
            self._adopt(fallback.base_url)
        if not self._probe(fallback.base_url):
            return ActivationOutcome(
                False,
                failed.revision,
                "The active backend and its retained fallback both failed health checks.",
            )
        if not fallback_is_bundled:
            self._adopt(fallback.base_url)
        self._stop(failed)
        self._active = fallback
        self._fallback = None
        self.store.record_rollback(fallback.revision, fallback.base_url, failed.revision)
        self._prune_releases()
        return ActivationOutcome(
            False,
            fallback.revision,
            f"The unhealthy release {failed.revision[:12]} was rolled back automatically.",
            rolled_back=True,
        )

    def close(self) -> None:
        self._stop(self._active)
        self._stop(self._fallback)
