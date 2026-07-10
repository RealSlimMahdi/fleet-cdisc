"""Study design aggregate — define the trial design once, derive every domain.

``StudyDesign`` is the single typed source of truth for a study's structure:
elements, arms (as ordered element paths), visits, criteria, and summary
parameters.  Every Trial Design domain (TE, TA, TV, TS, TI, TD, TM) is
*derived* from it, so TAETORD ordering, element/epoch duplication across
arms, and cross-domain FK consistency fall out mechanically instead of being
hand-maintained per row.

Usage::

    import fleet

    design = fleet.StudyDesign(
        study_id="CDISCPILOT01",
        elements=[
            {"etcd": "SCRN", "element": "Screening", "tedur": "P14D",
             "epoch": "SCREENING"},
            {"etcd": "TRT", "element": "Treatment", "tedur": "P84D",
             "epoch": "TREATMENT"},
            {"etcd": "FU", "element": "Follow-up", "tedur": "P28D",
             "epoch": "FOLLOW-UP"},
        ],
        arms={"PBO": ["SCRN", "TRT", "FU"], "XAN_LO": ["SCRN", "TRT", "FU"]},
        arm_names={"PBO": "Placebo", "XAN_LO": "Xanomeline Low Dose"},
    )
    ta = design.to_ta()
    frames = design.domains()       # {"TE": df, "TA": df, ...}
    findings = design.audit()       # P21-style conformance pre-check
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

import polars as pl
import yaml
from pydantic import BaseModel, Field, model_validator

from fleet.sdtm.tdd import (
    TrialArm,
    TrialArms,
    TrialCriteria,
    TrialCriterion,
    TrialDiseaseAssessment,
    TrialDiseaseAssessments,
    TrialElement,
    TrialElements,
    TrialMilestone,
    TrialMilestones,
    TrialParameter,
    TrialParameters,
    TrialVisit,
    TrialVisits,
    parse_trial_design,
)


def _dates_to_iso(value: Any) -> Any:
    """Recursively turn YAML-parsed date/datetime scalars back into ISO strings.

    YAML parses an unquoted ``2026-01-01`` as ``datetime.date``, but every
    SDTM date-bearing field (TSVAL, rule text, ...) is a string.
    """
    if isinstance(value, dict):
        return {k: _dates_to_iso(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dates_to_iso(v) for v in value]
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    return value


def _sdtm_code(name: str, max_len: int, taken: set[str]) -> str:
    """Derive a unique upper-case SDTM short code from a free-text name."""
    base = re.sub(r"[^A-Z0-9]", "", name.upper())[:max_len] or "X"
    code, n = base, 1
    while code in taken:
        n += 1
        suffix = str(n)
        code = base[: max_len - len(suffix)] + suffix
    taken.add(code)
    return code


class StudyDesign(BaseModel):
    """Typed aggregate of a study's trial design.

    ``arms`` maps each ARMCD to its ordered path of element codes — the
    per-arm element name/epoch/TAETORD repetition of raw TA rows is derived,
    never written by hand.  All fields accept plain dicts (Pydantic coerces),
    so a ``trial_design.yaml`` deserialises directly via :meth:`from_yaml`.
    """

    study_id: str = Field(min_length=1)
    elements: list[TrialElement] = []
    arms: dict[str, list[str]] = {}
    arm_names: dict[str, str] = {}
    visits: list[TrialVisit] = []
    criteria: list[TrialCriterion] = []
    parameters: list[TrialParameter] = []
    assessments: list[TrialDiseaseAssessment] = []
    milestones: list[TrialMilestone] = []

    @model_validator(mode="after")
    def check_referential_integrity(self) -> StudyDesign:
        TrialElements(elements=self.elements)  # uniqueness + epoch consistency
        known = {e.etcd for e in self.elements}
        for armcd, path in self.arms.items():
            if not path:
                raise ValueError(f"Arm '{armcd}' has an empty element path")
            missing = [etcd for etcd in path if etcd not in known]
            if missing:
                raise ValueError(f"Arm '{armcd}' references undefined elements: {missing}")
        for visit in self.visits:
            if visit.armcd and visit.armcd not in self.arms:
                raise ValueError(f"Visit '{visit.visit}' references undefined arm '{visit.armcd}'")
        return self

    # ------------------------------------------------------------------ #
    # Derivation                                                           #
    # ------------------------------------------------------------------ #

    def _frame(self, df: pl.DataFrame, domain: str) -> pl.DataFrame:
        """Prepend STUDYID/DOMAIN in SDTM column order."""
        return df.select(
            pl.lit(self.study_id).alias("STUDYID"),
            pl.lit(domain).alias("DOMAIN"),
            pl.all(),
        )

    def _branch_index(self) -> int | None:
        """Index of the last element shared by every arm before paths diverge.

        ponytail: single randomized-branch designs only; nested or adaptive
        branch points need explicit TrialArm rows built by hand.
        """
        paths = list(self.arms.values())
        if len(paths) < 2:
            return None
        prefix = 0
        while all(len(p) > prefix for p in paths) and len({p[prefix] for p in paths}) == 1:
            prefix += 1
        if prefix == 0 or all(p[prefix:] == paths[0][prefix:] for p in paths):
            return None  # identical paths or no shared prefix — no branch to describe
        return prefix - 1

    def arm_collection(self) -> TrialArms:
        """Derive the validated ``TrialArms`` collection from the arm paths.

        Returns:
            TrialArms: One row per arm/element with TAETORD, ELEMENT, EPOCH
                looked up from the element definitions and TABRANCH rendered
                at the randomization branch point.

        Examples:
            Derive TA rows from a design::

                design = fleet.StudyDesign(study_id="S1", elements=[...],
                                           arms={"PBO": ["SCRN", "TRT"]})
                ta_rows = design.arm_collection()
        """
        lookup = {e.etcd: e for e in self.elements}
        branch_at = self._branch_index()
        rows = []
        for armcd, path in self.arms.items():
            arm = self.arm_names.get(armcd) or armcd.replace("_", " ").title()
            for order, etcd in enumerate(path, start=1):
                el = lookup[etcd]
                rows.append(
                    TrialArm(
                        armcd=armcd,
                        arm=arm,
                        taetord=order,
                        etcd=etcd,
                        element=el.element,
                        tabranch=f"Randomized to {arm}" if branch_at == order - 1 else "",
                        epoch=el.epoch,
                    )
                )
        return TrialArms(arms=rows)

    def to_te(self) -> pl.DataFrame:
        """Derive the TE (Trial Elements) domain.

        Returns:
            pl.DataFrame: TE with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TE from a design::

                te = design.to_te()
        """
        return self._frame(TrialElements(elements=self.elements).to_polars(), "TE")

    def to_ta(self) -> pl.DataFrame:
        """Derive the TA (Trial Arms) domain from the arm paths.

        Returns:
            pl.DataFrame: TA with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TA from a design::

                ta = design.to_ta()
        """
        return self._frame(self.arm_collection().to_polars(), "TA")

    def to_tv(self) -> pl.DataFrame:
        """Derive the TV (Trial Visits) domain.

        Returns:
            pl.DataFrame: TV with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TV from a design::

                tv = design.to_tv()
        """
        return self._frame(TrialVisits(visits=self.visits).to_polars(), "TV")

    def to_ts(self) -> pl.DataFrame:
        """Derive the TS (Trial Summary) domain.

        Returns:
            pl.DataFrame: TS with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TS from a design::

                ts = design.to_ts()
        """
        return self._frame(TrialParameters(parameters=self.parameters).to_polars(), "TS")

    def to_ti(self) -> pl.DataFrame:
        """Derive the TI (Trial Inclusion/Exclusion) domain.

        Returns:
            pl.DataFrame: TI with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TI from a design::

                ti = design.to_ti()
        """
        return self._frame(TrialCriteria(criteria=self.criteria).to_polars(), "TI")

    def to_td(self) -> pl.DataFrame:
        """Derive the TD (Trial Disease Assessments) domain.

        Returns:
            pl.DataFrame: TD with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TD from a design::

                td = design.to_td()
        """
        return self._frame(TrialDiseaseAssessments(assessments=self.assessments).to_polars(), "TD")

    def to_tm(self) -> pl.DataFrame:
        """Derive the TM (Trial Disease Milestones) domain.

        Returns:
            pl.DataFrame: TM with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TM from a design::

                tm = design.to_tm()
        """
        return self._frame(TrialMilestones(milestones=self.milestones).to_polars(), "TM")

    def domains(self) -> dict[str, pl.DataFrame]:
        """Derive every populated Trial Design domain.

        Returns:
            dict[str, pl.DataFrame]: Domain code → DataFrame, skipping
                domains whose design section is empty.

        Examples:
            Build all domains and write them out::

                for domain, df in design.domains().items():
                    df.write_parquet(f"data/sdtm/{domain.lower()}.parquet")
        """
        sections = {
            "TE": (self.elements, self.to_te),
            "TA": (self.arms, self.to_ta),
            "TV": (self.visits, self.to_tv),
            "TS": (self.parameters, self.to_ts),
            "TI": (self.criteria, self.to_ti),
            "TD": (self.assessments, self.to_td),
            "TM": (self.milestones, self.to_tm),
        }
        return {domain: build() for domain, (section, build) in sections.items() if section}

    def audit(self, *, dm: pl.DataFrame | None = None) -> pl.DataFrame:
        """Run the P21-style conformance pre-check over the derived domains.

        Args:
            dm: Optional DM domain for cross-checking ARMCD assignments.

        Returns:
            pl.DataFrame: One row per finding (``rule_id``, ``severity``,
                ``domain``, ``message``); empty when clean.

        Examples:
            Audit a design before export::

                findings = design.audit()
                errors = findings.filter(pl.col("severity") == "error")
        """
        from fleet.sdtm.tdd_audit import audit

        frames = self.domains()
        return audit(
            te=frames.get("TE"),
            ta=frames.get("TA"),
            tv=frames.get("TV"),
            # TS is always audited: an absent parameters section means every
            # FDA-required parameter is missing (rejection-level), not "skip".
            ts=frames.get("TS", self.to_ts()),
            ti=frames.get("TI"),
            dm=dm,
        )

    # ------------------------------------------------------------------ #
    # Interchange                                                          #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_yaml(cls, path: str | Path) -> StudyDesign:
        """Load a design from a ``trial_design.yaml`` spec.

        The YAML mirrors the model schema; a top-level ``trial_design:``
        wrapper key is accepted so the section can live inside a larger
        study file.

        Args:
            path: Path to the YAML file.

        Returns:
            StudyDesign: The validated design.

        Examples:
            Load and build every domain::

                design = fleet.StudyDesign.from_yaml("metadata/trial_design.yaml")
                frames = design.domains()
        """
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(**_dates_to_iso(data.get("trial_design", data)))

    def to_yaml(self, path: str | Path | None = None) -> str:
        """Serialise the design to YAML (the ``from_yaml`` round-trip).

        Args:
            path: Optional file path to write to.

        Returns:
            str: The YAML document.

        Examples:
            Persist a design next to the study metadata::

                design.to_yaml("metadata/trial_design.yaml")
        """
        text = yaml.dump(
            self.model_dump(mode="json", exclude_defaults=True),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    @classmethod
    def from_mermaid(cls, mermaid_text: str, *, study_id: str, **sections: Any) -> StudyDesign:
        """Build a design from a Mermaid flowchart.

        Args:
            mermaid_text: A Mermaid ``flowchart TD`` string (see
                :func:`fleet.sdtm.tdd.parse_trial_design`).
            study_id: The study identifier.
            **sections: Extra design sections (``visits=``, ``criteria=``,
                ``parameters=``, ...) passed through to the constructor.

        Returns:
            StudyDesign: Design with elements and arm paths from the diagram.

        Examples:
            Diagram in, datasets out::

                design = fleet.StudyDesign.from_mermaid(diagram_text,
                                                        study_id="CDISCPILOT01")
                ta = design.to_ta()
        """
        te, ta = parse_trial_design(mermaid_text)
        arms: dict[str, list[str]] = {}
        arm_names: dict[str, str] = {}
        for row in sorted(ta.arms, key=lambda a: (a.armcd, a.taetord)):
            arms.setdefault(row.armcd, []).append(row.etcd)
            arm_names[row.armcd] = row.arm
        return cls(
            study_id=study_id,
            elements=te.elements,
            arms=arms,
            arm_names=arm_names,
            **sections,
        )

    def to_mermaid(self) -> str:
        """Render the design as a Mermaid flowchart (inverse of ``from_mermaid``).

        Elements are grouped into epoch subgraphs; edges follow the arm
        paths, labelled with the ARMCD where the design branches — so the
        output round-trips through :meth:`from_mermaid` and drops straight
        into protocol documents or review decks.

        Returns:
            str: A Mermaid ``flowchart TD`` document.

        Examples:
            Render for a design-review doc::

                print(design.to_mermaid())
        """
        lines = ["flowchart TD"]
        by_epoch: dict[str, list[TrialElement]] = {}
        for el in self.elements:
            by_epoch.setdefault(str(el.epoch), []).append(el)
        for i, (epoch, els) in enumerate(by_epoch.items()):
            lines.append(f"    subgraph EP{i}[{epoch}]")
            for el in els:
                dur = f"<br/>{el.tedur}" if el.tedur else ""
                lines.append(f'        {el.etcd}["{el.element}{dur}"]')
            lines.append("    end")
        branch_at = self._branch_index()
        seen: set[tuple[str, str, str]] = set()
        for armcd, path in self.arms.items():
            for i, (src, dst) in enumerate(zip(path, path[1:])):
                label = f"|{armcd}|" if branch_at is not None and i == branch_at else ""
                edge = (src, label, dst)
                if edge not in seen:
                    seen.add(edge)
                    lines.append(f"    {src} -->{label} {dst}")
        return "\n".join(lines)

    @classmethod
    def from_usdm(cls, data: dict, *, study_id: str | None = None) -> StudyDesign:
        """Build a design from a CDISC USDM (DDF) study definition.

        Maps the structural subset of USDM v3/v4 JSON: arms + epochs +
        elements + studyCells become the arm paths, encounters become
        visits, and eligibility criteria become TI rows.

        ponytail: schedule timelines, objectives/endpoints, and biomedical
        concepts are intentionally not mapped — extend when a consumer needs
        them.

        Args:
            data: Parsed USDM JSON (the ``{"study": ...}`` wrapper or the
                study object itself).
            study_id: Override for STUDYID; defaults to the first study
                identifier found in the USDM document.

        Returns:
            StudyDesign: Design with the mapped structural subset.

        Examples:
            Import an OpenStudyBuilder / DDF export::

                import json
                design = fleet.StudyDesign.from_usdm(
                    json.loads(Path("usdm.json").read_text()),
                    study_id="CDISCPILOT01",
                )
        """
        study = data.get("study", data)
        versions = study.get("versions") or study.get("studyVersions") or [study]
        version = versions[0]
        designs = version.get("studyDesigns") or []
        sd = designs[0] if designs else {}

        if study_id is None:
            idents = version.get("studyIdentifiers") or []
            study_id = next(
                (i.get("studyIdentifier") or i.get("text") for i in idents if isinstance(i, dict)),
                None,
            ) or (study.get("name") or "STUDY")

        def label(obj: dict) -> str:
            return obj.get("label") or obj.get("name") or obj.get("id", "")

        epoch_order = [e["id"] for e in sd.get("epochs", [])]
        epoch_label = {e["id"]: label(e).upper() for e in sd.get("epochs", [])}
        taken: set[str] = set()
        etcd_by_id: dict[str, str] = {}
        element_models: dict[str, dict] = {}
        for el in sd.get("elements", []):
            etcd = _sdtm_code(label(el), 8, taken)
            etcd_by_id[el["id"]] = etcd
            element_models[el["id"]] = {
                "etcd": etcd,
                "element": label(el)[:200],
                "testrl": (el.get("transitionStartRule") or {}).get("text", "")[:2000],
                "teenrl": (el.get("transitionEndRule") or {}).get("text", "")[:2000],
            }

        arm_label = {a["id"]: label(a) for a in sd.get("arms", [])}
        arm_taken: set[str] = set()
        armcd_by_id = {aid: _sdtm_code(name, 20, arm_taken) for aid, name in arm_label.items()}

        arms: dict[str, list[str]] = {}
        cells = sorted(
            sd.get("studyCells", []),
            key=lambda c: epoch_order.index(c["epochId"]) if c.get("epochId") in epoch_order else 0,
        )
        for cell in cells:
            armcd = armcd_by_id.get(cell.get("armId", ""))
            if armcd is None:
                continue
            for element_id in cell.get("elementIds", []):
                if element_id in element_models:
                    element_models[element_id].setdefault(
                        "epoch", epoch_label.get(cell.get("epochId", ""), "TREATMENT")
                    )
                    arms.setdefault(armcd, []).append(etcd_by_id[element_id])

        elements = [
            TrialElement(**{"epoch": "TREATMENT", **model}) for model in element_models.values()
        ]

        visits = [
            TrialVisit(visitnum=num, visit=label(enc)[:200])
            for num, enc in enumerate(sd.get("encounters", []), start=1)
        ]

        criteria = []
        raw_criteria = sd.get("eligibilityCriteria") or version.get("eligibilityCriteria") or []
        crit_taken: set[str] = set()
        for crit in raw_criteria:
            category = str((crit.get("category") or {}).get("decode", "")).upper()
            iecat = "EXCLUSION" if "EXCL" in category else "INCLUSION"
            criteria.append(
                TrialCriterion(
                    ietestcd=_sdtm_code(
                        crit.get("identifier") or crit.get("name", "C"), 8, crit_taken
                    ),
                    ietest=(crit.get("text") or label(crit))[:200],
                    iecat=iecat,
                )
            )

        return cls(
            study_id=study_id,
            elements=elements,
            arms=arms,
            arm_names={armcd_by_id[aid]: name for aid, name in arm_label.items()},
            visits=visits,
            criteria=criteria,
        )
