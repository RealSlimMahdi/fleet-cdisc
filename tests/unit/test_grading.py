"""Unit tests for Fleet's CTCAE / DAIDS toxicity-grading system.

Covers: Pydantic models, criteria registry, expression compiler,
combine-grades logic, and the ``atoxgr`` / ``combine_grades`` namespace verbs.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.adam.grading import (
    ComparisonRule,
    CriteriaFile,
    GradeRule,
    GradingSystem,
    TermCriteria,
    list_systems,
    load_criteria,
)
from fleet.adam.grading._compiler import (
    combine_grades_expr,
    compile_filter_expr,
    compile_term_expr,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def anemia_criteria() -> TermCriteria:
    """Anemia (CTCAE v5 SI): low direction, grades 1-3."""
    return TermCriteria(
        term="Anemia",
        direction="L",
        unit="g/L",
        required_vars=["AVAL", "ANRLO"],
        na_check=["AVAL"],
        grades=[
            GradeRule(
                grade=3,
                rules=[ComparisonRule(left="AVAL", op="lt", right=80)],
            ),
            GradeRule(
                grade=2,
                rules=[ComparisonRule(left="AVAL", op="lt", right=100)],
            ),
            GradeRule(
                grade=1,
                na_guard=["ANRLO"],
                rules=[ComparisonRule(left="AVAL", op="lt", right_var="ANRLO")],
            ),
        ],
    )


@pytest.fixture()
def anemia_df() -> pl.DataFrame:
    """Lab rows exercising every Anemia grade boundary."""
    return pl.from_repr("""\
