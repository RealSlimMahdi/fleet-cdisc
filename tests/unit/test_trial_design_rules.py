"""Trial design builders: TS split, ctgov enrollment, YAML loader, arm paths, Mermaid, USDM."""

from __future__ import annotations

from textwrap import dedent

import pytest
import yaml
from pydantic import ValidationError

from fleet.sdtm.design import StudyDesign
from fleet.sdtm.tdd import (
    TrialElement,
    TrialElements,
    TrialParameter,
    TrialParameters,
    _ctgov_to_parameters,
    parse_trial_design,
)
from fleet.sdtm.tdd_audit import audit


class TestTsvalSplit:
    """c1-246: TSVAL over 200 characters splits; TSPARM holds 40 at most."""

    def test_long_tsval_splits_at_a_word_boundary(self):
        text = "word " * 90 + "end"  # 453 characters
        ts = TrialParameters(
            parameters=[
                TrialParameter(tsparmcd="TITLE", tsparm="Trial Title", tsval=text),
                TrialParameter(tsparmcd="REGID", tsparm="Registry Identifier", tsval="NCT1"),
            ]
        ).to_polars()
        assert ts.columns[ts.columns.index("TSVAL") : ts.columns.index("TSVAL") + 3] == [
            "TSVAL",
            "TSVAL1",
            "TSVAL2",
        ]
        title = ts.row(0, named=True)
        pieces = [title["TSVAL"], title["TSVAL1"], title["TSVAL2"]]
        assert "".join(pieces) == text
        assert all(len(p) <= 200 for p in pieces)
        assert pieces[1].startswith(" ") and not pieces[0].endswith(" ")
        assert ts.row(1, named=True)["TSVAL1"] == ""

    def test_one_word_over_200_is_cut_at_200(self):
        ts = TrialParameters(
            parameters=[TrialParameter(tsparmcd="TITLE", tsparm="Trial Title", tsval="x" * 250)]
        ).to_polars()
        assert (len(ts["TSVAL"][0]), len(ts["TSVAL1"][0])) == (200, 50)

    def test_short_tsval_adds_no_column(self):
        ts = TrialParameters(
            parameters=[TrialParameter(tsparmcd="REGID", tsparm="Registry Identifier", tsval="N")]
        ).to_polars()
        assert "TSVAL1" not in ts.columns

    def test_tsparm_over_40_is_refused(self):
        with pytest.raises(ValidationError, match="40"):
            TrialParameter(tsparmcd="TITLE", tsparm="T" * 41, tsval="x")

    def test_audit_names_another_char_value_over_200(self):
        ts = TrialParameters(
            parameters=[TrialParameter(tsparmcd="TITLE", tsparm="Trial Title", tsval="x " * 150)]
        ).to_polars()
        assert "FLEETTD03" not in audit(ts=ts)["rule_id"].to_list()
        te = TrialElements(
            elements=[
                TrialElement(etcd="SCRN", element="Screening", testrl="r" * 201, epoch="SCREENING")
            ]
        ).to_polars()
        found = audit(te=te).filter(rule_id="FLEETTD03")
        assert found["message"].to_list() == [
            "TE.TESTRL holds 1 value(s) over 200 characters, the XPT V5 limit. Reword the "
            "text; only TSVAL splits into TSVAL1-TSVALn."
        ]


class TestCtgovEnrollment:
    """c1-249: ACTUAL enrollment is ACTSUB, not PLANSUB."""

    @staticmethod
    def _rows(info: dict) -> dict[str, str]:
        record = {"protocolSection": {"designModule": {"enrollmentInfo": info}}}
        return {r.tsparmcd: r.tsval for r in _ctgov_to_parameters(record)}

    def test_actual_gives_actsub(self):
        assert self._rows({"count": 1062, "type": "ACTUAL"}) == {"ACTSUB": "1062"}

    def test_estimated_gives_plansub(self):
        assert self._rows({"count": 300, "type": "ESTIMATED"}) == {"PLANSUB": "300"}

    def test_no_type_gives_neither(self):
        assert self._rows({"count": 300}) == {}


