"""Tests for the nsv() verb and export_supp() terminal."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def dm_raw_with_flags() -> pl.DataFrame:
    """3-row DM with population flag columns suitable for NSV derivation."""
    return pl.from_repr("""\
┌──────────────┬────────┬─────────────┬─────┬─────────────┬──────────┬───────────────┐
│ STUDYID      ┆ DOMAIN ┆ USUBJID     ┆ AGE ┆ safety_flag ┆ itt_flag ┆ efficacy_flag │
│ ---          ┆ ---    ┆ ---         ┆ --- ┆ ---         ┆ ---      ┆ ---           │
│ str          ┆ str    ┆ str         ┆ i64 ┆ str         ┆ str      ┆ str           │
╞══════════════╪════════╪═════════════╪═════╪═════════════╪══════════╪═══════════════╡
│ CDISCPILOT01 ┆ DM     ┆ 01-701-1015 ┆ 63  ┆ Y           ┆ Y        ┆ Y             │
│ CDISCPILOT01 ┆ DM     ┆ 01-701-1023 ┆ 64  ┆ Y           ┆ Y        ┆ null          │
│ CDISCPILOT01 ┆ DM     ┆ 01-701-1028 ┆ 71  ┆ Y           ┆ null     ┆ Y             │
└──────────────┴────────┴─────────────┴─────┴─────────────┴──────────┴───────────────┘
""")


@pytest.fixture
def ae_raw_with_seq() -> pl.DataFrame:
    """AE domain with AESEQ to test IDVAR handling."""
    return pl.from_repr("""\
