"""
Fleet Trial Design Domains (TDD) Example

Demonstrates creating all five protocol-reference TDD domains (TE, TA, TV, TS, TI)
and the two subject-level domains (SV, SE) using Fleet's fixed-sequence pipeline
with rich Pydantic models and collection-level validators.

Pipeline pattern for protocol-reference domains:
    fetch_structure() → study_header() → add_*() → to_frame()

Subject-level domains (SV, SE) mix TDD verbs freely with standard SDTM verbs.

Run from repo root:
    uv run python examples/tdd_example.py
"""

from __future__ import annotations

from unittest.mock import patch

import polars as pl

import fleet  # registers .sdtm namespace extension
from fleet.sdtm.tdd import (
    Epoch,
    TrialArm,
    TrialArms,
    TrialCriteria,
    TrialCriterion,
    TrialElement,
    TrialElements,
    TrialParameter,
    TrialParameters,
    TrialVisit,
    TrialVisits,
    parse_trial_design,
)

# ── Fake IG metadata (avoids CDISC API key requirement for this demo) ─────
MOCK_META = {
    "domain": "TE",
    "label": "Trial Elements",
    "ig_version": "3-4",
    "variables": [
        {
            "name": "STUDYID",
            "type": "Char",
            "core": "Req",
            "label": "Study Identifier",
            "role": "Identifier",
        },
        {
            "name": "DOMAIN",
            "type": "Char",
            "core": "Req",
            "label": "Domain Abbreviation",
            "role": "Identifier",
        },
        {"name": "ETCD", "type": "Char", "core": "Req", "label": "Element Code", "role": "Topic"},
        {
            "name": "ELEMENT",
            "type": "Char",
            "core": "Req",
            "label": "Description of Element",
            "role": "",
        },
        {"name": "TESTRL", "type": "Char", "core": "Perm", "label": "Rule for Start", "role": ""},
        {"name": "TEENRL", "type": "Char", "core": "Perm", "label": "Rule for End", "role": ""},
        {"name": "TEDUR", "type": "Char", "core": "Perm", "label": "Planned Duration", "role": ""},
        {
            "name": "EPOCH",
            "type": "Char",
            "core": "Req",
            "label": "Epoch",
            "role": "",
            "codelist": "C99079",
        },
    ],
}


def _mock_fetch(domain: str, ig_version: str) -> dict:
    """Return fake IG metadata for any domain (demo purposes)."""
    return {**MOCK_META, "domain": domain}


