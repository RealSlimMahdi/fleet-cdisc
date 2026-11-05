"""Tests for the libcst-based migration tool (``fleet.tools.migrate``)."""

from __future__ import annotations

import os

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


class TestAuditFindings:
    @pytest.mark.parametrize(
        "code",
        [
            "codecs.lookup('utf-8')",
            "heapq.merge([1, 3], [2, 4], [5])",
            "obj.assigned('x')",
            "x.adam.lookup(adsl, on='USUBJID')",
        ],
    )
    def test_c1_827_calls_without_the_fleet_keyword_are_left_alone(self, code):
        assert _migrate(code) == (code, [])

    def test_c1_827_a_second_run_changes_nothing(self):
        once, _ = _migrate("x.adam.lookup(['TRTSDT'], dataset=adsl, on='USUBJID')")
        assert _migrate(once) == (once, [])

    def test_c1_827_hidden_folders_and_venvs_are_not_walked(self, tmp_path, capsys):
        from fleet.tools.migrate import main

        for folder in (".venv/lib", "venv/lib", "programs"):
            (tmp_path / folder).mkdir(parents=True)
            (tmp_path / folder / "x.py").write_text("x.sdtm.assign_no_ct('A')\n", encoding="utf-8")
        (tmp_path / "venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
        assert main([str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "programs/x.py" in out
        assert "venv" not in out

    def test_c1_826_assign_dtc_becomes_date_with_format(self):
        out, _ = _migrate("dm.sdtm.assign_dtc('RFSTDTC', source='a', input_format='x')")
        assert out == "dm.sdtm.date('RFSTDTC', source='a', format='x')"

    def test_c1_826_remove_dup_is_reported(self, tmp_path, capsys):
        from fleet.tools.migrate import main

        f = tmp_path / "p.py"
        f.write_text("x.sdtm.remove_dup(subset=['USUBJID'])\n", encoding="utf-8")
        assert main([str(f), "--write"]) == 1
        err = capsys.readouterr().err
        assert "left as is, rewrite by hand: line 1: .remove_dup()" in err
        assert "Nothing to migrate" not in err

    def test_c1_828_the_comment_of_the_keep_list_stays(self):
        code = (
            "x.adam.lookup(['TRTSDT', 'TRTEDT'],  # keep the dates: SAP 9.1\n"
            "    dataset=adsl,\n    on='USUBJID')"
        )
        out, _ = _migrate(code)
        assert out == (
            "x.adam.merge(keep=['TRTSDT', 'TRTEDT'],  # keep the dates: SAP 9.1\n"
            "    dataset=adsl,\n    on='USUBJID')"
        )

    def test_c1_828_a_name_as_first_argument_becomes_keep(self):
        out, _ = _migrate("x.adam.lookup(cols, dataset=adsl, on='USUBJID')")
        assert out == "x.adam.merge(keep=cols, dataset=adsl, on='USUBJID')"

    def test_c1_828_an_old_verb_used_as_a_value_is_reported(self):
        notes: list[str] = []
        code = "fn = raw.sdtm.assign_no_ct\n"
        assert migrate_source(code, notes=notes) == (code, [])
        assert notes == ["line 1: .assign_no_ct is used as a value"]

    def test_c1_829_crlf_line_endings_are_kept(self, tmp_path):
        from fleet.tools.migrate import main

        f = tmp_path / "p.py"
        f.write_bytes(b"import x\r\nx.sdtm.assign_no_ct('U', source='s')\r\nprint(1)\r\n")
        assert main([str(f), "--write"]) == 0
        data = f.read_bytes()
        assert b".assign('U'" in data
        assert data.count(b"\n") == data.count(b"\r\n") == 3

    def test_c1_824_a_bad_file_does_not_stop_the_batch(self, tmp_path, capsys):
        from fleet.tools.migrate import main

        bad = tmp_path / "a.py"
        bad.write_text("x.sdtm.assign_no_ct('U')\n", encoding="utf-8")
        bad.chmod(0o444)
        (tmp_path / "b.py").write_text("def broken(:\n", encoding="utf-8")
        (tmp_path / "c.py").write_text("x.sdtm.assign_no_ct('U')\n", encoding="utf-8")
        try:
            assert main([str(tmp_path), "--write"]) == 1
        finally:
            bad.chmod(0o644)
        err = capsys.readouterr().err
        assert "b.py: failed to migrate" in err
        assert "Nothing to migrate" not in err
        assert ".assign('U')" in (tmp_path / "c.py").read_text(encoding="utf-8")
        if os.geteuid() != 0:  # root writes a read-only file
            assert "a.py: cannot write" in err
