"""Executable-docs guardrail — run the code blocks in the flagship docs.

This test extracts fenced code blocks from two docs sources and executes
them so a copy-pasted example can never silently rot:

* ``docs/concepts/define-yaml.md`` — every ``python`` block and every
  ``yaml`` block (yaml is checked for syntax, and a full-spec yaml block
  is written to ``define.yaml`` in the temp cwd so a following
  ``from_spec("define.yaml")`` block can execute it).
* ``GUIDE.md`` — the code-driven DM pipeline (Part 4), the unbroken
  ``flag -> baseline -> chg`` ADVS chain (Part 8), and the ADAE OCCDS
  chain (Part 9). These run against tiny in-memory frames seeded by the
  harness.

Marker convention
-----------------
A block is executed **by default**. To mark a block as intentionally
illustrative (a fragment, or one that needs files/services not present
in the harness), put the HTML comment ``<!-- docs:no-run -->`` on the
line immediately before its opening fence::

    <!-- docs:no-run -->

    ```python
    # not executed by the guardrail
    ```

The same convention is documented at the top of ``docs/concepts/define-yaml.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import yaml

import fleet  # noqa: F401 — registers the namespaces used by the doc blocks

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFINE_YAML_DOC = REPO_ROOT / "docs" / "concepts" / "define-yaml.md"
GUIDE = REPO_ROOT / "GUIDE.md"

_FENCE_RE = re.compile(
    r"(?P<marker><!--\s*docs:no-run\s*-->\s*\n\s*\n)?```(?P<lang>python|yaml)\n"
    r"(?P<body>.*?)\n```",
    re.DOTALL,
)


def _iter_blocks(text: str):
    """Yield ``(lang, body, run)`` for every python/yaml fence in *text*."""
    for m in _FENCE_RE.finditer(text):
        run = m.group("marker") is None
        yield m.group("lang"), m.group("body"), run


def _section(text: str, start_heading: str, stop_prefix: str = "## ") -> str:
    """Return the slice of *text* from *start_heading* to the next ``## ``."""
    start = text.index(start_heading)
    rest = text[start + len(start_heading) :]
    end = rest.find(f"\n{stop_prefix}")
    return start_heading + (rest if end == -1 else rest[:end])


# --------------------------------------------------------------------------- #
# GUIDE fixtures — tiny in-memory frames shared by the enforced pipelines      #
# --------------------------------------------------------------------------- #


