"""
Fleet Trial Design Domains (TDD) Example

Demonstrates the two ways to create trial design datasets:

1. **StudyDesign aggregate** (recommended) — define the design once, derive
   every protocol-reference domain (TE, TA, TV, TS, TI, TD, TM), audit it
   against P21-style conformance rules, and round-trip through Mermaid/YAML.

2. **Row-level pipeline** — the fixed-sequence verb chain
   ``fetch_structure() → study_header() → add_*() → to_frame()``
   with rich Pydantic collections, for when you need full row control.

Subject-level domains (SV, SE) mix TDD verbs freely with standard SDTM
verbs; EPOCH is stamped from the subject's own SE intervals.

Everything runs offline: SDTMIG 3.4 structures for the TDD domains ship
with Fleet, so no CDISC Library API key is needed.

Run from repo root:
    uv run python examples/tdd_example.py
"""

from __future__ import annotations

import polars as pl

import fleet  # registers .sdtm namespace extension
from fleet.sdtm.tdd import (
    TrialCriteria,
    TrialCriterion,
    TrialDiseaseAssessment,
    TrialDiseaseAssessments,
    TrialMilestone,
    TrialMilestones,
    TrialVisits,
)


def main() -> None:
    print("═" * 72)
    print("  Fleet — Trial Design Domains (TDD) Example")
    print("═" * 72)

    # ════════════════════════════════════════════════════════════════════
    # 1. StudyDesign — define the design ONCE
    # ════════════════════════════════════════════════════════════════════
    print("\n── 1. StudyDesign (define once, derive everything) ─────────")

    design = fleet.StudyDesign(
        study_id="CDISCPILOT01",
        elements=[
            {
                "etcd": "SCRN",
                "element": "Screening",
                "tedur": "P14D",
                "epoch": "SCREENING",
                "testrl": "INFORMED CONSENT",
                "teenrl": "RANDOMIZATION - 1",
            },
            {
                "etcd": "PBO",
                "element": "Placebo Treatment",
                "tedur": "P84D",
                "epoch": "TREATMENT",
                "testrl": "RANDOMIZATION",
            },
            {
                "etcd": "XANLO",
                "element": "Xanomeline Low Dose Treatment",
                "tedur": "P84D",
                "epoch": "TREATMENT",
                "testrl": "RANDOMIZATION",
            },
            {
                "etcd": "FU",
                "element": "Follow-up",
                "tedur": "P28D",
                "epoch": "FOLLOW-UP",
                "testrl": "END OF TREATMENT + 1",
            },
        ],
        # Arms are element paths — TAETORD, ELEMENT, EPOCH, TABRANCH derive.
        arms={"PBO": ["SCRN", "PBO", "FU"], "XAN_LO": ["SCRN", "XANLO", "FU"]},
        arm_names={"PBO": "Placebo", "XAN_LO": "Xanomeline Low Dose"},
        # Anchor-based visit schedule: (name, day offset from randomization).
        visits=TrialVisits.from_schedule(
            [("Screening", -14), ("Baseline", 0), ("Week 4", 28), ("Week 8", 56)],
            anchor="RANDOMIZATION",
            window=3,
        ).visits,
        criteria=[
            {"ietestcd": "INCL01", "ietest": "Age 50-80 years at screening", "iecat": "INCLUSION"},
            {"ietestcd": "EXCL01", "ietest": "Pregnancy or lactation", "iecat": "EXCLUSION"},
        ],
        parameters=[
            {"tsparmcd": "TITLE", "tsparm": "Trial Title", "tsval": "Xanomeline TTS Study"},
            {"tsparmcd": "STYPE", "tsparm": "Study Type", "tsval": "INTERVENTIONAL"},
            {"tsparmcd": "SSTDTC", "tsparm": "Study Start Date", "tsval": "2014-01-01"},
        ],
    )

    frames = design.domains()
    for domain, df in frames.items():
        print(f"   {domain}: {df.shape[0]} rows × {df.shape[1]} cols")
    print("\n   TA (derived — note TAETORD, TABRANCH, EPOCH):")
    print(design.to_ta())

    # ════════════════════════════════════════════════════════════════════
    # 2. Conformance audit — P21 dry-run, offline
    # ════════════════════════════════════════════════════════════════════
    print("\n── 2. Conformance audit (P21-style rule IDs) ───────────────")

    findings = design.audit()
    print(f"   {findings.height} finding(s) — e.g. the FDA TS parameter profile:")
    print(findings.head(5))

    # ════════════════════════════════════════════════════════════════════
    # 3. Mermaid round trip — diagram in, diagram out
    # ════════════════════════════════════════════════════════════════════
    print("\n── 3. Mermaid round trip ───────────────────────────────────")

    mermaid = design.to_mermaid()
    print(mermaid)
    reparsed = fleet.StudyDesign.from_mermaid(mermaid, study_id="CDISCPILOT01")
    print(f"   Round trip OK: {reparsed.arms == design.arms}")

    # ════════════════════════════════════════════════════════════════════
    # 4. Row-level pipeline — fetch_structure → study_header → add_*
    # ════════════════════════════════════════════════════════════════════
    print("\n── 4. Row-level pipeline (TI example, offline) ─────────────")

    ti_rows = TrialCriteria(
        criteria=[
            TrialCriterion(
                ietestcd="INCL01", ietest="Age 50-80 years at screening", iecat="INCLUSION"
            ),
            TrialCriterion(ietestcd="EXCL01", ietest="Pregnancy or lactation", iecat="EXCLUSION"),
        ]
    )
    ti = (
        fleet.frame(pl.DataFrame())
        .sdtm.fetch_structure("TI")  # packaged SDTMIG 3.4 structure — no API call
        .study_header("CDISCPILOT01", "TI")
        .add_criteria(ti_rows)
        .to_frame()
    )
    print(ti)

    # ════════════════════════════════════════════════════════════════════
    # 5. TD + TM — disease assessments and milestones
    # ════════════════════════════════════════════════════════════════════
    print("\n── 5. TD / TM (disease assessments & milestones) ───────────")

    td = (
        fleet.frame(pl.DataFrame())
        .sdtm.fetch_structure("TD")
        .study_header("CDISCPILOT01", "TD")
        .add_disease_assessments(
            TrialDiseaseAssessments(
                assessments=[
                    TrialDiseaseAssessment(
                        tdorder=1,
                        tdancvar="TDANCH01",
                        tdstoff="P0D",
                        tdtgtpai="P8W",
                        tdminpai="P7W",
                        tdmaxpai="P9W",
                        tdnumrpt=6,
                    )
                ]
            )
        )
        .to_frame()
    )
    print(td)

    tm = (
        fleet.frame(pl.DataFrame())
        .sdtm.fetch_structure("TM")
        .study_header("CDISCPILOT01", "TM")
        .add_milestones(
            TrialMilestones(
                milestones=[
                    TrialMilestone(
                        midstype="DIAGNOSIS",
                        tmdef="Initial diagnosis of Alzheimer's disease",
                        tmrpt="N",
                    )
                ]
            )
        )
        .to_frame()
    )
    print(tm)

    # ════════════════════════════════════════════════════════════════════
    # 6. SV — Subject Visits (subject-level, mixes with SDTM verbs)
    # ════════════════════════════════════════════════════════════════════
    print("\n── 6. SV (Subject Visits) ──────────────────────────────────")

    tv_rows = TrialVisits.from_schedule(
        [("Screening", -14), ("Baseline", 0), ("Week 4", 28)],
        anchor="RANDOMIZATION",
        window=5,
    )

    raw_visits = fleet.frame(
        pl.from_repr("""\
┌─────────────┬────────────┬────────────┐
│ subject_id  ┆ visit_date ┆ ref_date   │
│ ---         ┆ ---        ┆ ---        │
│ str         ┆ str        ┆ str        │
╞═════════════╪════════════╪════════════╡
│ 01-701-1015 ┆ 2014-01-02 ┆ 2014-01-15 │
│ 01-701-1015 ┆ 2014-01-15 ┆ 2014-01-15 │
│ 01-701-1015 ┆ 2014-02-13 ┆ 2014-01-15 │
│ 01-701-1023 ┆ 2014-01-03 ┆ 2014-01-16 │
│ 01-701-1023 ┆ 2014-01-17 ┆ 2014-01-16 │
│ 01-701-1023 ┆ 2014-02-14 ┆ 2014-01-16 │
└─────────────┴────────────┴────────────┘
""")
    )

    sv = (
        raw_visits.sdtm.assign("DOMAIN", value="SV")
        .assign("STUDYID", value="CDISCPILOT01")
        .assign("USUBJID", source="subject_id")
        .assign("SVSTDTC", source="visit_date")
        .visit_map(
            "VISITNUM",
            "VISIT",
            date_col="visit_date",
            planned_visits=tv_rows,
            ref_date="ref_date",
            tolerance={"before": 5, "after": 5},
        )
        .duration("SVSTDY", start="ref_date", end="visit_date")
        .to_frame()
    )
    print(sv)

    # ════════════════════════════════════════════════════════════════════
    # 7. SE — Subject Elements, then EPOCH stamped from SE
    # ════════════════════════════════════════════════════════════════════
    print("\n── 7. SE (Subject Elements) + EPOCH from SE ────────────────")

    disposition = fleet.frame(
        pl.from_repr("""\
┌─────────────┬──────┬────────────────┬─────────────────┬─────────────────┐
│ subject_id  ┆ ETCD ┆ screening_date ┆ first_dose_date ┆ last_visit_date │
│ ---         ┆ ---  ┆ ---            ┆ ---             ┆ ---             │
│ str         ┆ str  ┆ str            ┆ str             ┆ str             │
╞═════════════╪══════╪════════════════╪═════════════════╪═════════════════╡
│ 01-701-1015 ┆ SCRN ┆ 2014-01-01     ┆ 2014-01-15      ┆ 2014-05-01      │
│ 01-701-1015 ┆ PBO  ┆ 2014-01-01     ┆ 2014-01-15      ┆ 2014-05-01      │
│ 01-701-1015 ┆ FU   ┆ 2014-01-01     ┆ 2014-01-15      ┆ 2014-05-01      │
└─────────────┴──────┴────────────────┴─────────────────┴─────────────────┘
""")
    )

    se = (
        disposition.sdtm.assign("DOMAIN", value="SE")
        .assign("STUDYID", value="CDISCPILOT01")
        .assign("USUBJID", source="subject_id")
        .assign("ETCD", source="ETCD")
        .element_boundaries(
            "SESTDTC",
            "SEENDTC",
            milestones={
                "SCRN": "screening_date",
                "PBO": "first_dose_date",
                "FU": "last_visit_date",
            },
            element_col="ETCD",
            subject_col="USUBJID",
        )
        .epoch_assign(
            "EPOCH",
            date_col="SESTDTC",
            epoch_ranges=[
                {"start": "2014-01-01", "end": "2014-01-14", "epoch": "SCREENING"},
                {"start": "2014-01-15", "end": "2014-04-30", "epoch": "TREATMENT"},
                {"start": "2014-05-01", "end": "2014-12-31", "epoch": "FOLLOW-UP"},
            ],
        )
        .seq("SESEQ", order_by=["SESTDTC"])
        .to_frame()
    )
    print(se)

    # EPOCH on any other domain, derived from the subject's own SE intervals.
    ae_raw = fleet.frame(
        pl.from_repr("""\
┌─────────────┬────────────┐
│ subject_id  ┆ ae_date    │
│ ---         ┆ ---        │
│ str         ┆ str        │
╞═════════════╪════════════╡
│ 01-701-1015 ┆ 2014-01-05 │
│ 01-701-1015 ┆ 2014-02-01 │
└─────────────┴────────────┘
""")
    )
    ae_epoch = (
        ae_raw.sdtm.assign("USUBJID", source="subject_id")
        .assign("AESTDTC", source="ae_date")
        .epoch_assign("EPOCH", date_col="AESTDTC", se=se)
        .to_frame()
    )
    print(ae_epoch)

    # ════════════════════════════════════════════════════════════════════
    # 8. TS seeding from ClinicalTrials.gov (network — shown, not run)
    # ════════════════════════════════════════════════════════════════════
    print("\n── 8. TS seeding from ClinicalTrials.gov ───────────────────")
    print("   ts_rows = TrialParameters.from_ctgov('NCT00048217')")
    print("   (fetches REGID/TITLE/TPHASE/AGEMIN/AGEMAX/... — needs network,")
    print("    so it is not executed in this offline example)")

    print("\n" + "═" * 72)
    print("  All trial design domains created successfully — fully offline!")
    print("═" * 72)


if __name__ == "__main__":
    main()