┌──────────────┬────────┬─────────────┬───────┬──────────┐
│ STUDYID      ┆ DOMAIN ┆ USUBJID     ┆ AESEQ ┆ ae_toxgr │
│ ---          ┆ ---    ┆ ---         ┆ ---   ┆ ---      │
│ str          ┆ str    ┆ str         ┆ i64   ┆ str      │
╞══════════════╪════════╪═════════════╪═══════╪══════════╡
│ CDISCPILOT01 ┆ AE     ┆ 01-701-1015 ┆ 1     ┆ 1        │
│ CDISCPILOT01 ┆ AE     ┆ 01-701-1015 ┆ 2     ┆ 2        │
│ CDISCPILOT01 ┆ AE     ┆ 01-701-1023 ┆ 1     ┆ 3        │
│ CDISCPILOT01 ┆ AE     ┆ 01-701-1023 ┆ 2     ┆ 1        │
└──────────────┴────────┴─────────────┴───────┴──────────┘
""")


@pytest.fixture
def nsv_spec_yaml(tmp_path: Path) -> Path:
    """Temporary define.yaml with NSV variables."""
    content = dedent("""\
        study:
          id: TEST01

        datasets:
          - name: DM
            label: Demographics
            variables:
              - name: STUDYID
                label: Study Identifier
                type: text
                origin: Assigned
                derivation:
                  algorithm: assign
                  value: "TEST01"

              - name: DOMAIN
                label: Domain Abbreviation
                type: text
                origin: Assigned
                derivation:
                  algorithm: assign
                  value: "DM"

              - name: USUBJID
                label: Unique Subject Identifier
                type: text
                origin: Collected
                derivation:
                  algorithm: assign
                  source: patient_number

              - name: SAFETY
                label: Safety Population Flag
                type: text
                role: qualifier
                origin: Derived
                derivation:
                  algorithm: nsv
                  source: safety_flag

              - name: ITT
                label: Intent to Treat Population Flag
                type: text
                role: qualifier
                origin: Derived
                derivation:
                  algorithm: nsv
                  source: itt_flag
    """)
    spec_path = tmp_path / "define.yaml"
    spec_path.write_text(content)
    return spec_path


# ──────────────────────────────────────────────────────────────────────
# TestNSVChaining
# ──────────────────────────────────────────────────────────────────────


class TestNSVChaining:
    """nsv() returns SDTMNamespace and column appears in to_frame()."""

    def test_nsv_returns_namespace(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv(
            "SAFETY", source="safety_flag", label="Safety Population Flag"
        )
        assert hasattr(ns, "to_frame")

    def test_nsv_column_in_to_frame(self, dm_raw_with_flags):
        result = dm_raw_with_flags.sdtm.nsv(
            "SAFETY", source="safety_flag", label="Safety Population Flag"
        ).to_frame()
        assert "SAFETY" in result.columns

    def test_multiple_nsv_chained(self, dm_raw_with_flags):
        result = (
            dm_raw_with_flags.sdtm.nsv(
                "SAFETY", source="safety_flag", label="Safety Population Flag"
            )
            .nsv("ITT", source="itt_flag", label="Intent to Treat Population Flag")
            .to_frame()
        )
        assert "SAFETY" in result.columns
        assert "ITT" in result.columns

    def test_nsv_chains_with_other_verbs(self, dm_raw_with_flags):
        result = (
            dm_raw_with_flags.sdtm.assign("DOMAIN", value="DM")
            .assign("USUBJID", source="USUBJID")
            .nsv("SAFETY", source="safety_flag", label="Safety Population Flag")
            .to_frame()
        )
        assert "DOMAIN" in result.columns
        assert "SAFETY" in result.columns


# ──────────────────────────────────────────────────────────────────────
# TestNSVMetadataCapture
# ──────────────────────────────────────────────────────────────────────


class TestNSVMetadataCapture:
    """_nsv_meta accumulates across chained nsv() calls."""

    def test_single_nsv_meta(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv(
            "SAFETY", source="safety_flag", label="Safety Population Flag"
        )
        assert len(ns._nsv_meta) == 1
        assert ns._nsv_meta[0].target == "SAFETY"
        assert ns._nsv_meta[0].label == "Safety Population Flag"
        assert ns._nsv_meta[0].origin == "Derived"

    def test_multiple_nsv_meta(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag").nsv(
            "ITT", source="itt_flag", label="ITT Flag", origin="Collected"
        )
        assert len(ns._nsv_meta) == 2
        assert ns._nsv_meta[1].target == "ITT"
        assert ns._nsv_meta[1].origin == "Collected"

    def test_evaluator_captured(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv(
            "SAFETY", source="safety_flag", label="Safety Flag", evaluator="INVESTIGATOR"
        )
        assert ns._nsv_meta[0].evaluator == "INVESTIGATOR"


# ──────────────────────────────────────────────────────────────────────
# TestNSVImmutability
# ──────────────────────────────────────────────────────────────────────


class TestNSVImmutability:
    """Prior namespace's _nsv_meta is not mutated."""

    def test_original_unchanged(self, dm_raw_with_flags):
        ns1 = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        ns2 = ns1.nsv("ITT", source="itt_flag", label="ITT Flag")
        assert len(ns1._nsv_meta) == 1
        assert len(ns2._nsv_meta) == 2

    def test_base_namespace_empty(self, dm_raw_with_flags):
        base = dm_raw_with_flags.sdtm
        _ = base.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        assert len(base._nsv_meta) == 0


# ──────────────────────────────────────────────────────────────────────
# TestNSVWithSource
# ──────────────────────────────────────────────────────────────────────


class TestNSVWithSource:
    """Source-based nsv() derivation (like assign_no_ct)."""

    def test_values_from_source(self, dm_raw_with_flags):
        result = dm_raw_with_flags.sdtm.nsv(
            "SAFETY", source="safety_flag", label="Safety Flag"
        ).to_frame()
        assert result["SAFETY"].to_list() == ["Y", "Y", "Y"]

    def test_null_values_preserved(self, dm_raw_with_flags):
        result = dm_raw_with_flags.sdtm.nsv("ITT", source="itt_flag", label="ITT Flag").to_frame()
        assert result["ITT"].to_list() == ["Y", "Y", None]


# ──────────────────────────────────────────────────────────────────────
# TestNSVWithValue
# ──────────────────────────────────────────────────────────────────────


