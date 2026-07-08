"""Tests for the libcst-based migration tool (``fleet.tools.migrate``)."""

from __future__ import annotations

import pytest

pytest.importorskip("libcst", reason="migrate extra (libcst) not installed")

from fleet.tools.migrate import migrate_source  # noqa: E402


def _migrate(code: str) -> tuple[str, list[str]]:
    return migrate_source(code)


class TestVerbRenames:
    def test_assign_no_ct(self):
        out, changes = _migrate('x.sdtm.assign_no_ct("USUBJID", source="sid")')
        assert 'assign("USUBJID", source="sid")' in out
        assert ".assign_no_ct() -> .assign()" in changes

    def test_assign_ct_kwargs(self):
        out, _ = _migrate('x.sdtm.assign_ct("SEX", source="s", ct_codelist=SEX, ct_mapping={})')
        assert ".assign(" in out
        assert "ct=SEX" in out
        assert "ct_map={}" in out

    def test_if_then_else(self):
        out, _ = _migrate('x.sdtm.if_then_else("G", when=[], else_value="z")')
        assert 'case_when("G", when=[], else_="z")' in out

    def test_condderivation(self):
        out, _ = _migrate('x.adam.condderivation("G", conditions=[], else_value="z")')
        assert 'case_when("G", when=[], else_="z")' in out


class TestKwargRenames:
    def test_groups_to_by(self):
        out, _ = _migrate('x.adam.flag("F", criteria="last", order_by="A", groups=["USUBJID"])')
        assert "by=[" in out
        assert "groups=" not in out

    def test_by_vars_to_by(self):
        out, _ = _migrate('x.adam.derive_locf_records(by_vars=["USUBJID"])')
        assert "by=[" in out


class TestMergeLookup:
    def test_lookup_to_merge_with_positional_keep(self):
        out, _ = _migrate('x.adam.lookup(["TRTSDT"], dataset=adsl, on="USUBJID")')
        assert ".merge(" in out
        assert "keep=[" in out
        assert ".lookup(" not in out

    def test_merge_positional_list_to_keep(self):
        out, _ = _migrate('x.sdtm.merge(["RFSTDTC"], dataset=supp, on="USUBJID")')
        assert "keep=[" in out
        assert "dataset=supp" in out


class TestGuards:
    def test_polars_rename_untouched(self):
        # Polars DataFrame.rename({...}) has no source= kwarg — must be left alone.
        code = 'df.rename({"a": "b"})'
        out, changes = _migrate(code)
        assert out == code
        assert changes == []

    def test_fleet_rename_migrated(self):
        out, _ = _migrate('x.adam.rename("PARAM", source="VSTEST")')
        assert 'assign("PARAM", source="VSTEST")' in out

    def test_no_change_returns_identical(self):
        code = 'x.sdtm.assign("USUBJID", source="sid")'
        out, changes = _migrate(code)
        assert out == code
        assert changes == []


class TestMainCli:
    def test_main_diff_mode(self, tmp_path, capsys):
        from fleet.tools.migrate import main

        f = tmp_path / "p.py"
        f.write_text('x.sdtm.assign_no_ct("U", source="s")\n', encoding="utf-8")
        rc = main([str(f)])
        assert rc == 0
        # File left unchanged in diff mode.
        assert "assign_no_ct" in f.read_text()

    def test_main_write_mode(self, tmp_path):
        from fleet.tools.migrate import main

        f = tmp_path / "p.py"
        f.write_text('x.sdtm.assign_no_ct("U", source="s")\n', encoding="utf-8")
        rc = main([str(f), "--write"])
        assert rc == 0
        assert "assign_no_ct" not in f.read_text()
        assert ".assign(" in f.read_text()