def main() -> None:
    print("═" * 72)
    print("  Fleet — Trial Design Domains (TDD) Example")
    print("═" * 72)

    # ════════════════════════════════════════════════════════════════════
    # 1. TE — Trial Elements
    # ════════════════════════════════════════════════════════════════════
    print("\n── 1. TE (Trial Elements) ──────────────────────────────────")

    te_rows = TrialElements(
        elements=[
            TrialElement(
                etcd="SCRN",
                element="Screening",
                testrl="INFORMED CONSENT",
                teenrl="RANDOMIZATION - 1",
                tedur="P14D",
                epoch=Epoch.SCREENING,
            ),
            TrialElement(
                etcd="TRT",
                element="Treatment",
                testrl="RANDOMIZATION",
                teenrl="END OF TREATMENT",
                tedur="P84D",
                epoch=Epoch.TREATMENT,
            ),
            TrialElement(
                etcd="FU",
                element="Follow-up",
                testrl="END OF TREATMENT + 1",
                teenrl="END OF FOLLOW-UP",
                tedur="P28D",
                epoch=Epoch.FOLLOW_UP,
            ),
        ]
    )

    with patch(
        "fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain",
        side_effect=_mock_fetch,
    ):
        te = (
            fleet.frame(pl.DataFrame())
            .sdtm.fetch_structure("TE", ig_version="3-4")
            .study_header(study_id="CDISCPILOT01", domain="TE")
            .add_elements(te_rows)
            .to_frame()
        )
    print(te)

    # ════════════════════════════════════════════════════════════════════
    # 2. TA — Trial Arms (with FK validation against TE)
    # ════════════════════════════════════════════════════════════════════
    print("\n── 2. TA (Trial Arms) ──────────────────────────────────────")

    ta_rows = TrialArms(
        arms=[
            TrialArm(
                armcd="PBO",
                arm="Placebo",
                taetord=1,
                etcd="SCRN",
                element="Screening",
                epoch=Epoch.SCREENING,
            ),
            TrialArm(
                armcd="PBO",
                arm="Placebo",
                taetord=2,
                etcd="TRT",
                element="Treatment",
                epoch=Epoch.TREATMENT,
            ),
            TrialArm(
                armcd="PBO",
                arm="Placebo",
                taetord=3,
                etcd="FU",
                element="Follow-up",
                epoch=Epoch.FOLLOW_UP,
            ),
            TrialArm(
                armcd="XAN_LO",
                arm="Xanomeline Low Dose",
                taetord=1,
                etcd="SCRN",
                element="Screening",
                epoch=Epoch.SCREENING,
            ),
            TrialArm(
                armcd="XAN_LO",
                arm="Xanomeline Low Dose",
                taetord=2,
                etcd="TRT",
                element="Treatment",
                epoch=Epoch.TREATMENT,
            ),
            TrialArm(
                armcd="XAN_LO",
                arm="Xanomeline Low Dose",
                taetord=3,
                etcd="FU",
                element="Follow-up",
                epoch=Epoch.FOLLOW_UP,
            ),
        ]
    )

    with patch(
        "fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain",
        side_effect=_mock_fetch,
    ):
        ta = (
            fleet.frame(pl.DataFrame())
            .sdtm.fetch_structure("TA")
            .study_header("CDISCPILOT01", "TA")
            .add_arms(ta_rows, te=te_rows)  # FK check: ETCD ∈ TE.ETCD
            .to_frame()
        )
    print(ta)

    # ════════════════════════════════════════════════════════════════════
    # 3. TV — Trial Visits
    # ════════════════════════════════════════════════════════════════════
    print("\n── 3. TV (Trial Visits) ────────────────────────────────────")

    tv_rows = TrialVisits(
        visits=[
            TrialVisit(visitnum=1, visit="Screening", visitdy=1),
            TrialVisit(visitnum=2, visit="Baseline", visitdy=14),
            TrialVisit(visitnum=3, visit="Week 4", visitdy=42),
            TrialVisit(visitnum=4, visit="Week 8", visitdy=70),
            TrialVisit(visitnum=5, visit="Week 12", visitdy=98),
            TrialVisit(visitnum=6, visit="End of Treatment", visitdy=112),
            TrialVisit(visitnum=7, visit="Follow-up", visitdy=140),
        ]
    )

    with patch(
        "fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain",
        side_effect=_mock_fetch,
    ):
        tv = (
            fleet.frame(pl.DataFrame())
            .sdtm.fetch_structure("TV")
            .study_header("CDISCPILOT01", "TV")
            .add_visits(tv_rows)
            .to_frame()
        )
    print(tv)

    # ════════════════════════════════════════════════════════════════════
    # 4. TS — Trial Summary
    # ════════════════════════════════════════════════════════════════════
    print("\n── 4. TS (Trial Summary) ───────────────────────────────────")

    ts_rows = TrialParameters(
        parameters=[
            TrialParameter(tsparmcd="ADDON", tsparm="Added on to Existing Treatments", tsval="N"),
            TrialParameter(tsparmcd="AGEMAX", tsparm="Planned Maximum Age of Subjects", tsval="80"),
            TrialParameter(tsparmcd="AGEMIN", tsparm="Planned Minimum Age of Subjects", tsval="50"),
            TrialParameter(tsparmcd="LENGTH", tsparm="Trial Length", tsval="26"),
            TrialParameter(
                tsparmcd="PLTEFFL", tsparm="Planned Treatment Epoch Length", tsval="182"
            ),
            TrialParameter(tsparmcd="STOTEFFL", tsparm="Study Objective", tsval="EFFICACY"),
        ]
    )

    with patch(
        "fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain",
        side_effect=_mock_fetch,
    ):
        ts = (
            fleet.frame(pl.DataFrame())
            .sdtm.fetch_structure("TS")
            .study_header("CDISCPILOT01", "TS")
            .add_parameters(ts_rows)
            .to_frame()
        )
    print(ts)

    # ════════════════════════════════════════════════════════════════════
    # 5. TI — Trial Inclusion/Exclusion
    # ════════════════════════════════════════════════════════════════════
    print("\n── 5. TI (Trial Inclusion/Exclusion) ───────────────────────")

    ti_rows = TrialCriteria(
        criteria=[
            TrialCriterion(
                ietestcd="INCL01", ietest="Age 50-80 years at screening", iecat="INCLUSION"
            ),
            TrialCriterion(
                ietestcd="INCL02", ietest="Diagnosis of Alzheimer's Disease", iecat="INCLUSION"
            ),
            TrialCriterion(ietestcd="EXCL01", ietest="Pregnancy or lactation", iecat="EXCLUSION"),
            TrialCriterion(
                ietestcd="EXCL02", ietest="Known hypersensitivity to study drug", iecat="EXCLUSION"
            ),
        ]
    )

    with patch(
        "fleet.sdtm._tdd_mixin.TrialDesignMixin._fetch_ig_domain",
        side_effect=_mock_fetch,
    ):
        ti = (
            fleet.frame(pl.DataFrame())
            .sdtm.fetch_structure("TI")
            .study_header("CDISCPILOT01", "TI")
            .add_criteria(ti_rows)
            .to_frame()
        )
    print(ti)

    # ════════════════════════════════════════════════════════════════════
    # 6. SV — Subject Visits (subject-level, mixes with SDTM verbs)
    # ════════════════════════════════════════════════════════════════════
    print("\n── 6. SV (Subject Visits) ──────────────────────────────────")

    raw_visits = fleet.frame(
        pl.from_repr("""\
┌─────────────┬────────────┬────────────┐
│ subject_id  ┆ visit_date ┆ ref_date   │
│ ---         ┆ ---        ┆ ---        │
│ str         ┆ str        ┆ str        │
╞═════════════╪════════════╪════════════╡
│ 01-701-1015 ┆ 2014-01-02 ┆ 2014-01-01 │
│ 01-701-1015 ┆ 2014-01-15 ┆ 2014-01-01 │
│ 01-701-1015 ┆ 2014-02-13 ┆ 2014-01-01 │
│ 01-701-1023 ┆ 2014-01-03 ┆ 2014-01-01 │
│ 01-701-1023 ┆ 2014-01-17 ┆ 2014-01-01 │
│ 01-701-1023 ┆ 2014-02-14 ┆ 2014-01-01 │
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
        .epoch_assign(
            "EPOCH",
            date_col="visit_date",
            epoch_ranges=[
                {"start": "2014-01-01", "end": "2014-01-13", "epoch": "SCREENING"},
                {"start": "2014-01-14", "end": "2014-04-15", "epoch": "TREATMENT"},
                {"start": "2014-04-16", "end": "2014-12-31", "epoch": "FOLLOW-UP"},
            ],
        )
        .to_frame()
    )
    print(sv)

    # ════════════════════════════════════════════════════════════════════
    # 7. SE — Subject Elements (subject-level)
    # ════════════════════════════════════════════════════════════════════
    print("\n── 7. SE (Subject Elements) ────────────────────────────────")

    disposition = fleet.frame(
        pl.from_repr("""\
┌─────────────┬──────┬────────────────┬─────────────────┬─────────────────┬────────────┐
│ subject_id  ┆ ETCD ┆ screening_date ┆ first_dose_date ┆ last_visit_date ┆ ref_date   │
│ ---         ┆ ---  ┆ ---            ┆ ---             ┆ ---             ┆ ---        │
│ str         ┆ str  ┆ str            ┆ str             ┆ str             ┆ str        │
╞═════════════╪══════╪════════════════╪═════════════════╪═════════════════╪════════════╡
│ 01-701-1015 ┆ SCRN ┆ 2014-01-01     ┆ 2014-01-15      ┆ 2014-05-01      ┆ 2014-01-15 │
│ 01-701-1015 ┆ TRT  ┆ 2014-01-01     ┆ 2014-01-15      ┆ 2014-05-01      ┆ 2014-01-15 │
│ 01-701-1015 ┆ FU   ┆ 2014-01-01     ┆ 2014-01-15      ┆ 2014-05-01      ┆ 2014-01-15 │
└─────────────┴──────┴────────────────┴─────────────────┴─────────────────┴────────────┘
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
                "TRT": "first_dose_date",
                "FU": "last_visit_date",
            },
            element_col="ETCD",
            subject_col="USUBJID",
        )
        .duration("SESTDY", start="ref_date", end="SESTDTC")
        .epoch_assign(
            "EPOCH",
            date_col="SESTDTC",
            epoch_ranges=[
                {"start": "2014-01-01", "end": "2014-01-14", "epoch": "SCREENING"},
                {"start": "2014-01-15", "end": "2014-04-30", "epoch": "TREATMENT"},
                {"start": "2014-05-01", "end": "2014-12-31", "epoch": "FOLLOW-UP"},
            ],
        )
        .to_frame()
    )
    print(se)

    # ════════════════════════════════════════════════════════════════════
    # 8. Bonus — Mermaid flowchart → TE + TA
    # ════════════════════════════════════════════════════════════════════
    print("\n── 8. Mermaid Parser ───────────────────────────────────────")

    mermaid_text = """
        flowchart TD
        subgraph SCR[SCREENING]
            SCRN["Screening<br/>P14D"]
        end
        subgraph TRT[TREATMENT]
            DRUG["Drug Treatment<br/>P84D"]
            PBO["Placebo<br/>P84D"]
        end
        subgraph FU[FOLLOW-UP]
            FOLL["Follow-up<br/>P28D"]
        end
        SCRN -->|DRUG_ARM| DRUG
        SCRN -->|PBO_ARM| PBO
        DRUG --> FOLL
        PBO --> FOLL
    """

    te_parsed, ta_parsed = parse_trial_design(mermaid_text)
    print(f"   Parsed TE: {len(te_parsed.elements)} elements")
    for e in te_parsed.elements:
        print(f"      {e.etcd:8s}  {e.element:25s}  {e.tedur or '-':8s}  {e.epoch.value}")
    print(f"   Parsed TA: {len(ta_parsed.arms)} arm-element rows")
    for a in ta_parsed.arms:
        print(f"      {a.armcd:10s}  ord={a.taetord}  {a.etcd:8s}  {a.epoch.value}")

    print("\n" + "═" * 72)
    print("  All 7 TDD domains created successfully!")
    print("═" * 72)


if __name__ == "__main__":
    main()
