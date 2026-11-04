"""Regression tests for the documentation findings (README, quickstart, GUIDE, examples)."""

from __future__ import annotations

import ast
import importlib
import re
import runpy
import subprocess
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet  # noqa: F401 — registers the namespaces
from fleet.core import spec_registry

REPO_ROOT = Path(__file__).resolve().parents[2]

_BASH_FENCE = re.compile(r"^[ \t]*```bash[^\n]*\n(?P<body>.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)
_PY_FENCE = re.compile(r"^[ \t]*```python[^\n]*\n(?P<body>.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)
_YAML_FENCE = re.compile(
    r"^[ \t]*```ya?ml[^\n]*\n(?P<body>.*?)^[ \t]*```", re.DOTALL | re.MULTILINE
)

FIRST_RUN_PAGES = [
    "README.md",
    "docs/getting-started/quickstart.md",
    "docs/getting-started/installation.md",
    "docs/examples/full_pipeline.md",
]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _commands(block: str) -> list[str]:
    """Return the shell commands of a bash block: continuations joined, comments removed."""
    joined = re.sub(r"\\\n\s*", " ", block)
    commands = []
    for line in joined.splitlines():
        cmd = line.split("#", 1)[0].strip()
        if cmd:
            commands.append(cmd)
    return commands


def _dedent_block(body: str) -> str:
    lines = body.splitlines()
    indent = min((len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()), default=0)
    return "\n".join(ln[indent:] for ln in lines)


# --------------------------------------------------------------------------- #
# c1-181, c1-193: the first-run lines run as printed                          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("page", FIRST_RUN_PAGES)
def test_first_run_commands_go_through_uv_run(page):
    """c1-193: bare ``fleet`` and ``python`` are not on the path of a uv project."""
    bare = [
        cmd
        for m in _BASH_FENCE.finditer(_read(page))
        for cmd in _commands(m.group("body"))
        if cmd.split()[0] in {"fleet", "python"}
    ]
    assert bare == []


@pytest.mark.parametrize("page", FIRST_RUN_PAGES)
def test_init_cfg_with_root_is_followed_by_cd(page):
    """c1-181: ``fleet init define`` must run inside the folder that ``init cfg --root`` made."""
    checked = 0
    for m in _BASH_FENCE.finditer(_read(page)):
        cmds = _commands(m.group("body"))
        for i, cmd in enumerate(cmds):
            root = re.search(r"fleet init cfg .*--root (\S+)", cmd)
            if root is None or i + 1 == len(cmds):
                continue
            checked += 1
            target = root.group(1).removeprefix("./")
            assert cmds[i + 1] == f"cd {target}", f"{page}: no cd after {cmd!r}"
    if page != "docs/getting-started/installation.md":
        assert checked == 1


@pytest.mark.parametrize("page", ["README.md", "docs/getting-started/installation.md"])
def test_uv_add_follows_uv_init(page):
    """c1-193: ``uv add`` in an empty folder needs a project first."""
    for m in _BASH_FENCE.finditer(_read(page)):
        cmds = _commands(m.group("body"))
        for i, cmd in enumerate(cmds):
            if cmd.startswith("uv add fleet-cdisc --prerelease"):
                assert any(c.startswith("uv init") for c in cmds[:i]), page


# --------------------------------------------------------------------------- #
# c1-184, c1-684: no "submission-ready" claim; DM keeps only DM variables     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("page", ["README.md", "docs/index.md", "docs/examples/full_pipeline.md"])
def test_no_submission_ready_claim(page):
    """c1-184: the demo frame is SDTM-shaped, not a submission."""
    assert "submission-ready" not in _read(page).lower()


def test_readme_quick_demo_dm_has_only_dm_variables(tmp_path, monkeypatch):
    """c1-684: the Quick Demo DM drops the raw columns and is in IG order."""
    first = next(m for m in _PY_FENCE.finditer(_read("README.md")))
    monkeypatch.chdir(tmp_path)
    ns: dict = {}
    exec(compile(first.group("body"), "<README quick demo>", "exec"), ns)  # noqa: S102
    assert ns["dm"].columns == ["STUDYID", "DOMAIN", "USUBJID", "SEX", "RFSTDTC"]


# --------------------------------------------------------------------------- #
# c1-187: the laziness text matches the behaviour                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("page", "phrase"),
    [
        ("docs/why-fleet.md", "Zero overhead"),
        ("docs/why-fleet.md", "No intermediate DataFrames"),
        ("docs/why-fleet.md", "in milliseconds"),
        ("docs/why-fleet.md", "keeps the whole pipeline lazy"),
        ("README.md", "keeps a whole pipeline lazy"),
        ("CONTRIBUTING.md", "Nothing executes until"),
        ("docs/concepts/pick.md", "without materialisation breaks"),
        ("docs/concepts/pipeline.md", "single `df.with_columns(...)` pass"),
    ],
)
def test_no_overclaim_on_laziness(page, phrase):
    assert phrase not in _read(page)


_RAW_DM = """
┌────────────┬─────────┬─────────────────┐
│ patient_id ┆ sex_raw ┆ first_dose_date │
│ ---        ┆ ---     ┆ ---             │
│ str        ┆ str     ┆ str             │
╞════════════╪═════════╪═════════════════╡
│ 001        ┆ F       ┆ 2024-01-15      │
│ 002        ┆ M       ┆ 2024-01-17      │
└────────────┴─────────┴─────────────────┘
"""


def _counting_source() -> tuple[pl.LazyFrame, list[int]]:
    raw = pl.from_repr(_RAW_DM)
    reads: list[int] = []

    def count(df: pl.DataFrame) -> pl.DataFrame:
        reads.append(1)
        return df

    return raw.lazy().map_batches(count, schema=raw.schema), reads


def test_lazy_verbs_do_not_read_the_source_before_to_frame():
    """c1-187: the documented lazy verbs read the source once, at ``.to_frame()``."""
    lf, reads = _counting_source()
    ns = (
        lf.sdtm.assign("DOMAIN", value="DM")
        .assign("STUDYID", value="S1")
        .assign("USUBJID", source="patient_id")
        .assign("SEX", source="sex_raw")
        .derivation("SUBJID", expression=pl.col("patient_id"))
        .case_when("AGEU", when=[{"condition": pl.col("SUBJID") == "001", "value": "YEARS"}])
        .seq("DMSEQ", by=["USUBJID"], order_by=["USUBJID"])
        .keep("STUDYID", "DOMAIN", "USUBJID", "SUBJID", "SEX", "AGEU")
    )
    assert reads == []
    out = ns.to_frame()
    if isinstance(out, pl.LazyFrame):
        out = out.collect()
    assert len(reads) == 1
    assert out.columns == ["STUDYID", "DOMAIN", "USUBJID", "SUBJID", "SEX", "AGEU"]


def test_date_to_dtc_is_a_documented_check():
    """c1-187: ``date`` to a DTC variable reads rows to check the layout, as the docs say."""
    lf, reads = _counting_source()
    lf.sdtm.date("RFSTDTC", source="first_dose_date")
    assert len(reads) == 1
    assert "`date` to a DTC variable" in _read("README.md")


# --------------------------------------------------------------------------- #
# c1-591, c1-592: documented imports resolve; namespaces named right          #
# --------------------------------------------------------------------------- #


def _doc_pages() -> list[Path]:
    pages = [REPO_ROOT / "README.md", REPO_ROOT / "GUIDE.md"]
    pages += sorted(p for p in (REPO_ROOT / "docs").rglob("*.md") if "adr" not in p.parts)
    return [p for p in pages if p.name != "changelog.md"]


def test_every_fleet_import_in_the_docs_resolves():
    """c1-591: ``from fleet... import X`` in a docs python block names a real object."""
    broken = []
    for page in _doc_pages():
        for m in _PY_FENCE.finditer(page.read_text(encoding="utf-8")):
            try:
                tree = ast.parse(_dedent_block(m.group("body")))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                    continue
                if node.module.split(".")[0] != "fleet":
                    continue
                module = importlib.import_module(node.module)
                for alias in node.names:
                    if alias.name == "*" or hasattr(module, alias.name):
                        continue
                    try:
                        importlib.import_module(f"{node.module}.{alias.name}")
                    except ImportError:
                        broken.append(f"{page.relative_to(REPO_ROOT)}: {node.module}.{alias.name}")
    assert broken == []


def test_installation_names_the_real_namespaces():
    """c1-592: ADSL and OCCDS verbs live under ``.adam``, not on the DataFrame."""
    text = _read("docs/getting-started/installation.md")
    assert "`.adsl`, and `.occds` namespaces" not in text
    assert "`.adam.adsl` and `.adam.occds`" in text
    df = pl.from_repr(_RAW_DM)
    assert not hasattr(df, "adsl")
    assert hasattr(df.adam, "adsl") and hasattr(df.adam, "occds")


# --------------------------------------------------------------------------- #
# c1-476: every documented `algorithm:` is a verb that from_spec accepts       #
# --------------------------------------------------------------------------- #


def _tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [
        REPO_ROOT / rel
        for rel in out
        if not rel.startswith("docs/adr/") and rel != "docs/changelog.md"
    ]


def _algorithms(node: object):
    if isinstance(node, dict):
        if isinstance(node.get("algorithm"), str):
            yield node["algorithm"]
        for value in node.values():
            yield from _algorithms(value)
    elif isinstance(node, list):
        for value in node:
            yield from _algorithms(value)


def test_documented_spec_algorithms_are_verbs():
    """c1-476: a yaml block in the docs never teaches a spec name that from_spec refuses."""
    unknown = []
    checked = 0
    for page in _tracked_markdown():
        if not page.is_file():
            continue
        for m in _YAML_FENCE.finditer(page.read_text(encoding="utf-8")):
            try:
                loaded = yaml.safe_load(_dedent_block(m.group("body")))
            except yaml.YAMLError:
                continue
            for name in _algorithms(loaded):
                checked += 1
                if not (
                    spec_registry.get_algorithm("sdtm", name)
                    or spec_registry.get_algorithm("adam", name)
                ):
                    unknown.append(f"{page.relative_to(REPO_ROOT)}: algorithm: {name}")
    assert unknown == []
    assert checked > 10


def test_guide_states_the_hard_cut_on_old_spec_names():
    """c1-476: GUIDE no longer says that old spec names keep working."""
    text = _read("GUIDE.md")
    assert "keeps working" not in text
    assert "algorithm: callable" not in text


# --------------------------------------------------------------------------- #
# c1-474: the rule snapshot is a reference copy, not the rules applied         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("page", ["GUIDE.md", "docs/validation-strategy.md"])
def test_rule_snapshot_is_not_called_an_audit_trail(page):
    text = _read(page)
    for phrase in ("version-locked", "Version lock", "which rules were applied"):
        assert phrase not in text
    assert "reference copy" in text
    assert "install-engine --version" in text


def test_init_rules_message_names_the_engine_pin():
    """c1-474: ``fleet init rules`` does not promise an audit trail of the rules applied."""
    source = (REPO_ROOT / "src" / "fleet" / "cli.py").read_text(encoding="utf-8")
    assert "permanent audit trail" not in source
    assert "Rules cached for reference" in source


# --------------------------------------------------------------------------- #
# c1-674: ADPPK file order and ASEQ                                            #
# --------------------------------------------------------------------------- #


def test_adnca_example_adppk_order_and_aseq(tmp_path, monkeypatch, capsys):
    """c1-674: subjects stay together, the dose follows the pre-dose sample, the file is stable."""
    monkeypatch.chdir(tmp_path)
    runs = [
        runpy.run_path(str(REPO_ROOT / "examples" / "adnca_example.py"))["adppk"] for _ in range(2)
    ]
    capsys.readouterr()
    adppk = runs[0]
    assert adppk.equals(runs[1])

    key = adppk.select("USUBJID", "AFRLT", "EVID", "CMT")
    assert key.equals(key.sort("USUBJID", "AFRLT", "EVID", "CMT"))
    # Subjects together: each USUBJID is one contiguous run of rows.
    runs_per_subject = adppk.select(pl.col("USUBJID").rle_id()).n_unique()
    assert runs_per_subject == adppk["USUBJID"].n_unique()
    # ASEQ is 1..n per subject in file order.
    assert adppk["ASEQ"].to_list() == (
        adppk.select(pl.int_range(1, pl.len() + 1).over("USUBJID")).to_series().to_list()
    )
    first = adppk.filter(pl.col("USUBJID") == "01-701-1015").head(3)
    assert first.select("AFRLT", "EVID", "ASEQ").rows() == [
        (0.0, 0, 1),
        (0.0, 1, 2),
        (0.5, 0, 3),
    ]


# --------------------------------------------------------------------------- #
# c1-678: the documented ADAE chain imputes partial dates as admiral does      #
# --------------------------------------------------------------------------- #


def test_guide_adae_chain_imputes_partial_dates_like_admiral():
    """c1-678 (option A): start to the first day but not before TRTSDT, end to the last day."""
    text = _read("GUIDE.md")
    section = text[text.index("## Part 9 — ADAE with OCCDS Verbs") :]
    block = next(_PY_FENCE.finditer(section)).group("body")

    ae = pl.from_repr("""
┌─────────┬──────────┬────────────┬────────────┬───────┬───────┬───────┬───────┬───────┐
│ USUBJID ┆ AETERM   ┆ AESTDTC    ┆ AEENDTC    ┆ AESEV ┆ AESER ┆ AEREL ┆ AEOUT ┆ AEACN │
│ ---     ┆ ---      ┆ ---        ┆ ---        ┆ ---   ┆ ---   ┆ ---   ┆ ---   ┆ ---   │
│ str     ┆ str      ┆ str        ┆ str        ┆ str   ┆ str   ┆ str   ┆ str   ┆ str   │
╞═════════╪══════════╪════════════╪════════════╪═══════╪═══════╪═══════╪═══════╪═══════╡
│ P1      ┆ HEADACHE ┆ 2014-03-15 ┆ 2014-03    ┆ MILD  ┆ N     ┆ NONE  ┆ R     ┆ NONE  │
│ P2      ┆ NAUSEA   ┆ 2014-01    ┆ 2014-02-10 ┆ MILD  ┆ N     ┆ NONE  ┆ R     ┆ NONE  │
│ P3      ┆ RASH     ┆ 2014       ┆ null       ┆ MILD  ┆ N     ┆ NONE  ┆ R     ┆ NONE  │
│ P5      ┆ COUGH    ┆ 2014-03-15 ┆ 2014       ┆ MILD  ┆ N     ┆ NONE  ┆ R     ┆ NONE  │
└─────────┴──────────┴────────────┴────────────┴───────┴───────┴───────┴───────┴───────┘
""")
    adsl = pl.from_repr("""
┌─────────┬────────────┬────────────┬────────┬─────┬─────┬───────┐
│ USUBJID ┆ TRTSDT     ┆ TRTEDT     ┆ TRT01P ┆ AGE ┆ SEX ┆ SAFFL │
│ ---     ┆ ---        ┆ ---        ┆ ---    ┆ --- ┆ --- ┆ ---   │
│ str     ┆ date       ┆ date       ┆ str    ┆ i64 ┆ str ┆ str   │
╞═════════╪════════════╪════════════╪════════╪═════╪═════╪═══════╡
│ P1      ┆ 2014-01-15 ┆ 2014-06-30 ┆ A      ┆ 60  ┆ F   ┆ Y     │
│ P2      ┆ 2014-01-15 ┆ 2014-06-30 ┆ A      ┆ 61  ┆ M   ┆ Y     │
│ P3      ┆ 2014-01-15 ┆ 2014-06-30 ┆ A      ┆ 62  ┆ F   ┆ Y     │
│ P5      ┆ 2014-01-15 ┆ 2014-06-30 ┆ A      ┆ 63  ┆ M   ┆ Y     │
└─────────┴────────────┴────────────┴────────┴─────┴─────┴───────┘
""")
    ns = {"pl": pl, "ae": ae, "adsl": adsl}
    exec(compile(block, "<GUIDE Part 9>", "exec"), ns)  # noqa: S102 — trusted doc source
    got = ns["adae"].sort("USUBJID").select("USUBJID", "ASTDT", "AENDT", "TRTEMFL")
    expected = pl.from_repr("""
┌─────────┬────────────┬────────────┬─────────┐
│ USUBJID ┆ ASTDT      ┆ AENDT      ┆ TRTEMFL │
│ ---     ┆ ---        ┆ ---        ┆ ---     │
│ str     ┆ date       ┆ date       ┆ str     │
╞═════════╪════════════╪════════════╪═════════╡
│ P1      ┆ 2014-03-15 ┆ 2014-03-31 ┆ Y       │
│ P2      ┆ 2014-01-15 ┆ 2014-02-10 ┆ Y       │
│ P3      ┆ 2014-01-15 ┆ null       ┆ Y       │
│ P5      ┆ 2014-03-15 ┆ 2014-12-31 ┆ Y       │
└─────────┴────────────┴────────────┴─────────┘
""")
    assert got.equals(expected)
