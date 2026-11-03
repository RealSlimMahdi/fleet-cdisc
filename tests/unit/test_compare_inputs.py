"""``fleet compare`` on blanks, CSV types and file encodings (package F)."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from fleet import cli, compare

ADAE = pl.from_repr("""
┌─────────┬───────┬────────────────────┐
│ USUBJID ┆ AESEQ ┆ AEOUT              │
│ ---     ┆ ---   ┆ ---                │
│ str     ┆ i64   ┆ str                │
╞═════════╪═══════╪════════════════════╡
│ 01-002  ┆ 1     ┆ null               │
│ 01-003  ┆ 1     ┆ RECOVERED/RESOLVED │
└─────────┴───────┴────────────────────┘
""")


def _run(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _csv(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


# ── A blank against a null ────────────────────────────────────────────────────


def test_a_blank_differs_from_null_by_default() -> None:
    """Exact stays the default: an R file that kept "" is not the SAS missing value."""
    report = compare(ADAE.with_columns(pl.col("AEOUT").fill_null("")), ADAE, keys="USUBJID")

    assert report.flags == {"values_differ"}


def test_blank_is_missing_makes_a_blank_equal_null_and_says_so() -> None:
    report = compare(
        ADAE.with_columns(pl.col("AEOUT").fill_null("")),
        ADAE,
        keys="USUBJID",
        blank_is_missing=True,
    )

    assert report.is_equal
    assert "blank equals missing" in report.settings.equality


def test_blank_is_missing_pairs_a_blank_key_with_a_null_key() -> None:
    base = pl.DataFrame({"USUBJID": ["S1", "S1"], "ATPT": ["", "PRE"], "AVAL": [1.0, 2.0]})
    candidate = base.with_columns(pl.col("ATPT").replace("", None))

    report = compare(base, candidate, keys=["USUBJID", "ATPT"], blank_is_missing=True)

    assert report.is_equal


def test_cli_blank_is_missing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    base, candidate = tmp_path / "adae.parquet", tmp_path / "adae_qc.parquet"
    ADAE.with_columns(pl.col("AEOUT").fill_null("")).write_parquet(base)
    ADAE.write_parquet(candidate)
    argv = ["compare", str(base), str(candidate), "--keys", "USUBJID,AESEQ"]

    assert _run(argv) == 1
    capsys.readouterr()
    assert _run([*argv, "--blank-is-missing"]) == 0
    assert "blank equals missing" in capsys.readouterr().out


# ── Two CSV files ─────────────────────────────────────────────────────────────


def test_csv_text_with_a_leading_zero_differs_and_numbers_compare_by_value(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """PROC COMPARE: SITEID 001 against 1 differs as character; AVAL 1.10 equals 1.1."""
    base = _csv(tmp_path / "adlb.csv", "USUBJID,SITEID,AVAL\n01-701-1015,001,1.10\n")
    candidate = _csv(tmp_path / "adlb_qc.csv", "USUBJID,SITEID,AVAL\n01-701-1015,1,1.1\n")

    code = _run(["compare", base, candidate, "--keys", "USUBJID"])

    out = capsys.readouterr().out
    assert code == 1
    assert "AVAL numeric" in out and "SITEID text" in out
    _run(["compare", base, candidate, "--keys", "USUBJID", "--format", "json"])
    listing = json.loads(capsys.readouterr().out)["listing"]["rows"]
    assert [row["variable"] for row in listing] == ["SITEID"]


def test_csv_keys_with_and_without_a_leading_zero_do_not_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base = _csv(tmp_path / "dm.csv", "SUBJID,AGE\n0012,45\n")
    candidate = _csv(tmp_path / "dm_qc.csv", "SUBJID,AGE\n12,45\n")

    code = _run(["compare", base, candidate, "--keys", "SUBJID"])

    out = capsys.readouterr().out
    assert code == 1
    assert "base_only_observations" in out and "candidate_only_observations" in out


def test_csv_text_option_reads_a_number_as_characters(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """LBORRES is character in SDTM: --text LBORRES is the $ informat."""
    base = _csv(tmp_path / "lb.csv", "USUBJID,LBORRES\nS1,1.10\n")
    candidate = _csv(tmp_path / "lb_qc.csv", "USUBJID,LBORRES\nS1,1.1\n")

    assert _run(["compare", base, candidate, "--keys", "USUBJID"]) == 0
    capsys.readouterr()
    assert _run(["compare", base, candidate, "--keys", "USUBJID", "--text", "LBORRES"]) == 1


def test_a_csv_against_a_typed_file_takes_the_typed_side(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base = tmp_path / "dm.parquet"
    pl.DataFrame({"USUBJID": ["S1"], "SITEID": ["001"], "AGE": [45]}).write_parquet(base)
    candidate = _csv(tmp_path / "dm_qc.csv", "USUBJID,SITEID,AGE\nS1,001,45\n")

    code = _run(["compare", str(base), candidate, "--keys", "USUBJID"])

    assert code == 0, capsys.readouterr().out


# ── Encodings ─────────────────────────────────────────────────────────────────


def test_compare_reads_a_latin1_xpt_with_encoding(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    pyreadstat = pytest.importorskip("pyreadstat")
    path = tmp_path / "ae.xpt"
    ae = pl.DataFrame({"USUBJID": ["S1"], "AETERM": ["CAFX"]})
    pyreadstat.write_xport(ae, str(path), file_format_version=5, table_name="AE")
    path.write_bytes(path.read_bytes().replace(b"CAFX", b"CAF\xe9"))
    candidate = tmp_path / "ae_qc.parquet"
    ae.with_columns(pl.lit("CAFé").alias("AETERM")).write_parquet(candidate)
    argv = ["compare", str(path), str(candidate), "--keys", "USUBJID"]

    assert _run(argv) == 2
    assert "--encoding" in capsys.readouterr().err
    assert _run([*argv, "--encoding", "iso-8859-1"]) == 0


def test_validate_loads_a_latin1_xpt_with_encoding(tmp_path: Path) -> None:
    """fleet validate reads its datasets through the same loader option as fleet compare."""
    pyreadstat = pytest.importorskip("pyreadstat")
    path = tmp_path / "ts.xpt"
    pyreadstat.write_xport(
        pl.DataFrame({"TSVAL": ["CAFX"]}), str(path), file_format_version=5, table_name="TS"
    )
    path.write_bytes(path.read_bytes().replace(b"CAFX", b"CAF\x92"))

    ts = cli._load_dataset(str(path), "cp1252")

    assert ts["TSVAL"].to_list() == ["CAF\u2019"]
    assert cli._build_parser().parse_args(["validate", "--encoding", "cp1252"]).encoding == "cp1252"
