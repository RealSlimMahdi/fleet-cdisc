"""Join checks of merge, merge_adsl, join_adsl and their neighbours (ADR-0032).

One test class per audit finding: c1-12, c1-14, c1-15, c1-17, c1-131,
c1-30, c1-32, c1-38 / c1-195 and c1-63.
"""

import warnings
from pathlib import Path

import polars as pl
import pytest

import fleet
from fleet.core.exceptions import ComparisonError, DerivationError, SpecError

LEFT = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 40  │
│ S2      ┆ 50  │
└─────────┴─────┘
""")

RIGHT = pl.from_repr("""\
┌─────────┬─────┬────────────┐
│ USUBJID ┆ AGE ┆ TRTSDT     │
│ ---     ┆ --- ┆ ---        │
│ str     ┆ i64 ┆ date       │
╞═════════╪═════╪════════════╡
│ S1      ┆ 99  ┆ 2020-01-01 │
│ S2      ┆ 98  ┆ 2020-01-01 │
└─────────┴─────┴────────────┘
""")

ADSL_REPEATED = pl.from_repr("""\
┌─────────┬─────────┬────────────┐
│ USUBJID ┆ TRT01P  ┆ TRTSDT     │
│ ---     ┆ ---     ┆ ---        │
│ str     ┆ str     ┆ date       │
╞═════════╪═════════╪════════════╡
│ S1      ┆ Placebo ┆ 2020-01-01 │
│ S1      ┆ Drug    ┆ 2020-01-05 │
│ S2      ┆ B       ┆ 2020-01-01 │
└─────────┴─────────┴────────────┘
""")

ADAE = pl.from_repr("""\
┌─────────┬───────┬────────────┐
│ USUBJID ┆ AESEQ ┆ ASTDT      │
│ ---     ┆ ---   ┆ ---        │
│ str     ┆ i64   ┆ date       │
╞═════════╪═══════╪════════════╡
│ S1      ┆ 1     ┆ 2020-01-10 │
│ S2      ┆ 1     ┆ 2020-01-10 │
└─────────┴───────┴────────────┘
""")


class TestSharedColumnsStop:
    """c1-12: a non-key column on both sides raises and names the column."""

    def test_merge_names_the_shared_column(self):
        with pytest.raises(DerivationError, match="AGE is on both sides"):
            LEFT.sdtm.merge(RIGHT, on="USUBJID")

    def test_merge_stays_lazy_and_works_after_a_select(self):
        right = RIGHT.select("USUBJID", "TRTSDT")
        out = LEFT.sdtm.merge(right, on="USUBJID").to_frame()
        assert out.columns == ["USUBJID", "AGE", "TRTSDT"]

    def test_merge_adsl_without_keep_names_the_shared_column(self):
        with pytest.raises(DerivationError, match="AGE is on both sides.*keep="):
            LEFT.adam.merge_adsl(RIGHT)

    def test_merge_adsl_with_keep_adds_the_column(self):
        out = LEFT.adam.merge_adsl(RIGHT, keep=["TRTSDT"]).to_frame()
        assert out.columns == ["USUBJID", "AGE", "TRTSDT"]
        assert "AGE_right" not in out.columns

    def test_first_date_on_an_existing_target_raises(self):
        with pytest.raises(DerivationError, match="TRTSDT is on both sides"):
            RIGHT.adam.first_date("TRTSDT", from_dataset=ADAE, date_col="ASTDT")

    def test_count_events_on_an_existing_target_raises(self):
        with pytest.raises(DerivationError, match="AGE is on both sides"):
            LEFT.adam.count_events("AGE", from_dataset=ADAE)


class TestRepeatedKeysOnTheAdslPaths:
    """c1-14: ADSL holds one record per subject; a repeat stops and names the key."""

    def test_merge_adsl_names_the_repeated_subject(self):
        with pytest.raises(DerivationError, match="ADSL has more than one row.*USUBJID=S1"):
            ADAE.adam.merge_adsl(ADSL_REPEATED, keep=["TRT01P"])

    def test_join_adsl_names_the_repeated_subject(self):
        with pytest.raises(DerivationError, match="USUBJID=S1"):
            ADAE.adam.pin("ADSL", ADSL_REPEATED).join_adsl("TRT01P")

    def test_study_day_with_a_reference_frame_names_the_repeated_subject(self):
        with pytest.raises(DerivationError, match="USUBJID=S1"):
            ADAE.adam.study_day("ASTDY", date_col="ASTDT", adsl=ADSL_REPEATED).to_frame()

    def test_identical_repeats_still_join(self):
        adsl = pl.concat([ADSL_REPEATED.filter(pl.col("TRT01P") == "B")] * 2)
        out = ADAE.adam.merge_adsl(adsl, keep=["TRT01P"]).to_frame()
        assert out.height == 2

    def test_merge_validate_names_the_repeated_key(self):
        ns = ADAE.sdtm.merge(ADSL_REPEATED, on="USUBJID", keep=["TRT01P"], validate="m:1")
        with pytest.raises(DerivationError, match=r"validate='m:1'.*USUBJID=S1"):
            ns.to_frame()

    def test_merge_one_to_many_is_silent(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            out = LEFT.sdtm.merge(ADSL_REPEATED, on="USUBJID", keep=["TRT01P"]).to_frame()
        assert out.height == 3

    def test_merge_many_to_many_warns_at_to_frame(self):
        ns = ADSL_REPEATED.select("USUBJID").sdtm.merge(
            ADSL_REPEATED, on="USUBJID", keep=["TRT01P"]
        )
        with pytest.warns(UserWarning, match="USUBJID=S1.*many-to-many"):
            ns.to_frame()


class TestFullJoinKeepsOneKey:
    """c1-15: how="full" gives one key column, as SAS MERGE."""

    RIGHT_ONLY = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ X   │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 7   │
│ S9      ┆ 8   │
└─────────┴─────┘
""")

    def test_right_only_subject_keeps_its_key(self):
        out = LEFT.sdtm.merge(self.RIGHT_ONLY, on="USUBJID", how="full").to_frame()
        assert out.columns == ["USUBJID", "AGE", "X"]
        assert sorted(out["USUBJID"].to_list()) == ["S1", "S2", "S9"]

    def test_with_keep_the_key_stays(self):
        out = LEFT.sdtm.merge(self.RIGHT_ONLY, on="USUBJID", how="full", keep=["X"]).to_frame()
        assert out.filter(pl.col("X") == 8)["USUBJID"].to_list() == ["S9"]


