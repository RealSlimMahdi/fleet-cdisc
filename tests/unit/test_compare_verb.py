"""Pipeline-verb tests for ``.compare()`` (ticket #101, spec #99).

The chain is the candidate, the argument is the base.  Every test runs a
two-step chain and looks only at what the verb promises: the report kept on
the namespace as ``last_comparison``, the ``on_fail`` behaviour, and the
chain continuing after the verb.  The engine itself is tested in
``test_compare.py``.
"""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — registers the namespaces


def _dm() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬─────┬─────┐
│ USUBJID ┆ AGE ┆ SEX │
│ ---     ┆ --- ┆ --- │
│ str     ┆ i64 ┆ str │
╞═════════╪═════╪═════╡
│ 01      ┆ 34  ┆ M   │
│ 02      ┆ 45  ┆ F   │
│ 03      ┆ 52  ┆ F   │
└─────────┴─────┴─────┘
""")


@pytest.fixture
def base() -> pl.DataFrame:
    """The base DM, already carrying DOMAIN."""
    return _dm().with_columns(pl.lit("DM").alias("DOMAIN"))


class TestChainContinues:
    def test_two_step_sdtm_chain_keeps_the_report_and_continues(self, base):
        ns = _dm().sdtm.assign("DOMAIN", value="DM").compare(base, keys="USUBJID")
        assert ns.last_comparison is not None
        assert ns.last_comparison.is_equal is True
        out = ns.assign("STUDYID", value="S1").to_frame()
        assert out.columns == ["USUBJID", "AGE", "SEX", "DOMAIN", "STUDYID"]


class TestOnFail:
    """Same three values and the same error family as ``validate``."""

    @pytest.fixture
    def differing(self):
        """A chain whose DOMAIN disagrees with the base on every observation."""
        return _dm().sdtm.assign("DOMAIN", value="XX")

    def test_warn_is_the_default_and_keeps_the_chain(self, base, differing):
        with pytest.warns(UserWarning, match="NOT EQUAL") as record:
            ns = differing.compare(base, keys="USUBJID")
        assert "last_comparison" in str(record[0].message)
        assert ns.last_comparison is not None
        assert ns.last_comparison.is_equal is False
        assert ns.last_comparison.flags == {"values_differ"}
        assert ns.to_frame().height == 3

    def test_raise_raises_a_comparison_error_in_the_fleet_family(self, base, differing):
        from fleet.core.exceptions import ComparisonError, FleetError

        with pytest.raises(ComparisonError, match="values_differ") as exc:
            differing.compare(base, keys="USUBJID", on_fail="raise")
        assert isinstance(exc.value, FleetError)

    def test_ignore_is_silent_but_still_keeps_the_report(self, base, differing, recwarn):
        ns = differing.compare(base, keys="USUBJID", on_fail="ignore")
        assert ns.last_comparison is not None
        assert ns.last_comparison.is_equal is False
        assert not any("NOT EQUAL" in str(w.message) for w in recwarn.list)

    def test_equal_datasets_never_warn_or_raise(self, base, recwarn):
        chain = _dm().sdtm.assign("DOMAIN", value="DM")
        chain.compare(base, keys="USUBJID", on_fail="raise")
        chain.compare(base, keys="USUBJID", on_fail="warn")
        assert not recwarn.list

    def test_unknown_on_fail_fails_fast_like_validate(self, base):
        from fleet.core.exceptions import DerivationError

        with pytest.raises(DerivationError, match="on_fail"):
            _dm().sdtm.compare(base, keys="USUBJID", on_fail="explode")  # type: ignore[arg-type]


class TestWhichSideIsWhich:
    """The chain is the candidate; the argument is the base."""

    def test_the_chain_is_the_candidate_and_the_argument_the_base(self, base):
        chain = _dm().sdtm.assign("DOMAIN", value="DM").assign("AGE", value=99)
        ns = chain.compare(base, keys="USUBJID", on_fail="ignore")
        rows = ns.last_comparison.listing.to_dicts()
        assert [r["variable"] for r in rows] == ["AGE", "AGE", "AGE"]
        assert rows[0]["base"] == "34"
        assert rows[0]["candidate"] == "99"
        assert ns.last_comparison.datasets.candidate.variables == 4

    def test_a_lazy_base_is_accepted(self, base):
        ns = _dm().sdtm.assign("DOMAIN", value="DM").compare(base.lazy(), keys="USUBJID")
        assert ns.last_comparison.is_equal is True

    def test_names_and_print_limits_reach_the_engine(self, base):
        ns = (
            _dm()
            .sdtm.assign("DOMAIN", value="DM")
            .compare(
                base,
                keys="USUBJID",
                max_print=None,
                base_name="dm (prod)",
                candidate_name="dm (qc)",
            )
        )
        settings = ns.last_comparison.settings
        assert settings.max_print is None
        assert settings.base_name == "dm (prod)"
        assert settings.candidate_name == "dm (qc)"

    def test_missing_key_stops_the_compare_with_a_comparison_error(self, base):
        from fleet.core.exceptions import ComparisonError

        with pytest.raises(ComparisonError, match="SUBJID"):
            _dm().sdtm.compare(base, keys="SUBJID")


class TestNamespaces:
    def test_last_comparison_is_none_before_compare(self):
        assert _dm().sdtm.last_comparison is None
        assert _dm().adam.last_comparison is None

    def test_two_step_adam_chain_keeps_the_report_and_continues(self):
        base = _dm().with_columns(pl.lit("S1").alias("STUDYID"))
        ns = (
            _dm().adam.source("USUBJID").assign("STUDYID", value="S1").compare(base, keys="USUBJID")
        )
        assert ns.last_comparison is not None
        assert ns.last_comparison.is_equal is True
        assert ns.assign("SITEID", value="01").to_frame()["SITEID"].to_list() == ["01"] * 3

    @pytest.mark.parametrize("namespace", ["sdtm", "adam", "adam.adsl", "adam.occds"])
    def test_verb_is_listed_on_every_namespace(self, namespace):
        ns = _dm()
        for attr in namespace.split("."):
            ns = getattr(ns, attr)
        assert "compare" in ns.verbs()["verb"].to_list()
        report = ns.compare(_dm(), keys="USUBJID").last_comparison
        assert report is not None and report.is_equal is True

    def test_the_report_is_printed_through_the_fleet_logger(self, base, capsys):
        _dm().sdtm.assign("DOMAIN", value="DM").compare(base, keys="USUBJID")
        out = capsys.readouterr().out
        assert "Comparison report" in out
        assert "EQUAL: no differences found." in out

    def test_the_original_namespace_is_left_untouched(self, base):
        chain = _dm().sdtm.assign("DOMAIN", value="DM")
        chain.compare(base, keys="USUBJID")
        assert chain.last_comparison is None
