"""The ingestion pipeline: Inspect (unpack + fingerprint) and Convert + Stage
produce review-ready candidates; Commit runs one atomic, zero-trace transaction
through the M2 add_part seam. Partial (3D-only) packages attach to an existing
part (spec section 5)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from stockroom.ingest.fingerprint import detect_source
from stockroom.ingest.lcsc import fetch_lcsc
from stockroom.ingest.sandbox import unpack_inputs
from stockroom.ingest.staging import StagingCandidate, build_candidates
from stockroom.kicad.cli import KiCadCli
from stockroom.model.part import PartRecord, Provenance
from stockroom.mutation.library_ops import LibraryOps
from stockroom.store.profile import Profile
from stockroom.vcs.repo import GitRepo


class IngestPipeline:
    def __init__(self, profile: Profile, repo: GitRepo, cli: KiCadCli):
        self.profile = profile
        self.repo = repo
        self.cli = cli
        self.ops = LibraryOps(profile, repo, cli=cli)

    def inspect(
        self,
        inputs: list[Path] = (),
        lcsc_ids: list[str] = (),
        workdir: Path | None = None,
    ) -> list[StagingCandidate]:
        workdir = Path(workdir) if workdir is not None else Path(tempfile.mkdtemp(prefix="sr-ingest-"))
        workdir.mkdir(parents=True, exist_ok=True)
        candidates: list[StagingCandidate] = []

        unpacked = unpack_inputs(list(inputs), workdir / "unpack")
        for u in unpacked:
            detected = detect_source(u.root)
            prov = Provenance(
                source=detected.vendor,
                original_zip_sha256=u.sha256,
            )
            stage_dir = workdir / "stage" / u.root.name
            candidates.extend(build_candidates(self.cli, detected, stage_dir, prov))

        for i, lcsc_id in enumerate(lcsc_ids):
            fetch_dir = workdir / "lcsc" / str(i)
            detected = fetch_lcsc(lcsc_id, fetch_dir, runner=None)
            prov = Provenance(source="lcsc", source_url="")
            stage_dir = workdir / "stage" / f"lcsc-{i}"
            for c in build_candidates(self.cli, detected, stage_dir, prov):
                c.mpn = c.mpn or lcsc_id.upper()
                candidates.append(c)

        return candidates

    def commit(self, candidate: StagingCandidate) -> PartRecord:
        # M3 ingestion stages a candidate before M4 enrichment exists (no purchase
        # link field yet), so a freshly ingested part cannot yet satisfy the strict
        # complete-to-add gate. Commit here is the "land it, flag the gaps" step;
        # the gate applies again in full once M4 enrichment can complete the
        # passport and a normal (non-ingest) add_part call is made.
        staged = candidate.to_staged_part()
        return self.ops.add_part(staged, require_complete=False)
