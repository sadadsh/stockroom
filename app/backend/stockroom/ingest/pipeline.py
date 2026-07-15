"""The ingestion pipeline: Inspect (unpack + fingerprint) and Convert + Stage
produce review-ready candidates; Commit runs one atomic, zero-trace transaction
through the M2 add_part seam and enforces the strict complete-to-add gate on
entry to the primary library (spec sections 5 and 6). Partial (3D-only) packages
attach to an existing part (spec section 5)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import detect_source
from stockroom.ingest.lcsc import fetch_lcsc
from stockroom.ingest.sandbox import unpack_inputs
from stockroom.ingest.staging import StagingCandidate, build_candidates, merge_candidates
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.footprint import Footprint
from stockroom.model.part import ModelRef, PartRecord, Provenance
from stockroom.mutation.library_ops import LibraryOps
from stockroom.mutation.transaction import Transaction
from stockroom.store.profile import Profile
from stockroom.vcs.repo import GitRepo


class IngestPipeline:
    def __init__(self, profile: Profile, repo: GitRepo, cli: KiCadCli):
        self.profile = profile
        self.repo = repo
        self.cli = cli
        self.ops = LibraryOps(profile, repo, cli=cli)
        # Tempdirs inspect() created itself (no workdir supplied); removed by
        # cleanup() or on __exit__ so an inspect->commit cycle never orphans a
        # sandbox tree in the system temp dir.
        self._owned_workdirs: list[Path] = []

    def inspect(
        self,
        inputs: list[Path] = (),
        lcsc_ids: list[str] = (),
        workdir: Path | None = None,
    ) -> list[StagingCandidate]:
        if workdir is not None:
            workdir = Path(workdir)
        else:
            # A candidate's file paths point INTO this workdir and must survive
            # until commit(), so the tree cannot be torn down when inspect returns.
            # Own it and dispose of it in cleanup()/__exit__ instead of leaking it.
            workdir = Path(tempfile.mkdtemp(prefix="sr-ingest-"))
            self._owned_workdirs.append(workdir)
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

        # A part often arrives split across two vendor files (symbol+footprint in
        # one, the 3D model or datasheet in another): fold the fragments into the
        # candidate they complete instead of staging orphan attach-me cards.
        return merge_candidates(candidates)

    def commit(self, candidate: StagingCandidate) -> PartRecord:
        # Committing is ENTRY into the library, so the strict complete-to-add gate
        # (spec section 6) applies here in full: an incomplete part is REJECTED with
        # an honest per-field report (add_part raises IncompleteError.missing), never
        # a silent partial add. Staging is where a candidate is worked toward
        # completeness (edit its fields, attach a datasheet/model, paste a purchase
        # URL); the gate fires only at commit. An archive profile is grandfathered
        # (spec section 7) and add_part bypasses the gate for it automatically, so a
        # legacy-library import still lands. This is a full gate, not a deferral.
        staged = candidate.to_staged_part()
        return self.ops.add_part(staged)

    def attach_model(self, part_id: str, candidate: StagingCandidate) -> PartRecord:
        if candidate.model_path is None:
            raise IngestError("candidate has no 3D model to attach")
        record = self.ops.load_record(part_id)
        if record.footprint is None:
            raise IngestError(f"part {part_id} has no footprint to link a model to")
        lib = self.profile.library
        fp_path = lib.footprint_lib_path(record.category) / f"{record.footprint.name}.kicad_mod"
        if not fp_path.exists():
            raise IngestError(f"footprint file missing for {part_id}: {fp_path.name}")
        lib.models_dir.mkdir(parents=True, exist_ok=True)
        model_name = f"{record.footprint.name}{Path(candidate.model_path).suffix}"
        model_dst = lib.models_dir / model_name
        json_path = lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            shutil.copyfile(candidate.model_path, model_dst)
            txn.track(model_dst)
            fp = Footprint.load(fp_path)
            fp.set_model_path(f"${{SR_LIB}}/models/{model_name}")
            fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")
            txn.track(fp_path)
            record.model = ModelRef(file=f"models/{model_name}")
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Attach 3D model to {part_id}")
        return record

    def cleanup(self) -> None:
        """Remove every sandbox tree inspect() created for itself. Idempotent and
        safe to call after commit(); the committed library files live under the
        profile, never under these tempdirs. A caller-supplied workdir is left
        alone (the caller owns it)."""
        while self._owned_workdirs:
            wd = self._owned_workdirs.pop()
            shutil.rmtree(wd, ignore_errors=True)

    def __enter__(self) -> "IngestPipeline":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.cleanup()
        return False  # never suppress exceptions
