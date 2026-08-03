"""The ingestion pipeline: Inspect (unpack + fingerprint) and Convert + Stage
produce review-ready candidates; Commit runs one atomic, zero-trace transaction
through the M2 add_part seam and enforces the strict complete-to-add gate on
entry to the primary library (spec sections 5 and 6). Partial (3D-only) packages
attach to an existing part (spec section 5)."""

from __future__ import annotations

import html
import shutil
import tempfile
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path

from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import detect_source
from stockroom.ingest.sandbox import unpack_inputs
from stockroom.ingest.staging import StagingCandidate, build_candidates, merge_candidates
from stockroom.kicad.category_lib import create_empty_symbol_lib, ensure_footprint_lib
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.asset import Asset, AssetOrigin
from stockroom.model.cad_variant import CadVariantPointer
from stockroom.model.category import category_nickname
from stockroom.model.part import AssetRef, PartRecord, Provenance
from stockroom.mutation.library_ops import LibraryOps
from stockroom.mutation.placement import (
    merge_symbol_into_lib,
    mirror_fields_to_symbol,
    place_footprint,
)
from stockroom.mutation.transaction import Transaction
from stockroom.store.profile import Profile
from stockroom.vcs.repo import GitRepo


def _with_origin(ref: AssetRef, origin: AssetOrigin | None, now_iso: str):
    """An asset carrying `ref`, tagged with where it came from when that is known.

    Returns the BARE ref when there is no origin, so an unattributed attach stays unattributed
    rather than acquiring an origin whose vendor is the empty string -- `Asset.of` wraps a bare
    ref with `origin=None`, which is the honest shape for "attached, nobody recorded a source".
    """
    if origin is None:
        return ref
    from stockroom.model.asset import Asset

    return Asset(
        ref=ref,
        origin=AssetOrigin(
            vendor=origin.vendor, url=origin.url,
            captured_at=now_iso or origin.captured_at, extra=dict(origin.extra),
        ),
    )


def _native_footprint_entry(candidate: StagingCandidate) -> str:
    """Read the selected KiCad footprint's logical name from its native payload.

    Capture materialization deliberately uses neutral temporary filenames such as
    ``Variant.kicad_mod``.  The filename is therefore not an identity binding.  The
    footprint declaration inside the provider payload is the exact entry already
    cross-verified against the Altium package and remains valid even when a download
    contains several package variants.
    """

    selected = candidate.chosen_footprint
    if selected is None:
        return ""
    # Ultra Librarian writes a literal ``+`` as ``&plus_`` in both the KiCad filename and
    # footprint declaration, while the converted native Altium entry correctly retains ``+``.
    # Decode that provider transport spelling before selecting among native PcbLib entries.
    return html.unescape(Footprint.load(selected).name.strip()).replace("&plus_", "+")


