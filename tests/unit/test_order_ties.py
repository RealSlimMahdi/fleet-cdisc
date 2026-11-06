"""Record order on ties and missing keys: pick, nodup, seq, flag, and group order.

Each test names the alpha-audit finding it pins. The reference for a tie is
PROC SORT EQUALS: tied records keep their input order.
"""

from __future__ import annotations

import random
import warnings

import polars as pl
import pytest

import fleet  # noqa: F401 — registers namespaces
from fleet.core.exceptions import DerivationError, VerbUsageError


def _ties(n: int = 200, seed: int = 7) -> pl.DataFrame:
    """Random AE-like rows with many ties on small key domains."""
    rng = random.Random(seed)
    return pl.DataFrame(
        {
            "ROWID": list(range(n)),
            "USUBJID": [f"S{rng.randint(1, 5)}" for _ in range(n)],
            "AEDECOD": [rng.choice(["NAUSEA", "RASH", "HEADACHE"]) for _ in range(n)],
            "AESTDTC": [f"2024-01-0{rng.randint(1, 4)}" for _ in range(n)],
            "AEBODSYS": [rng.choice(["GI", "NERV", "SKIN"]) for _ in range(n)],
        }
    )


@pytest.fixture
def fatal_ae() -> pl.DataFrame:
    return pl.from_repr("""
┌─────────┬─────────┬───────┬────────────┐
│ USUBJID ┆ AEDECOD ┆ AEOUT ┆ AEENDTC    │
│ ---     ┆ ---     ┆ ---   ┆ ---        │
│ str     ┆ str     ┆ str   ┆ str        │
╞═════════╪═════════╪═══════╪════════════╡
│ S1      ┆ MI      ┆ FATAL ┆ 2024-01-05 │
│ S1      ┆ STROKE  ┆ FATAL ┆ 2024-01-03 │
│ S1      ┆ PE      ┆ FATAL ┆ 2024-01-05 │
└─────────┴─────────┴───────┴────────────┘
""")


def _dthcaus(ae: pl.DataFrame, **event: object) -> dict[str, object]:
    return {
        "when": pl.col("AEOUT") == "FATAL",
        "set": {"DTHCAUS": "AEDECOD"},
        "source": ae,
        **event,
    }