class TestKeepLimitsTheRightDataset:
    """c1-17: keep= limits the right frame; every pipeline column stays."""

    AE = pl.from_repr("""\
┌─────────┬───────┬────────┐
│ USUBJID ┆ AESEQ ┆ AETERM │
│ ---     ┆ ---   ┆ ---    │
│ str     ┆ i64   ┆ str    │
╞═════════╪═══════╪════════╡
│ S1      ┆ 1     ┆ HEAD   │
│ S2      ┆ 1     ┆ NAUS   │
└─────────┴───────┴────────┘
""")
    DM = pl.from_repr("""\
┌─────────┬─────┬─────┐
│ USUBJID ┆ AGE ┆ SEX │
│ ---     ┆ --- ┆ --- │
│ str     ┆ i64 ┆ str │
╞═════════╪═════╪═════╡
│ S1      ┆ 40  ┆ M   │
│ S2      ┆ 50  ┆ F   │
└─────────┴─────┴─────┘
""")

    def test_left_columns_survive(self):
        out = (
            self.AE.sdtm.assign("DOMAIN", value="AE")
            .merge(self.DM, on="USUBJID", keep=["AGE"])
            .to_frame()
        )
        assert out.columns == ["USUBJID", "AESEQ", "AETERM", "DOMAIN", "AGE"]

    def test_a_keep_name_not_in_the_right_dataset_raises(self):
        with pytest.raises(DerivationError, match="'AGEE' \\(did you mean 'AGE'\\?\\).*right"):
            self.AE.sdtm.merge(self.DM, on="USUBJID", keep=["AGEE"])

    def test_where_may_use_a_column_keep_leaves_out(self):
        out = self.AE.sdtm.merge(
            self.DM, on="USUBJID", keep=["AGE"], where='pl.col("SEX") == "M"'
        ).to_frame()
        assert out["AGE"].to_list() == [40, None]

    def test_from_spec_raises_when_the_merge_block_does_not_give_its_variable(self, tmp_path: Path):
        spec = tmp_path / "ae.yaml"
        spec.write_text(
            "fleet_spec_version: 2\ndomain: AE\nvariables:\n"
            "  - target: RACE\n    algorithm: merge\n    dataset: DM\n"
            "    on: USUBJID\n    keep: [SEX]\n",
            encoding="utf-8",
        )
        ns = self.AE.sdtm.pin("DM", self.DM)
        with pytest.raises(SpecError, match="does not give the column 'RACE'"):
            ns.from_spec(spec)


