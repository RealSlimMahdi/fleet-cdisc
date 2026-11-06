"""The README namespace catalog lists the live verbs of each namespace (c1-180)."""

import re
from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401

README = Path(__file__).resolve().parents[2] / "README.md"

_ADAM = ["adsl", "occds", "onco", "ophtha", "peds", "vaccine", "metabolic", "neuro", "pk", "tte"]


def _block_verbs(text: str, accessor: str) -> list[str]:
    m = re.search(rf"<code>{re.escape(accessor)}</code></b>[^\n]*\n\n([^\n]*)\n", text)
    assert m, f"no README block for {accessor}"
    return re.findall(r"`([a-z_0-9]+)`", m.group(1))


def _namespaces() -> dict[str, object]:
    adam = pl.DataFrame().adam
    return {"df.adam": adam} | {f"df.adam.{n}": getattr(adam, n) for n in _ADAM}


@pytest.mark.skipif(not README.exists(), reason="README.md is not shipped here")
def test_each_specific_list_matches_verbs():
    text = README.read_text(encoding="utf-8").split("AUTO:NAMESPACES:BEGIN", 1)[1]
    live = {acc: set(ns.verbs()["verb"].to_list()) for acc, ns in _namespaces().items()}
    shared = set.intersection(*live.values())
    intro = text.split("<details>", 1)[0]
    assert set(re.findall(r"`([a-z_0-9]+)`", intro)) - {"fleet"} == shared
    for acc, verbs in live.items():
        assert set(_block_verbs(text, acc)) == verbs - shared, acc
