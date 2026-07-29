"""Unit tests for PinMixin — core pin/repin/FK/introspection behaviour."""

import warnings

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ── Fixtures ────────────────────────────────────────────────────────────── #


@pytest.fixture
def simple_ae():
    return pl.from_repr("""\
┌────────────────┬──────────┬───────────────┐
│ patient_number ┆ ae_term  ┆ ae_start_date │
│ ---            ┆ ---      ┆ ---           │
│ str            ┆ str      ┆ str           │
╞════════════════╪══════════╪═══════════════╡
│ 01-701-1015    ┆ HEADACHE ┆ 2014-01-10    │
│ 01-701-1023    ┆ NAUSEA   ┆ 2014-02-15    │
│ 01-701-1028    ┆ RASH     ┆ 2014-03-20    │
└────────────────┴──────────┴───────────────┘
""")


@pytest.fixture
def dm_ref():
    return pl.from_repr("""\
┌─────────────┬────────────┬────────┐
│ USUBJID     ┆ RFSTDTC    ┆ ARMCD  │
│ ---         ┆ ---        ┆ ---    │
│ str         ┆ str        ┆ str    │
╞═════════════╪════════════╪════════╡
│ 01-701-1015 ┆ 2014-01-02 ┆ PBO    │
│ 01-701-1023 ┆ 2014-01-03 ┆ XAN_LO │
│ 01-701-1028 ┆ 2014-01-04 ┆ XAN_HI │
└─────────────┴────────────┴────────┘
""")


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
        tv_df = pl.from_repr("""\
┌──────────┬───────────┐
│ VISITNUM ┆ VISIT     │
│ ---      ┆ ---       │
│ i64      ┆ str       │
╞══════════╪═══════════╡
│ 1        ┆ SCREENING │
│ 2        ┆ WEEK 1    │
└──────────┴───────────┘
""")
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


class TestKeywordPins:
    """pin(DM=dm_df, TV=tv_df) — several datasets, one call."""

    def test_keyword_form_pins_several(self, simple_ae, dm_ref):
        tv_df = pl.from_repr("""\
┌──────────┬───────────┐
│ VISITNUM ┆ VISIT     │
│ ---      ┆ ---       │
│ i64      ┆ str       │
╞══════════╪═══════════╡
│ 1        ┆ SCREENING │
└──────────┴───────────┘
""")
        ns = simple_ae.sdtm.pin(DM=dm_ref, TV=tv_df)
        assert set(ns.pins().keys()) == {"DM", "TV"}

    def test_keyword_names_are_uppercased(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin(dm=dm_ref)
        assert "DM" in ns.pins()

    def test_join_on_applies_to_every_pin_in_the_call(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin(DM=dm_ref, ADSL=dm_ref, join_on=["USUBJID", "ARMCD"])
        assert ns.pins()["DM"]["join_on"] == ["USUBJID", "ARMCD"]
        assert ns.pins()["ADSL"]["join_on"] == ["USUBJID", "ARMCD"]

    def test_positional_and_keyword_mix(self, simple_ae, dm_ref):
        tv_df = pl.from_repr("""\
┌──────────┐
│ VISITNUM │
│ ---      │
│ i64      │
╞══════════╡
│ 1        │
└──────────┘
""")
        ns = simple_ae.sdtm.pin("DM", dm_ref, TV=tv_df)
        assert set(ns.pins().keys()) == {"DM", "TV"}

    def test_keyword_duplicate_still_warns(self, simple_ae, dm_ref):
        ns = simple_ae.sdtm.pin("DM", dm_ref)
        with pytest.warns(UserWarning, match="Pin 'DM' replaced"):
            ns.pin(DM=dm_ref)

    def test_empty_call_raises(self, simple_ae):
        with pytest.raises(Exception, match="at least one pin"):
            simple_ae.sdtm.pin()

    def test_domain_without_frame_raises(self, simple_ae):
        with pytest.raises(Exception, match="both a domain name and a DataFrame"):
            simple_ae.sdtm.pin("DM")

    def test_no_keyword_name_is_reserved(self, simple_ae, dm_ref):
        """domain/df are positional-only, so even those spellings pin datasets."""
        ns = simple_ae.sdtm.pin(domain=dm_ref, df=dm_ref)
        assert {"DOMAIN", "DF"} <= set(ns.pins().keys())

    def test_non_frame_value_raises(self, simple_ae):
        with pytest.raises(Exception, match="expected a DataFrame or LazyFrame, got str"):
            simple_ae.sdtm.pin(DM="not a frame")

    def test_old_style_keyword_call_errors_loudly(self, simple_ae, dm_ref):
        """pin(domain="DM", df=...) is not silently mispinned — the str value errors."""
        with pytest.raises(Exception, match="expected a DataFrame or LazyFrame"):
            simple_ae.sdtm.pin(domain="DM", df=dm_ref)

    def test_keyword_pins_feed_cross_domain_verbs(self, simple_ae, dm_ref):
        """A keyword pin is a real pin — study_day resolves it."""
        result = (
            simple_ae.sdtm.assign("DOMAIN", value="AE")
            .assign("USUBJID", source="patient_number")
            .pin(DM=dm_ref)
            .study_day("AESTDY", date_col="ae_start_date")
            .to_frame()
        )
        assert "AESTDY" in result.columns


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
        bad_df = pl.from_repr("""\
┌────────────────┐
│ patient_number │
│ ---            │
│ str            │
╞════════════════╡
│ 01-701-1015    │
│ UNKNOWN_SUBJ   │
└────────────────┘
""")
        ns = bad_df.sdtm.pin("DM", dm_ref).assign("USUBJID", source="patient_number")
        with pytest.warns(UserWarning, match="FK check"):
            orphans = ns._check_fk("USUBJID", pin="DM")
        assert "UNKNOWN_SUBJ" in orphans

    def test_fk_check_error_mode(self, dm_ref):
        bad_df = pl.from_repr("""\
┌────────────────┐
│ patient_number │
│ ---            │
│ str            │
╞════════════════╡
│ UNKNOWN_SUBJ   │
└────────────────┘
""")
        ns = (
            bad_df.sdtm.pin("DM", dm_ref)
            .fk_policy("error")
            .assign("DOMAIN", value="AE")
            .assign("SUBJID", source="patient_number")
        )
        with pytest.raises(ValueError, match="FK check"):
            ns._check_fk("SUBJID", pin="DM", ref_col="USUBJID")

    def test_fk_check_off(self, dm_ref):
        bad_df = pl.from_repr("""\
┌────────────────┐
│ patient_number │
│ ---            │
│ str            │
╞════════════════╡
│ UNKNOWN_SUBJ   │
└────────────────┘
""")
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