class TestJoinAdslNamesItsColumns:
    """c1-131: an absent column and a column on both sides both raise."""

    ADSL = pl.from_repr("""\
┌─────────┬─────┬────────┐
│ USUBJID ┆ AGE ┆ TRT01P │
│ ---     ┆ --- ┆ ---    │
│ str     ┆ i64 ┆ str    │
╞═════════╪═════╪════════╡
│ 01      ┆ 40  ┆ A      │
│ 02      ┆ 50  ┆ B      │
└─────────┴─────┴────────┘
""")
    BASE = pl.from_repr("""\
┌─────────┬──────┬──────┐
│ USUBJID ┆ AGE  ┆ AVAL │
│ ---     ┆ ---  ┆ ---  │
│ str     ┆ i64  ┆ f64  │
╞═════════╪══════╪══════╡
│ 01      ┆ null ┆ 1.0  │
│ 02      ┆ 55   ┆ 2.0  │
└─────────┴──────┴──────┘
""")

    def test_a_misspelled_column_raises_before_lineage(self):
        ns = self.BASE.adam.pin("ADSL", self.ADSL)
        with pytest.raises(DerivationError, match="did you mean 'TRT01P'"):
            ns.join_adsl("TRT01PP")
        assert ns._pin_lineage == []

    def test_join_adsl_on_a_shared_column_raises(self):
        with pytest.raises(DerivationError, match="AGE is on both sides"):
            self.BASE.adam.pin("ADSL", self.ADSL).join_adsl("AGE")

    def test_merge_adsl_keep_on_a_shared_column_raises(self):
        with pytest.raises(DerivationError, match="AGE is on both sides"):
            self.BASE.adam.merge_adsl(self.ADSL, keep=["AGE"])

    def test_merge_keep_on_a_shared_column_raises(self):
        with pytest.raises(DerivationError, match="AGE is on both sides"):
            self.BASE.adam.merge(self.ADSL, on="USUBJID", keep=["AGE"])

    def test_the_explicit_way_takes_the_adsl_value(self):
        out = self.BASE.drop("AGE").adam.merge(self.ADSL, on="USUBJID", keep=["AGE"]).to_frame()
        assert out["AGE"].to_list() == [40, 50]


class TestSelectColumns:
    """c1-30: select(columns=) names an absent column; a string is one name."""

    DM = pl.from_repr("""\
┌─────────┬─────┬─────┐
│ USUBJID ┆ SEX ┆ AGE │
│ ---     ┆ --- ┆ --- │
│ str     ┆ str ┆ i64 │
╞═════════╪═════╪═════╡
│ S1      ┆ M   ┆ 40  │
│ S2      ┆ F   ┆ 50  │
└─────────┴─────┴─────┘
""")

    @pytest.mark.parametrize("namespace", ["sdtm", "adam"])
    def test_an_absent_name_raises_with_a_hint(self, namespace):
        with pytest.raises(DerivationError, match="'SEXX' \\(did you mean 'SEX'\\?\\)"):
            getattr(self.DM, namespace).select(columns=["USUBJID", "SEXX"])

    def test_a_string_is_one_name(self):
        assert self.DM.sdtm.select(columns="USUBJID").to_frame().shape == (2, 1)