EXT_ELEMENTS = [
    {"etcd": "SCRN", "element": "Screening", "epoch": "SCREENING"},
    {"etcd": "CORE", "element": "Core", "epoch": "TREATMENT"},
    {"etcd": "EXT", "element": "Extension", "epoch": "OPEN LABEL TREATMENT"},
]


def _ta_rows(design: StudyDesign, *cols: str) -> list[tuple]:
    return list(design.to_ta().select(cols).iter_rows())


class TestTabranch:
    """c1-781 (decision A): the default stays, a step can state the real branch rule."""

    def test_default_text_stays_without_override(self):
        design = StudyDesign(
            study_id="S",
            elements=EXT_ELEMENTS,
            arms={"C": ["SCRN", "CORE"], "E": ["SCRN", "CORE", "EXT"]},
            arm_names={"C": "C", "E": "E"},
        )
        assert ("C", "CORE", "Randomized to C") in _ta_rows(design, "ARMCD", "ETCD", "TABRANCH")

    def test_step_tabranch_and_tatrans_replace_the_default(self):
        design = StudyDesign(
            study_id="S",
            elements=EXT_ELEMENTS,
            arms={
                "C": ["SCRN", {"etcd": "CORE", "tabranch": "Non-responder at end of Core"}],
                "E": [
                    "SCRN",
                    {
                        "etcd": "CORE",
                        "tabranch": "Responder at end of Core",
                        "tatrans": "If relapse, go to follow-up",
                    },
                    "EXT",
                ],
            },
            arm_names={"C": "C", "E": "E"},
        )
        rows = _ta_rows(design, "ARMCD", "ETCD", "TABRANCH", "TATRANS")
        assert ("C", "CORE", "Non-responder at end of Core", "") in rows
        assert ("E", "CORE", "Responder at end of Core", "If relapse, go to follow-up") in rows
        assert not any("Randomized" in r[2] for r in rows)

    def test_randomized_at_puts_the_text_on_that_element(self):
        design = StudyDesign(
            study_id="S",
            elements=EXT_ELEMENTS,
            arms={"C": ["SCRN", "CORE"], "E": ["SCRN", "CORE", "EXT"]},
            arm_names={"C": "C", "E": "E"},
            randomized_at="SCRN",
        )
        rows = _ta_rows(design, "ARMCD", "ETCD", "TABRANCH")
        assert [r for r in rows if r[2]] == [
            ("C", "SCRN", "Randomized to C"),
            ("E", "SCRN", "Randomized to E"),
        ]

    def test_identical_paths_get_an_audit_warning(self):
        design = StudyDesign(
            study_id="S",
            elements=EXT_ELEMENTS,
            arms={"A": ["SCRN", "CORE"], "B": ["SCRN", "CORE"]},
            arm_names={"A": "Arm A", "B": "Arm B"},
        )
        assert "FLEETTD04" in design.audit()["rule_id"].to_list()


XO_ELEMENTS = [
    {"etcd": "SCRN", "element": "Screening", "epoch": "SCREENING"},
    {"etcd": "A", "element": "Drug A", "epoch": "TREATMENT 1"},
    {"etcd": "B", "element": "Drug B", "epoch": "TREATMENT 2"},
    {"etcd": "WO", "element": "Washout", "epoch": "WASHOUT"},
]


