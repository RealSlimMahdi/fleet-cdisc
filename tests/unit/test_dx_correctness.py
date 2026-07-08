"""Regression tests for the DX-review correctness fixes (C2/C3/C4/C5/C10/C11/C12).

Each test would have caught the original silent-wrong-answer bug.
"""

import warnings

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.exceptions import DerivationError, FleetError

# ------------------------------------------------------------------ #
# C2 — target_cols must actually restrict the joined result            #
# ------------------------------------------------------------------ #


class TestMergeTargetCols:
    @pytest.fixture
    def base(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬───────┐
│ USUBJID ┆ AESEQ │
│ ---     ┆ ---   │
│ str     ┆ i64   │
╞═════════╪═══════╡
│ S001    ┆ 1     │
│ S002    ┆ 2     │
└─────────┴───────┘
""")

    @pytest.fixture
    def lookup_df(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬─────────┬───────┐
│ USUBJID ┆ RFSTDTC ┆ EXTRA │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ str   │
╞═════════╪═════════╪═══════╡
│ S001    ┆ 2014-01 ┆ x     │
│ S002    ┆ 2014-02 ┆ y     │
└─────────┴─────────┴───────┘
""")

    def test_sdtm_merge_restricts_columns(self, base, lookup_df):
        result = base.sdtm.merge(["RFSTDTC"], dataset=lookup_df, on="USUBJID").to_frame()
        assert result.columns == ["USUBJID", "RFSTDTC"]
        assert "EXTRA" not in result.columns

    def test_sdtm_merge_without_target_cols_keeps_all(self, base, lookup_df):
        result = base.sdtm.merge(dataset=lookup_df, on="USUBJID").to_frame()
        assert set(result.columns) == {"USUBJID", "AESEQ", "RFSTDTC", "EXTRA"}

    def test_sdtm_merge_unknown_target_col_raises_with_suggestion(self, base, lookup_df):
        with pytest.raises(DerivationError, match="RFSTDTC"):
            base.sdtm.merge(["RFSTDTX"], dataset=lookup_df, on="USUBJID")

    def test_adam_lookup_restricts_columns(self, base, lookup_df):
        result = base.adam.lookup(["RFSTDTC"], dataset=lookup_df, on="USUBJID").to_frame()
        assert result.columns == ["USUBJID", "RFSTDTC"]

    def test_adam_lookup_no_dead_pipeline_attr(self, base, lookup_df):
        ns = base.adam.lookup(["RFSTDTC"], dataset=lookup_df, on="USUBJID")
        assert not hasattr(ns, "_pipeline")

    def test_adam_lookup_unknown_target_col_raises(self, base, lookup_df):
        with pytest.raises(DerivationError, match="not found"):
            base.adam.lookup(["NOPE"], dataset=lookup_df, on="USUBJID")


# ------------------------------------------------------------------ #
# C3 — nrind null semantics                                            #
# ------------------------------------------------------------------ #