┌─────────┬─────────┬───────┬───────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  ┆ ANRLO ┆ AVALU │
│ ---     ┆ ---     ┆ ---   ┆ ---   ┆ ---   │
│ str     ┆ str     ┆ f64   ┆ f64   ┆ str   │
╞═════════╪═════════╪═══════╪═══════╪═══════╡
│ S1      ┆ Anemia  ┆ 75.0  ┆ 140.0 ┆ g/L   │
│ S2      ┆ Anemia  ┆ 90.0  ┆ 140.0 ┆ g/L   │
│ S3      ┆ Anemia  ┆ 130.0 ┆ 140.0 ┆ g/L   │
│ S4      ┆ Anemia  ┆ 150.0 ┆ 140.0 ┆ g/L   │
│ S5      ┆ Anemia  ┆ null  ┆ 140.0 ┆ g/L   │
└─────────┴─────────┴───────┴───────┴───────┘
""")


@pytest.fixture()
def alt_criteria() -> TermCriteria:
    """ALT increased (CTCAE v5 SI): high direction with branch rules."""
    from fleet.adam.grading._models import BranchCondition, BranchRule

    def _branch(
        indicator_dir: str, col: str, op: str, mult: float | None = None, var: str | None = None
    ) -> BranchRule:
        if indicator_dir == "not_in":
            cond = BranchCondition(var="BNRIND", not_in_values="high_indicator")
        else:
            cond = BranchCondition(var="BNRIND", in_values="high_indicator")
        if mult is not None:
            comp = ComparisonRule(left="AVAL", op=op, right_expr={"multiply": [col, mult]})
        elif var is not None:
            comp = ComparisonRule(left="AVAL", op=op, right_var=var)
        else:
            raise AssertionError  # pragma: no cover
        return BranchRule(when=cond, then=comp)

    return TermCriteria(
        term="Alanine aminotransferase increased",
        direction="H",
        required_vars=["AVAL", "ANRHI", "BASE", "BNRIND"],
        na_check=["AVAL", "ANRHI"],
        grades=[
            GradeRule(
                grade=4,
                branches=[
                    _branch("not_in", "ANRHI", "gt", mult=20),
                    _branch("in", "BASE", "gt", mult=20),
                ],
            ),
            GradeRule(
                grade=3,
                branches=[
                    _branch("not_in", "ANRHI", "gt", mult=5),
                    _branch("in", "BASE", "gt", mult=5),
                ],
            ),
            GradeRule(
                grade=2,
                branches=[
                    _branch("not_in", "ANRHI", "gt", mult=3),
                    _branch("in", "BASE", "gt", mult=3),
                ],
            ),
            GradeRule(
                grade=1,
                branches=[
                    _branch("not_in", "ANRHI", "gt", var="ANRHI"),
                    _branch("in", "BASE", "ge", mult=1.5),
                ],
            ),
        ],
    )


@pytest.fixture()
def indicators() -> dict[str, list[str]]:
    """Default indicator parameter map."""
    return {"high_indicator": ["HIGH", "H"], "low_indicator": ["LOW", "L"]}


# ---------------------------------------------------------------------------
# TestModels — Pydantic validation
# ---------------------------------------------------------------------------


class TestModels:
    """Pydantic model validation rules."""

    def test_comparison_rule_requires_exactly_one_rhs(self):
        """ComparisonRule rejects zero or multiple RHS specifications."""
        with pytest.raises(ValueError, match="Exactly one"):
            ComparisonRule(left="AVAL", op="lt")

        with pytest.raises(ValueError, match="Exactly one"):
            ComparisonRule(left="AVAL", op="lt", right=5.0, right_var="ANRHI")

    def test_grade_rule_requires_at_least_one_rule_source(self):
        """GradeRule rejects grades with no rules and no branches."""
        with pytest.raises(ValueError, match="At least one"):
            GradeRule(grade=1)


# ---------------------------------------------------------------------------
# TestRegistry — criteria file discovery and loading
# ---------------------------------------------------------------------------


class TestRegistry:
    """Grading-criteria registry and loader."""

    def test_list_systems(self):
        systems = list_systems()
        assert len(systems) == 8
        assert "ctcae_v5" in systems
        assert "daids" in systems

    def test_load_builtin_by_enum(self):
        cf = load_criteria(GradingSystem.CTCAE_V5)
        assert isinstance(cf, CriteriaFile)
        assert cf.version == "ctcae_v5"

    def test_load_builtin_by_string(self):
        cf = load_criteria("ctcae_v5")
        assert cf.version == "ctcae_v5"
        assert cf.unit_system == "SI"

    def test_load_custom_path(self, tmp_path: Path):
        custom = {
            "version": "custom_v1",
            "unit_system": "SI",
            "criteria": [
                {
                    "term": "TestParam",
                    "direction": "H",
                    "required_vars": ["AVAL"],
                    "na_check": ["AVAL"],
                    "grades": [
                        {"grade": 1, "rules": [{"left": "AVAL", "op": "gt", "right": 10}]},
                    ],
                }
            ],
        }
        p = tmp_path / "custom.json"
        p.write_text(json.dumps(custom))
        cf = load_criteria(p)
        assert cf.version == "custom_v1"
        assert len(cf.criteria) == 1

    def test_load_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown grading system"):
            load_criteria("nonexistent_v99")

    def test_all_builtin_criteria_valid(self):
        """Every bundled JSON file parses and validates without error."""
        for gs in GradingSystem:
            cf = load_criteria(gs)
            assert isinstance(cf, CriteriaFile)
            assert len(cf.criteria) > 0


# ---------------------------------------------------------------------------
# TestCompiler — expression compilation
# ---------------------------------------------------------------------------


class TestCompiler:
    """Low-level compiler functions: comparisons, branches, filters, combine."""

    def test_simple_literal_comparison(self, anemia_criteria):
        """AVAL < 80 → grade 3."""
        expr = compile_term_expr(anemia_criteria)
        df = pl.from_repr("""\
┌──────┬───────┐
│ AVAL ┆ ANRLO │
│ ---  ┆ ---   │
│ f64  ┆ f64   │
╞══════╪═══════╡
│ 75.0 ┆ 140.0 │
└──────┴───────┘
""")
        result = df.with_columns(expr.alias("GR"))
        assert result["GR"][0] == "3"

    def test_variable_comparison(self, anemia_criteria):
        """AVAL < ANRLO → grade 1 (when above literal thresholds)."""
        expr = compile_term_expr(anemia_criteria)
        df = pl.from_repr("""\
┌───────┬───────┐
│ AVAL  ┆ ANRLO │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 130.0 ┆ 140.0 │
└───────┴───────┘
""")
        result = df.with_columns(expr.alias("GR"))
        assert result["GR"][0] == "1"

    def test_multiplier_comparison(self, alt_criteria, indicators):
        """AVAL > 5*ANRHI → grade 3 (baseline normal)."""
        expr = compile_term_expr(alt_criteria, indicators=indicators)
        df = pl.from_repr("""\