def _guide_namespace() -> dict:
    """Seed the variables the GUIDE Part 4/8/9 blocks reference."""
    dm_raw = pl.from_repr("""\
┌────────────────┬─────────┬─────┬─────┬───────────────────────────┬────────────────────────┬──────────┬──────────────────────┬─────────────────┬────────────────┬───────────────────────┐
│ patient_number ┆ site_id ┆ age ┆ sex ┆ race                      ┆ ethnic                 ┆ arm_code ┆ arm_description      ┆ first_dose_date ┆ last_dose_date ┆ informed_consent_date │
│ ---            ┆ ---     ┆ --- ┆ --- ┆ ---                       ┆ ---                    ┆ ---      ┆ ---                  ┆ ---             ┆ ---            ┆ ---                   │
│ str            ┆ i64     ┆ i64 ┆ str ┆ str                       ┆ str                    ┆ str      ┆ str                  ┆ str             ┆ str            ┆ str                   │
╞════════════════╪═════════╪═════╪═════╪═══════════════════════════╪════════════════════════╪══════════╪══════════════════════╪═════════════════╪════════════════╪═══════════════════════╡
│ 01-701-1015    ┆ 701     ┆ 63  ┆ F   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Pbo      ┆ Placebo              ┆ 2014-01-02      ┆ 2014-07-02     ┆ 2014-01-01            │
│ 01-701-1023    ┆ 701     ┆ 64  ┆ F   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Xan_Lo   ┆ Xanomeline Low Dose  ┆ 2014-01-03      ┆ 2014-07-04     ┆ 2014-01-02            │
│ 01-701-1028    ┆ 701     ┆ 71  ┆ M   ┆ BLACK OR AFRICAN AMERICAN ┆ NOT HISPANIC OR LATINO ┆ Xan_Hi   ┆ Xanomeline High Dose ┆ 2014-01-04      ┆ 2014-07-05     ┆ 2014-01-03            │
└────────────────┴─────────┴─────┴─────┴───────────────────────────┴────────────────────────┴──────────┴──────────────────────┴─────────────────┴────────────────┴───────────────────────┘
""")
    ae_raw = pl.from_repr("""\
┌────────────────┬───────────┬───────────────┬─────────────┬─────────────┬────────────┬────────────────────┬──────────────────┬──────────────────┐
│ patient_number ┆ ae_term   ┆ ae_start_date ┆ ae_end_date ┆ ae_severity ┆ ae_serious ┆ ae_outcome         ┆ ae_action_taken  ┆ ae_relationship  │
│ ---            ┆ ---       ┆ ---           ┆ ---         ┆ ---         ┆ ---        ┆ ---                ┆ ---              ┆ ---              │
│ str            ┆ str       ┆ str           ┆ str         ┆ str         ┆ str        ┆ str                ┆ str              ┆ str              │
╞════════════════╪═══════════╪═══════════════╪═════════════╪═════════════╪════════════╪════════════════════╪══════════════════╪══════════════════╡
│ 01-701-1015    ┆ HEADACHE  ┆ 2014-01-10    ┆ 2014-01-12  ┆ MILD        ┆ N          ┆ RECOVERED/RESOLVED ┆ DOSE NOT CHANGED ┆ POSSIBLY RELATED │
│ 01-701-1015    ┆ NAUSEA    ┆ 2014-02-05    ┆ 2014-02-06  ┆ MODERATE    ┆ Y          ┆ RECOVERED/RESOLVED ┆ DOSE NOT CHANGED ┆ NOT RELATED      │
│ 01-701-1023    ┆ DIZZINESS ┆ 2014-01-15    ┆ 2014-01-16  ┆ MILD        ┆ N          ┆ RECOVERED/RESOLVED ┆ DOSE NOT CHANGED ┆ POSSIBLY RELATED │
└────────────────┴───────────┴───────────────┴─────────────┴─────────────┴────────────┴────────────────────┴──────────────────┴──────────────────┘
""")
    vs_raw = pl.from_repr("""\
┌────────────────┬─────────────┬──────────┬──────────────────────────┬─────────┬──────────┬────────────┬──────┐
│ patient_number ┆ site_number ┆ vstestcd ┆ vstest                   ┆ vsorres ┆ vsorresu ┆ vsdtc      ┆ vsdy │
│ ---            ┆ ---         ┆ ---      ┆ ---                      ┆ ---     ┆ ---      ┆ ---        ┆ ---  │
│ str            ┆ i64         ┆ str      ┆ str                      ┆ str     ┆ str      ┆ str        ┆ i64  │
╞════════════════╪═════════════╪══════════╪══════════════════════════╪═════════╪══════════╪════════════╪══════╡
│ 01-701-1015    ┆ 701         ┆ SYSBP    ┆ Systolic Blood Pressure  ┆ 117     ┆ mmHg     ┆ 2013-12-26 ┆ -7   │
│ 01-701-1015    ┆ 701         ┆ SYSBP    ┆ Systolic Blood Pressure  ┆ 121     ┆ mmHg     ┆ 2014-01-01 ┆ -1   │
│ 01-701-1015    ┆ 701         ┆ SYSBP    ┆ Systolic Blood Pressure  ┆ 124     ┆ mmHg     ┆ 2014-01-16 ┆ 15   │
│ 01-701-1015    ┆ 701         ┆ DIABP    ┆ Diastolic Blood Pressure ┆ 76      ┆ mmHg     ┆ 2013-12-26 ┆ -7   │
│ 01-701-1015    ┆ 701         ┆ DIABP    ┆ Diastolic Blood Pressure ┆ 78      ┆ mmHg     ┆ 2014-01-01 ┆ -1   │
│ 01-701-1015    ┆ 701         ┆ DIABP    ┆ Diastolic Blood Pressure ┆ 80      ┆ mmHg     ┆ 2014-01-16 ┆ 15   │
│ 01-701-1023    ┆ 701         ┆ SYSBP    ┆ Systolic Blood Pressure  ┆ 112     ┆ mmHg     ┆ 2013-12-26 ┆ -7   │
│ 01-701-1023    ┆ 701         ┆ SYSBP    ┆ Systolic Blood Pressure  ┆ 118     ┆ mmHg     ┆ 2014-01-01 ┆ -1   │
│ 01-701-1023    ┆ 701         ┆ SYSBP    ┆ Systolic Blood Pressure  ┆ 115     ┆ mmHg     ┆ 2014-01-16 ┆ 15   │
│ 01-701-1023    ┆ 701         ┆ DIABP    ┆ Diastolic Blood Pressure ┆ 71      ┆ mmHg     ┆ 2013-12-26 ┆ -7   │
│ 01-701-1023    ┆ 701         ┆ DIABP    ┆ Diastolic Blood Pressure ┆ 74      ┆ mmHg     ┆ 2014-01-01 ┆ -1   │
│ 01-701-1023    ┆ 701         ┆ DIABP    ┆ Diastolic Blood Pressure ┆ 73      ┆ mmHg     ┆ 2014-01-16 ┆ 15   │
└────────────────┴─────────────┴──────────┴──────────────────────────┴─────────┴──────────┴────────────┴──────┘
""")

    # SDTM DM (canonical verbs) — what Part 4.1 produces.
    from examples.cdiscpilot01.sdtm.codelists import ETHNIC, RACE, SEX

    dm = (
        dm_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
        .assign("DOMAIN", value="DM")
        .assign("USUBJID", source="patient_number")
        .assign("SUBJID", source="patient_number")
        .derivation("SITEID", expression="pl.col('site_id').cast(pl.String)")
        .assign("AGE", source="age")
        .assign("AGEU", value="YEARS")
        .assign("SEX", source="sex", ct=SEX, ct_map={"F": "F", "M": "M"})
        .assign("RACE", source="race", ct=RACE)
        .assign("ETHNIC", source="ethnic", ct=ETHNIC)
        .assign("ARM", source="arm_description")
        .assign("ARMCD", source="arm_code")
        .assign("ACTARM", source="arm_description")
        .assign("ACTARMCD", source="arm_code")
        .date("RFSTDTC", source="first_dose_date")
        .date("RFENDTC", source="last_dose_date")
        .to_frame()
    )
    ae = (
        ae_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
        .assign("DOMAIN", value="AE")
        .assign("USUBJID", source="patient_number")
        .assign("AETERM", source="ae_term")
        .date("AESTDTC", source="ae_start_date")
        .date("AEENDTC", source="ae_end_date")
        .assign("AESEV", source="ae_severity")
        .assign("AESER", source="ae_serious")
        .assign("AEOUT", source="ae_outcome")
        .assign("AEACN", source="ae_action_taken")
        .ae_aerel("AEREL", source="ae_relationship")
        .to_frame()
    )
    ex = (
        dm.sdtm.assign("USUBJID", source="USUBJID")
        .assign("EXSTDTC", source="RFSTDTC")
        .assign("EXENDTC", source="RFENDTC")
        .assign("EXDOSE", value=54.0)
        .to_frame()
    )
    ds = (
        dm.sdtm.assign("USUBJID", source="USUBJID")
        .assign("DSCAT", value="DISPOSITION EVENT")
        .assign("DSDECOD", value="COMPLETED")
        .assign("DSSTDTC", source="RFENDTC")
        .to_frame()
    )
    adsl = (
        dm.adam.adsl.source("STUDYID", "USUBJID", "AGE", "SEX", "ARM", "ARMCD", "ACTARM")
        .assign("TRT01P", source="ARM")
        .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
        .last_date("TRTEDT", from_dataset=ex, date_col="EXENDTC")
        .flag("SAFFL", criteria='pl.col("TRTSDT").is_not_null()', false_value="N")
        .to_frame()
    )

    return {
        "pl": pl,
        "fleet": fleet,
        "dm_raw": dm_raw,
        "ae_raw": ae_raw,
        "vs_raw": vs_raw,
        "dm": dm,
        "ae": ae,
        "ex": ex,
        "ds": ds,
        "adsl": adsl,
    }