class TestNrindNullGuard:
    @pytest.fixture
    def lb(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌──────┬──────┬──────┐
│ AVAL ┆ LO   ┆ HI   │
│ ---  ┆ ---  ┆ ---  │
│ f64  ┆ f64  ┆ f64  │
╞══════╪══════╪══════╡
│ null ┆ 1.0  ┆ 10.0 │
│ 5.0  ┆ null ┆ null │
│ 0.5  ┆ 1.0  ┆ 10.0 │
│ 11.0 ┆ 1.0  ┆ 10.0 │
│ 5.0  ┆ 1.0  ┆ 10.0 │
│ 11.0 ┆ null ┆ 10.0 │
│ 5.0  ┆ null ┆ 10.0 │
│ 0.5  ┆ 1.0  ┆ null │
└──────┴──────┴──────┘
""")

    def test_null_value_and_null_limits_yield_null(self, lb):
        result = lb.adam.nrind("NRIND", value="AVAL", low="LO", high="HI").to_frame()
        assert result["NRIND"].to_list() == [
            None,  # null AVAL — never "NORMAL"
            None,  # both limits null — never "NORMAL"
            "LOW",
            "HIGH",
            "NORMAL",
            "HIGH",  # one-sided: high only
            "NORMAL",  # one-sided: within high
            "LOW",  # one-sided: low only
        ]


# ------------------------------------------------------------------ #
# C4 — CT degradation is never silent                                  #
# ------------------------------------------------------------------ #


class TestAssignCTDegradeWarning:
    def test_unknown_codelist_warns_unvalidated(self):
        df = pl.DataFrame({"sex": ["M", "F"]})
        with pytest.warns(UserWarning, match="copied unvalidated"):
            result = df.sdtm.assign_ct(
                "SEX", source="sex", ct_codelist="C_DOES_NOT_EXIST"
            ).to_frame()
        assert result["SEX"].to_list() == ["M", "F"]

    def test_validate_values_false_opts_out_silently(self):
        # Uses the canonical assign() spelling: assign_ct is a deprecated
        # alias whose FutureWarning would trip simplefilter("error").
        df = pl.DataFrame({"sex": ["M", "F"]})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = df.sdtm.assign(
                "SEX",
                source="sex",
                ct="C_DOES_NOT_EXIST",
                validate_values=False,
            ).to_frame()
        assert result["SEX"].to_list() == ["M", "F"]

    def test_loaded_codelist_validates_by_default(self):
        from fleet.ct.validator import get_validator

        validator = get_validator()
        validator._ct_cache["C_TEST_ASSIGN"] = {"M": {}, "F": {}}
        try:
            df = pl.DataFrame({"sex": ["M", "BAD"]})
            with pytest.warns(UserWarning, match="not in codelist"):
                df.sdtm.assign_ct("SEX", source="sex", ct_codelist="C_TEST_ASSIGN").to_frame()
        finally:
            validator._ct_cache.pop("C_TEST_ASSIGN", None)

    def test_hardcode_ct_unknown_codelist_warns(self, simple_raw):
        with pytest.warns(UserWarning, match="assigned unvalidated"):
            simple_raw.sdtm.hardcode_ct(
                "AGEU", value="YEARS", ct_codelist="C_DOES_NOT_EXIST"
            ).to_frame()


# ------------------------------------------------------------------ #
# C5 — no-mapping mode must never rewrite submission values            #
# ------------------------------------------------------------------ #


class TestAssignCTNoDecode:
    def test_valid_submission_values_pass_through_unchanged(self):
        """CT loaded with decodes: "M" must stay "M", never become "Male"."""
        from fleet.ct.validator import get_validator

        validator = get_validator()
        validator._ct_cache["C_TEST_SEX"] = {
            "M": {"preferred_term": "Male"},
            "F": {"preferred_term": "Female"},
        }
        try:
            df = pl.DataFrame({"sex": ["M", "F"]})
            result = df.sdtm.assign_ct("SEX", source="sex", ct_codelist="C_TEST_SEX").to_frame()
            assert result["SEX"].to_list() == ["M", "F"]
        finally:
            validator._ct_cache.pop("C_TEST_SEX", None)

    def test_explicit_mapping_still_translates(self):
        df = pl.DataFrame({"sex": ["1", "2"]})
        result = df.sdtm.assign_ct(
            "SEX", source="sex", ct_codelist="C66731", ct_mapping={"1": "M", "2": "F"}
        ).to_frame()
        assert result["SEX"].to_list() == ["M", "F"]


# ------------------------------------------------------------------ #
# C10 — ambiguous baseline must not be silently max()'d                #
# ------------------------------------------------------------------ #


class TestBaselineStrict:
    @pytest.fixture
    def dup_baseline(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬─────────┬──────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL ┆ ABLFL │
│ ---     ┆ ---     ┆ ---  ┆ ---   │
│ str     ┆ str     ┆ f64  ┆ str   │
╞═════════╪═════════╪══════╪═══════╡
│ S001    ┆ SYSBP   ┆ 120  ┆ Y     │
│ S001    ┆ SYSBP   ┆ 118  ┆ Y     │
│ S001    ┆ SYSBP   ┆ 125  ┆ null  │
│ S002    ┆ SYSBP   ┆ 110  ┆ Y     │
└─────────┴─────────┴──────┴───────┘
""")

    def test_strict_default_raises_naming_group(self, dup_baseline):
        with pytest.raises(DerivationError, match="S001") as excinfo:
            dup_baseline.adam.baseline("BASE")
        assert "ABLFL" in str(excinfo.value)
        # Legacy catch style still works
        with pytest.raises(ValueError):
            dup_baseline.adam.baseline("BASE")

    def test_strict_false_warns_and_keeps_legacy_max(self, dup_baseline):
        with pytest.warns(UserWarning, match="ambiguous"):
            result = dup_baseline.adam.baseline("BASE", strict=False).to_frame()
        assert result.filter(pl.col("USUBJID") == "S001")["BASE"].to_list() == [
            120.0,
            120.0,
            120.0,
        ]

    def test_unique_baseline_passes_strict(self, dup_baseline):
        clean = dup_baseline.filter(pl.col("AVAL") != 118.0)
        result = clean.adam.baseline("BASE").to_frame()
        assert result.filter(pl.col("USUBJID") == "S002")["BASE"].to_list() == [110.0]


