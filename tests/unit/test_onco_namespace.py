"""Unit tests for the Oncology Polars namespace extension (df.adam.onco)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ---------------------------------------------------------------------------
# Reference RECIST mapping — mirrors admiralonco aval_resp() exactly
# ---------------------------------------------------------------------------
_RECIST_MAPPING = [
    ("CR", 1.0),
    ("PR", 2.0),
    ("SD", 3.0),
    ("NON-CR/NON-PD", 4.0),
    ("PD", 5.0),
    ("NE", 6.0),
    ("MISSING", 7.0),
    ("UNKNOWN", None),
]


@pytest.fixture
def onco_frame():
    """Minimal frame for shared verb tests on the onco namespace."""
    return pl.DataFrame(
        {
            "USUBJID": ["01-001", "01-002", "01-003"],
            "RSSTRESC": ["CR", "PR", "PD"],
            "AGE": [55, 68, 42],
        }
    )


class TestBaseVerbs:
    """Shared verbs inherited from SharedADaMVerbsMixin."""

    def test_source(self, onco_frame):
        result = onco_frame.adam.onco.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assigned(self, onco_frame):
        result = onco_frame.adam.onco.assigned("STUDYID", value="ONC01").to_frame()
        assert result["STUDYID"].to_list() == ["ONC01"] * 3

    def test_derivation(self, onco_frame):
        result = onco_frame.adam.onco.derivation("AGE2", expression='pl.col("AGE") * 2').to_frame()
        assert result["AGE2"].to_list() == [110, 136, 84]

    def test_recode(self, onco_frame):
        result = onco_frame.adam.onco.recode(
            "RESP",
            source="RSSTRESC",
            recode_map={"CR": "Complete", "PR": "Partial"},
            default="Other",
        ).to_frame()
        assert result["RESP"].to_list() == ["Complete", "Partial", "Other"]

    def test_rename(self, onco_frame):
        result = onco_frame.adam.onco.rename("SUBJ", source="USUBJID").to_frame()
        assert result["SUBJ"].to_list() == onco_frame["USUBJID"].to_list()

    def test_condderivation(self, onco_frame):
        result = onco_frame.adam.onco.condderivation(
            "AGEGR",
            conditions=[{"condition": 'pl.col("AGE") < 60', "value": "<60"}],
            else_value=">=60",
        ).to_frame()
        assert result["AGEGR"].to_list() == ["<60", ">=60", "<60"]

    def test_whereclauses(self, onco_frame):
        result = onco_frame.adam.onco.whereclauses(where='pl.col("RSSTRESC") == "CR"').to_frame()
        assert result.height == 1


class TestAvalResp:
    """
    Test 1: RECIST text → numeric mapping (all 7 categories + unknown + null).

    Mirrors admiralonco test-derive_param_bor pattern of testing every
    response category individually via parametrize, then the full vector.
    """

    @pytest.mark.parametrize("response,expected_aval", _RECIST_MAPPING)
    def test_each_recist_category(self, response, expected_aval):
        df = pl.DataFrame({"OVRLRESP": [response]})
        aval = df.adam.onco.aval_resp("AVAL", source="OVRLRESP").to_frame()["AVAL"][0]
        if expected_aval is None:
            assert aval is None
        else:
            assert aval == pytest.approx(expected_aval)

    def test_full_vector_at_once(self):
        """All 8 values in a single call — verifies correct row-wise behaviour."""
        responses = [r for r, _ in _RECIST_MAPPING]
        expected_aval = [e for _, e in _RECIST_MAPPING]
        df = pl.DataFrame({"OVRLRESP": responses})
        result = df.adam.onco.aval_resp("AVAL", source="OVRLRESP").to_frame()
        assert result["AVAL"].to_list() == expected_aval

    def test_null_input_maps_to_null(self):
        df = pl.DataFrame({"R": [None]}, schema={"R": pl.Utf8})
        result = df.adam.onco.aval_resp("N", source="R").to_frame()
        assert result["N"][0] is None

    def test_non_derived_columns_preserved(self):
        """Input columns not named AVAL must survive the derivation."""
        df = pl.DataFrame({"USUBJID": ["01-701-1015"], "OVRLRESP": ["CR"]})
        result = df.adam.onco.aval_resp("AVAL", source="OVRLRESP").to_frame()
        assert "USUBJID" in result.columns
        assert result["USUBJID"][0] == "01-701-1015"


class TestTumorResponseFlag:
    """Test 2: Flagging responders."""

    def test_cr_pr_flagged_by_default(self):
        df = pl.DataFrame({"RESP": ["CR", "PR", "SD", "PD"]})
        result = df.adam.onco.tumor_response_flag("RSPFL", source="RESP").to_frame()
        assert result["RSPFL"].to_list() == ["Y", "Y", None, None]

    def test_custom_responses(self):
        df = pl.DataFrame({"RESP": ["CR", "PR", "SD", "PD"]})
        result = df.adam.onco.tumor_response_flag(
            "CBFL", source="RESP", responses=["CR", "PR", "SD"]
        ).to_frame()
        assert result["CBFL"].to_list() == ["Y", "Y", "Y", None]

    def test_pd_never_flagged(self):
        """PD must never be a responder under default settings."""
        df = pl.DataFrame({"RESP": ["PD", "NE", "MISSING"]})
        result = df.adam.onco.tumor_response_flag("RSPFL", source="RESP").to_frame()
        assert all(v is None for v in result["RSPFL"].to_list())

    def test_custom_flag_value(self):
        df = pl.DataFrame({"RESP": ["CR"]})
        result = df.adam.onco.tumor_response_flag("RSPFL", source="RESP", flag_value="1").to_frame()
        assert result["RSPFL"][0] == "1"


class TestBestOverallResponse:
    """
    Test 3: Best Overall Response per subject group.

    Admiral derives BOR as the response with the lowest numeric rank (most
    favourable).  Multi-subject cases are crucial: each subject must receive
    its own BOR independently.
    """

    def test_best_response_is_pr(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01", "S01"],
                "OVRLRESP": ["SD", "PR", "PD"],
            }
        )
        result = df.adam.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        # PR is rank 2, SD=3, PD=5 → best is PR
        assert all(r == "PR" for r in result["BOR"].to_list())

    def test_no_response_gives_ne(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S02", "S02"],
                "OVRLRESP": ["NE", "NE"],
            }
        )
        result = df.adam.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        assert all(r == "NE" for r in result["BOR"].to_list())

    def test_multi_subject_independent_bor(self):
        """BOR must be computed independently per subject — core admiral pattern."""
        df = pl.DataFrame(
            {
                "STUDYID": ["CDISCPILOT01"] * 4,
                "USUBJID": ["01-701-1015", "01-701-1015", "01-701-1023", "01-701-1023"],
                "OVRLRESP": ["SD", "CR", "PD", "PR"],
            }
        )
        result = df.adam.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        bor = dict(zip(result["USUBJID"].to_list(), result["BOR"].to_list()))
        assert bor["01-701-1015"] == "CR"  # CR beats SD
        assert bor["01-701-1023"] == "PR"  # PR beats PD

    def test_subject_with_only_pd(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S03", "S03"],
                "OVRLRESP": ["PD", "PD"],
            }
        )
        result = df.adam.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        assert all(r == "PD" for r in result["BOR"].to_list())


class TestFilterPD:
    """
    Test 4: filter_pd — keep records up to and including first PD per group.

    Mirrors admiralonco test-filter_pd.R which tests:
      - subjects with PD (rows after PD dropped)
      - subjects without PD (all rows retained)
      - multiple subjects in one call (independent per subject)
    """

    def test_records_after_pd_dropped(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01", "S01", "S01"],
                "ADT": ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"],
                "OVRLRESP": ["SD", "PD", "PD", "NE"],
            }
        )
        result = df.adam.onco.filter_pd(
            response_col="OVRLRESP", date_col="ADT", groups=["USUBJID"]
        ).to_frame()
        # Only rows up to and including first PD (2024-02-01)
        assert result.height == 2
        assert result["ADT"].to_list() == ["2024-01-01", "2024-02-01"]

    def test_no_pd_retains_all(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S02", "S02"],
                "ADT": ["2024-01-01", "2024-02-01"],
                "OVRLRESP": ["SD", "PR"],
            }
        )
        result = df.adam.onco.filter_pd(
            response_col="OVRLRESP", date_col="ADT", groups=["USUBJID"]
        ).to_frame()
        assert result.height == 2

    def test_multi_subject_with_realistic_ids(self):
        """
        Multi-subject filter_pd — admiral's primary pattern.

        01-701-1015: PD at 2024-02-01 → only 2 rows kept
        01-701-1023: no PD            → all 3 rows kept
        """
        df = pl.DataFrame(
            {
                "STUDYID": ["CDISCPILOT01"] * 5,
                "USUBJID": [
                    "01-701-1015",
                    "01-701-1015",
                    "01-701-1015",
                    "01-701-1023",
                    "01-701-1023",
                ],
                "ADT": [
                    "2024-01-01",
                    "2024-02-01",
                    "2024-03-01",
                    "2024-01-01",
                    "2024-02-01",
                ],
                "OVRLRESP": ["CR", "PD", "NE", "SD", "PR"],
            }
        )
        result = df.adam.onco.filter_pd(
            response_col="OVRLRESP", date_col="ADT", groups=["USUBJID"]
        ).to_frame()
        subj1015 = result.filter(pl.col("USUBJID") == "01-701-1015")
        subj1023 = result.filter(pl.col("USUBJID") == "01-701-1023")
        assert subj1015.height == 2  # row at PD date included, post-PD dropped
        assert subj1023.height == 2  # no PD → all retained


class TestConfirmedResponseFlag:
    """
    Test 5: confirmed_response_flag — response confirmed ≥ N days later.

    Admiral (test-derive_param_confirmed_resp.R) tests:
      - response confirmed → "Y"
      - gap too short → null
      - null response → null
    """

    def test_confirmed_with_sufficient_gap(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["01-701-1015", "01-701-1015"],
                "OVRLRESP": ["CR", "CR"],
                "ADT": ["2024-01-01", "2024-03-15"],  # 74 days apart
            }
        )
        result = df.adam.onco.confirmed_response_flag(
            "CNFFL", source="OVRLRESP", date_col="ADT", confirmation_days=28, groups=["USUBJID"]
        ).to_frame()
        # At least one "Y" in the group (≥28-day gap exists)
        assert "Y" in result["CNFFL"].to_list()

    def test_gap_too_short_gives_null(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S02", "S02"],
                "OVRLRESP": ["PR", "PR"],
                "ADT": ["2024-01-01", "2024-01-20"],  # only 19 days
            }
        )
        result = df.adam.onco.confirmed_response_flag(
            "CNFFL", source="OVRLRESP", date_col="ADT", confirmation_days=28, groups=["USUBJID"]
        ).to_frame()
        assert all(v is None for v in result["CNFFL"].to_list())

    def test_no_matching_response_gives_null(self):
        """PD records should not be considered for confirmation."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S03", "S03"],
                "OVRLRESP": ["PD", "PD"],
                "ADT": ["2024-01-01", "2024-03-01"],
            }
        )
        result = df.adam.onco.confirmed_response_flag(
            "CNFFL", source="OVRLRESP", date_col="ADT", groups=["USUBJID"]
        ).to_frame()
        assert all(v is None for v in result["CNFFL"].to_list())