┌───────┬───────┬──────┬────────┐
│ AVAL  ┆ ANRHI ┆ BASE ┆ BNRIND │
│ ---   ┆ ---   ┆ ---  ┆ ---    │
│ f64   ┆ f64   ┆ f64  ┆ str    │
╞═══════╪═══════╪══════╪════════╡
│ 300.0 ┆ 40.0  ┆ 35.0 ┆ NORMAL │
└───────┴───────┴──────┴────────┘
""")
        result = df.with_columns(expr.alias("GR"))
        assert result["GR"][0] == "3"

    def test_na_check_produces_null(self, anemia_criteria):
        """Null AVAL triggers global na_check → null grade."""
        expr = compile_term_expr(anemia_criteria)
        df = pl.from_repr("""\
┌──────┬───────┐
│ AVAL ┆ ANRLO │
│ ---  ┆ ---   │
│ f64  ┆ f64   │
╞══════╪═══════╡
│ null ┆ 140.0 │
└──────┴───────┘
""")
        result = df.with_columns(expr.alias("GR"))
        assert result["GR"][0] is None

    def test_na_guard_per_grade(self, anemia_criteria):
        """Null ANRLO → null (via na_guard on grade 1) instead of grade 0."""
        expr = compile_term_expr(anemia_criteria)
        df = pl.from_repr("""\
┌───────┬───────┐
│ AVAL  ┆ ANRLO │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 130.0 ┆ null  │
└───────┴───────┘
""")
        result = df.with_columns(expr.alias("GR"))
        assert result["GR"][0] is None

    def test_branch_with_indicator(self, alt_criteria, indicators):
        """Baseline HIGH → branch to BASE multiples; NORMAL → ANRHI multiples."""
        expr = compile_term_expr(alt_criteria, indicators=indicators)

        # NORMAL baseline: 300 > 5*40 → grade 3
        normal = pl.from_repr("""\
┌───────┬───────┬──────┬────────┐
│ AVAL  ┆ ANRHI ┆ BASE ┆ BNRIND │
│ ---   ┆ ---   ┆ ---  ┆ ---    │
│ f64   ┆ f64   ┆ f64  ┆ str    │
╞═══════╪═══════╪══════╪════════╡
│ 300.0 ┆ 40.0  ┆ 35.0 ┆ NORMAL │
└───────┴───────┴──────┴────────┘
""").with_columns(expr.alias("GR"))
        assert normal["GR"][0] == "3"

        # HIGH baseline: 300 > 5*35=175 → grade 3 (via BASE branch)
        high = pl.from_repr("""\
┌───────┬───────┬──────┬────────┐
│ AVAL  ┆ ANRHI ┆ BASE ┆ BNRIND │
│ ---   ┆ ---   ┆ ---  ┆ ---    │
│ f64   ┆ f64   ┆ f64  ┆ str    │
╞═══════╪═══════╪══════╪════════╡
│ 300.0 ┆ 40.0  ┆ 35.0 ┆ HIGH   │
└───────┴───────┴──────┴────────┘
""").with_columns(expr.alias("GR"))
        assert high["GR"][0] == "3"

        # HIGH baseline, low AVAL: 10 vs 1.5*35=52.5 → grade 0
        high_low = pl.from_repr("""\
┌──────┬───────┬──────┬────────┐
│ AVAL ┆ ANRHI ┆ BASE ┆ BNRIND │
│ ---  ┆ ---   ┆ ---  ┆ ---    │
│ f64  ┆ f64   ┆ f64  ┆ str    │
╞══════╪═══════╪══════╪════════╡
│ 10.0 ┆ 40.0  ┆ 35.0 ┆ HIGH   │
└──────┴───────┴──────┴────────┘
""").with_columns(expr.alias("GR"))
        assert high_low["GR"][0] == "0"

    def test_compile_filter_age_days(self):
        """Parse age_days(BRTHDT, ADT) > 28 and evaluate."""
        expr = compile_filter_expr("age_days(BRTHDT, ADT) > 28")
        df = pl.from_repr("""\
┌────────────┬────────────┐
│ BRTHDT     ┆ ADT        │
│ ---        ┆ ---        │
│ date       ┆ date       │
╞════════════╪════════════╡
│ 2024-01-01 ┆ 2024-03-01 │
│ 2024-01-01 ┆ 2024-01-20 │
└────────────┴────────────┘
""")
        result = df.with_columns(expr.alias("PASS"))
        assert result["PASS"].to_list() == [True, False]

    def test_compile_filter_age_years(self):
        """Parse age_years(BRTHDT, ADT) >= 18."""
        expr = compile_filter_expr("age_years(BRTHDT, ADT) >= 18")
        df = pl.from_repr("""\