class TestPickOrder:
    """c1-125, c1-207: pick needs an order and takes the last tied record."""

    def test_no_order_with_two_records_raises(self, fatal_ae):
        adsl = pl.DataFrame({"USUBJID": ["S1"]})
        with pytest.raises(DerivationError, match=r"event #0 has no order.*USUBJID='S1'"):
            adsl.adam.pick("DTHCAUS", by=["USUBJID"], events=[_dthcaus(fatal_ae)])

    def test_no_order_with_one_record_passes(self, fatal_ae):
        adsl = pl.DataFrame({"USUBJID": ["S1"]})
        one = fatal_ae.filter(pl.col("AEDECOD") == "STROKE")
        result = adsl.adam.pick("DTHCAUS", by=["USUBJID"], events=[_dthcaus(one)]).to_frame()
        assert result["DTHCAUS"].to_list() == ["STROKE"]

    def test_last_on_a_tie_takes_the_last_record_and_warns(self, fatal_ae):
        adsl = pl.DataFrame({"USUBJID": ["S1"]})
        event = _dthcaus(fatal_ae, order=["AEENDTC"])
        with pytest.warns(UserWarning, match="tie on \\['AEENDTC'\\]"):
            result = adsl.adam.pick("DTHCAUS", by=["USUBJID"], events=[event], mode="last")
        assert result.to_frame()["DTHCAUS"].to_list() == ["PE"]

    def test_last_on_a_tie_follows_input_order(self, fatal_ae):
        adsl = pl.DataFrame({"USUBJID": ["S1"]})
        event = _dthcaus(fatal_ae.reverse(), order=["AEENDTC"])
        with pytest.warns(UserWarning):
            result = adsl.adam.pick("DTHCAUS", by=["USUBJID"], events=[event], mode="last")
        assert result.to_frame()["DTHCAUS"].to_list() == ["MI"]

    def test_first_with_a_unique_minimum_does_not_warn(self, fatal_ae):
        adsl = pl.DataFrame({"USUBJID": ["S1"]})
        event = _dthcaus(fatal_ae, order=["AEENDTC"])
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = adsl.adam.pick("DTHCAUS", by=["USUBJID"], events=[event]).to_frame()
        assert result["DTHCAUS"].to_list() == ["STROKE"]

    def test_same_day_retest_last_takes_the_last_value(self):
        lb = pl.from_repr("""
┌─────────┬───────┬────────────┬──────┐
│ USUBJID ┆ LBSEQ ┆ ADT        ┆ AVAL │
│ ---     ┆ ---   ┆ ---        ┆ ---  │
│ str     ┆ i64   ┆ date       ┆ f64  │
╞═════════╪═══════╪════════════╪══════╡
│ S1      ┆ 1     ┆ 2024-01-01 ┆ 5.0  │
│ S1      ┆ 2     ┆ 2024-01-01 ┆ 10.0 │
│ S1      ┆ 3     ┆ 2024-01-01 ┆ 30.0 │
└─────────┴───────┴────────────┴──────┘
""")
        adsl = pl.DataFrame({"USUBJID": ["S1"]})
        with pytest.warns(UserWarning):
            result = adsl.adam.adsl.pick(
                ["PICKV"],
                events=[{"when": pl.lit(True), "set": {"PICKV": "AVAL"}, "source": lb}],
                by=["USUBJID"],
                order=["ADT"],
                mode="last",
            ).to_frame()
        assert result["PICKV"].to_list() == [30.0]


class TestNodupOrder:
    """c1-18, c1-21: nodup sorts a missing key as SAS and keeps input order on ties."""

    @pytest.fixture
    def ae(self) -> pl.DataFrame:
        return pl.from_repr("""
┌─────────┬──────────┬────────┐
│ USUBJID ┆ AEDECOD  ┆ AESEVN │
│ ---     ┆ ---      ┆ ---    │
│ str     ┆ str      ┆ i64    │
╞═════════╪══════════╪════════╡
│ S1      ┆ HEADACHE ┆ null   │
│ S1      ┆ HEADACHE ┆ 1      │
│ S1      ┆ HEADACHE ┆ 3      │
│ S2      ┆ NAUSEA   ┆ 2      │
│ S2      ┆ NAUSEA   ┆ null   │
│ S3      ┆ RASH     ┆ 1      │
└─────────┴──────────┴────────┘
""")

    @pytest.mark.parametrize(
        ("keep", "descending", "expected"),
        [
            ("first", True, [3, 2, 1]),
            ("last", True, [None, None, 1]),
            ("first", False, [None, None, 1]),
            ("last", False, [3, 2, 1]),
        ],
    )
    def test_missing_is_the_lowest_value(self, ae, keep, descending, expected):
        result = (
            ae.sdtm.nodup(
                subset=["USUBJID", "AEDECOD"], sort_by=["AESEVN"], keep=keep, descending=descending
            )
            .to_frame()
            .sort("USUBJID")
        )
        assert result["AESEVN"].to_list() == expected

    @pytest.mark.parametrize(("keep", "agg"), [("first", "min"), ("last", "max")])
    def test_ties_keep_input_order(self, keep, agg):
        df = _ties()
        result = df.sdtm.nodup(
            subset=["USUBJID", "AEDECOD"], sort_by=["USUBJID", "AEDECOD"], keep=keep
        ).to_frame()
        expected = df.group_by(["USUBJID", "AEDECOD"]).agg(getattr(pl.col("ROWID"), agg)())
        assert sorted(result["ROWID"].to_list()) == sorted(expected["ROWID"].to_list())


