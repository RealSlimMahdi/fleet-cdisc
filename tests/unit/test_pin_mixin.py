"""Unit tests for PinMixin — core pin/repin/FK/introspection behaviour."""

import warnings

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ── Fixtures ────────────────────────────────────────────────────────────── #


@pytest.fixture
def simple_ae():
    return pl.DataFrame(
        {
            "patient_number": ["01-701-1015", "01-701-1023", "01-701-1028"],
            "ae_term": ["HEADACHE", "NAUSEA", "RASH"],
            "ae_start_date": ["2014-01-10", "2014-02-15", "2014-03-20"],
        }
    )


@pytest.fixture
def dm_ref():
    return pl.DataFrame(
        {
            "USUBJID": ["01-701-1015", "01-701-1023", "01-701-1028"],
            "RFSTDTC": ["2014-01-02", "2014-01-03", "2014-01-04"],
            "ARMCD": ["PBO", "XAN_LO", "XAN_HI"],
        }
    )


# ── Pin basics ──────────────────────────────────────────────────────────── #


class TestPin:
    def test_pin_attaches_domain(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref)
        assert "DM" in ns.pins()

    def test_pin_stores_join_key(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref, join_on="USUBJID")
        assert ns.pins()["DM"]["join_on"] == ["USUBJID"]

    def test_pin_compound_key(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref, join_on=["USUBJID", "ARMCD"])
        assert ns.pins()["DM"]["join_on"] == ["USUBJID", "ARMCD"]

    def test_pin_case_insensitive(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("dm", dm_ref)
        assert "DM" in ns.pins()

    def test_pin_multiple_domains(self, simple_ae, dm_ref):
        tv_df = pl.DataFrame({"VISITNUM": [1, 2], "VISIT": ["SCREENING", "WEEK 1"]})
        ns = simple_ae.sdtm.pin("DM", dm_ref).pin("TV", tv_df, join_on="VISITNUM")
        assert set(ns.pins().keys()) == {"DM", "TV"}

    def test_pin_returns_new_instance(self, simple_ae, dm_ref):
        ns1 = simple_ae.sdtm
        ns2 = ns1.pin("DM", dm_ref)
        assert ns1 is not ns2
        assert "DM" not in ns1.pins()

    def test_pin_survives_chain(self, simple_ae, dm_ref):
        ns = (
            simple_ae.sdtm.pin("DM", dm_ref)
            .assign("DOMAIN", value="AE")
            .assign("USUBJID", source="patient_number")
        )
        assert "DM" in ns.pins()


# ── Duplicate pin guard ─────────────────────────────────────────────────── #


class TestDuplicatePin:
    def test_duplicate_pin_warns(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref)
        with pytest.warns(UserWarning, match="Pin 'DM' replaced"):
            ns.pin("DM", dm_ref)

    def test_repin_no_warning(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            ns.repin("DM", dm_ref)  # Should not raise


# ── _require_pin ─────────────────────────────────────────────────────── #


class TestRequirePin:
    def test_require_pin_raises_without_pin(self, simple_ae):
        ns = simple_ae.sdtm
        with pytest.raises(LookupError, match="study_day.*requires.*pinned.*DM"):
            ns._require_pin("DM", "study_day")

    def test_require_pin_returns_df(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref)
        result = ns._require_pin("DM", "study_day")
        assert isinstance(result, pl.DataFrame)
        assert result.shape == dm_ref.shape

    def test_require_pin_surgical_columns(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref)
        result = ns._require_pin("DM", "study_day", columns=["RFSTDTC"])
        assert "RFSTDTC" in result.columns
        assert "USUBJID" in result.columns  # join key included
        assert "ARMCD" not in result.columns  # not requested


# ── FK checks ────────────────────────────────────────────────────────── #


class TestFKCheck:
    def test_fk_check_clean(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref).assign("USUBJID", source="patient_number")
        orphans = ns._check_fk("USUBJID", pin="DM")
        assert orphans == set()

    def test_fk_check_orphans_warn(self, dm_ref):
        bad_df = pl.DataFrame({"patient_number": ["01-701-1015", "UNKNOWN_SUBJ"]})
        ns = bad_df.sdtm.pin("DM", dm_ref).assign("USUBJID", source="patient_number")
        with pytest.warns(UserWarning, match="FK check"):
            orphans = ns._check_fk("USUBJID", pin="DM")
        assert "UNKNOWN_SUBJ" in orphans

    def test_fk_check_error_mode(self, dm_ref):
        bad_df = pl.DataFrame({"patient_number": ["UNKNOWN_SUBJ"]})
        ns = (
            bad_df.sdtm.pin("DM", dm_ref)
            .fk_policy("error")
            .assign("DOMAIN", value="AE")
            .assign("SUBJID", source="patient_number")
        )
        with pytest.raises(ValueError, match="FK check"):
            ns._check_fk("SUBJID", pin="DM", ref_col="USUBJID")

    def test_fk_check_off(self, dm_ref):
        bad_df = pl.DataFrame({"patient_number": ["UNKNOWN_SUBJ"]})
        ns = (
            bad_df.sdtm.pin("DM", dm_ref)
            .fk_policy("off")
            .assign("USUBJID", source="patient_number")
        )
        orphans = ns._check_fk("USUBJID", pin="DM")
        assert orphans == set()

    def test_fk_policy_invalid(self, simple_ae):
        with pytest.raises(ValueError, match="'warn', 'error', or 'off'"):
            simple_ae.sdtm.fk_policy("invalid")


# ── .pins() introspection ───────────────────────────────────────────── #


class TestPinsIntrospection:
    def test_empty_pins(self, simple_ae):
        assert simple_ae.sdtm.pins() == {}

    def test_pins_structure(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref)
        info = ns.pins()["DM"]
        assert "df" in info
        assert "join_on" in info
        assert info["join_on"] == ["USUBJID"]