┌────────────┬────────────┐
│ BRTHDT     ┆ ADT        │
│ ---        ┆ ---        │
│ date       ┆ date       │
╞════════════╪════════════╡
│ 2000-06-15 ┆ 2024-06-15 │
│ 2015-06-15 ┆ 2024-06-15 │
└────────────┴────────────┘
""")
        result = df.with_columns(expr.alias("PASS"))
        assert result["PASS"].to_list() == [True, False]

    def test_combine_grades_low_positive(self):
        """Low grade present → negative string (e.g. "-3")."""
        expr = combine_grades_expr("ATOXGRL", "ATOXGRH")
        df = pl.from_repr("""\
┌─────────┬─────────┐
│ ATOXGRL ┆ ATOXGRH │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ 3       ┆ null    │
└─────────┴─────────┘
""")
        result = df.with_columns(expr.alias("ATOXGR"))
        assert result["ATOXGR"][0] == "-3"

    def test_combine_grades_high_positive(self):
        """High grade present → positive string (e.g. "3")."""
        expr = combine_grades_expr("ATOXGRL", "ATOXGRH")
        df = pl.from_repr("""\
┌─────────┬─────────┐
│ ATOXGRL ┆ ATOXGRH │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ null    ┆ 3       │
└─────────┴─────────┘
""")
        result = df.with_columns(expr.alias("ATOXGR"))
        assert result["ATOXGR"][0] == "3"

    def test_combine_grades_both_zero(self):
        """Both sides zero → "0"."""
        expr = combine_grades_expr("ATOXGRL", "ATOXGRH")
        df = pl.from_repr("""\
┌─────────┬─────────┐
│ ATOXGRL ┆ ATOXGRH │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ 0       ┆ 0       │
└─────────┴─────────┘
""")
        result = df.with_columns(expr.alias("ATOXGR"))
        assert result["ATOXGR"][0] == "0"

    def test_combine_grades_both_null(self):
        """Both sides null → null."""
        expr = combine_grades_expr("ATOXGRL", "ATOXGRH")
        df = pl.from_repr("""\
┌─────────┬─────────┐
│ ATOXGRL ┆ ATOXGRH │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ null    ┆ null    │
└─────────┴─────────┘
""")
        result = df.with_columns(expr.alias("ATOXGR"))
        assert result["ATOXGR"][0] is None


# ---------------------------------------------------------------------------
# TestAtoxgrVerb — namespace integration
# ---------------------------------------------------------------------------


class TestAtoxgrVerb:
    """End-to-end tests for the ``atoxgr`` and ``combine_grades`` verbs."""

    def test_ctcae_v5_anemia_all_grades(self, anemia_df):
        """Anemia grading: 75→3, 90→2, 130→1, 150→0, null→null."""
        result = (
            anemia_df.adam.atoxgr(
                "ATOXGRL",
                system="ctcae_v5",
                direction="L",
                term_var="PARAMCD",
                unit_var="AVALU",
            )
            .to_frame()
            .sort("USUBJID")
        )
        grades = result["ATOXGRL"].to_list()
        assert grades == ["3", "2", "1", "0", None]

    def test_ctcae_v5_alt_increased(self):
        """ALT with BNRIND branching: 300/40/NORMAL → grade 3."""
        df = pl.from_repr("""\