class TestStableSorts:
    """c1-21: seq and derive_locf_records keep input order on ties."""

    def test_seq_ties_keep_input_order(self):
        df = _ties()
        result = df.sdtm.seq("AESEQ", order_by=["AESTDTC", "AEBODSYS"], by=["USUBJID"])
        expected = (
            df.sort(["AESTDTC", "AEBODSYS", "ROWID"])
            .with_columns((pl.int_range(pl.len()).over("USUBJID") + 1).alias("AESEQ"))
            .sort("ROWID")
        )
        got = result.to_frame().sort("ROWID")
        assert got["AESEQ"].cast(pl.Int64).to_list() == expected["AESEQ"].to_list()

    def test_locf_ties_keep_input_order(self):
        df = (
            _ties()
            .rename({"AEDECOD": "PARAMCD", "AESTDTC": "ADT"})
            .with_columns(pl.col("ROWID").cast(pl.Float64).alias("AVAL"))
        )
        visits = df.select("USUBJID", "PARAMCD", "ADT").unique()
        result = df.adam.derive_locf_records(
            by=["USUBJID", "PARAMCD"], dataset_ref=visits, order_by="ADT"
        ).to_frame()
        expected = df.sort(["USUBJID", "PARAMCD", "ADT", "ROWID"])
        assert result["ROWID"].to_list() == expected["ROWID"].to_list()


def _many_groups(n_subj: int = 400, seed: int = 3) -> pl.DataFrame:
    rng = random.Random(seed)
    rows = [(f"S{i:04d}", p, float(v)) for i in range(n_subj) for p in "ABC" for v in (1, 2)]
    rng.shuffle(rows)
    return pl.DataFrame(rows, schema=["USUBJID", "PARAMCD", "AVAL"], orient="row")


class TestGroupOrder:
    """c1-325: new rows come in the order of the first record of each group."""

    def test_derive_summary_records_order(self):
        df = _many_groups()
        result = df.adam.derive_summary_records(
            by=["USUBJID", "PARAMCD"], set_values_to={"DTYPE": "AVERAGE"}
        ).to_frame()
        new = result.filter(pl.col("DTYPE") == "AVERAGE").select("USUBJID", "PARAMCD")
        first_seen = df.select("USUBJID", "PARAMCD").unique(maintain_order=True)
        assert new.equals(first_seen)

    def test_sdtm_group_by_order(self):
        df = _many_groups()
        result = df.sdtm.group_by(by=["USUBJID", "PARAMCD"], agg=[pl.col("AVAL").max()]).to_frame()
        first_seen = df.select("USUBJID", "PARAMCD").unique(maintain_order=True)
        assert result.select("USUBJID", "PARAMCD").equals(first_seen)

    def test_tte_param_order(self):
        ids = [f"S{i:04d}" for i in range(400)]
        random.Random(5).shuffle(ids)
        adsl = pl.DataFrame({"USUBJID": ids}).with_columns(
            pl.date(2023, 1, 1).alias("TRTSDT"),
            pl.date(2023, 6, 1).alias("LSTALVDT"),
            pl.lit(None, pl.String).alias("DTHFL"),
            pl.lit(None, pl.Date).alias("DTHDT"),
        )
        result = adsl.adam.tte.param(
            "OS",
            "Overall Survival",
            start="TRTSDT",
            events={"DEATH": adsl.filter(pl.col("DTHFL") == "Y").select("USUBJID", ADT="DTHDT")},
            censors={1: adsl.select("USUBJID", ADT="LSTALVDT")},
        ).to_frame()
        assert result["USUBJID"].to_list() == ids