class TestChaining:
    """Test 6: multi-verb chaining produces all derived columns."""

    def test_full_onco_chain(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01", "S02"],
                "OVRLRESP": ["CR", "PD", "PR"],
            }
        )
        result = (
            df.adam.onco.aval_resp("AVAL", source="OVRLRESP")
            .tumor_response_flag("RSPFL", source="OVRLRESP")
            .best_overall_response("BOR", source="OVRLRESP", groups=["USUBJID"])
            .to_frame()
        )
        assert "AVAL" in result.columns
        assert "RSPFL" in result.columns
        assert "BOR" in result.columns
        # Original columns must still be present
        assert "USUBJID" in result.columns
        assert "OVRLRESP" in result.columns


# ------------------------------------------------------------------ #
# Phase 5 hardening: progression ambiguity and null responses          #
# ------------------------------------------------------------------ #


class TestOncoProgressionAmbiguity:
    """Edge cases for progression timing and response ordering."""

    def test_all_ne_responses_bor_is_ne(self):
        """Subject with only NE responses should get BOR = NE."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01", "S01"],
                "OVRLRESP": ["NE", "NE", "NE"],
                "ADT": ["2020-01-01", "2020-02-01", "2020-03-01"],
            }
        )
        result = df.adam.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        assert all(v == "NE" for v in result["BOR"].to_list())

    def test_null_response_excluded_from_bor(self):
        """Null responses should not count toward BOR."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01", "S01"],
                "OVRLRESP": ["CR", None, "SD"],
                "ADT": ["2020-01-01", "2020-02-01", "2020-03-01"],
            }
        )
        result = df.adam.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        # BOR should be CR (best non-null response)
        bor_vals = result["BOR"].drop_nulls().unique().to_list()
        assert "CR" in bor_vals

    def test_pd_after_cr_still_yields_cr_bor(self):
        """CR followed by PD — BOR should still be CR."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01"],
                "OVRLRESP": ["CR", "PD"],
                "ADT": ["2020-01-01", "2020-02-01"],
            }
        )
        result = df.adam.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        bor_vals = result["BOR"].unique().to_list()
        assert "CR" in bor_vals

    def test_aval_resp_unknown_maps_to_none(self):
        """UNKNOWN response should map to None in AVAL."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S01"],
                "RSSTRESC": ["UNKNOWN"],
            }
        )
        result = df.adam.onco.aval_resp("AVAL", source="RSSTRESC").to_frame()
        assert result["AVAL"][0] is None

    def test_tumor_response_flag_with_nulls(self):
        """Null responses should not be flagged as responders."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S01", "S02", "S03"],
                "RSSTRESC": ["CR", None, "PD"],
            }
        )
        result = df.adam.onco.tumor_response_flag("RSPFL", source="RSSTRESC").to_frame()
        assert result["RSPFL"][1] is None or result["RSPFL"][1] != "Y"