class TestCtMapOnANumericSource:
    """c1-32: ct_map keys match the text form of a numeric value."""

    RAW = pl.from_repr("""\
┌──────┬───────┐
│ sexn ┆ sexf  │
│ ---  ┆ ---   │
│ i64  ┆ f64   │
╞══════╪═══════╡
│ 1    ┆ 1.0   │
│ 2    ┆ 2.0   │
│ 9    ┆ 9.0   │
└──────┴───────┘
""")

    @pytest.mark.parametrize("ct_map", [{"1": "M", "2": "F"}, {1: "M", 2: "F"}])
    def test_integer_source(self, ct_map):
        out = self.RAW.sdtm.assign("SEX", source="sexn", ct_map=ct_map).to_frame()
        assert out["SEX"].to_list() == ["M", "F", "9"]

    def test_float_source(self):
        out = self.RAW.sdtm.assign("SEX", source="sexf", ct_map={1.0: "M"}).to_frame()
        assert out["SEX"].to_list() == ["M", "2.0", "9.0"]

    def test_validation_reads_the_mapped_values(self):
        class SEX:
            _concept_id = "C66731"
            M = "M"
            F = "F"

        with pytest.warns(UserWarning, match=r"not in codelist.*\['9'\]"):
            self.RAW.sdtm.assign("SEX", source="sexn", ct=SEX, ct_map={1: "M", 2: "F"})


class TestFkErrorOnEveryTerminalVerb:
    """c1-38 / c1-195: under fk_policy("error") every terminal verb raises, each time."""

    DM = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
└─────────┘
""")
    RAW = pl.from_repr("""\
┌────────┬────────┐
│ subj   ┆ AETERM │
│ ---    ┆ ---    │
│ str    ┆ str    │
╞════════╪════════╡
│ S1     ┆ A      │
│ ORPHAN ┆ B      │
└────────┴────────┘
""")

    def _ns(self, policy: str):
        return self.RAW.sdtm.pin("DM", self.DM).fk_policy(policy).assign("USUBJID", source="subj")

    def test_to_frame_raises_every_time(self):
        ns = self._ns("error")
        for _ in range(2):
            with pytest.raises(DerivationError, match="ORPHAN"):
                ns.to_frame()

    def test_write_parquet_raises_every_time_and_writes_nothing(self, tmp_path: Path):
        ns = self._ns("error")
        path = tmp_path / "ae.parquet"
        for _ in range(2):
            with pytest.raises(DerivationError, match="ORPHAN"):
                ns.write_parquet(path)
        assert not path.exists()

    def test_to_dataset_json_raises_and_writes_nothing(self, tmp_path: Path):
        path = tmp_path / "ae.json"
        with pytest.raises(DerivationError, match="ORPHAN"):
            self._ns("error").to_dataset_json(path, domain="AE")
        assert not path.exists()

    def test_to_dataset_json_warns_under_the_default_policy(self, tmp_path: Path):
        with pytest.warns(UserWarning, match="FK check.*ORPHAN"):
            self._ns("warn").to_dataset_json(tmp_path / "ae.json", domain="AE")


class TestCompareStripsPaddedKeys:
    """c1-63: ignore_trailing_whitespace strips string keys before pairing."""

    # A table cannot show a trailing blank, so the padded keys are literals.
    BASE = pl.DataFrame({"USUBJID": ["A ", "B"], "AVAL": [1.0, 2.0]})
    CAND = pl.DataFrame({"USUBJID": ["A", "B"], "AVAL": [1.0, 2.0]})

    def test_a_padded_key_pairs(self):
        report = fleet.compare(
            self.BASE, self.CAND, keys="USUBJID", ignore_trailing_whitespace=True
        )
        assert report.observations.matched == 2
        assert report.is_equal

    def test_padded_twins_are_duplicates(self):
        base = pl.DataFrame({"USUBJID": ["A ", "A"], "AVAL": [1.0, 2.0]})
        with pytest.raises(ComparisonError, match="duplicated key"):
            fleet.compare(base, self.CAND, keys="USUBJID", ignore_trailing_whitespace=True)

    def test_keys_match_exactly_by_default(self):
        report = fleet.compare(self.BASE, self.CAND, keys="USUBJID")
        assert report.observations.matched == 1