def _guide_enforced_python_blocks() -> list[str]:
    """Return the runnable python blocks under GUIDE Parts 4, 8, 9."""
    text = GUIDE.read_text(encoding="utf-8")
    blocks: list[str] = []
    for heading in (
        "## Part 4 — SDTM Derivation: DM",
        "## Part 8 — ADaM Derivation: ADVS",
        "## Part 9 — ADAE with OCCDS Verbs",
        "## Part 10 — Trial Design Domains (TDD)",
    ):
        section = _section(text, heading)
        for lang, body, run in _iter_blocks(section):
            if lang == "python" and run:
                blocks.append(body)
    return blocks


# --------------------------------------------------------------------------- #
# Tests                                                                         #
# --------------------------------------------------------------------------- #


def test_guide_pipeline_blocks_execute(tmp_path, monkeypatch):
    """GUIDE Part 4/8/9 pipeline blocks run (unbroken flag->baseline->chg chain)."""
    blocks = _guide_enforced_python_blocks()
    assert len(blocks) >= 3, f"expected >=3 enforced GUIDE blocks, found {len(blocks)}"

    ns = _guide_namespace()
    monkeypatch.chdir(tmp_path)
    for body in blocks:
        exec(compile(body, "<guide>", "exec"), ns)  # noqa: S102 — trusted doc source

    # Part 8 built the unbroken ADVS chain: ABLFL, BASE, CHG all present.
    advs = ns["advs"]
    assert {"ABLFL", "BASE", "CHG", "PCHG", "ADY"}.issubset(advs.columns)
    baseline_rows = advs.filter(pl.col("ABLFL") == "Y")
    assert (baseline_rows["CHG"] == 0.0).all()  # CHG is 0 at baseline
    # c1-587: two pre-dose records; the last one (day -1) is the baseline.
    assert baseline_rows.height == 4
    sysbp = advs.filter((pl.col("USUBJID") == "01-701-1015") & (pl.col("PARAMCD") == "SYSBP"))
    assert sysbp["BASE"].unique().to_list() == [121.0]
    # Part 9 built ADAE with TRTEMFL + ASEQ.
    assert {"TRTEMFL", "ASEQ", "AESEVN"}.issubset(ns["adae"].columns)
    # Part 10 built the trial design domains offline (StudyDesign + pipeline).
    assert set(ns["design"].domains()) >= {"TE", "TA", "TS"}
    assert {"TABRANCH", "TAETORD"}.issubset(ns["ta"].columns)
    assert "TSSEQ" in ns["ts"].columns
    assert ns["td"].shape[0] == 1 and ns["tm"].shape[0] == 1


