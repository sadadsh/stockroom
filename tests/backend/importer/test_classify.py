"""The part-class classifier, and the false-positive cases that are the whole point of it.

`PartClass` has had four values since 2026-07-27 but only PASSIVE was ever constructed, so
MECHANICAL and VIRTUAL were unreachable. Making them reachable is only safe if the classifier is
timid, because the dangerous direction is SILENT: a component wrongly called mechanical stops
asking for the symbol it genuinely needs and reports itself complete forever.

The spec's own warning is the measurement this file exists to honour: a package-vs-pad check
reported 16 mismatches on the owner's library and ALL 16 were false positives, because it read
"SOT-23" as 23 pins. *"A false-positive machine is worse than no check."*
"""
from __future__ import annotations

import pytest

from stockroom.importer.classify import classify, reclassify
from stockroom.model.part import PartRecord
from stockroom.model.part_class import PartClass

# --------------------------------------------------------------- the adversarial cases
#
# Each of these contains a keyword from the MECHANICAL or PASSIVE tables inside a part that is
# electrically functional. A naive substring classifier gets every one of them wrong, and getting
# them wrong is the invisible failure, not the noisy one.
MISLEADING = [
    ("LM317T", "ICs", "Adjustable regulator, heatsink mounted TO-220", "names a heatsink"),
    ("282836-2", "Connectors", "Terminal Block Screw Connector 2 pos", "a SCREW terminal"),
    ("ULN2003", "ICs", "Resistor network darlington driver array", "a RESISTOR network driver"),
    ("BRACKET-SW", "Switches", "Bracket-mounted limit switch", "a bracket-mounted switch"),
    ("HS-REG-1", "ICs", "Enclosure-mount LDO regulator with washer", "two mechanical words"),
]


@pytest.mark.parametrize("mpn,category,description,why", MISLEADING)
def test_an_electrically_functional_part_is_never_mechanical_however_it_reads(
    mpn, category, description, why
):
    got = classify(mpn=mpn, category=category, description=description)
    assert got is PartClass.COMPONENT, (
        f"{mpn} ({why}) classified {got.value}: a part that is electrically functional must never "
        f"be moved off COMPONENT, because doing so silently removes the files it really needs."
    )


# ------------------------------------------------------------------ each class is reachable

@pytest.mark.parametrize(
    "mpn,category,description,want",
    [
        ("29311", "Other", "Screws & Fasteners M3 6.0mm Screw Zinc Plated Steel", PartClass.MECHANICAL),
        ("SO-M3-6", "Other", "M3 brass standoff, 6mm", PartClass.MECHANICAL),
        ("W-M3", "Other", "Flat washer M3 stainless", PartClass.MECHANICAL),
        ("FID-1MM", "Other", "Fiducial marker 1mm copper", PartClass.VIRTUAL),
        ("5015", "Other", "PCB Test Point, compact", PartClass.VIRTUAL),
        ("LOGO-1", "Other", "Company logo silkscreen artwork", PartClass.VIRTUAL),
        ("ERJ-P03F1101V", "Resistors", "RES SMD 1.1K 1%", PartClass.PASSIVE),
        ("GCM155R71H102KA37D", "Capacitors", "1 nF 10% 0402", PartClass.PASSIVE),
        ("TPS62130RGTR", "ICs", "3A step-down converter", PartClass.COMPONENT),
    ],
)
def test_every_class_is_reachable_from_real_looking_text(mpn, category, description, want):
    """Without this, MECHANICAL and VIRTUAL stay unreachable and the taxonomy is decoration."""
    assert classify(mpn=mpn, category=category, description=description) is want


def test_a_part_with_no_signal_at_all_defaults_to_COMPONENT():
    """The acquisition case, deliberately. An unclassified part must show up as NEEDING WORK, not
    as excused - a wrong COMPONENT is noisy and correctable, a wrong VIRTUAL is silent."""
    assert classify(mpn="ZZZ-NOT-A-REAL-PART") is PartClass.COMPONENT
    assert classify() is PartClass.COMPONENT


def test_the_classifier_can_actually_DISTINGUISH_the_classes():
    """Anti-vacuous guard: if it returned COMPONENT for everything, every 'never mechanical' test
    above would pass while the classifier did nothing at all."""
    seen = {
        classify(mpn="29311", description="M3 Screw Zinc Plated").value,
        classify(mpn="F1", description="Fiducial marker").value,
        classify(mpn="ERJ-P03F1101V", category="Resistors").value,
        classify(mpn="TPS62130RGTR", category="ICs", description="converter").value,
    }
    assert seen == {"mechanical", "virtual", "passive", "component"}


# ------------------------------------------------------- never override a human decision

def test_reclassify_leaves_an_already_classified_record_alone():
    """A person who marked a part mechanical has made a decision; re-running the importer must not
    quietly overturn it. Same rule, same reason, as `refile_category` for categories."""
    rec = PartRecord(
        id="x-0000", mpn="LM317T", manufacturer="TI", part_class=PartClass.MECHANICAL,
        category="ICs", description="Adjustable regulator",
    )
    assert reclassify(rec) is None


def test_reclassify_DOES_move_an_unclassified_record():
    """The negative control for the test above: without this, that test would pass on a
    `reclassify` that always returned None."""
    rec = PartRecord(
        id="x-0000", mpn="29311", manufacturer="Keystone", part_class=PartClass.COMPONENT,
        category="Other", description="Screws & Fasteners M3 6.0mm Screw Zinc Plated Steel",
    )
    assert reclassify(rec) is PartClass.MECHANICAL


def test_reclassify_returns_None_when_the_proposal_matches_what_is_stored():
    """No churn: a record already on the class the classifier would pick is not a change."""
    rec = PartRecord(
        id="x-0000", mpn="TPS62130RGTR", manufacturer="TI", part_class=PartClass.COMPONENT,
        category="ICs", description="3A step-down converter",
    )
    assert reclassify(rec) is None
