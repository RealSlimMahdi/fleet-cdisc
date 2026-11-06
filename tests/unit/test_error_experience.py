"""Tests for the §2.2 error-experience overhaul.

Covers verb-attributed column errors, the ``to_frame()`` translation
fallback, the dual-inheritance exception hierarchy, keyword
did-you-mean in ``flag()``, bare-name resolution in
``parse_expression``, logging defaults, ``nodup`` report access, and
``validate()`` result access.
"""

import logging

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.exceptions import (
    DerivationError,
    FleetError,
    PinError,
    VerbUsageError,
)

# ------------------------------------------------------------------ #
# Verb-attributed column errors in _chain()                            #
# ------------------------------------------------------------------ #


class TestChainColumnValidation:
    @pytest.fixture
    def raw(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌────────────────┬─────┐
│ patient_number ┆ sex │
│ ---            ┆ --- │
│ str            ┆ str │
╞════════════════╪═════╡
│ S001           ┆ M   │
└────────────────┴─────┘
""")

    def test_typo_raises_at_verb_with_suggestion(self, raw):
        with pytest.raises(DerivationError) as excinfo:
            raw.sdtm.assign("USUBJID", source="patient_numbr")
        msg = str(excinfo.value)
        assert "assign" in msg
        assert "USUBJID" in msg
        assert "patient_numbr" in msg
        assert "Did you mean 'patient_number'?" in msg

    def test_error_surfaces_at_call_not_at_to_frame(self, raw):
        """The error must be raised by the verb call itself (eager schema check)."""
        with pytest.raises(DerivationError):
            raw.sdtm.assign("USUBJID", source="nope")  # no .to_frame()

    def test_previously_chained_columns_are_visible(self, raw):
        result = (
            raw.sdtm.assign("USUBJID", source="patient_number")
            .assign("SUBJID", source="USUBJID")  # created one verb earlier
            .to_frame()
        )
        assert result["SUBJID"].to_list() == ["S001"]

    def test_adam_verbs_are_attributed(self, raw):
        with pytest.raises(DerivationError, match=r"source\('USUBJID'\)"):
            raw.adam.source("USUBJID", from_col="patient_numbr")

    def test_legacy_catch_style_works(self, raw):
        with pytest.raises(ValueError):
            raw.sdtm.assign("USUBJID", source="patient_numbr")


# ------------------------------------------------------------------ #
# to_frame() translation fallback                                      #
# ------------------------------------------------------------------ #


class TestToFrameTranslation:
    def test_lazy_column_error_translated_with_lineage(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        ns = df.sdtm.assign("DOMAIN", value="DM")
        # Bypass _chain validation to simulate a lazily-surfacing error.
        ns._lazy = ns._lazy.with_columns(pl.col("DOMAIN").alias("COPY")).drop("DOMAIN")
        ns._lazy = ns._lazy.with_columns(pl.col("DOMAIN").alias("AGAIN"))
        with pytest.raises(DerivationError) as excinfo:
            ns.to_frame()
        msg = str(excinfo.value)
        assert "DOMAIN" in msg
        # Lineage names the verb that produced the missing column.
        assert "assign" in msg


# ------------------------------------------------------------------ #
# Exception hierarchy — dual inheritance                               #
# ------------------------------------------------------------------ #


class TestExceptionHierarchy:
    def test_derivation_error_is_both(self):
        assert issubclass(DerivationError, FleetError)
        assert issubclass(DerivationError, ValueError)

    def test_verb_usage_error_is_both(self):
        assert issubclass(VerbUsageError, FleetError)
        assert issubclass(VerbUsageError, TypeError)

    def test_pin_error_is_both(self):
        assert issubclass(PinError, FleetError)
        assert issubclass(PinError, LookupError)

    def test_missing_pin_raises_pin_error(self):
        df = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ ASTDT      │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2014-01-05 │
└─────────┴────────────┘
""")
        with pytest.raises(PinError, match="pinned 'ADSL'"):
            df.adam.study_day("ASTDY", date_col="ASTDT")
        with pytest.raises(LookupError):
            df.adam.study_day("ASTDY", date_col="ASTDT")

    def test_verb_type_error_catchable_both_ways(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        with pytest.raises(VerbUsageError):
            df.sdtm.duration("ADUR", start=123, end="a")
        with pytest.raises(TypeError):
            df.sdtm.duration("ADUR", start=123, end="a")

    def test_fleet_error_catches_verb_value_errors(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        with pytest.raises(FleetError):
            df.sdtm.duration("ADUR", start="a", end="a", unit="fortnights")


# ------------------------------------------------------------------ #
# flag() keyword did-you-mean                                          #
# ------------------------------------------------------------------ #


class TestFlagKeywordDidYouMean:
    @pytest.fixture
    def advs(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬─────────┬─────────┐
│ USUBJID ┆ AVISITN ┆ FIRSTFL │
│ ---     ┆ ---     ┆ ---     │
│ str     ┆ i64     ┆ str     │
╞═════════╪═════════╪═════════╡
│ S001    ┆ 1       ┆ Y       │
│ S001    ┆ 2       ┆ null    │
└─────────┴─────────┴─────────┘
""")

    def test_keyword_typo_reports_both_interpretations(self, advs):
        with pytest.raises(DerivationError) as excinfo:
            advs.adam.flag("ABLFL", criteria="frist", order_by="AVISITN")
        msg = str(excinfo.value)
        assert "criteria='first'" in msg  # keyword interpretation
        assert "neither a criteria keyword nor a column" in msg

    def test_column_typo_suggests_column(self, advs):
        with pytest.raises(DerivationError, match="FIRSTFL"):
            advs.adam.flag("ANLFL", criteria="FIRSTLF")

    def test_bare_boolean_column_still_accepted(self):
        df = pl.from_repr("""\
┌─────────┬──────────┐
│ USUBJID ┆ ELIGIBLE │
│ ---     ┆ ---      │
│ str     ┆ bool     │
╞═════════╪══════════╡
│ S1      ┆ true     │
│ S2      ┆ false    │
└─────────┴──────────┘
""")
        result = df.adam.flag("ELIGFL", criteria="ELIGIBLE").to_frame()
        assert result["ELIGFL"].to_list() == ["Y", None]

    def test_real_keywords_still_dispatch(self, advs):
        result = advs.adam.flag(
            "ABLFL", criteria="first", order_by="AVISITN", by=["USUBJID"]
        ).to_frame()
        assert result["ABLFL"].to_list() == ["Y", None]


# ------------------------------------------------------------------ #
# parse_expression bare-name resolution                                #
# ------------------------------------------------------------------ #


class TestParseExpressionBareNames:
    def test_bare_name_arithmetic_works(self):
        from fleet.sdtm.utils import parse_expression

        df = pl.from_repr("""\
┌──────┐
│ AVAL │
│ ---  │
│ f64  │
╞══════╡
│ 1.0  │
│ 2.0  │
└──────┘
""")
        result = df.select(parse_expression("AVAL * 2").alias("OUT"))
        assert result["OUT"].to_list() == [2.0, 4.0]

    def test_mixed_bare_and_pl_syntax(self):
        from fleet.sdtm.utils import parse_expression

        df = pl.from_repr("""\
┌──────┬─────┐
│ AVAL ┆ HI  │
│ ---  ┆ --- │
│ f64  ┆ f64 │
╞══════╪═════╡
│ 5    ┆ 4   │
└──────┴─────┘
""")
        result = df.select(parse_expression("pl.col('AVAL') > HI").alias("OUT"))
        assert result["OUT"].to_list() == [True]

    def test_verb_level_bare_name_expression(self):
        df = pl.from_repr("""\
┌──────────┐
│ VSSTRESN │
│ ---      │
│ f64      │
╞══════════╡
│ 10.0     │
└──────────┘
""")
        result = df.adam.derivation("AVAL", expression="VSSTRESN * 2").to_frame()
        assert result["AVAL"].to_list() == [20.0]

    def test_unparseable_input_suggests_pl_col(self):
        from fleet.sdtm.utils import parse_expression

        with pytest.raises(DerivationError, match=r"pl\.col"):
            parse_expression("AVAL +* 2")

    def test_security_posture_kept(self):
        from fleet.sdtm.utils import parse_expression

        with pytest.raises(DerivationError, match="Disallowed construct"):
            parse_expression("(lambda: 1)()")
        with pytest.raises(DerivationError, match="Dunder"):
            parse_expression("__import__('os').system('true')")
        with pytest.raises(DerivationError, match="Dunder"):
            parse_expression("pl.col('A').__class__")


# ------------------------------------------------------------------ #
# Logging replaces print                                                #
# ------------------------------------------------------------------ #


class TestFleetLogging:
    def test_default_console_output_visible(self, capsys):
        """Interactive UX preserved: diagnostics reach stdout by default."""
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        df.sdtm.nodup(subset=["a"])
        assert "NODUP" in capsys.readouterr().out

    def test_diagnostics_route_through_fleet_logger(self, caplog):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
│ 1   │
└─────┘
""")
        with caplog.at_level(logging.INFO, logger="fleet"):
            df.sdtm.nodup(subset=["a"])
        assert any("NODUP" in message for message in caplog.messages)
        assert all(rec.name.startswith("fleet") for rec in caplog.records)

    def test_enable_disable_console(self):
        from fleet.core import log as fleet_log

        handler = fleet_log.enable_console(logging.INFO)
        assert handler in logging.getLogger("fleet").handlers
        fleet_log.disable_console()
        assert handler not in logging.getLogger("fleet").handlers
        # Restore the default for subsequent tests.
        fleet_log.enable_console(logging.INFO)


# ------------------------------------------------------------------ #
# nodup programmatic report                                             #
# ------------------------------------------------------------------ #


class TestNodupReport:
    def test_report_only_attaches_duplicates_frame(self):
        df = pl.from_repr("""\
┌─────────┬───────┐
│ USUBJID ┆ AESEQ │
│ ---     ┆ ---   │
│ str     ┆ i64   │
╞═════════╪═══════╡
│ S1      ┆ 1     │
│ S1      ┆ 1     │
│ S2      ┆ 2     │
└─────────┴───────┘
""")
        ns = df.sdtm.nodup(subset=["USUBJID", "AESEQ"])
        report = ns.last_nodup_report
        assert report is not None
        assert report.height == 2  # both S1 rows participate in the dup group
        assert set(report["USUBJID"].to_list()) == {"S1"}
        # Frame itself is unchanged in report-only mode.
        assert ns.to_frame().height == 3

    def test_no_duplicates_gives_empty_report(self):
        df = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
│ S2      │
└─────────┘
""")
        ns = df.sdtm.nodup(subset=["USUBJID"])
        assert ns.last_nodup_report is not None
        assert ns.last_nodup_report.height == 0

    def test_before_nodup_report_is_none(self):
        df = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
└─────────┘
""")
        assert df.sdtm.last_nodup_report is None


# ------------------------------------------------------------------ #
# validate() result access                                              #
# ------------------------------------------------------------------ #


class TestValidateResultAccess:
    @pytest.fixture
    def failing_ns(self, monkeypatch):
        """An SDTM chain whose validation run reports one error."""
        from fleet.validation.models import Severity, ValidationIssue, ValidationResult
        from fleet.validation.service import ValidationService

        result = ValidationResult(
            dataset_name="DM",
            dataset_type="SDTM",
            model_version="3.4",
            total_issues=1,
            errors=[ValidationIssue(severity=Severity.ERROR, rule_id="X1", message="boom")],
        )
        # Bypass provider construction too — it discovers the rules-engine
        # binary, which is absent in CI (these tests exercise on_fail
        # plumbing, not the engine).
        monkeypatch.setattr(ValidationService, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(ValidationService, "validate_sdtm", lambda self, df, **kw: result)
        df = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
└─────────┘
""")
        return df.sdtm.assign("DOMAIN", value="DM")

    def test_on_fail_warn_default_keeps_chain_and_stashes_result(self, failing_ns):
        with pytest.warns(UserWarning, match="validation failed"):
            ns = failing_ns.validate("DM")
        assert ns.last_validation is not None
        assert not ns.last_validation.is_valid
        assert ns.to_frame().height == 1  # chain still fluent

    def test_on_fail_raise(self, failing_ns):
        from fleet.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="1 error"):
            failing_ns.validate("DM", on_fail="raise")

    def test_on_fail_ignore(self, failing_ns, recwarn):
        ns = failing_ns.validate("DM", on_fail="ignore")
        assert ns.last_validation is not None
        assert not any("validation failed" in str(w.message) for w in recwarn.list)

    def test_invalid_on_fail_rejected(self, failing_ns):
        with pytest.raises(DerivationError, match="on_fail"):
            failing_ns.validate("DM", on_fail="explode")

    def test_last_validation_none_before_validate(self):
        df = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
└─────────┘
""")
        assert df.sdtm.last_validation is None

    def test_issues_are_enriched_with_producing_verb(self, monkeypatch):
        from fleet.validation.models import Severity, ValidationIssue, ValidationResult
        from fleet.validation.service import ValidationService

        result = ValidationResult(
            dataset_name="DM",
            dataset_type="SDTM",
            model_version="3.4",
            total_issues=2,
            errors=[
                ValidationIssue(Severity.ERROR, "X1", "bad DOMAIN", variable="DOMAIN"),
                ValidationIssue(Severity.ERROR, "X2", "missing AGE", variable="AGE"),
            ],
        )
        monkeypatch.setattr(ValidationService, "__init__", lambda self, **kw: None)
        monkeypatch.setattr(ValidationService, "validate_sdtm", lambda self, df, **kw: result)
        df = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
└─────────┘
""")
        with pytest.warns(UserWarning, match="validation failed"):
            ns = df.sdtm.assign("DOMAIN", value="DM").validate("DM")

        derived, underived = ns.last_validation.errors
        assert derived.producing_verb == "assign"
        assert derived.verb_method.endswith(".assign")
        assert underived.producing_verb is None  # AGE is not derived by this chain


class TestDateDifferenceInAStringExpression:
    """c1-62: TRTEDT - TRTSDT is a Polars Duration, so > 10 compared with 10 microseconds."""

    @pytest.fixture
    def adsl(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ TRTEDT     │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╡
│ S1      ┆ 2024-01-01 ┆ 2024-01-06 │
│ S2      ┆ 2024-01-01 ┆ 2024-01-31 │
└─────────┴────────────┴────────────┘
""")

    def test_flag_refuses_a_bare_date_difference(self, adsl):
        from fleet.core.exceptions import DerivationError

        with pytest.raises(DerivationError, match=r"\(TRTEDT - TRTSDT\)\.dt\.total_days\(\)"):
            adsl.adam.flag("F", criteria="TRTEDT - TRTSDT > 10")

    def test_case_when_refuses_a_bare_date_difference(self, adsl):
        from fleet.core.exceptions import DerivationError

        with pytest.raises(DerivationError, match="duration, not a number of days"):
            adsl.adam.case_when(
                "D", when=[{"condition": "TRTEDT - TRTSDT > 10", "value": "LONG"}], else_="SHORT"
            )

    def test_derivation_refuses_a_bare_date_difference(self, adsl):
        from fleet.core.exceptions import DerivationError

        with pytest.raises(DerivationError, match="duration"):
            adsl.adam.derivation("D", expression="TRTEDT - TRTSDT + 1")

    def test_the_dt_total_days_form_gives_days(self, adsl):
        out = adsl.adam.flag("F", criteria="(TRTEDT - TRTSDT).dt.total_days() > 10").to_frame()
        assert out["F"].to_list() == [None, "Y"]