┌─────────┬────────────────────────────────────┬───────┬───────┬──────┬────────┐
│ USUBJID ┆ PARAMCD                            ┆ AVAL  ┆ ANRHI ┆ BASE ┆ BNRIND │
│ ---     ┆ ---                                ┆ ---   ┆ ---   ┆ ---  ┆ ---    │
│ str     ┆ str                                ┆ f64   ┆ f64   ┆ f64  ┆ str    │
╞═════════╪════════════════════════════════════╪═══════╪═══════╪══════╪════════╡
│ A1      ┆ Alanine aminotransferase increased ┆ 300.0 ┆ 40.0  ┆ 35.0 ┆ NORMAL │
│ A2      ┆ Alanine aminotransferase increased ┆ 10.0  ┆ 40.0  ┆ 35.0 ┆ NORMAL │
└─────────┴────────────────────────────────────┴───────┴───────┴──────┴────────┘
""")
        result = (
            df.adam.atoxgr(
                "ATOXGRH",
                system="ctcae_v5",
                direction="H",
                term_var="PARAMCD",
            )
            .to_frame()
            .sort("USUBJID")
        )
        assert result["ATOXGRH"].to_list() == ["3", "0"]

    def test_ctcae_v5_unit_matching(self, anemia_df):
        """Rows with wrong unit get null; matching unit gets graded."""
        df = anemia_df.with_columns(
            pl.when(pl.col("USUBJID") == "S1")
            .then(pl.lit("mmol/L"))
            .otherwise(pl.col("AVALU"))
            .alias("AVALU")
        )
        result = (
            df.adam.atoxgr(
                "ATOXGRL",
                system="ctcae_v5",
                direction="L",
                term_var="PARAMCD",
                unit_var="AVALU",
            )
            .to_frame()
            .sort("USUBJID")
        )
        # S1 has wrong unit → null
        assert result["ATOXGRL"][0] is None
        # S2 (AVAL=90) → grade 2
        assert result["ATOXGRL"][1] == "2"

    def test_multiple_terms_in_one_dataset(self):
        """Dataset with Anemia + Platelet count decreased graded together."""
        df = pl.from_repr("""\
┌─────────┬──────────────────────────┬──────┬───────┬────────┐
│ USUBJID ┆ PARAMCD                  ┆ AVAL ┆ ANRLO ┆ AVALU  │
│ ---     ┆ ---                      ┆ ---  ┆ ---   ┆ ---    │
│ str     ┆ str                      ┆ f64  ┆ f64   ┆ str    │
╞═════════╪══════════════════════════╪══════╪═══════╪════════╡
│ S1      ┆ Anemia                   ┆ 75.0 ┆ 140.0 ┆ g/L    │
│ S2      ┆ Platelet count decreased ┆ 40.0 ┆ 150.0 ┆ 10^9/L │
└─────────┴──────────────────────────┴──────┴───────┴────────┘
""")
        result = (
            df.adam.atoxgr(
                "ATOXGRL",
                system="ctcae_v5",
                direction="L",
                term_var="PARAMCD",
                unit_var="AVALU",
            )
            .to_frame()
            .sort("USUBJID")
        )
        # S1: Anemia AVAL=75 < 80 → grade 3
        assert result["ATOXGRL"][0] == "3"
        # S2: Platelet AVAL=40 < 50 → grade 3 (platelet criteria: <50 = grade 3)
        assert result["ATOXGRL"][1] == "3"

    def test_null_term_rows_preserved(self, anemia_df):
        """Rows with null term_var get null grade, not dropped."""
        df = anemia_df.with_columns(
            pl.when(pl.col("USUBJID") == "S1")
            .then(pl.lit(None, dtype=pl.Utf8))
            .otherwise(pl.col("PARAMCD"))
            .alias("PARAMCD")
        )
        result = (
            df.adam.atoxgr(
                "ATOXGRL",
                system="ctcae_v5",
                direction="L",
                term_var="PARAMCD",
                unit_var="AVALU",
            )
            .to_frame()
            .sort("USUBJID")
        )
        assert result.height == 5
        # S1 has null PARAMCD → null grade
        assert result["ATOXGRL"][0] is None

    def test_unmatched_term_gets_null(self):
        """A term not in the criteria file receives null grade."""
        df = pl.from_repr("""\
┌─────────┬─────────────────────────┬───────┬───────┐
│ USUBJID ┆ PARAMCD                 ┆ AVAL  ┆ ANRLO │
│ ---     ┆ ---                     ┆ ---   ┆ ---   │
│ str     ┆ str                     ┆ f64   ┆ f64   │
╞═════════╪═════════════════════════╪═══════╪═══════╡
│ U1      ┆ Completely Made Up Term ┆ 999.0 ┆ 10.0  │
└─────────┴─────────────────────────┴───────┴───────┘
""")
        result = df.adam.atoxgr(
            "ATOXGRL",
            system="ctcae_v5",
            direction="L",
            term_var="PARAMCD",
        ).to_frame()
        assert result["ATOXGRL"][0] is None

    def test_daids_system(self):
        """Basic DAIDS grading works (Acidosis, low direction)."""
        cf = load_criteria("daids")
        assert cf.version == "daids"

        df = pl.from_repr("""\
