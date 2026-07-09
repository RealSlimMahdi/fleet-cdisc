"""CT unification tests (§4.3): one CT truth reachable from every path.

* ``from_spec`` honours the spec-level ``ct: {validate: true, file: …}``
  block — assign-family derivations validate values and the warning
  names dataset, variable, and codelist;
* ``DatasetChecker`` verifies values against the spec's own inline
  ``codelists:`` items (ERROR on out-of-codelist values, with decode /
  ``ct_mapping`` hints);
* ``CTValidator`` resolves aliases at load time so a codelist is
  reachable by OID (C66731) or registered name (SEX) interchangeably.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet  # noqa: F401
from fleet.core.exceptions import SpecError
from fleet.ct.validator import CTValidator, get_validator
from fleet.define_xml.checker import DatasetChecker

# ────────────────────────────────────────────────────────────────────
# from_spec: spec-level ct block
# ────────────────────────────────────────────────────────────────────


@pytest.fixture
def ct_file(tmp_path: Path) -> Path:
    p = tmp_path / "ct.yaml"
    p.write_text(yaml.safe_dump({"C66731": {"M": "Male", "F": "Female"}}))
    return p


def _dm_spec(tmp_path: Path, ct: dict | None, ct_mapping: dict | None = None) -> Path:
    derivation: dict = {"algorithm": "assign_ct", "source": "sex", "ct_codelist": "C66731"}
    if ct_mapping is not None:
        derivation["ct_mapping"] = ct_mapping
    spec: dict = {
        "datasets": [
            {
                "name": "DM",
                "variables": [
                    {
                        "name": "DOMAIN",
                        "derivation": {"algorithm": "hardcode_no_ct", "value": "DM"},
                    },
                    {"name": "SEX", "derivation": derivation},
                ],
            }
        ]
    }
    if ct is not None:
        spec["ct"] = ct
    p = tmp_path / "define.yaml"
    p.write_text(yaml.safe_dump(spec))
    return p


@pytest.fixture
def _restore_singleton():
    validator = get_validator()
    cache, aliases = dict(validator._ct_cache), dict(validator._codelist_aliases)
    yield
    validator._ct_cache, validator._codelist_aliases = cache, aliases


@pytest.mark.usefixtures("_restore_singleton")
class TestFromSpecCTConfig:
    def test_validate_true_warns_naming_dataset_variable_codelist(self, tmp_path, ct_file):
        spec = _dm_spec(
            tmp_path,
            ct={"validate": True, "file": ct_file.name},
            ct_mapping={"F": "F", "M": "M"},
        )
        df = pl.DataFrame({"sex": ["F", "UNKNOWN"]})
        with pytest.warns(UserWarning, match=r"DM\.SEX.*'sex'.*not in codelist 'C66731'"):
            df.sdtm.from_spec(spec, dataset="DM").to_frame()

    def test_validate_true_passthrough_warns(self, tmp_path, ct_file):
        spec = _dm_spec(tmp_path, ct={"validate": True, "file": ct_file.name})
        df = pl.DataFrame({"sex": ["Female"]})
        with pytest.warns(UserWarning, match=r"not in codelist 'C66731'.*Female"):
            df.sdtm.from_spec(spec, dataset="DM").to_frame()

    def test_no_ct_block_behaves_as_before(self, tmp_path, ct_file):
        """Back-compat: a mapped assign_ct without ct: stays silent."""
        get_validator().load_ct_file(ct_file)
        spec = _dm_spec(tmp_path, ct=None, ct_mapping={"F": "F", "M": "M"})
        df = pl.DataFrame({"sex": ["F", "UNKNOWN"]})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            df.sdtm.from_spec(spec, dataset="DM").to_frame()
        assert not [w for w in caught if "not in codelist" in str(w.message)]

    def test_validate_false_is_inert(self, tmp_path, ct_file):
        spec = _dm_spec(
            tmp_path, ct={"validate": False, "file": ct_file.name}, ct_mapping={"F": "F"}
        )
        df = pl.DataFrame({"sex": ["UNKNOWN"]})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            df.sdtm.from_spec(spec, dataset="DM").to_frame()
        assert not [w for w in caught if "not in codelist" in str(w.message)]

    def test_unloadable_ct_file_raises_spec_error(self, tmp_path):
        spec = _dm_spec(tmp_path, ct={"validate": True, "file": "missing_ct.yaml"})
        df = pl.DataFrame({"sex": ["F"]})
        with pytest.raises(SpecError, match=r"ct\.file 'missing_ct\.yaml'"):
            df.sdtm.from_spec(spec, dataset="DM")


# ────────────────────────────────────────────────────────────────────
# DatasetChecker: inline codelists
# ────────────────────────────────────────────────────────────────────


CHECKER_SPEC = {
    "codelists": [
        {
            "oid": "C66731",
            "name": "Sex",
            "type": "text",
            "items": [
                {"coded_value": "M", "decode": "Male"},
                {"coded_value": "F", "decode": "Female"},
            ],
        }
    ],
    "datasets": [
        {
            "name": "DM",
            "label": "Demographics",
            "structure": "One record per subject",
            "keys": ["USUBJID"],
            "variables": [
                {"name": "USUBJID", "label": "Unique Subject Identifier", "type": "text"},
                {
                    "name": "SEX",
                    "label": "Sex",
                    "type": "text",
                    "codelist": "C66731",
                    "derivation": {
                        "algorithm": "assign_ct",
                        "source": "sex_raw",
                        "ct_codelist": "C66731",
                        "ct_mapping": {"1": "M", "2": "F"},
                    },
                },
            ],
        }
    ],
}


@pytest.fixture
def checker(tmp_path: Path) -> DatasetChecker:
    p = tmp_path / "define.yaml"
    p.write_text(yaml.safe_dump(CHECKER_SPEC))
    return DatasetChecker(p, validate_schema=False)


class TestCheckerInlineCodelists:
    def test_valid_values_pass(self, checker):
        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ SEX │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ S1      ┆ M   │
│ S2      ┆ F   │
└─────────┴─────┘
""")
        result = checker.check(df, dataset="DM")
        assert result.is_valid
        assert result.ct_violations == []

    def test_out_of_codelist_value_is_error(self, checker):
        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ SEX │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ S1      ┆ X   │
