"""Unit tests for df.adam.pk — PKNamespace and the shared merge_adsl verb."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pc_frame():
    """Minimal PC SDTM-like concentration–time frame (3 subjects × 4 timepoints)."""
    return pl.DataFrame(
        {
            "USUBJID": [
                "01-001",
                "01-001",
                "01-001",
                "01-001",
                "01-002",
                "01-002",
                "01-002",
                "01-002",
                "01-003",
                "01-003",
                "01-003",
                "01-003",
            ],
            "PCTPTNUM": [0.0, 1.0, 4.0, 24.0] * 3,
            "PCTPT": ["PRE-DOSE", "1 HR", "4 HR", "24 HR"] * 3,
            "PCSTRESN": [
                None,
                10.27,
                22.31,
                0.73,
                None,
                9.56,
                20.54,
                None,
                None,
                11.78,
                24.67,
                0.88,
            ],
            "PCLLOQ": [1.0] * 12,
            # Pre-dose datetimes and dose reference datetimes (ISO 8601)
            "PCDTC": [
                "2014-01-17T08:00:00",
                "2014-01-17T09:00:00",
                "2014-01-17T12:00:00",
                "2014-01-18T08:00:00",
                "2014-02-10T07:55:00",
                "2014-02-10T09:00:00",
                "2014-02-10T12:00:00",
                "2014-02-11T08:00:00",
                "2014-03-05T08:00:00",
                "2014-03-05T09:00:00",
                "2014-03-05T12:00:00",
                "2014-03-06T08:00:00",
            ],
            "EXSTDTC": ["2014-01-17T08:00:00"] * 4
            + ["2014-02-10T08:00:00"] * 4
            + ["2014-03-05T08:00:00"] * 4,
            "DOSE": [100.0] * 12,
        }
    )


@pytest.fixture
def adsl_frame():
    """Minimal ADSL-like subject-level frame."""
    return pl.DataFrame(
        {
            "USUBJID": ["01-001", "01-002", "01-003"],
            "TRT01P": ["Drug A", "Placebo", "Drug A"],
            "TRTSDT": ["2014-01-17", "2014-02-10", "2014-03-05"],
        }
    )


# ---------------------------------------------------------------------------
# TestMergeAdsl — shared verb now in SharedADaMVerbsMixin
# ---------------------------------------------------------------------------


class TestMergeAdsl:
    def test_all_adsl_cols_merged(self, pc_frame, adsl_frame):
        result = pc_frame.adam.pk.merge_adsl(adsl_frame).to_frame()
        assert "TRT01P" in result.columns
        assert "TRTSDT" in result.columns
        assert result.height == 12

    def test_keep_cols_subsets_adsl(self, pc_frame, adsl_frame):
        result = pc_frame.adam.pk.merge_adsl(adsl_frame, keep_cols=["TRT01P"]).to_frame()
        assert "TRT01P" in result.columns
        assert "TRTSDT" not in result.columns

    def test_custom_by_key(self, adsl_frame):
        """Merge using a different join key."""
        left = pl.DataFrame(
            {
                "SUBJID": ["01-001", "01-002"],
                "AVAL": [1.0, 2.0],
            }
        )
        right = pl.DataFrame(
            {
                "SUBJID": ["01-001", "01-002"],
                "TRT": ["A", "B"],
            }
        )
        result = left.adam.pk.merge_adsl(right, by=["SUBJID"]).to_frame()
        assert "TRT" in result.columns

    def test_merge_adsl_available_on_occds(self, pc_frame, adsl_frame):
        """merge_adsl is a shared verb — must work on occds too."""
        result = pc_frame.adam.occds.merge_adsl(adsl_frame, keep_cols=["TRT01P"]).to_frame()
        assert "TRT01P" in result.columns


# ---------------------------------------------------------------------------
# TestSeq — seq() sourced from MultiRowMixin
# ---------------------------------------------------------------------------


class TestSeq:
    def test_seq_starts_at_one(self, pc_frame):
        result = pc_frame.adam.pk.seq("PCSEQ", groups=["USUBJID"]).to_frame()
        subj_001 = result.filter(pl.col("USUBJID") == "01-001")
        assert sorted(subj_001["PCSEQ"].to_list()) == [1, 2, 3, 4]

    def test_seq_resets_per_subject(self, pc_frame):
        result = pc_frame.adam.pk.seq("PCSEQ", groups=["USUBJID"]).to_frame()
        for subj in ["01-001", "01-002", "01-003"]:
            rows = result.filter(pl.col("USUBJID") == subj)
            assert sorted(rows["PCSEQ"].to_list()) == [1, 2, 3, 4]

    def test_seq_default_target(self, pc_frame):
        result = pc_frame.adam.pk.seq(groups=["USUBJID"]).to_frame()
        assert "ASEQ" in result.columns


# ---------------------------------------------------------------------------
# TestBlqFlag
# ---------------------------------------------------------------------------


class TestBlqFlag:
    def test_blq_flag_y_when_below_lloq(self, pc_frame):
        result = pc_frame.adam.pk.blq_flag(
            "BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ"
        ).to_frame()
        # PCSTRESN=0.73 < LLOQ=1.0 → "Y"
        low_row = result.filter(pl.col("PCSTRESN") == 0.73)
        assert low_row["BLQFL"][0] == "Y"

    def test_blq_flag_null_when_above_lloq(self, pc_frame):
        result = pc_frame.adam.pk.blq_flag(
            "BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ"
        ).to_frame()
        high_row = result.filter(pl.col("PCSTRESN") == 22.31)
        assert high_row["BLQFL"][0] is None

    def test_blq_flag_null_conc_not_flagged(self, pc_frame):
        """Null concentrations (e.g. BLQ already coded as null) should not propagate."""
        result = pc_frame.adam.pk.blq_flag(
            "BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ"
        ).to_frame()
        null_rows = result.filter(pl.col("PCSTRESN").is_null())
        # null < 1.0 is null in Polars → flag should be null
        assert all(v is None for v in null_rows["BLQFL"].to_list())


# ---------------------------------------------------------------------------
# TestBlqImpute
# ---------------------------------------------------------------------------


class TestBlqImpute:
    def test_half_lloq(self, pc_frame):
        result = pc_frame.adam.pk.blq_impute(
            "AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", method="half_lloq"
        ).to_frame()
        # 0.73 < 1.0 → imputed to 0.5
        low_row = result.filter(pl.col("PCSTRESN") == 0.73)
        assert low_row["AVAL"][0] == pytest.approx(0.5)

    def test_zero_method(self, pc_frame):
        result = pc_frame.adam.pk.blq_impute(
            "AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", method="zero"
        ).to_frame()
        low_row = result.filter(pl.col("PCSTRESN") == 0.73)
        assert low_row["AVAL"][0] == pytest.approx(0.0)

    def test_lloq_method(self, pc_frame):
        result = pc_frame.adam.pk.blq_impute(
            "AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", method="lloq"
        ).to_frame()
        low_row = result.filter(pl.col("PCSTRESN") == 0.73)
        assert low_row["AVAL"][0] == pytest.approx(1.0)

    def test_missing_method(self, pc_frame):
        result = pc_frame.adam.pk.blq_impute(
            "AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", method="missing"
        ).to_frame()
        low_row = result.filter(pl.col("PCSTRESN") == 0.73)
        assert low_row["AVAL"][0] is None

    def test_above_lloq_unchanged(self, pc_frame):
        result = pc_frame.adam.pk.blq_impute(
            "AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ"
        ).to_frame()
        high_row = result.filter(pl.col("PCSTRESN") == 22.31)
        assert high_row["AVAL"][0] == pytest.approx(22.31)

    def test_invalid_method_raises(self, pc_frame):
        with pytest.raises(ValueError, match="method="):
            pc_frame.adam.pk.blq_impute(
                "AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", method="badmethod"
            )


# ---------------------------------------------------------------------------
# TestNominalTime
# ---------------------------------------------------------------------------


class TestNominalTime:
    def test_passthrough_same_unit(self, pc_frame):
        result = pc_frame.adam.pk.nominal_time("NTIME", from_col="PCTPTNUM").to_frame()
        assert result.filter(pl.col("PCTPTNUM") == 4.0)["NTIME"][0] == pytest.approx(4.0)

    def test_hours_to_days(self, pc_frame):
        result = pc_frame.adam.pk.nominal_time(
            "NTIME", from_col="PCTPTNUM", input_unit="h", output_unit="d"
        ).to_frame()
        assert result.filter(pl.col("PCTPTNUM") == 24.0)["NTIME"][0] == pytest.approx(1.0)

    def test_invalid_unit_raises(self, pc_frame):
        with pytest.raises(ValueError, match="unit="):
            pc_frame.adam.pk.nominal_time("NTIME", from_col="PCTPTNUM", input_unit="yr")


# ---------------------------------------------------------------------------
# TestActualTime
# ---------------------------------------------------------------------------


class TestActualTime:
    def test_actual_time_hours(self, pc_frame):
        result = pc_frame.adam.pk.actual_time(
            "ATIME", sample_dtm="PCDTC", dose_dtm="EXSTDTC", unit="h"
        ).to_frame()
        # Subject 01-001 row 1: sample_dtm = 09:00, dose_dtm = 08:00 → 1.0 h
        row = result.filter((pl.col("USUBJID") == "01-001") & (pl.col("PCTPTNUM") == 1.0))
        assert row["ATIME"][0] == pytest.approx(1.0)

    def test_actual_time_predose_negative(self, pc_frame):
        """Subject 01-002 pre-dose sample at 07:55 → actual time = -5 min = -1/12 h."""
        result = pc_frame.adam.pk.actual_time(
            "ATIME", sample_dtm="PCDTC", dose_dtm="EXSTDTC", unit="h"
        ).to_frame()
        row = result.filter((pl.col("USUBJID") == "01-002") & (pl.col("PCTPTNUM") == 0.0))
        assert row["ATIME"][0] == pytest.approx(-5 / 60)

    def test_actual_time_unit_minutes(self, pc_frame):
        result = pc_frame.adam.pk.actual_time(
            "ATIME", sample_dtm="PCDTC", dose_dtm="EXSTDTC", unit="min"
        ).to_frame()
        row = result.filter((pl.col("USUBJID") == "01-001") & (pl.col("PCTPTNUM") == 1.0))
        assert row["ATIME"][0] == pytest.approx(60.0)

    def test_invalid_unit_raises(self, pc_frame):
        with pytest.raises(ValueError, match="unit="):
            pc_frame.adam.pk.actual_time(
                "ATIME", sample_dtm="PCDTC", dose_dtm="EXSTDTC", unit="week"
            )


# ---------------------------------------------------------------------------
# TestPredoseFlag
# ---------------------------------------------------------------------------


class TestPredoseFlag:
    def _frame_with_atime(self):
        return pl.DataFrame(
            {
                "USUBJID": ["01-001", "01-001", "01-001", "01-001"],
                "ATIME": [-0.5, 0.0, 1.0, 4.0],
            }
        )

    def test_predose_within_window(self):
        df = self._frame_with_atime()
        result = df.adam.pk.predose_flag("PREDFL", time_col="ATIME", window_hrs=1.0).to_frame()
        # ATIME=-0.5 within [-1,0) → "Y"
        assert result.filter(pl.col("ATIME") == -0.5)["PREDFL"][0] == "Y"

    def test_zero_time_not_flagged(self):
        df = self._frame_with_atime()
        result = df.adam.pk.predose_flag("PREDFL", time_col="ATIME").to_frame()
        # ATIME=0.0 is NOT < 0 → null
        assert result.filter(pl.col("ATIME") == 0.0)["PREDFL"][0] is None

    def test_post_dose_not_flagged(self):
        df = self._frame_with_atime()
        result = df.adam.pk.predose_flag("PREDFL", time_col="ATIME").to_frame()
        assert result.filter(pl.col("ATIME") == 4.0)["PREDFL"][0] is None

    def test_outside_window_not_flagged(self):
        df = pl.DataFrame({"USUBJID": ["01-001"], "ATIME": [-2.0]})
        result = df.adam.pk.predose_flag("PREDFL", time_col="ATIME", window_hrs=1.0).to_frame()
        # -2.0 < -1.0 → outside window → null
        assert result["PREDFL"][0] is None


# ---------------------------------------------------------------------------
# TestDoseNormalized
# ---------------------------------------------------------------------------


class TestDoseNormalized:
    def test_basic_normalisation(self, pc_frame):
        result = (
            pc_frame.adam.pk.blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ")
            .dose_normalized("AVALDNM", conc_col="AVAL", dose_col="DOSE")
            .to_frame()
        )
        row = result.filter(pl.col("PCSTRESN") == 22.31)
        assert row["AVALDNM"][0] == pytest.approx(22.31 / 100.0)

    def test_zero_dose_returns_null(self):
        df = pl.DataFrame(
            {
                "AVAL": [10.0, 5.0],
                "DOSE": [0.0, 100.0],
            }
        )
        result = df.adam.pk.dose_normalized("AVALDNM", conc_col="AVAL", dose_col="DOSE").to_frame()
        assert result["AVALDNM"][0] is None
        assert result["AVALDNM"][1] == pytest.approx(0.05)

    def test_null_dose_returns_null(self):
        df = pl.DataFrame(
            {
                "AVAL": [10.0],
                "DOSE": [None],
            }
        ).cast({"DOSE": pl.Float64})
        result = df.adam.pk.dose_normalized("AVALDNM", conc_col="AVAL", dose_col="DOSE").to_frame()
        assert result["AVALDNM"][0] is None


# ---------------------------------------------------------------------------
# TestEvid
# ---------------------------------------------------------------------------


class TestEvid:
    def test_default_all_zeros(self):
        df = pl.DataFrame({"USUBJID": ["01-001", "01-001"], "PCSTRESN": [10.0, 5.0]})
        result = df.adam.pk.evid("EVID").to_frame()
        assert result["EVID"].to_list() == [0, 0]

    def test_from_col_cast(self):
        df = pl.DataFrame({"USUBJID": ["01-001", "01-001"], "IS_DOSE": [0, 1]})
        result = df.adam.pk.evid("EVID", from_col="IS_DOSE").to_frame()
        assert result["EVID"].to_list() == [0, 1]
        assert result["EVID"].dtype == pl.Int64


# ---------------------------------------------------------------------------
# TestMrrlt
# ---------------------------------------------------------------------------


class TestMrrlt:
    def _frame(self):
        return pl.DataFrame(
            {
                "USUBJID": ["01-001"] * 4,
                "ARRLT": [-1.0, 0.0, 1.0, 4.0],
            }
        )

    def test_negative_clipped_to_zero(self):
        result = self._frame().adam.pk.mrrlt("MRRLT", arrlt_col="ARRLT").to_frame()
        assert result.filter(pl.col("ARRLT") == -1.0)["MRRLT"][0] == pytest.approx(0.0)

    def test_zero_unchanged(self):
        result = self._frame().adam.pk.mrrlt("MRRLT", arrlt_col="ARRLT").to_frame()
        assert result.filter(pl.col("ARRLT") == 0.0)["MRRLT"][0] == pytest.approx(0.0)

    def test_positive_unchanged(self):
        result = self._frame().adam.pk.mrrlt("MRRLT", arrlt_col="ARRLT").to_frame()
        assert result.filter(pl.col("ARRLT") == 4.0)["MRRLT"][0] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# TestBlqfn
# ---------------------------------------------------------------------------


class TestBlqfn:
    def test_blq_is_one(self, pc_frame):
        result = pc_frame.adam.pk.blqfn("BLQFN", conc_col="PCSTRESN", lloq_col="PCLLOQ").to_frame()
        # 0.73 < 1.0 → 1
        row = result.filter(pl.col("PCSTRESN") == 0.73)
        assert row["BLQFN"][0] == 1

    def test_above_lloq_is_zero(self, pc_frame):
        result = pc_frame.adam.pk.blqfn("BLQFN", conc_col="PCSTRESN", lloq_col="PCLLOQ").to_frame()
        row = result.filter(pl.col("PCSTRESN") == 22.31)
        assert row["BLQFN"][0] == 0

    def test_dtype_is_int64(self, pc_frame):
        result = pc_frame.adam.pk.blqfn("BLQFN", conc_col="PCSTRESN", lloq_col="PCLLOQ").to_frame()
        assert result["BLQFN"].dtype == pl.Int64


# ---------------------------------------------------------------------------
# TestLogConc
# ---------------------------------------------------------------------------


class TestLogConc:
    def test_natural_log(self):
        import math

        df = pl.DataFrame({"DV": [1.0, math.e, 10.0]})
        result = df.adam.pk.log_conc("DVL", conc_col="DV").to_frame()
        assert result["DVL"][0] == pytest.approx(0.0, abs=1e-6)
        assert result["DVL"][1] == pytest.approx(1.0, abs=1e-6)

    def test_log10(self):
        df = pl.DataFrame({"DV": [1.0, 10.0, 100.0]})
        result = df.adam.pk.log_conc("DVL", conc_col="DV", base="10").to_frame()
        assert result["DVL"][0] == pytest.approx(0.0, abs=1e-6)
        assert result["DVL"][1] == pytest.approx(1.0, abs=1e-6)
        assert result["DVL"][2] == pytest.approx(2.0, abs=1e-6)

    def test_zero_or_null_returns_null(self):
        df = pl.DataFrame({"DV": [0.0, None]}).cast({"DV": pl.Float64})
        result = df.adam.pk.log_conc("DVL", conc_col="DV").to_frame()
        assert result["DVL"][0] is None
        assert result["DVL"][1] is None

    def test_invalid_base_raises(self):
        df = pl.DataFrame({"DV": [1.0]})
        with pytest.raises(ValueError, match="base="):
            df.adam.pk.log_conc("DVL", conc_col="DV", base="3")


# ---------------------------------------------------------------------------
# TestMdv
# ---------------------------------------------------------------------------


class TestMdv:
    def test_mdv_from_evid(self):
        df = pl.DataFrame(
            {
                "EVID": [0, 1, 0],
                "DV": [10.0, None, 5.0],
            }
        )
        result = df.adam.pk.mdv("MDV", evid_col="EVID").to_frame()
        assert result["MDV"].to_list() == [0, 1, 0]

    def test_mdv_from_null_conc(self):
        df = pl.DataFrame(
            {
                "EVID": [0, 0, 0],
                "DV": [10.0, None, 5.0],
            }
        )
        result = df.adam.pk.mdv("MDV", conc_col="DV").to_frame()
        assert result["MDV"].to_list() == [0, 1, 0]

    def test_mdv_combined(self):
        df = pl.DataFrame(
            {
                "EVID": [0, 1, 0],
                "DV": [10.0, None, None],
            }
        )
        result = df.adam.pk.mdv("MDV", conc_col="DV", evid_col="EVID").to_frame()
        assert result["MDV"].to_list() == [0, 1, 1]

    def test_mdv_no_condition(self):
        df = pl.DataFrame({"EVID": [0, 1]})
        result = df.adam.pk.mdv("MDV").to_frame()
        assert result["MDV"].to_list() == [0, 0]


# ---------------------------------------------------------------------------
# TestAmt
# ---------------------------------------------------------------------------


class TestAmt:
    def test_dose_on_evid1_null_otherwise(self):
        df = pl.DataFrame(
            {
                "EVID": [0, 1, 0],
                "EXDOSE": [100.0, 100.0, 100.0],
            }
        )
        result = df.adam.pk.amt("AMT", dose_col="EXDOSE", evid_col="EVID").to_frame()
        assert result["AMT"][0] is None
        assert result["AMT"][1] == pytest.approx(100.0)
        assert result["AMT"][2] is None


# ---------------------------------------------------------------------------
# TestCmt
# ---------------------------------------------------------------------------


class TestCmt:
    def test_dose_cmt_and_conc_cmt(self):
        df = pl.DataFrame({"EVID": [0, 1, 0]})
        result = df.adam.pk.cmt("CMT", evid_col="EVID", dose_cmt=1, conc_cmt=2).to_frame()
        assert result["CMT"].to_list() == [2, 1, 2]

    def test_default_compartments(self):
        df = pl.DataFrame({"EVID": [1, 0]})
        result = df.adam.pk.cmt().to_frame()
        assert result["CMT"].to_list() == [1, 2]


# ---------------------------------------------------------------------------
# TestAvalcat
# ---------------------------------------------------------------------------


class TestAvalcat:
    def test_blq_labeled(self, pc_frame):
        result = pc_frame.adam.pk.avalcat(
            "AVALCAT1", conc_col="PCSTRESN", lloq_col="PCLLOQ"
        ).to_frame()
        # 0.73 < 1.0 → BLQ
        row = result.filter(pl.col("PCSTRESN") == 0.73)
        assert row["AVALCAT1"][0] == "BLQ"

    def test_above_lloq_is_string(self, pc_frame):
        result = pc_frame.adam.pk.avalcat(
            "AVALCAT1", conc_col="PCSTRESN", lloq_col="PCLLOQ"
        ).to_frame()
        row = result.filter(pl.col("PCSTRESN") == 22.31)
        assert row["AVALCAT1"][0] is not None
        assert "22" in row["AVALCAT1"][0]

    def test_custom_blq_label(self, pc_frame):
        result = pc_frame.adam.pk.avalcat(
            "AVALCAT1", conc_col="PCSTRESN", lloq_col="PCLLOQ", blq_label="<BLQ"
        ).to_frame()
        row = result.filter(pl.col("PCSTRESN") == 0.73)
        assert row["AVALCAT1"][0] == "<BLQ"


# ---------------------------------------------------------------------------
# TestAnlFlag
# ---------------------------------------------------------------------------


class TestAnlFlag:
    def test_anl01fl_all_y(self):
        df = pl.DataFrame({"USUBJID": ["01-001", "01-002"]})
        result = df.adam.pk.anl_flag("ANL01FL").to_frame()
        assert result["ANL01FL"].to_list() == ["Y", "Y"]

    def test_anl02fl_excludes_dtype(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["01-001", "01-001", "01-001"],
                "DTYPE": [None, "COPY", "HALFLLOQ"],
            }
        )
        result = df.adam.pk.anl_flag("ANL02FL", exclude_dtype=True).to_frame()
        assert result["ANL02FL"].to_list() == ["Y", None, None]

    def test_anl02fl_all_null_dtype_all_y(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["01-001", "01-002"],
                "DTYPE": [None, None],
            }
        )
        result = df.adam.pk.anl_flag("ANL02FL", exclude_dtype=True).to_frame()
        assert result["ANL02FL"].to_list() == ["Y", "Y"]