class TestPerPositionEpoch:
    """c1-247: a path entry {etcd, epoch} gives the epoch of that position."""

    def test_crossover_epochs_follow_the_position(self):
        design = StudyDesign(
            study_id="S",
            elements=XO_ELEMENTS,
            arms={
                "AB": ["SCRN", "A", "WO", "B"],
                "BA": [
                    "SCRN",
                    {"etcd": "B", "epoch": "TREATMENT 1"},
                    "WO",
                    {"etcd": "A", "epoch": "TREATMENT 2"},
                ],
            },
            arm_names={"AB": "A then B", "BA": "B then A"},
        )
        rows = _ta_rows(design, "ARMCD", "TAETORD", "ETCD", "EPOCH")
        assert ("BA", 2, "B", "TREATMENT 1") in rows
        assert ("BA", 4, "A", "TREATMENT 2") in rows
        assert ("AB", 2, "A", "TREATMENT 1") in rows

    def test_repeated_element_with_no_epoch_warns(self):
        design = StudyDesign(
            study_id="S",
            elements=[
                {"etcd": "SCRN", "element": "Screening", "epoch": "SCREENING"},
                {"etcd": "C1", "element": "Cycle", "epoch": "TREATMENT"},
            ],
            arms={"DRUGX": ["SCRN", "C1", "C1"]},
            arm_names={"DRUGX": "Drug X"},
        )
        assert "FLEETTD05" in design.audit()["rule_id"].to_list()

    def test_yaml_round_trip_keeps_the_steps(self, tmp_path):
        design = StudyDesign(
            study_id="S",
            elements=XO_ELEMENTS,
            arms={"BA": ["SCRN", {"etcd": "B", "epoch": "TREATMENT 1"}, "WO", "A"]},
            arm_names={"BA": "B then A"},
        )
        path = tmp_path / "td.yaml"
        design.to_yaml(path)
        assert StudyDesign.from_yaml(path) == design

    def test_from_usdm_takes_the_epoch_of_each_cell(self):
        usdm = {
            "studyDesigns": [
                {
                    "arms": [{"id": "a1", "name": "AB"}, {"id": "a2", "name": "BA"}],
                    "epochs": [
                        {"id": "e1", "name": "Treatment 1"},
                        {"id": "e2", "name": "Treatment 2"},
                    ],
                    "elements": [{"id": "x", "name": "Drug A"}, {"id": "y", "name": "Drug B"}],
                    "studyCells": [
                        {"armId": "a1", "epochId": "e1", "elementIds": ["x"]},
                        {"armId": "a1", "epochId": "e2", "elementIds": ["y"]},
                        {"armId": "a2", "epochId": "e1", "elementIds": ["y"]},
                        {"armId": "a2", "epochId": "e2", "elementIds": ["x"]},
                    ],
                }
            ]
        }
        design = StudyDesign.from_usdm(usdm, study_id="S")
        rows = _ta_rows(design, "ARMCD", "TAETORD", "EPOCH")
        assert rows == [
            ("AB", 1, "TREATMENT 1"),
            ("AB", 2, "TREATMENT 2"),
            ("BA", 1, "TREATMENT 1"),
            ("BA", 2, "TREATMENT 2"),
        ]


class TestStrictYaml:
    """c1-782: a key Fleet does not read, or a repeated key, stops the load."""

    BASE = """\
        study_id: S
        elements:
          - etcd: SCRN
            element: Screening
            epoch: SCREENING
        arms:
          A: [SCRN]
        """

    def _load(self, tmp_path, extra: str = "", base: str | None = None):
        path = tmp_path / "trial_design.yaml"
        path.write_text(dedent(base or self.BASE) + dedent(extra))
        return StudyDesign.from_yaml(path)

    @pytest.mark.parametrize(
        ("extra", "key"),
        [
            ("arm_name:\n  A: Arm A\n", "arm_name"),
            ("visit:\n  - visitnum: 1\n    visit: V1\n", "visit"),
        ],
    )
    def test_unknown_top_key_is_named(self, tmp_path, extra, key):
        with pytest.raises(ValidationError, match=key):
            self._load(tmp_path, extra)

    def test_upper_case_te_key_is_named(self, tmp_path):
        base = self.BASE.replace("epoch: SCREENING", "epoch: SCREENING\n            TESTRL: X")
        with pytest.raises(ValidationError, match="TESTRL"):
            self._load(tmp_path, base=base)

    def test_repeated_arm_key_raises(self, tmp_path):
        with pytest.raises(yaml.constructor.ConstructorError, match="repeated key 'A'"):
            self._load(
                tmp_path, base=self.BASE.replace("A: [SCRN]", "A: [SCRN]\n          A: [SCRN]")
            )

    def test_arm_names_key_not_in_arms_raises(self, tmp_path):
        with pytest.raises(ValidationError, match="not in arms"):
            self._load(tmp_path, "arm_names:\n  B: Arm B\n")


