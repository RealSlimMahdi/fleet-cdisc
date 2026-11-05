"""Regression tests for the medium and low ADaM audit findings of package ml-adam-a."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — registers namespaces
from fleet.core.exceptions import DerivationError


class TestWrongStringsRaise:
    """c1-140: a misspelled column or keyword raises instead of a silent value."""

    @pytest.fixture
    def adsl(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬────────────┬────────────┬────────┐
│ USUBJID ┆ AP01SDT    ┆ AP01EDT    ┆ TRT01P │
│ ---     ┆ ---        ┆ ---        ┆ ---    │
│ str     ┆ date       ┆ date       ┆ str    │
╞═════════╪════════════╪════════════╪════════╡
│ S1      ┆ 2024-01-01 ┆ 2024-02-01 ┆ DRUG A │
│ S2      ┆ 2024-01-03 ┆ 2024-02-03 ┆ DRUG B │
└─────────┴────────────┴────────────┴────────┘
""")

    def test_a_misspelled_treatment_column_raises(self, adsl):
        period = {"number": 1, "start": "AP01SDT", "end": "AP01EDT", "treatment": "TRT01PP"}
        with pytest.raises(DerivationError, match="'TRT01PP' not found. Did you mean 'TRT01P'"):
            adsl.adam.adsl.derive_period(periods=[period])

    def test_a_treatment_value_is_a_literal(self, adsl):
        period = {"number": 1, "start": "AP01SDT", "end": "AP01EDT", "treatment_value": "DRUG A"}

        out = adsl.adam.adsl.derive_period(periods=[period]).to_frame()

        assert out["TRT01P"].to_list() == ["DRUG A", "DRUG A"]

    def test_a_misspelled_impute_value_raises(self):
        vs = pl.from_repr("""\
┌─────────┬─────────┐
│ USUBJID ┆ VSDTC   │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ A       ┆ 2021-03 │
└─────────┴─────────┘
""")
        with pytest.raises(DerivationError, match="impute='fist'.*Did you mean 'first'"):
            vs.adam.date("ASTDT", source="VSDTC", impute="fist")