class TestNSVWithValue:
    """Value-based nsv() derivation (like hardcode_no_ct)."""

    def test_literal_broadcast(self, dm_raw_with_flags):
        result = dm_raw_with_flags.sdtm.nsv(
            "COMPLT16", value="Y", label="Completers of Week 16"
        ).to_frame()
        assert result["COMPLT16"].to_list() == ["Y", "Y", "Y"]

    def test_source_and_value_error(self, dm_raw_with_flags):
        with pytest.raises(ValueError, match="not both"):
            dm_raw_with_flags.sdtm.nsv(
                "SAFETY", source="safety_flag", value="Y", label="Safety Flag"
            )

    def test_neither_source_nor_value_error(self, dm_raw_with_flags):
        with pytest.raises(ValueError, match="requires either"):
            dm_raw_with_flags.sdtm.nsv("SAFETY", label="Safety Flag")


# ──────────────────────────────────────────────────────────────────────
# TestExportSuppStructure
# ──────────────────────────────────────────────────────────────────────


class TestExportSuppStructure:
    """export_supp() output has the correct 10-column SUPPQUAL schema."""

    def test_column_names(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        supp = ns.export_supp()
        assert supp.columns == [
            "STUDYID",
            "RDOMAIN",
            "USUBJID",
            "IDVAR",
            "IDVARVAL",
            "QNAM",
            "QLABEL",
            "QVAL",
            "QORIG",
            "QEVAL",
        ]

    def test_all_columns_string_type(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        supp = ns.export_supp()
        for col in supp.columns:
            assert supp[col].dtype == pl.String


# ──────────────────────────────────────────────────────────────────────
# TestExportSuppContent
# ──────────────────────────────────────────────────────────────────────


class TestExportSuppContent:
    """export_supp() produces correct QNAM, QLABEL, QVAL, null-dropping."""

    def test_qnam_matches_target(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag").nsv(
            "ITT", source="itt_flag", label="ITT Flag"
        )
        supp = ns.export_supp()
        assert set(supp["QNAM"].to_list()) == {"SAFETY", "ITT"}

    def test_qlabel_from_metadata(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv(
            "SAFETY", source="safety_flag", label="Safety Population Flag"
        )
        supp = ns.export_supp()
        assert all(v == "Safety Population Flag" for v in supp["QLABEL"].to_list())

    def test_null_qval_dropped(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag").nsv(
            "ITT", source="itt_flag", label="ITT Flag"
        )
        supp = ns.export_supp()
        # SAFETY: 3 rows (all "Y"), ITT: 2 rows (one null dropped)
        assert supp.filter(pl.col("QNAM") == "SAFETY").height == 3
        assert supp.filter(pl.col("QNAM") == "ITT").height == 2
        assert supp.height == 5

    def test_rdomain_inferred(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        supp = ns.export_supp()
        assert all(v == "DM" for v in supp["RDOMAIN"].to_list())

    def test_qorig_from_metadata(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv(
            "SAFETY", source="safety_flag", label="Safety Flag", origin="Collected"
        )
        supp = ns.export_supp()
        assert all(v == "Collected" for v in supp["QORIG"].to_list())

    def test_qeval_from_metadata(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv(
            "SAFETY", source="safety_flag", label="Safety Flag", evaluator="INVESTIGATOR"
        )
        supp = ns.export_supp()
        assert all(v == "INVESTIGATOR" for v in supp["QEVAL"].to_list())


# ──────────────────────────────────────────────────────────────────────
# TestExportSuppIDVAR
# ──────────────────────────────────────────────────────────────────────


class TestExportSuppIDVAR:
    """IDVAR/IDVARVAL handling in export_supp()."""

    def test_idvar_none_for_dm(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        supp = ns.export_supp()
        assert all(v is None for v in supp["IDVAR"].to_list())
        assert all(v is None for v in supp["IDVARVAL"].to_list())

    def test_idvar_populated_for_ae(self, ae_raw_with_seq):
        ns = ae_raw_with_seq.sdtm.nsv("AETOXGR", source="ae_toxgr", label="AE Toxicity Grade")
        supp = ns.export_supp(idvar="AESEQ")
        assert all(v == "AESEQ" for v in supp["IDVAR"].to_list())
        assert set(supp["IDVARVAL"].to_list()) == {"1", "2"}


# ──────────────────────────────────────────────────────────────────────
# TestExportSuppDomain
# ──────────────────────────────────────────────────────────────────────


class TestExportSuppDomain:
    """RDOMAIN inference vs explicit override."""

    def test_rdomain_from_domain_column(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        supp = ns.export_supp()
        assert supp["RDOMAIN"][0] == "DM"

    def test_rdomain_explicit_override(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        supp = ns.export_supp(domain="XX")
        assert all(v == "XX" for v in supp["RDOMAIN"].to_list())


# ──────────────────────────────────────────────────────────────────────
# TestExportSuppPostHocDict
# ──────────────────────────────────────────────────────────────────────


class TestExportSuppPostHocDict:
    """export_supp(qualifiers={...}) works without nsv() pipeline metadata."""

    def test_explicit_qualifiers_dict(self, dm_raw_with_flags):
        # No nsv() calls — use explicit dict on an existing frame
        supp = dm_raw_with_flags.sdtm.export_supp(
            qualifiers={
                "safety_flag": {"label": "Safety Population Flag", "origin": "Derived"},
                "itt_flag": {"label": "ITT Population Flag", "origin": "Derived"},
            },
        )
        assert supp.columns == [
            "STUDYID",
            "RDOMAIN",
            "USUBJID",
            "IDVAR",
            "IDVARVAL",
            "QNAM",
            "QLABEL",
            "QVAL",
            "QORIG",
            "QEVAL",
        ]
        assert set(supp["QNAM"].to_list()) == {"safety_flag", "itt_flag"}
        # null itt_flag row dropped
        assert supp.filter(pl.col("QNAM") == "itt_flag").height == 2

    def test_qualifiers_dict_priority_over_nsv_meta(self, dm_raw_with_flags):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        # qualifiers dict should override _nsv_meta
        supp = ns.export_supp(
            qualifiers={"efficacy_flag": {"label": "Efficacy Flag", "origin": "Derived"}}
        )
        assert set(supp["QNAM"].to_list()) == {"efficacy_flag"}


# ──────────────────────────────────────────────────────────────────────
# TestExportSuppSpecAware
# ──────────────────────────────────────────────────────────────────────


class TestExportSuppSpecAware:
    """export_supp(spec=..., dataset=...) reads qualifier metadata from YAML."""

    def test_spec_reads_qualifiers(self, dm_raw_with_flags, nsv_spec_yaml):
        # Build a frame that has the qualifier columns
        df = (
            dm_raw_with_flags.sdtm.assign("SAFETY", source="safety_flag")
            .assign("ITT", source="itt_flag")
            .to_frame()
        )
        supp = df.sdtm.export_supp(spec=str(nsv_spec_yaml), dataset="DM")
        assert set(supp["QNAM"].to_list()) == {"SAFETY", "ITT"}
        # Verify labels came from spec
        safety_rows = supp.filter(pl.col("QNAM") == "SAFETY")
        assert safety_rows["QLABEL"][0] == "Safety Population Flag"

    def test_spec_priority_over_nsv_meta(self, dm_raw_with_flags, nsv_spec_yaml):
        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="WRONG LABEL").nsv(
            "ITT", source="itt_flag", label="WRONG LABEL 2"
        )
        # spec should take priority over pipeline metadata
        supp = ns.export_supp(spec=str(nsv_spec_yaml), dataset="DM")
        safety_rows = supp.filter(pl.col("QNAM") == "SAFETY")
        assert safety_rows["QLABEL"][0] == "Safety Population Flag"


# ──────────────────────────────────────────────────────────────────────
# TestExportSuppEmpty
# ──────────────────────────────────────────────────────────────────────


class TestExportSuppEmpty:
    """Empty NSV list returns empty frame with correct schema."""

    def test_no_nsv_meta_returns_empty(self, dm_raw_with_flags):
        supp = dm_raw_with_flags.sdtm.export_supp()
        assert supp.height == 0
        assert supp.columns == [
            "STUDYID",
            "RDOMAIN",
            "USUBJID",
            "IDVAR",
            "IDVARVAL",
            "QNAM",
            "QLABEL",
            "QVAL",
            "QORIG",
            "QEVAL",
        ]


# ──────────────────────────────────────────────────────────────────────
# TestNSVFromSpec
# ──────────────────────────────────────────────────────────────────────


class TestNSVFromSpec:
    """from_spec() dispatches algorithm: nsv and populates _nsv_meta."""

    def test_from_spec_creates_nsv_columns(self, dm_raw_with_flags, nsv_spec_yaml):
        raw = pl.from_repr("""\
┌────────────────┬─────────────┬──────────┐
│ patient_number ┆ safety_flag ┆ itt_flag │
│ ---            ┆ ---         ┆ ---      │
│ str            ┆ str         ┆ str      │
╞════════════════╪═════════════╪══════════╡
│ 01-701-1015    ┆ Y           ┆ Y        │
│ 01-701-1023    ┆ Y           ┆ Y        │
│ 01-701-1028    ┆ Y           ┆ null     │
└────────────────┴─────────────┴──────────┘
""")
        ns = raw.sdtm.from_spec(str(nsv_spec_yaml), dataset="DM")
        result = ns.to_frame()
        assert "SAFETY" in result.columns
        assert "ITT" in result.columns

    def test_from_spec_populates_nsv_meta(self, nsv_spec_yaml):
        raw = pl.from_repr("""\
┌────────────────┬─────────────┬──────────┐
│ patient_number ┆ safety_flag ┆ itt_flag │
│ ---            ┆ ---         ┆ ---      │
│ str            ┆ str         ┆ str      │
╞════════════════╪═════════════╪══════════╡
│ 01-701-1015    ┆ Y           ┆ Y        │
└────────────────┴─────────────┴──────────┘
""")
        ns = raw.sdtm.from_spec(str(nsv_spec_yaml), dataset="DM")
        assert len(ns._nsv_meta) == 2
        targets = [m.target for m in ns._nsv_meta]
        assert "SAFETY" in targets
        assert "ITT" in targets

    def test_from_spec_then_export_supp(self, nsv_spec_yaml):
        raw = pl.from_repr("""\
┌────────────────┬─────────────┬──────────┐
│ patient_number ┆ safety_flag ┆ itt_flag │
│ ---            ┆ ---         ┆ ---      │
│ str            ┆ str         ┆ str      │
╞════════════════╪═════════════╪══════════╡
│ 01-701-1015    ┆ Y           ┆ Y        │
│ 01-701-1023    ┆ Y           ┆ null     │
└────────────────┴─────────────┴──────────┘
""")
        ns = raw.sdtm.from_spec(str(nsv_spec_yaml), dataset="DM")
        supp = ns.export_supp()
        assert supp.height == 3  # 2 SAFETY + 1 ITT (one null dropped)


# ──────────────────────────────────────────────────────────────────────
# TestNSVLineage
# ──────────────────────────────────────────────────────────────────────


class TestNSVLineage:
    """lineage_of() records nsv verb name."""

    def test_lineage_records_nsv(self, dm_raw_with_flags):
        from fleet.core.lineage import lineage_of

        ns = dm_raw_with_flags.sdtm.nsv("SAFETY", source="safety_flag", label="Safety Flag")
        entries = lineage_of(ns)
        nsv_entries = [e for e in entries if e.verb == "nsv"]
        assert len(nsv_entries) == 1
        assert nsv_entries[0].name == "SAFETY"
