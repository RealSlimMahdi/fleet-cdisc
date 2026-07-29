"""
Cross-namespace tests for SharedADaMVerbsMixin.

Verifies that all 7 shared verbs (source, assigned, derivation, recode,
rename, condderivation, whereclauses) behave identically on every ADaM
sub-namespace that inherits from the mixin.

This is the **authoritative** regression test for the mixin architecture:
if a verb is accidentally removed or its signature changes, one of these
parametrised cases will fail.
"""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ── Shared fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def base_frame():
    """Minimal DataFrame that every namespace can work with."""
    return pl.from_repr("""\
┌─────────┬─────┬─────┬─────────┐
│ USUBJID ┆ AGE ┆ SEX ┆ ARM     │
│ ---     ┆ --- ┆ --- ┆ ---     │
│ str     ┆ i64 ┆ str ┆ str     │
╞═════════╪═════╪═════╪═════════╡
│ 01-001  ┆ 45  ┆ F   ┆ Placebo │
│ 01-002  ┆ 62  ┆ M   ┆ Active  │
│ 01-003  ┆ 38  ┆ F   ┆ Active  │
└─────────┴─────┴─────┴─────────┘
""")


# ── Namespace accessor helpers ────────────────────────────────────────────────
# Each tuple: (accessor_path, label)  — accessor_path is how to reach the
# namespace from df.adam.

_NAMESPACES = [
    ("adam", "AdamNamespace (base)"),
    ("adsl", "ADSLNamespace"),
    ("occds", "OCCDSNamespace"),
    ("onco", "OncoNamespace"),
    ("ophtha", "OphthaNamespace"),
    ("peds", "PedsNamespace"),
    ("vaccine", "VaccineNamespace"),
    ("metabolic", "MetabolicNamespace"),
    ("neuro", "NeuroNamespace"),
]


def _get_ns(df: pl.DataFrame, accessor: str):
    """Resolve a namespace from a DataFrame.  e.g. 'adsl' → df.adam.adsl."""
    ns = df.adam
    if accessor != "adam":
        ns = getattr(ns, accessor)
    return ns


# ── Parametrised tests ────────────────────────────────────────────────────────


@pytest.mark.parametrize("accessor, label", _NAMESPACES, ids=[n[1] for n in _NAMESPACES])
class TestSourceOnAllNamespaces:
    def test_source_copies_column(self, base_frame, accessor, label):
        ns = _get_ns(base_frame, accessor)
        result = ns.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns
        assert result["USUBJID"].to_list() == ["01-001", "01-002", "01-003"]

    def test_source_from_col(self, base_frame, accessor, label):
        ns = _get_ns(base_frame, accessor)
        result = ns.source("SUBJECT", from_col="USUBJID").to_frame()
        assert result["SUBJECT"].to_list() == base_frame["USUBJID"].to_list()


@pytest.mark.parametrize("accessor, label", _NAMESPACES, ids=[n[1] for n in _NAMESPACES])
class TestAssignedOnAllNamespaces:
    def test_assigned_constant(self, base_frame, accessor, label):
        ns = _get_ns(base_frame, accessor)
        result = ns.assign("STUDYID", value="STUDY01").to_frame()
        assert result["STUDYID"].to_list() == ["STUDY01"] * 3


@pytest.mark.parametrize("accessor, label", _NAMESPACES, ids=[n[1] for n in _NAMESPACES])
class TestDerivationOnAllNamespaces:
    def test_derivation_expression(self, base_frame, accessor, label):
        ns = _get_ns(base_frame, accessor)
        result = ns.derivation("AGE2", expression='pl.col("AGE") * 2').to_frame()
        assert result["AGE2"].to_list() == [90, 124, 76]


@pytest.mark.parametrize("accessor, label", _NAMESPACES, ids=[n[1] for n in _NAMESPACES])
class TestRecodeOnAllNamespaces:
    def test_recode_values(self, base_frame, accessor, label):
        ns = _get_ns(base_frame, accessor)
        result = ns.recode(
            "SEXN",
            source="SEX",
            recode_map={"F": "Female", "M": "Male"},
        ).to_frame()
        assert result["SEXN"].to_list() == ["Female", "Male", "Female"]

    def test_recode_unmapped_default(self, base_frame, accessor, label):
        ns = _get_ns(base_frame, accessor)
        result = ns.recode(
            "ARMCD",
            source="ARM",
            recode_map={"Placebo": "PBO"},
            default="ACTIVE",
        ).to_frame()
        assert result["ARMCD"].to_list() == ["PBO", "ACTIVE", "ACTIVE"]


