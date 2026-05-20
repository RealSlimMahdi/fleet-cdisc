"""Unit tests for date derivation verbs: .date() unified API."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #


@pytest.fixture
def dtc_frame():
    """Frame with various --DTC completeness levels."""
    return pl.DataFrame(
        {
            "USUBJID": ["S01", "S02", "S03", "S04", "S05"],
            "AESTDTC": ["2014-07-15", "2014-07", "2014", "2014-07-15T08:30:00", None],
        }
    )


@pytest.fixture
def vs_dtc_frame():
    """Frame with complete dates for merge/flag scenarios."""
    return pl.DataFrame(
        {
            "USUBJID": ["S01", "S01", "S01", "S02", "S02"],
            "PARAMCD": ["SYSBP", "SYSBP", "SYSBP", "SYSBP", "SYSBP"],
            "VSDTC": ["2014-01-01", "2014-01-15", "2014-02-01", "2014-01-01", "2014-01-15"],
            "AVAL": [120.0, 130.0, 125.0, 118.0, 115.0],
            "TRTSDT": ["2014-01-10", "2014-01-10", "2014-01-10", "2014-01-05", "2014-01-05"],
            "TRTEDT": ["2014-02-10", "2014-02-10", "2014-02-10", "2014-02-10", "2014-02-10"],
        }
    )


# ------------------------------------------------------------------ #
# derive_dt tests                                                      #
# ------------------------------------------------------------------ #


class TestDeriveDt:
    def test_complete_date(self, dtc_frame):
        result = dtc_frame.adam.date("ADT", source="AESTDTC").to_frame()
        assert result["ADT"].dtype == pl.Date
        assert str(result["ADT"][0]) == "2014-07-15"

    def test_partial_yyyymm_first(self, dtc_frame):
        result = dtc_frame.adam.date("ADT", source="AESTDTC").to_frame()
        assert str(result["ADT"][1]) == "2014-07-01"

    def test_partial_yyyymm_last(self, dtc_frame):
        result = dtc_frame.adam.date("ADT", source="AESTDTC", impute="last").to_frame()
        assert str(result["ADT"][1]) == "2014-07-31"

    def test_partial_yyyymm_mid(self, dtc_frame):
        result = dtc_frame.adam.date("ADT", source="AESTDTC", impute="mid").to_frame()
        assert str(result["ADT"][1]) == "2014-07-15"

    def test_partial_yyyy_first(self, dtc_frame):
        result = dtc_frame.adam.date(
            "ADT",
            source="AESTDTC",
        ).to_frame()
        assert str(result["ADT"][2]) == "2014-01-01"

    def test_partial_yyyy_last(self, dtc_frame):
        result = dtc_frame.adam.date(
            "ADT",
            source="AESTDTC",
            impute="last",
        ).to_frame()
        assert str(result["ADT"][2]) == "2014-12-31"

    def test_partial_yyyy_mid(self, dtc_frame):
        result = dtc_frame.adam.date(
            "ADT",
            source="AESTDTC",
            impute="mid",
        ).to_frame()
        assert str(result["ADT"][2]) == "2014-06-15"

    def test_null_input(self, dtc_frame):
        result = dtc_frame.adam.date("ADT", source="AESTDTC").to_frame()
        assert result["ADT"][4] is None

    def test_none_imputation_returns_null(self, dtc_frame):
        result = dtc_frame.adam.date("ADT", source="AESTDTC", impute="none").to_frame()
        # YYYY-MM with impute="none" → null
        assert result["ADT"][1] is None
        # Complete date still parses
        assert str(result["ADT"][0]) == "2014-07-15"

    def test_dtf_flag_generated(self, dtc_frame):
        result = dtc_frame.adam.date("ADT", source="AESTDTC", flag=True).to_frame()
        assert "ADTF" in result.columns
        assert result["ADTF"][0] is None  # complete → null
        assert result["ADTF"][1] == "D"  # YYYY-MM → day imputed
        assert result["ADTF"][2] == "M"  # YYYY → month imputed
        assert result["ADTF"][4] is None  # null input → null flag

    def test_strips_time_from_datetime_string(self, dtc_frame):
        result = dtc_frame.adam.date("ADT", source="AESTDTC").to_frame()
        # YYYY-MM-DDTHH:MM:SS → should still produce correct Date
        assert str(result["ADT"][3]) == "2014-07-15"


# ------------------------------------------------------------------ #
# derive_dtm tests                                                     #
# ------------------------------------------------------------------ #


class TestDeriveDtm:
    def test_complete_datetime(self):
        df = pl.DataFrame({"DTC": ["2014-07-15T08:30:00"]})
        result = df.adam.date("ADTM", source="DTC").to_frame()
        assert result["ADTM"].dtype.is_(pl.Datetime) or str(result["ADTM"].dtype).startswith(
            "Datetime"
        )
        dtm = result["ADTM"][0]
        assert dtm.hour == 8
        assert dtm.minute == 30

    def test_date_only_time_imputed_first(self):
        df = pl.DataFrame({"DTC": ["2014-07-15"]})
        result = df.adam.date("ADTM", source="DTC", impute_time="first").to_frame()
        dtm = result["ADTM"][0]
        assert dtm.hour == 0
        assert dtm.minute == 0

    def test_date_only_time_imputed_last(self):
        df = pl.DataFrame({"DTC": ["2014-07-15"]})
        result = df.adam.date("ADTM", source="DTC", impute_time="last").to_frame()
        dtm = result["ADTM"][0]
        assert dtm.hour == 23
        assert dtm.minute == 59
        assert dtm.second == 59

    def test_date_only_time_imputed_mid(self):
        df = pl.DataFrame({"DTC": ["2014-07-15"]})
        result = df.adam.date("ADTM", source="DTC", impute_time="mid").to_frame()
        dtm = result["ADTM"][0]
        assert dtm.hour == 12

    def test_tmf_flag_generated(self):
        df = pl.DataFrame({"DTC": ["2014-07-15T08:30:00", "2014-07-15", None]})
        result = df.adam.date("ADTM", source="DTC", flag=True).to_frame()
        assert "ATMF" in result.columns
        assert result["ATMF"][0] is None  # complete datetime → null
        assert result["ATMF"][1] == "H"  # no time → hours imputed
        assert result["ATMF"][2] is None  # null → null

    def test_null_input(self):
        df = pl.DataFrame({"DTC": pl.Series([None], dtype=pl.String)})
        result = df.adam.date("ADTM", source="DTC").to_frame()
        assert result["ADTM"][0] is None


# ------------------------------------------------------------------ #
# format_iso tests                                                     #
# ------------------------------------------------------------------ #


class TestFormatIso:
    def test_date_to_iso(self):
        df = pl.DataFrame({"DTC": ["2014-07-15"]})
        result = (
            df.adam.date("ADT", source="DTC")
            .derivation("ADTC", expression='pl.col("ADT").dt.to_string("%Y-%m-%d")')
            .to_frame()
        )
        assert result["ADTC"][0] == "2014-07-15"
        assert result["ADTC"].dtype == pl.String

    def test_datetime_to_iso(self):
        df = pl.DataFrame({"DTC": ["2014-07-15T08:30:00"]})
        result = (
            df.adam.date("ADTM", source="DTC")
            .derivation("ADTMC", expression='pl.col("ADTM").dt.to_string("%Y-%m-%dT%H:%M:%S")')
            .to_frame()
        )
        assert result["ADTMC"][0] == "2014-07-15T08:30:00"
        assert result["ADTMC"].dtype == pl.String


# ------------------------------------------------------------------ #
# on_treatment open_ended tests                                        #
# ------------------------------------------------------------------ #


class TestOnTreatmentOpenEnded:
    def test_null_trtedt_open_ended_true(self):
        df = pl.DataFrame(
            {
                "ADT": ["2024-01-15"],
                "TRTSDT": ["2024-01-10"],
                "TRTEDT": [None],
            }
        )
        result = df.adam.on_treatment(
            "ONTRTFL",
            adt="ADT",
            trtsdt="TRTSDT",
            trtedt="TRTEDT",
            open_ended=True,
        ).to_frame()
        assert result["ONTRTFL"][0] == "Y"

    def test_null_trtedt_open_ended_false(self):
        df = pl.DataFrame(
            {
                "ADT": ["2024-01-15"],
                "TRTSDT": ["2024-01-10"],
                "TRTEDT": [None],
            }
        )
        result = df.adam.on_treatment(
            "ONTRTFL",
            adt="ADT",
            trtsdt="TRTSDT",
            trtedt="TRTEDT",
            open_ended=False,
        ).to_frame()
        assert result["ONTRTFL"][0] is None


# ------------------------------------------------------------------ #
# flag false_value tests (formerly eligibility_flag)                    #
# ------------------------------------------------------------------ #


class TestFlagFalseValue:
    def test_yn_convention(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S02"],
                "EXDOSE": [54, 0],
            }
        )
        result = df.adam.adsl.flag(
            "SAFFL", criteria='pl.col("EXDOSE") > 0', false_value="N"
        ).to_frame()
        assert result["SAFFL"][0] == "Y"
        assert result["SAFFL"][1] == "N"

    def test_default_y_null(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S02"],
                "EXDOSE": [54, 0],
            }
        )
        result = df.adam.adsl.flag("SAFFL", criteria='pl.col("EXDOSE") > 0').to_frame()
        assert result["SAFFL"][0] == "Y"
        assert result["SAFFL"][1] is None


# ------------------------------------------------------------------ #
# flag max/min mode tests (formerly worst_flag)                        #
# ------------------------------------------------------------------ #


class TestFlagMaxSeverity:
    def test_max_severity_flags_worst(self):
        """Use flag(criteria='max') with numeric-encoded severity."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01", "S01"],
                "AESEV": ["SEVERE", "SEVERE", "MILD"],
                "AESEVN": [3, 3, 1],
                "AEBODSYS": ["Nervous", "Nervous", "Nervous"],
            }
        )
        result = df.adam.occds.flag(
            "AOCSFL",
            criteria="max",
            value_col="AESEVN",
            groups=["USUBJID"],
        ).to_frame()
        flags = result["AOCSFL"].to_list()
        # Both rows with AESEVN=3 are tied max → both flagged
        assert flags.count("Y") == 2
        assert flags[2] is None  # MILD not flagged

    def test_max_with_expression_filter(self):
        """Flag worst severity using expression-based criteria."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01", "S01"],
                "AESEV": ["SEVERE", "SEVERE", "MILD"],
                "AESEVN": [3, 3, 1],
            }
        )
        result = df.adam.occds.flag(
            "AOCSFL",
            criteria="max",
            value_col="AESEVN",
            groups=["USUBJID"],
        ).to_frame()
        # Both SEVERE rows (max AESEVN=3) flagged
        assert result["AOCSFL"].to_list().count("Y") == 2


# ------------------------------------------------------------------ #
# flag where-clause pre-filter tests                                   #
# ------------------------------------------------------------------ #


class TestFlagWherePreFilter:
    def test_last_within_where_subset(self):
        """Ranking should be scoped to rows matching where clause."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01", "S01", "S01"],
                "PARAMCD": ["BP", "BP", "BP", "BP"],
                "ADT": ["2024-01-01", "2024-01-15", "2024-01-20", "2024-02-01"],
                "ONTRTFL": ["Y", "Y", None, None],
            }
        )
        result = df.adam.flag(
            "LSTOBSFL",
            criteria="last",
            order_by="ADT",
            groups=["USUBJID", "PARAMCD"],
            where=pl.col("ONTRTFL") == "Y",
        ).to_frame()
        flags = result["LSTOBSFL"].to_list()
        # Last among on-treatment rows (ONTRTFL="Y") is 2024-01-15
        assert flags[0] is None
        assert flags[1] == "Y"
        assert flags[2] is None
        assert flags[3] is None


# ------------------------------------------------------------------ #
# age_from_dates tests                                                 #
# ------------------------------------------------------------------ #


class TestAgeFromDates:
    def test_basic_age_calculation(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S01"],
                "BRTHDT": ["1950-06-15"],
                "RANDDT": ["2014-01-15"],
            }
        ).with_columns(
            pl.col("BRTHDT").str.to_date("%Y-%m-%d"),
            pl.col("RANDDT").str.to_date("%Y-%m-%d"),
        )
        result = df.adam.adsl.age_from_dates(
            "AAGE", birth_date="BRTHDT", reference_date="RANDDT"
        ).to_frame()
        age = result["AAGE"][0]
        assert 63.0 <= age <= 64.0  # approximately 63.6

    def test_null_date_returns_null(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S01"],
                "BRTHDT": [None],
                "RANDDT": ["2014-01-15"],
            }
        ).with_columns(
            pl.col("BRTHDT").cast(pl.Date),
            pl.col("RANDDT").str.to_date("%Y-%m-%d"),
        )
        result = df.adam.adsl.age_from_dates(
            "AAGE", birth_date="BRTHDT", reference_date="RANDDT"
        ).to_frame()
        assert result["AAGE"][0] is None