class TestFlagFixes:
    """c1-209, c1-210, c1-213."""

    def test_exists_after_with_two_order_keys_raises(self):
        rs = pl.from_repr("""
┌─────────┬────────────┬───────┬───────┐
│ USUBJID ┆ ADT        ┆ ATM   ┆ AVALC │
│ ---     ┆ ---        ┆ ---   ┆ ---   │
│ str     ┆ date       ┆ str   ┆ str   │
╞═════════╪════════════╪═══════╪═══════╡
│ S1      ┆ 2024-03-01 ┆ 08:00 ┆ PR    │
│ S1      ┆ 2024-03-01 ┆ 09:00 ┆ CR    │
└─────────┴────────────┴───────┴───────┘
""")
        with pytest.raises(VerbUsageError, match="one ordered key column"):
            rs.adam.flag(
                "CONF",
                criteria="exists_after",
                from_dataset=rs,
                on=["USUBJID"],
                condition=pl.col("AVALC") == "PR",
                order_by=["ADT", "ATM"],
            )

    @pytest.mark.parametrize(
        ("flag_no_ref_groups", "expected"),
        [
            (True, [None, "Y", "Y", "Y", "Y", "Y", "Y"]),
            (False, [None, "Y", "Y", "Y", None, None, None]),
        ],
    )
    def test_relative_after_follows_flag_no_ref_groups(self, flag_no_ref_groups, expected):
        rs = pl.from_repr("""
┌─────────┬─────────┬───────┐
│ USUBJID ┆ AVISITN ┆ AVALC │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ i64     ┆ str   │
╞═════════╪═════════╪═══════╡
│ S1      ┆ 1       ┆ SD    │
│ S1      ┆ 2       ┆ PD    │
│ S1      ┆ 3       ┆ SD    │
│ S1      ┆ 4       ┆ SD    │
│ S2      ┆ 1       ┆ SD    │
│ S2      ┆ 2       ┆ SD    │
│ S2      ┆ 3       ┆ SD    │
└─────────┴─────────┴───────┘
""")
        result = rs.adam.flag_relative(
            "PSTFL",
            when="after",
            condition=pl.col("AVALC") == "PD",
            order_by="AVISITN",
            by=["USUBJID"],
            flag_no_ref_groups=flag_no_ref_groups,
        ).to_frame()
        assert result["PSTFL"].to_list() == expected

    def test_flag_exists_with_two_keys_adds_only_the_flag(self, capsys):
        dm = pl.from_repr("""
┌─────────┬─────────┬─────┐
│ STUDYID ┆ USUBJID ┆ AGE │
│ ---     ┆ ---     ┆ --- │
│ str     ┆ str     ┆ i64 │
╞═════════╪═════════╪═════╡
│ X       ┆ S1      ┆ 40  │
│ X       ┆ S2      ┆ 50  │
│ X       ┆ S3      ┆ 60  │
└─────────┴─────────┴─────┘
""")
        ae = pl.from_repr("""
┌─────────┬─────────┬──────────┐
│ STUDYID ┆ USUBJID ┆ AEREL    │
│ ---     ┆ ---     ┆ ---      │
│ str     ┆ str     ┆ str      │
╞═════════╪═════════╪══════════╡
│ X       ┆ S1      ┆ PROBABLE │
│ X       ┆ S2      ┆ NONE     │
└─────────┴─────────┴──────────┘
""")
        ns = dm.adam.adsl.flag_exists(
            "AERELFL",
            from_dataset=ae,
            on=["STUDYID", "USUBJID"],
            source_filter=pl.col("AEREL") == "PROBABLE",
        ).flag_exists("AEFL", from_dataset=ae, on=["STUDYID", "USUBJID"], false_value="N")
        result = ns.to_frame()
        assert result.columns == ["STUDYID", "USUBJID", "AGE", "AERELFL", "AEFL"]
        assert result["AERELFL"].to_list() == ["Y", None, None]
        assert result["AEFL"].to_list() == ["Y", "Y", "N"]
        ns.trail()
        assert "Variable trail (2 derivation(s)):" in capsys.readouterr().out