┌─────────┬──────────┬──────┬───────┐
│ USUBJID ┆ PARAMCD  ┆ AVAL ┆ ANRLO │
│ ---     ┆ ---      ┆ ---  ┆ ---   │
│ str     ┆ str      ┆ f64  ┆ f64   │
╞═════════╪══════════╪══════╪═══════╡
│ D1      ┆ Acidosis ┆ 7.2  ┆ 7.35  │
│ D2      ┆ Acidosis ┆ 7.4  ┆ 7.35  │
└─────────┴──────────┴──────┴───────┘
""")
        result = (
            df.adam.atoxgr(
                "ATOXGRL",
                system="daids",
                direction="L",
                term_var="PARAMCD",
            )
            .to_frame()
            .sort("USUBJID")
        )
        # D1: 7.2 < 7.3 → grade 4
        assert result["ATOXGRL"][0] == "4"
        # D2: 7.4 not < 7.35 → grade 0
        assert result["ATOXGRL"][1] == "0"

    def test_combine_grades_full_pipeline(self):
        """Both directions graded, then combined into signed ATOXGR."""
        df = pl.from_repr("""\
┌─────────┬─────────┬───────┬───────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  ┆ ANRLO ┆ AVALU │
│ ---     ┆ ---     ┆ ---   ┆ ---   ┆ ---   │
│ str     ┆ str     ┆ f64   ┆ f64   ┆ str   │
╞═════════╪═════════╪═══════╪═══════╪═══════╡
│ S1      ┆ Anemia  ┆ 75.0  ┆ 140.0 ┆ g/L   │
│ S2      ┆ Anemia  ┆ 150.0 ┆ 140.0 ┆ g/L   │
│ S3      ┆ Anemia  ┆ 150.0 ┆ 140.0 ┆ g/L   │
│ S4      ┆ Anemia  ┆ 130.0 ┆ 140.0 ┆ g/L   │
└─────────┴─────────┴───────┴───────┴───────┘
""")
        graded = df.adam.atoxgr(
            "ATOXGRL",
            system="ctcae_v5",
            direction="L",
            term_var="PARAMCD",
            unit_var="AVALU",
        ).to_frame()
        # No high-direction criteria for Anemia, so ATOXGRH = null
        graded = graded.with_columns(pl.lit(None, dtype=pl.Utf8).alias("ATOXGRH"))

        result = (
            graded.adam.combine_grades(
                "ATOXGR",
                low_var="ATOXGRL",
                high_var="ATOXGRH",
                low_desc_var=None,
                high_desc_var=None,
            )
            .to_frame()
            .sort("USUBJID")
        )
        # S1: low=3, high=null → "-3"
        assert result["ATOXGR"][0] == "-3"
        # S2: low=0, high=null → "0"
        assert result["ATOXGR"][1] == "0"
        # S3: low=0, high=null → "0"
        assert result["ATOXGR"][2] == "0"
        # S4: low=1, high=null → "-1"
        assert result["ATOXGR"][3] == "-1"

    def test_custom_criteria_file(self, tmp_path: Path):
        """Load a custom single-term JSON and grade through the verb."""
        custom = {
            "version": "custom_test",
            "unit_system": "SI",
            "criteria": [
                {
                    "term": "MyParam",
                    "direction": "H",
                    "required_vars": ["AVAL"],
                    "na_check": ["AVAL"],
                    "grades": [
                        {"grade": 2, "rules": [{"left": "AVAL", "op": "gt", "right": 100}]},
                        {"grade": 1, "rules": [{"left": "AVAL", "op": "gt", "right": 50}]},
                    ],
                }
            ],
        }
        p = tmp_path / "custom_grading.json"
        p.write_text(json.dumps(custom))

        df = pl.from_repr("""\
┌─────────┬─────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ f64   │
╞═════════╪═════════╪═══════╡
│ C1      ┆ MyParam ┆ 150.0 │
│ C2      ┆ MyParam ┆ 75.0  │
│ C3      ┆ MyParam ┆ 30.0  │
└─────────┴─────────┴───────┘
""")
        result = (
            df.adam.atoxgr(
                "ATOXGRH",
                system=str(p),
                direction="H",
                term_var="PARAMCD",
            )
            .to_frame()
            .sort("USUBJID")
        )
        assert result["ATOXGRH"].to_list() == ["2", "1", "0"]