def test_readme_blocks_execute(tmp_path, monkeypatch):
    """c1-179: every python block of the README (the PyPI page) runs as written, in an empty folder."""
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    ns: dict = {}

    ran_python = 0
    for lang, body, run in _iter_blocks(text):
        if not run:
            continue
        if lang == "yaml":
            loaded = yaml.safe_load(body)
            if isinstance(loaded, dict) and "datasets" in loaded:
                (tmp_path / "define.yaml").write_text(body, encoding="utf-8")
        else:
            exec(compile(body, "<README>", "exec"), ns)  # noqa: S102 — trusted doc source
            ran_python += 1

    assert ran_python == 3
    assert {"ADY", "BASE", "CHG"}.issubset(ns["advs"].columns)
    assert ns["dm"]["SEX"].to_list() == ["F", "M", "M"]  # the spec-driven DM, last block
    assert ns["dm"]["STUDYID"].to_list() == ["CDISCPILOT01"] * 3
    adsl = ns["adsl"]
    assert adsl.columns == [
        "STUDYID",
        "USUBJID",
        "AGE",
        "SEX",
        "ARM",
        "TRT01P",
        "TRTSDT",
        "TRTEDT",
        "TRTDURD",
        "SAFFL",
    ]
    assert set(adsl["SAFFL"].to_list()) <= {"Y", "N"}


def test_quickstart_blocks_execute(tmp_path, monkeypatch):
    """c1-848: every python block of the quickstart runs as written, in an empty folder.

    The page generates ``codelists.py`` with ``fleet add-ct``, which needs the
    CDISC Library; the pilot's generated file stands in for it.
    """
    text = (REPO_ROOT / "docs" / "getting-started" / "quickstart.md").read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(REPO_ROOT / "examples" / "cdiscpilot01" / "sdtm"))
    ns: dict = {}

    ran_python = 0
    for lang, body, run in _iter_blocks(text):
        if run and lang == "python":
            exec(compile(body, "<quickstart>", "exec"), ns)  # noqa: S102 — trusted doc source
            ran_python += 1

    assert ran_python == 6
    assert ns["dm"]["SEX"].to_list() == ["M", "F", "M"]
    assert {"BASE", "CHG", "PCHG"}.issubset(ns["advs"].columns)
    assert ns["adsl"]["SAFFL"].to_list() == ["Y", "Y"]
    assert (tmp_path / "studies" / "MYSTUDY01" / "study_config.yaml").is_file()