# ------------------------------------------------------------------ #
# C11 — duration must never silently ignore an explicit kwarg          #
# ------------------------------------------------------------------ #


class TestDurationExplicitKwargs:
    @pytest.fixture
    def dates(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌────────────┬────────────┐
│ START      ┆ END        │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 2014-01-01 ┆ 2014-01-05 │
└────────────┴────────────┘
""")

    def test_dy_target_with_iso8601_raises(self, dates):
        with pytest.raises(DerivationError, match="study-day convention"):
            dates.sdtm.duration("AESTDY", start="START", end="END", out="iso8601")

    def test_dy_target_with_explicit_add_one_allows_iso(self, dates):
        result = dates.sdtm.duration(
            "AESTDY", start="START", end="END", out="iso8601", add_one=False
        ).to_frame()
        assert result["AESTDY"].to_list() == ["P4D"]

    def test_unknown_out_value_raises(self, dates):
        with pytest.raises(DerivationError, match="out="):
            dates.sdtm.duration("ADUR", start="START", end="END", out="iso")


# ------------------------------------------------------------------ #
# C12 — pick() must reject unknown event keys                          #
# ------------------------------------------------------------------ #


class TestPickUnknownKeys:
    @pytest.fixture
    def adsl(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ TRTEDT     │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S001    ┆ 2014-07-02 │
└─────────┴────────────┘
""")

    def test_orderby_typo_rejected_with_did_you_mean(self, adsl):
        with pytest.raises(DerivationError, match="did you mean 'order'"):
            adsl.adam.pick(
                "LSTALVDT",
                events=[
                    {
                        "when": pl.col("TRTEDT").is_not_null(),
                        "set": {"LSTALVDT": "TRTEDT"},
                        "orderby": ["TRTEDT"],
                    }
                ],
            )

    def test_unknown_key_is_fleet_error_and_value_error(self, adsl):
        event = {
            "when": pl.col("TRTEDT").is_not_null(),
            "set": {"LSTALVDT": "TRTEDT"},
            "bogus": 1,
        }
        with pytest.raises(FleetError):
            adsl.adam.pick("LSTALVDT", events=[event])
        with pytest.raises(ValueError):
            adsl.adam.pick("LSTALVDT", events=[event])

    def test_valid_keys_still_work(self, adsl):
        result = adsl.adam.pick(
            "LSTALVDT",
            events=[
                {
                    "when": pl.col("TRTEDT").is_not_null(),
                    "set": {"LSTALVDT": "TRTEDT"},
                    "label": "Treatment end",
                }
            ],
        ).to_frame()
        assert result["LSTALVDT"].to_list() == ["2014-07-02"]