MERMAID_FORK = """
flowchart TD
subgraph SCR[SCREENING]
    SCRN["Screening<br/>P14D"]
end
subgraph TRT[TREATMENT]
    DRUG["Drug<br/>P84D"]
    PBO["Placebo<br/>P84D"]
end
"""


class TestMermaidStrict:
    """c1-250, c1-660: the parser reads the drawn structure or raises."""

    def test_unlabelled_fork_raises(self):
        with pytest.raises(ValueError, match="unlabelled edge"):
            parse_trial_design(MERMAID_FORK + "SCRN --> DRUG\nSCRN --> PBO\n")

    def test_labelled_fork_gives_both_arms(self):
        _, ta = parse_trial_design(MERMAID_FORK + "SCRN -->|DRUG| DRUG\nSCRN -->|PBO| PBO\n")
        assert sorted({a.armcd for a in ta.arms}) == ["DRUG", "PBO"]

    def test_sponsor_epoch_is_kept_with_a_warning(self):
        text = MERMAID_FORK.replace("TRT[TREATMENT]", "ESC[DOSE ESCALATION]")
        with pytest.warns(UserWarning, match="DOSE ESCALATION"):
            te, _ = parse_trial_design(text + "SCRN -->|DRUG| DRUG\nSCRN -->|PBO| PBO\n")
        assert {str(e.epoch) for e in te.elements} == {"SCREENING", "DOSE ESCALATION"}

    def test_follow_up_title_matches_the_ct_term(self):
        te, _ = parse_trial_design(
            'flowchart TD\nsubgraph F["Follow-up"]\n  FU["Follow-up"]\nend\n'
        )
        assert te.elements[0].epoch == "FOLLOW-UP"

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("", "no element node"),
            ("flowchart TD\n", "no element node"),
            ('flowchart TD\nsubgraph S[SCREENING]\nend\nX["Lost"]\n', "outside every subgraph"),
            (MERMAID_FORK + "SCRN -> DRUG\n", "cannot read the line"),
            (MERMAID_FORK + "SCRN -->|A| DRUG\nDRUG --> SCRN\n", "no edge|start node|cycle"),
            (MERMAID_FORK + "SCRN --> DRUG\n", "no edge"),
            (MERMAID_FORK + "SCRN -->|A| DRUG\nSCRN -->|A| PBO\n", "ARMCD 'A'"),
        ],
    )
    def test_bad_diagrams_raise(self, text, message):
        with pytest.raises(ValueError, match=message):
            parse_trial_design(text)

    def test_comment_lines_and_br_forms_are_read(self):
        te, _ = parse_trial_design(
            'flowchart TD\n%% a note\nsubgraph S[SCREENING]\n  A["Screen<br>P7D"]\n'
            '  B["Run-in<br />P14D"]\nend\nA --> B\n'
        )
        assert [e.tedur for e in te.elements] == ["P7D", "P14D"]

    def test_single_arm_keeps_its_armcd(self):
        design = StudyDesign(
            study_id="S",
            elements=EXT_ELEMENTS,
            arms={"DRUGX": ["SCRN", "CORE", "EXT"]},
            arm_names={"DRUGX": "Drugx"},
        )
        back = StudyDesign.from_mermaid(design.to_mermaid(), study_id="S")
        assert back.arms == design.arms

    def test_crossover_cannot_be_read_back(self):
        design = StudyDesign(
            study_id="S",
            elements=XO_ELEMENTS,
            arms={"AB": ["SCRN", "A", "WO", "B"], "BA": ["SCRN", "B", "WO", "A"]},
            arm_names={"AB": "A then B", "BA": "B then A"},
        )
        with pytest.warns(UserWarning, match="cannot read this design back"):
            text = design.to_mermaid()
        with pytest.raises(ValueError, match="cycle"):
            StudyDesign.from_mermaid(text, study_id="S")

    def test_quotes_in_an_element_name_survive(self):
        design = StudyDesign(
            study_id="S",
            elements=[
                {"etcd": "SCRN", "element": 'Screening "Part 1"', "epoch": "SCREENING"},
                {"etcd": "TRT", "element": "Treatment", "epoch": "TREATMENT"},
            ],
            arms={"A": ["SCRN", "TRT"]},
            arm_names={"A": "Arm A"},
        )
        back = StudyDesign.from_mermaid(design.to_mermaid(), study_id="S")
        assert back.elements[0].element == 'Screening "Part 1"'


