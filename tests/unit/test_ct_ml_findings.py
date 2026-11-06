"""Regression tests for the medium and low CT findings of the alpha audit.

Each test names its finding: codelist attribute names (c1-552), escaped
definitions (c1-554), callable references (c1-555), a failed codelist import
(c1-759), the API client (c1-760, c1-761), the study .env (c1-762), CT file
shapes (c1-764), the URL download folder (c1-765) and the removed CTValidator
helpers (c1-769).
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from fleet import cli
from fleet.core.exceptions import CTError
from fleet.core.spec_source import _callable_call, program_from_spec
from fleet.ct import CodelistGenerator, import_codelists, load_controlled_terminology
from fleet.ct.api import CDISCClient, CDISCClientConfig, try_load_dotenv
from fleet.ct.validator import CTValidator


def _codelist(definition: str = "Frequency.", terms: list[tuple[str, str]] | None = None) -> dict:
    terms = terms or [("QD", "C25473")]
    return {
        "conceptId": "C71113",
        "submissionValue": "FREQ",
        "definition": definition,
        "terms": [{"submissionValue": sv, "conceptId": code} for sv, code in terms],
    }


def _render(codelist: dict) -> str:
    gen = CodelistGenerator()
    gen.add_codelist(codelist)
    return gen.render()


def _load(source: str) -> dict:
    namespace: dict = {}
    exec(compile(source, "codelists.py", "exec"), namespace)  # noqa: S102 — test-built source
    return namespace


# --------------------------------------------------------------------- #
# c1-552: one attribute per term                                         #
# --------------------------------------------------------------------- #


def test_c1_552_each_term_of_a_codelist_has_its_own_attribute():
    terms = [
        ("2 TIMES PER WEEK", "C64496"),
        ("7 TIMES PER WEEK", "C64497"),
        ("%", "C25613"),
        ("/", "C48155"),
        ("QD", "C25473"),
    ]

    freq = _load(_render(_codelist(terms=terms)))["C71113"]

    assert freq.T_2_TIMES_PER_WEEK == "2 TIMES PER WEEK"
    assert freq.T_7_TIMES_PER_WEEK == "7 TIMES PER WEEK"
    assert freq.T_C25613 == "%"
    assert freq.T_C48155 == "/"
    assert freq.QD == "QD"
    attrs = {v for k, v in vars(freq).items() if not k.startswith("_")}
    assert attrs == {sv for sv, _ in terms} == set(freq._terms)


def test_c1_552_two_terms_with_one_name_keep_their_nci_codes():
    terms = [("A-B", "C1"), ("A B", "C2")]

    cls = _load(_render(_codelist(terms=terms)))["C71113"]

    assert (cls.A_B_C1, cls.A_B_C2) == ("A-B", "A B")


# --------------------------------------------------------------------- #
# c1-554 / c1-555: definition text and callable references stay data      #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("definition", ['a """b""" c', r"C:\New folder", 'the "term"'])
def test_c1_554_a_definition_with_quotes_or_backslashes_gives_valid_python(definition):
    source = _render(_codelist(definition=definition))

    tree = ast.parse(source)

    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    assert definition in ast.get_docstring(cls, clean=False)


def test_c1_555_a_callable_that_is_not_a_dotted_name_becomes_a_todo_comment():
    imports: list[str] = []

    line = _callable_call("os.path\nimport os; os.system('x')\nfrom a.b", "", imports)

    assert imports == []
    assert line.lstrip().startswith("# TODO") and "\n" not in line
    assert _callable_call("study.derivations.bmi", "", imports) == "    .derivation(bmi)"
    assert imports == ["from study.derivations import bmi"]


def test_c1_555_program_from_spec_with_a_hostile_callable_parses(tmp_path):
    spec = {
        "study": {"standard": "ADAMIG"},
        "datasets": [
            {
                "name": "ADSL",
                "variables": [
                    {
                        "name": "BMI",
                        "derivation": {
                            "algorithm": "derivation",
                            "callable": "x\nimport os; os.system('x')\nfrom a.b",
                        },
                    }
                ],
            }
        ],
    }
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")

    program = program_from_spec(path, "ADSL")

    ast.parse(program)
    code_lines = [ln for ln in program.splitlines() if not ln.lstrip().startswith("#")]
    assert not [ln for ln in code_lines if "os.system" in ln or ln.startswith("from a")]


# --------------------------------------------------------------------- #
# c1-759: a failed import leaves sys.modules unchanged                   #
# --------------------------------------------------------------------- #


def test_c1_759_a_broken_codelists_file_is_not_left_in_sys_modules(tmp_path):
    broken = tmp_path / "codelists.py"
    broken.write_text("class SEX:\n    M = undefined_name\n", encoding="utf-8")

    with pytest.raises(NameError):
        import_codelists(broken, module_name="cl_ml_probe")

    assert "cl_ml_probe" not in sys.modules


# --------------------------------------------------------------------- #
# c1-760 / c1-761: the API client                                        #
# --------------------------------------------------------------------- #


def _client(handler) -> CDISCClient:
    client = CDISCClient(CDISCClientConfig(api_key="SECRET-KEY"))
    client._http = httpx.Client(
        base_url=client.config.base_url,
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    return client


def test_c1_760_the_key_is_not_in_the_repr_and_a_redirect_is_not_followed():
    client = CDISCClient(CDISCClientConfig(api_key="SECRET-KEY"))
    assert "SECRET-KEY" not in repr(client)
    assert client._http.follow_redirects is False

    redirect = _client(lambda req: httpx.Response(302, headers={"location": "https://evil/x"}))
    with pytest.raises(CTError, match="redirect to https://evil/x"):
        redirect.get_codelist("C66731")


def test_c1_761_a_non_json_answer_raises_a_ct_error_that_names_the_host():
    client = _client(lambda req: httpx.Response(200, text="<html>Sign in</html>"))

    with pytest.raises(CTError, match="library.cdisc.org answered with content that is not JSON"):
        client.get_codelist("C66731")
    assert not hasattr(client, "get_packages")


# --------------------------------------------------------------------- #
# c1-762: the .env of the --config study                                 #
# --------------------------------------------------------------------- #


def test_c1_762_the_env_of_the_start_folder_is_read(tmp_path, monkeypatch):
    study = tmp_path / "studies" / "X"
    study.mkdir(parents=True)
    (study / ".env").write_text("CDISC_API_KEY=from-study\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("CDISC_API_KEY", raising=False)

    try_load_dotenv(study)

    assert os.environ["CDISC_API_KEY"] == "from-study"


def test_c1_762_the_cli_reads_the_env_next_to_config(tmp_path, monkeypatch):
    study = tmp_path / "X"
    study.mkdir()
    (study / ".env").write_text("CDISC_API_KEY=from-config\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CDISC_API_KEY", raising=False)
    seen: list[str | None] = []
    args = argparse.Namespace(
        config=str(study / "study_config.yaml"),
        func=lambda _: seen.append(os.environ.get("CDISC_API_KEY")),
    )
    monkeypatch.setattr(cli, "_build_parser", lambda: SimpleNamespace(parse_args=lambda _: args))

    cli.main([])

    assert seen == ["from-config"]


# --------------------------------------------------------------------- #
# c1-764: CT file shapes                                                 #
# --------------------------------------------------------------------- #


def test_c1_764_numbers_and_yes_no_stay_exact_terms(tmp_path):
    ct = tmp_path / "ct.yaml"
    ct.write_text("C179944: {0: zero, 1: one}\nC182467: {Yes: y, No: n}\n", encoding="utf-8")
    v = CTValidator()

    v.load_ct_file(ct)

    assert v.validate_value("C179944", "0")[0]
    assert v.validate_value("C182467", "Yes")[0]
    assert v.get_valid_values("C182467") == ["No", "Yes"]


@pytest.mark.parametrize("text", ["", "- a\n- b\n", "C66731: [M, F]\n"])
def test_c1_764_a_bad_shape_raises_and_keeps_the_cache(tmp_path, text):
    good = tmp_path / "good.yaml"
    good.write_text("C66731: {M: Male, F: Female}\n", encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text(text, encoding="utf-8")
    v = CTValidator()
    v.load_ct_file(good)

    with pytest.raises(CTError, match="bad.yaml"):
        v.load_ct_file(bad)

    assert v.has_codelist("C66731")


def test_c1_764_csv_codes_stay_text(tmp_path):
    ct = tmp_path / "ct.csv"
    ct.write_text("codelist,code,value\nC179944,01,one\nC179944,1.10,x\n", encoding="utf-8")

    assert load_controlled_terminology(ct) == {"C179944": {"01": "one", "1.10": "x"}}


# --------------------------------------------------------------------- #
# c1-765: a URL file goes to a private folder                            #
# --------------------------------------------------------------------- #


def test_c1_765_a_url_file_never_writes_the_shared_temp_path(tmp_path, monkeypatch):
    old = Path(tempfile.gettempdir()) / "fleet_ct" / "terms.yaml"
    before = old.read_bytes() if old.is_file() else None
    real_client = httpx.Client

    def mock_client(**kwargs):
        body = b"C66731: {M: Male}\n"
        return real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
        )

    monkeypatch.setattr(httpx, "Client", mock_client)

    ct = load_controlled_terminology("https://host/ct/terms.yaml?x=1")

    assert ct == {"C66731": {"M": "Male"}}
    assert (old.read_bytes() if old.is_file() else None) == before


def test_c1_765_a_local_file_named_http_is_not_a_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("http_ct.yaml").write_text("C66731: {M: Male}\n", encoding="utf-8")

    assert load_controlled_terminology("http_ct.yaml") == {"C66731": {"M": "Male"}}


# --------------------------------------------------------------------- #
# c1-769: unused helpers are gone                                        #
# --------------------------------------------------------------------- #


def test_c1_769_the_unused_ctvalidator_helpers_are_removed():
    import fleet.ct

    for name in ("get_decode_map", "apply_ct_mapping", "load_codelist"):
        assert not hasattr(CTValidator, name)
    assert not hasattr(fleet.ct, "create_ct_lookup")
