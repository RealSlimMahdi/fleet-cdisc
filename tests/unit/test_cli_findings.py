"""``fleet`` CLI: regressions of the medium and low audit findings (package ml-cli)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from fleet import cli


def _run(argv: list[str]) -> int:
    """Invoke ``cli.main`` and return its exit code (0 when it returns)."""
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


_ADSL = """\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S01     ┆ 34  │
│ S02     ┆ 45  │
└─────────┴─────┘
"""


@pytest.fixture
def adsl_pair(tmp_path: Path) -> tuple[Path, Path]:
    base, candidate = tmp_path / "a.parquet", tmp_path / "b.parquet"
    pl.from_repr(_ADSL).write_parquet(base)
    pl.from_repr(_ADSL).write_parquet(candidate)
    return base, candidate


class TestCompare:
    def test_c1_275_an_internal_error_exits_2_not_1(
        self, adsl_pair, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("engine defect")

        monkeypatch.setattr("fleet.comparison.compare", boom)
        monkeypatch.delenv("FLEET_DEBUG", raising=False)
        base, candidate = adsl_pair

        assert _run(["compare", str(base), str(candidate), "--keys", "USUBJID"]) == 2

        err = capsys.readouterr().err
        assert "internal error in fleet compare: RuntimeError: engine defect" in err
        assert "Traceback" not in err

    def test_c1_275_fleet_debug_shows_the_traceback(
        self, adsl_pair, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("engine defect")

        monkeypatch.setattr("fleet.comparison.compare", boom)
        monkeypatch.setenv("FLEET_DEBUG", "1")
        base, candidate = adsl_pair

        with pytest.raises(RuntimeError, match="engine defect"):
            cli.main(["compare", str(base), str(candidate), "--keys", "USUBJID"])

    def test_c1_276_a_corrupt_file_is_named_with_its_side(
        self, adsl_pair, capsys: pytest.CaptureFixture
    ) -> None:
        base, candidate = adsl_pair
        candidate.write_bytes(b"PAR1 not a parquet file")

        assert _run(["compare", str(base), str(candidate), "--keys", "USUBJID"]) == 2

        assert f"cannot read the candidate {candidate}" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("flag", "side"),
        [
            ("--out", "base"),
            ("--out", "candidate"),
            ("--report", "base"),
            ("--report", "candidate"),
        ],
    )
    def test_c1_278_an_output_may_not_overwrite_an_input(
        self, flag: str, side: str, adsl_pair, capsys: pytest.CaptureFixture
    ) -> None:
        base, candidate = adsl_pair
        target = base if side == "base" else candidate
        before = target.read_bytes()

        code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID", flag, str(target)])

        assert code == 2
        assert f"{flag} is the {side} file" in capsys.readouterr().err
        assert target.read_bytes() == before

    def test_c1_278_out_and_report_may_not_name_one_file(
        self, adsl_pair, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        base, candidate = adsl_pair
        same = str(tmp_path / "x.out")

        code = _run(
            [
                "compare",
                str(base),
                str(candidate),
                "--keys",
                "USUBJID",
                "--out",
                same,
                "--report",
                same,
            ]
        )

        assert code == 2
        assert "--out and --report name the same file" in capsys.readouterr().err

    def test_c1_277_the_save_methods_create_the_parent_folder(self, tmp_path: Path) -> None:
        from fleet.comparison import compare

        frame = pl.from_repr(_ADSL)
        report = compare(frame, frame, keys=["USUBJID"])

        report.save_json(tmp_path / "a" / "x.json")
        report.save_html_report(tmp_path / "b" / "x.html")
        report.save_listing(tmp_path / "c" / "x.parquet")

        assert (tmp_path / "a" / "x.json").is_file()
        assert (tmp_path / "b" / "x.html").is_file()
        assert (tmp_path / "c" / "x.parquet").is_file()