def _usdm_v4(criteria: list[dict], items: list[dict], dictionaries: list[dict] | None = None):
    return {
        "study": {
            "versions": [
                {
                    "studyIdentifiers": [{"text": "S"}],
                    "eligibilityCriterionItems": items,
                    "dictionaries": dictionaries or [],
                    "studyDesigns": [{"eligibilityCriteria": criteria}],
                }
            ]
        }
    }


INCL = {"code": "C25532", "decode": "Inclusion Criteria"}
EXCL = {"code": "C25370", "decode": "Exclusion Criteria"}


class TestUsdmCriteria:
    """c1-783: TI from real USDM shapes."""

    def test_v4_text_comes_from_the_criterion_item(self):
        data = _usdm_v4(
            [{"identifier": "1", "name": "INC1", "criterionItemId": "ECI1", "category": INCL}],
            [{"id": "ECI1", "text": "<p>have had a diagnosis</p>"}],
        )
        ti = StudyDesign.from_usdm(data).to_ti()
        assert ti.select("IETESTCD", "IETEST", "IECAT").row(0) == (
            "IN1",
            "have had a diagnosis",
            "INCLUSION",
        )

    def test_tag_is_resolved_through_the_dictionary(self):
        data = _usdm_v4(
            [{"identifier": "2", "criterionItemId": "ECI2", "category": EXCL}],
            [
                {
                    "id": "ECI2",
                    "dictionaryId": "D1",
                    "text": '<p>Age under <usdm:tag name="min_age"/> years</p>',
                }
            ],
            [{"id": "D1", "parameterMaps": [{"tag": "min_age", "reference": "50"}]}],
        )
        assert StudyDesign.from_usdm(data).to_ti().select("IETESTCD", "IETEST").row(0) == (
            "EX2",
            "Age under 50 years",
        )

    def test_unresolved_tag_is_named(self):
        data = _usdm_v4(
            [{"identifier": "2", "criterionItemId": "ECI2", "category": EXCL}],
            [{"id": "ECI2", "text": '<usdm:tag name="nope"/>'}],
        )
        with pytest.raises(ValueError, match="'nope'"):
            StudyDesign.from_usdm(data)

    def test_missing_category_raises(self):
        data = _usdm_v4(
            [{"identifier": "1", "criterionItemId": "ECI1"}], [{"id": "ECI1", "text": "x"}]
        )
        with pytest.raises(ValueError, match="category"):
            StudyDesign.from_usdm(data)

    def test_code_collision_raises(self):
        data = _usdm_v4(
            [
                {"identifier": "IN1", "criterionItemId": "A", "category": INCL},
                {"identifier": "1", "criterionItemId": "B", "category": INCL},
            ],
            [{"id": "A", "text": "x"}, {"id": "B", "text": "y"}],
        )
        with pytest.raises(ValueError, match="'IN1' twice"):
            StudyDesign.from_usdm(data)

    def test_long_text_warns_once(self):
        data = _usdm_v4(
            [{"identifier": "1", "criterionItemId": "A", "category": INCL}],
            [{"id": "A", "text": "word " * 60}],
        )
        with pytest.warns(UserWarning, match=r"1 criterion text\(s\) are over 200"):
            StudyDesign.from_usdm(data)

    def test_v3_population_criteria_are_read(self):
        data = {
            "studyDesigns": [
                {
                    "population": {
                        "criteria": [{"identifier": "E01", "text": "Pregnant", "category": EXCL}]
                    }
                }
            ]
        }
        ti = StudyDesign.from_usdm(data, study_id="S").to_ti()
        assert ti.select("IETESTCD", "IETEST").row(0) == ("E01", "Pregnant")