def test_define_yaml_doc_blocks_execute(tmp_path, monkeypatch):
    """Every non-illustrative code block in define-yaml.md runs / parses."""
    text = DEFINE_YAML_DOC.read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    ns = {"pl": pl, "fleet": fleet}

    ran_python = 0
    for lang, body, run in _iter_blocks(text):
        if not run:
            continue
        if lang == "yaml":
            loaded = yaml.safe_load(body)
            # A full spec block becomes define.yaml so a following
            # from_spec("define.yaml") block can execute it.
            if isinstance(loaded, dict) and "datasets" in loaded:
                (tmp_path / "define.yaml").write_text(body, encoding="utf-8")
        elif lang == "python":
            exec(compile(body, "<define-yaml>", "exec"), ns)  # noqa: S102
            ran_python += 1

    assert ran_python >= 3, f"expected >=3 runnable python blocks, ran {ran_python}"
    # The flagship first_date spec executed and produced TRTSDT.
    assert "adsl" in ns
    assert "TRTSDT" in ns["adsl"].columns


_DOCSTRING_MODULES = [
    "fleet.core._verb_mixin",
    "fleet.core._flag_mixin",
    "fleet.sdtm.namespace",
    "fleet.adam._mixins",
    "fleet.adam.namespace",
    "fleet.adam.adsl_namespace",
    "fleet.adam.occds_namespace",
]


def _docstring_example_blocks(doc: str):
    """Yield the code blocks under a Google-style ``Examples:`` section."""
    if not doc or "Examples:" not in doc:
        return
    lines = doc.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "Examples:")
    except StopIteration:
        return
    block: list[str] = []
    in_code = False
    code_indent: int | None = None
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.endswith("::"):
            if block:
                yield "\n".join(block)
                block = []
            in_code = True
            code_indent = None
            continue
        if in_code:
            if not stripped:
                block.append("")
                continue
            indent = len(line) - len(line.lstrip())
            if code_indent is None:
                code_indent = indent
            if indent < code_indent:
                in_code = False
                if block:
                    yield "\n".join(block)
                    block = []
                continue
            block.append(line[code_indent:])
    if block:
        yield "\n".join(block)


def test_docstring_examples_are_valid_python():
    """Every verb-module ``Examples::`` block parses as Python (no syntax rot).

    The docstring examples are narrative Google-style snippets (they reference
    fixture frames like ``raw_df``), so they are not runnable ``>>>`` doctests
    and ``--doctest-modules`` collects nothing. This guard still catches the
    kind of rot that matters — a broken chain, an unbalanced call — by
    ``ast.parse``-ing every block.
    """
    import ast
    import importlib
    import textwrap

    checked = 0
    failures: list[str] = []
    for modname in _DOCSTRING_MODULES:
        mod = importlib.import_module(modname)
        for cls_name, cls in vars(mod).items():
            if not isinstance(cls, type) or not cls.__module__.startswith("fleet."):
                continue
            for name, attr in vars(cls).items():
                if name.startswith("_") or not callable(attr):
                    continue
                for code in _docstring_example_blocks(attr.__doc__ or ""):
                    checked += 1
                    try:
                        ast.parse(textwrap.dedent(code))
                    except SyntaxError as exc:  # pragma: no cover - failure path
                        failures.append(f"{modname}.{cls_name}.{name}: {exc}")
    assert not failures, "docstring example syntax errors:\n" + "\n".join(failures)
    assert checked > 50, f"expected many docstring examples, found {checked}"


def test_no_run_marker_is_respected():
    """A ``docs:no-run`` block is not counted as runnable."""
    sample = (
        "<!-- docs:no-run -->\n\n```python\nraise RuntimeError('should not run')\n```\n\n"
        "```python\nx = 1\n```\n"
    )
    blocks = list(_iter_blocks(sample))
    runnable = [b for lang, b, run in blocks if run]
    assert len(runnable) == 1
    assert "x = 1" in runnable[0]


def test_tdd_se_block_executes():
    """c1-588: the SE block of docs/concepts/tdd.md runs and gives element boundaries."""
    text = (REPO_ROOT / "docs" / "concepts" / "tdd.md").read_text(encoding="utf-8")
    (body,) = [
        b for lang, b, _ in _iter_blocks(text) if lang == "python" and ".element_boundaries(" in b
    ]
    ns: dict = {"pl": pl}
    exec(compile(body, "<tdd.md>", "exec"), ns)  # noqa: S102 — trusted doc source
    se = ns["se"]
    assert se["SEENDTC"].to_list() == ["2014-01-02", None]
    assert se["SESEQ"].to_list() == [1, 2]