@pytest.mark.parametrize("accessor, label", _NAMESPACES, ids=[n[1] for n in _NAMESPACES])
class TestRenameOnAllNamespaces:
    def test_rename_column(self, base_frame, accessor, label):
        ns = _get_ns(base_frame, accessor)
        result = ns.assign("SUBJECTID", source="USUBJID").to_frame()
        assert "SUBJECTID" in result.columns
        assert result["SUBJECTID"].to_list() == base_frame["USUBJID"].to_list()


@pytest.mark.parametrize("accessor, label", _NAMESPACES, ids=[n[1] for n in _NAMESPACES])
class TestCondderivationOnAllNamespaces:
    def test_multi_branch(self, base_frame, accessor, label):
        ns = _get_ns(base_frame, accessor)
        result = ns.case_when(
            "AGEGR1",
            when=[
                {"condition": "pl.col('AGE') < 40", "value": "<40"},
                {"condition": "pl.col('AGE') <= 64", "value": "40-64"},
            ],
            else_=">64",
        ).to_frame()
        assert result["AGEGR1"].to_list() == ["40-64", "40-64", "<40"]


@pytest.mark.parametrize("accessor, label", _NAMESPACES, ids=[n[1] for n in _NAMESPACES])
class TestWhereclausesOnAllNamespaces:
    def test_filter_rows(self, base_frame, accessor, label):
        ns = _get_ns(base_frame, accessor)
        result = ns.whereclauses(where='pl.col("SEX") == "F"').to_frame()
        assert result.height == 2
        assert all(s == "F" for s in result["SEX"].to_list())


# ── Chaining across shared verbs on each namespace ───────────────────────────


@pytest.mark.parametrize("accessor, label", _NAMESPACES, ids=[n[1] for n in _NAMESPACES])
class TestChainingSharedVerbs:
    def test_full_chain(self, base_frame, accessor, label):
        """Chain all shared verbs in one pipeline."""
        ns = _get_ns(base_frame, accessor)
        result = (
            ns.source("USUBJID")
            .assign("STUDYID", value="S01")
            .assign("SUBJ", source="USUBJID")
            .derivation("AGE_DBL", expression='pl.col("AGE") * 2')
            .recode("SEXN", source="SEX", recode_map={"F": "Female", "M": "Male"})
            .case_when(
                "AGEGR",
                when=[
                    {"condition": "pl.col('AGE') < 50", "value": "Young"},
                ],
                else_="Old",
            )
            .to_frame()
        )
        assert result["STUDYID"].to_list() == ["S01"] * 3
        assert result["SUBJ"].to_list() == ["01-001", "01-002", "01-003"]
        assert result["AGE_DBL"].to_list() == [90, 124, 76]
        assert result["SEXN"].to_list() == ["Female", "Male", "Female"]
        assert result["AGEGR"].to_list() == ["Young", "Old", "Young"]


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestSharedVerbEdgeCases:
    def test_whereclauses_empty_result(self, base_frame):
        result = base_frame.adam.whereclauses(where='pl.col("AGE") > 100').to_frame()
        assert result.height == 0

    def test_condderivation_empty_conditions(self, base_frame):
        result = base_frame.adam.case_when("FLAG", when=[], else_="DEFAULT").to_frame()
        assert result["FLAG"].to_list() == ["DEFAULT"] * 3

    def test_recode_empty_map_uses_default(self, base_frame):
        result = base_frame.adam.recode(
            "CODED", source="SEX", recode_map={}, default="UNK"
        ).to_frame()
        assert result["CODED"].to_list() == ["UNK"] * 3

    def test_condderivation_with_polars_expr(self, base_frame):
        result = base_frame.adam.case_when(
            "GRP",
            when=[
                {"condition": pl.col("AGE") < 40, "value": "Young"},
            ],
            else_="Old",
        ).to_frame()
        assert result["GRP"].to_list() == ["Old", "Old", "Young"]

    def test_derivation_with_polars_expr(self, base_frame):
        result = base_frame.adam.derivation("AGE10", expression=pl.col("AGE") + 10).to_frame()
        assert result["AGE10"].to_list() == [55, 72, 48]

    def test_whereclauses_with_polars_expr(self, base_frame):
        result = base_frame.adam.whereclauses(where=pl.col("ARM") == "Active").to_frame()
        assert result.height == 2