class IngestPipeline:
    def __init__(
        self,
        profile: Profile,
        repo: GitRepo,
        cli: KiCadCli,
        *,
        auto_embed_altium_models: bool = False,
        altium_driver=None,
    ):
        self.profile = profile
        self.repo = repo
        self.cli = cli
        self.ops = LibraryOps(profile, repo, cli=cli)
        self.auto_embed_altium_models = auto_embed_altium_models
        self.altium_driver = altium_driver
        # Tempdirs inspect() created itself (no workdir supplied); removed by
        # cleanup() or on __exit__ so an inspect->commit cycle never orphans a
        # sandbox tree in the system temp dir.
        self._owned_workdirs: list[Path] = []

    def inspect(
        self,
        inputs: Sequence[Path] = (),
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

        failures: list[Exception] = []
        for index, source in enumerate(inputs):
            try:
                unpacked = unpack_inputs([source], workdir / "unpack" / f"Input-{index + 1}")
                for unpacked_input in unpacked:
                    detected = detect_source(unpacked_input.root)
                    provenance = Provenance(
                        source=detected.vendor,
                        original_zip_sha256=unpacked_input.sha256,
                    )
                    stage_dir = workdir / "stage" / f"Input-{index + 1}"
                    candidates.extend(
                        build_candidates(self.cli, detected, stage_dir, provenance)
                    )
            except Exception as exc:  # noqa: BLE001 - one sibling must not discard the bundle
                failures.append(exc)
        if not candidates and failures:
            raise failures[0]

        # A part often arrives split across two vendor files (symbol+footprint in
        # one, the 3D model or datasheet in another): fold the fragments into the
        # candidate they complete instead of staging orphan attach-me cards.
        return merge_candidates(candidates)

    def commit(self, candidate: StagingCandidate) -> PartRecord:
        # Public Add A Part creates identity/spec records only. CAD must enter through
        # the network capture authority, which verifies and publishes one same-source
        # KiCad + Altium + STEP set atomically. Keeping this check on the pipeline
        # itself means a caller cannot bypass the API router and revive the former
        # local-ZIP/KiCad-only lane.
        if (
            candidate.symbol_lib_path is not None
            or bool(candidate.symbol_name)
            or bool(candidate.footprint_variants)
            or candidate.model_path is not None
            or candidate.datasheet_path is not None
        ):
            raise IngestError(
                "local files cannot be added through ingest; add the identity first, "
                "then use network capture for one coherent KiCad, Altium, and STEP set"
            )
        staged = candidate.to_staged_part()
        return self.ops.add_part(staged)

    def attach_model(self, part_id: str, candidate: StagingCandidate) -> PartRecord:
        if candidate.model_path is None:
            raise IngestError("candidate has no 3D model to attach")
        record = self.ops.load_record(part_id)
        kicad = record.assets_for("kicad")
        if kicad.footprint is None:
            raise IngestError(f"part {part_id} has no footprint to link a model to")
        lib = self.profile.library
        fp_path = lib.footprint_lib_path(record.category) / f"{kicad.footprint.name}.kicad_mod"
        if not fp_path.exists():
            raise IngestError(f"footprint file missing for {part_id}: {fp_path.name}")
        lib.models_dir.mkdir(parents=True, exist_ok=True)
        model_name = f"{kicad.footprint.name}{Path(candidate.model_path).suffix}"
        model_dst = lib.models_dir / model_name
        json_path = lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            shutil.copyfile(candidate.model_path, model_dst)
            txn.track(model_dst)
            fp = Footprint.load(fp_path)
            fp.set_model_path(f"${{SR_LIB}}/models/{model_name}")
            fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")
            txn.track(fp_path)
            kicad.model = Asset.of(AssetRef(file=f"models/{model_name}"))
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Attach 3D model to {part_id}")
        return record

    def attach_assets(
        self, part_id: str, candidate: StagingCandidate,
        *, origin: AssetOrigin | None = None, now_iso: str = "",
        active_variant: CadVariantPointer | None = None,
        replace_existing: bool = False,
        _transaction: Transaction | None = None,
        _record: PartRecord | None = None,
    ) -> PartRecord:
        """Attach a downloaded CAD ZIP's symbol/footprint/3D onto an EXISTING part (the
        owner's DigiKey-CAD-download flow for a part that already landed identity-only,
        via add_reference_part; spec section 5). Mirrors add_part's file-owning attach
        block (library_ops.py:218-296) exactly, but loads the existing record instead of
        minting a new one, and touches ONLY the assets the candidate actually carries: a
        candidate offering just a 3D model sets only `.model` (attach_model's shape,
        above); one that also carries a symbol + footprint merges the symbol into the
        category lib and places the footprint into the category `.pretty` too. One
        atomic Transaction: a failure restores every touched path, so an existing part
        can never end up half-attached.

        `origin` records WHERE these files came from, and is applied to every asset this call
        files. It is the guided flow's answer to the owner's complaint -- *"its not trusted where
        we've gotten them"* -- and it has to live HERE rather than only on `attach_symbol` /
        `attach_footprint`, because this is the path guided capture actually uses: a downloaded
        archive whose symbol, footprint and 3D all came from the same page in one click.
        `captured_at` is stamped by the caller's clock (the API passes the server's), never by the
        client. Omitted means the assets stay honestly UNATTRIBUTED.

        ``active_variant`` is the digest-bound evidence bundle that produced this projection.
        When supplied, all three KiCad roles are required and the pointer is written only after
        every role has materialized, in this same Transaction. ``replace_existing`` permits the
        activation flow to replace this part's stable symbol entry; ordinary ingestion keeps the
        add-only symbol guard."""
        fp = candidate.chosen_footprint  # None if no variants; IngestError if index invalid
        if candidate.symbol_lib_path is None and fp is None and candidate.model_path is None:
            raise IngestError("candidate carries no symbol, footprint, or 3D model to attach")
        if active_variant is not None:
            active_variant.validate_for_tool("kicad")
            if candidate.symbol_lib_path is None or fp is None or candidate.model_path is None:
                raise IngestError(
                    "an active KiCad CAD variant must materialize symbol, footprint, and model"
                )
        record = _record or self.ops.load_record(part_id)
        lib = self.profile.library
        nickname = category_nickname(record.category)
        sym_lib_path = lib.symbol_lib_path(record.category)
        pretty_dir = lib.footprint_lib_path(record.category)
        # The frontend's staging review always sets entry_name (the same field
        # to_staged_part uses to name the symbol/footprint on a brand-new add); fall back
        # to the record's own symbol name for the rare re-attach onto a part that already
        # carries one.
        kicad = record.assets_for("kicad")
        entry_name = candidate.entry_name or (kicad.symbol.name if kicad.symbol else "")

        # capture dirs that do not yet exist so a rollback prunes them (git cannot track
        # an empty dir; same reasoning as add_part's fresh_dirs, library_ops.py:206-213).
        fresh_dirs = [d for d in (lib.models_dir, pretty_dir) if not d.exists()]
        json_path = lib.parts_dir / f"{part_id}.json"

        transaction_scope = (
            Transaction(self.repo) if _transaction is None else nullcontext(_transaction)
        )
        with transaction_scope as txn:
            txn.track_dir(*fresh_dirs)

            if candidate.symbol_lib_path is not None:
                if not entry_name:
                    raise IngestError(f"part {part_id} has no entry name to place a symbol under")
                if not sym_lib_path.exists():
                    if self.cli is None:
                        raise ValueError(
                            f"category symbol library {sym_lib_path.name} is missing and "
                            "no kicad-cli was provided to create it"
                        )
                    create_empty_symbol_lib(self.cli, sym_lib_path)
                    txn.track(sym_lib_path)
                elif replace_existing:
                    # Track before the first write so a source-parse/merge failure after removal
                    # restores the prior symbol library. Replacement is intentionally local to
                    # this stable entry; every other category symbol remains byte-preserved.
                    txn.track(sym_lib_path)
                    existing = SymbolLib.load(sym_lib_path)
                    if entry_name in existing.symbol_names:
                        existing.remove_symbol(entry_name)
                        existing.save(sym_lib_path)
                merge_symbol_into_lib(
                    sym_lib_path, candidate.symbol_lib_path, candidate.symbol_name, entry_name
                )
                txn.track(sym_lib_path)
                kicad.symbol = _with_origin(AssetRef(lib=nickname, name=entry_name), origin, now_iso)

            if fp is not None:
                if not entry_name:
                    raise IngestError(f"part {part_id} has no entry name to place a footprint under")
                ensure_footprint_lib(pretty_dir)
                # Register the deterministic destination before copy/parse: even a short write or
                # malformed source must restore the prior footprint rather than leak a partial one.
                txn.track(pretty_dir / f"{entry_name}.kicad_mod")
                fp_path = place_footprint(pretty_dir, fp, entry_name)
                txn.track(fp_path)
                kicad.footprint = _with_origin(
                    AssetRef(lib=nickname, name=entry_name), origin, now_iso
                )

            if candidate.model_path is not None:
                if kicad.footprint is None:
                    raise IngestError(f"part {part_id} has no footprint to link a model to")
                fp_file = lib.footprint_lib_path(record.category) / f"{kicad.footprint.name}.kicad_mod"
                if not fp_file.exists():
                    raise IngestError(f"footprint file missing for {part_id}: {fp_file.name}")
                lib.models_dir.mkdir(parents=True, exist_ok=True)
                model_name = f"{kicad.footprint.name}{Path(candidate.model_path).suffix}"
                model_dst = lib.models_dir / model_name
                txn.track(model_dst)
                shutil.copyfile(candidate.model_path, model_dst)
                fp_obj = Footprint.load(fp_file)
                fp_obj.set_model_path(f"${{SR_LIB}}/models/{model_name}")
                fp_file.write_text(fp_obj.serialize(), encoding="utf-8", newline="")
                txn.track(fp_file)
                kicad.model = _with_origin(
                    AssetRef(file=f"models/{model_name}"), origin, now_iso
                )

            # the symbol's Footprint property + mirror the record's identity fields onto
            # it, whenever a symbol exists (freshly placed above, or already on the
            # record from an earlier attach) so the schematic view never shows stale
            # MPN/Manufacturer/Description/Datasheet metadata after this attach.
            if kicad.symbol is not None:
                sym_lib = SymbolLib.load(sym_lib_path)
                sym = sym_lib.get_symbol(kicad.symbol.name)
                if kicad.footprint is not None:
                    sym.set_property("Footprint", f"{kicad.footprint.lib}:{kicad.footprint.name}")
                mirror_fields_to_symbol(sym, record)
                sym_lib.save(sym_lib_path)
                txn.track(sym_lib_path)

            if active_variant is not None:
                # The pointer is the final in-memory mutation before the canonical record write.
                # A failure above leaves the old pointer untouched; a commit failure rolls the
                # projection and pointer back together.
                record.cad_variants.select("kicad", active_variant)

            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            if _transaction is None:
                txn.commit(f"Attach CAD assets to {part_id}")
        return record

    def attach_coherent_cad_assets(
        self,
        part_id: str,
        candidate: StagingCandidate,
        *altium_sources: Path,
        kicad_origin: AssetOrigin | None,
        altium_origin: AssetOrigin | None,
        now_iso: str,
        kicad_active_variant: CadVariantPointer,
        altium_active_variant: CadVariantPointer,
        preferred_altium_footprint: str = "",
    ) -> PartRecord:
        """Materialize one cross-EDA-proved KiCad/Altium pair in one Git transaction."""

        kicad_active_variant.validate_for_tool("kicad")
        altium_active_variant.validate_for_tool("altium")
        if not (
            altium_active_variant.manifest_digest == kicad_active_variant.manifest_digest
            and altium_active_variant.provider == kicad_active_variant.provider
            and altium_active_variant.source_manifests
            == kicad_active_variant.source_manifests
        ):
            raise IngestError(
                "KiCad and Altium must come from the same provider evidence set"
            )
        with Transaction(self.repo) as txn:
            record = self.ops.load_record(part_id)
            # The converted native library is authoritative for its own entry names. A
            # provider's KiCad and P-CAD exports can use different logical package labels even
            # though cross-EDA geometry has proved they are the same footprint. Prefer the
            # converter's declared native default when available; only use the KiCad payload
            # name for providers whose native library does not declare one.
            native_footprint_entry = (
                preferred_altium_footprint.strip() or _native_footprint_entry(candidate)
            )
            current_symbol = record.assets_for("kicad").symbol
            entry_name = candidate.entry_name or (
                current_symbol.name if current_symbol is not None else ""
            )
            if not entry_name:
                raise IngestError(f"part {part_id} has no entry name for coherent CAD attachment")
            library = self.profile.library
            exact_targets = [
                library.parts_dir / f"{part_id}.json",
                library.symbol_lib_path(record.category),
                library.footprint_lib_path(record.category) / f"{entry_name}.kicad_mod",
                library.models_dir / f"{entry_name}{Path(candidate.model_path or '').suffix}",
                library.parts_dir.parent / "altium" / f"{part_id}.SchLib",
                library.parts_dir.parent / "altium" / f"{part_id}.PcbLib",
            ]
            if not self.repo.is_clean(exact_targets):
                raise IngestError(
                    "coherent CAD attachment refused because one exact target has "
                    "uncommitted changes"
                )
            record = self.attach_assets(
                part_id,
                candidate,
                origin=kicad_origin,
                now_iso=now_iso,
                active_variant=kicad_active_variant,
                replace_existing=True,
                _transaction=txn,
                _record=record,
            )
            record = self.ops.attach_altium_assets(
                part_id,
                *altium_sources,
                origin=altium_origin,
                now_iso=now_iso,
                active_variant=altium_active_variant,
                preferred_footprint=native_footprint_entry,
                _transaction=txn,
                _record=record,
            )
            if self.auto_embed_altium_models:
                # The provider STEP has already passed candidate/evidence verification and now
                # exists at its canonical KiCad path. A built-in conversion may already have put
                # those exact bytes in the native PcbLib; independently read that payload first so
                # completion never launches Altium merely to embed the same model twice. Provider
                # PcbLibs that omit or alter the model retain the existing fail-closed native embed.
                from stockroom.altium.embed3d import read_model_index
                from stockroom.altium.native_authoring import read_embedded_model_payloads

                model_source = Path(candidate.model_path or "")
                pcblib = (
                    self.profile.library.parts_dir.parent
                    / "altium"
                    / f"{part_id}.PcbLib"
                )
                already_embedded = (
                    model_source.is_file()
                    and bool(read_model_index(pcblib))
                    and read_embedded_model_payloads(pcblib) == (model_source.read_bytes(),)
                )
                if not already_embedded:
                    self.ops.embed_altium_model(
                        part_id,
                        driver=self.altium_driver,
                        _transaction=txn,
                        _record=record,
                        _require_native_readback=True,
                    )
            txn.commit(f"Attach coherent KiCad and Altium assets to {part_id}")
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