└─────────┴─────┘
""")
        result = checker.check(df, dataset="DM")
        assert not result.is_valid
        (msg,) = result.ct_violations
        assert "SEX" in msg and "C66731" in msg and "Sex" in msg
        assert "['X']" in msg and "['F', 'M']" in msg
        assert msg in result.errors

    def test_decode_hint(self, checker):
        df = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ SEX  │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ Male │
└─────────┴──────┘
""")
        result = checker.check(df, dataset="DM")
        (msg,) = result.ct_violations
        assert "'Male' is the decode of submission value 'M'" in msg

    def test_ct_mapping_hint(self, checker):
        """A raw mapping key in the data means the mapping never ran."""
        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ SEX │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ S1      ┆ 1   │
└─────────┴─────┘
""")
        result = checker.check(df, dataset="DM")
        (msg,) = result.ct_violations
        assert "raw ct_mapping key" in msg

    def test_nulls_ignored(self, checker):
        df = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ SEX  │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ null │
└─────────┴──────┘
""")
        result = checker.check(df, dataset="DM")
        assert result.ct_violations == []

    def test_undeclared_codelist_ref_warns(self, tmp_path):
        spec = yaml.safe_load(yaml.safe_dump(CHECKER_SPEC))
        spec["datasets"][0]["variables"][1]["codelist"] = "C99999"
        p = tmp_path / "define.yaml"
        p.write_text(yaml.safe_dump(spec))
        checker = DatasetChecker(p, validate_schema=False)
        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ SEX │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ S1      ┆ M   │
└─────────┴─────┘
""")
        result = checker.check(df, dataset="DM")
        assert any("C99999" in w for w in result.warnings)
        assert result.ct_violations == []

    def test_check_ct_false_disables(self, tmp_path):
        p = tmp_path / "define.yaml"
        p.write_text(yaml.safe_dump(CHECKER_SPEC))
        checker = DatasetChecker(p, validate_schema=False, check_ct=False)
        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ SEX │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ S1      ┆ X   │
└─────────┴─────┘
""")
        result = checker.check(df, dataset="DM")
        assert result.ct_violations == []
        assert result.is_valid


# ────────────────────────────────────────────────────────────────────
# CTValidator: concept-ID normalisation
# ────────────────────────────────────────────────────────────────────


class TestAliasNormalisation:
    def _file(self, tmp_path: Path, key: str) -> Path:
        p = tmp_path / f"ct_{key}.yaml"
        p.write_text(yaml.safe_dump({key: {"M": "Male", "F": "Female"}}))
        return p

    def test_name_keyed_file_reachable_by_oid_and_name(self, tmp_path):
        """CT file keyed `SEX:` + alias {SEX: C66731} → both spellings work."""
        v = CTValidator()
        v.load_ct_file(self._file(tmp_path, "SEX"), aliases={"SEX": "C66731"})
        assert v.has_codelist("C66731") and v.has_codelist("SEX")
        assert v.validate_value("C66731", "M")[0]
        assert v.validate_value("SEX", "M")[0]
        assert v.get_valid_values("SEX") == v.get_valid_values("C66731") == ["F", "M"]

    def test_oid_keyed_file_reachable_by_oid_and_name(self, tmp_path):
        v = CTValidator()
        v.load_ct_file(self._file(tmp_path, "C66731"), aliases={"SEX": "C66731"})
        assert v.has_codelist("C66731") and v.has_codelist("SEX")
        assert not v.validate_value("SEX", "X")[0]

    def test_register_alias_after_load_rekeys(self, tmp_path):
        v = CTValidator()
        v.load_ct_file(self._file(tmp_path, "SEX"))
        assert not v.has_codelist("C66731")
        v.register_alias("SEX", "C66731")
        assert v.has_codelist("C66731")
        assert v.get_decode_map("C66731") == v.get_decode_map("SEX")

    def test_unknown_name_returned_unchanged(self, tmp_path):
        v = CTValidator()
        v.load_ct_file(self._file(tmp_path, "C66731"))
        valid, msg = v.validate_value("NOPE", "M")
        assert valid  # not-loaded semantics unchanged (skip with warning)
        assert "NOPE" in msg
