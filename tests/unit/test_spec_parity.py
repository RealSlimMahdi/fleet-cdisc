"""Parity guard: every YAML algorithm enum value must have a from_spec branch.

This locks inline↔YAML verb parity. If someone adds a verb to
``SDTMAlgorithm`` / ``ADAMAlgorithm`` without wiring it into ``from_spec``,
this test fails — preventing the silent "algorithm not supported, skipping
variable" drift.

ponytail: static source scan of the dispatch body; upgrade to a functional
round-trip test only if a verb's branch can exist without truly working.
"""

from __future__ import annotations

import inspect

import polars as pl
import pytest

from fleet.adam.models import ADAMAlgorithm
from fleet.adam.namespace import AdamNamespace
from fleet.sdtm.models import SDTMAlgorithm
from fleet.sdtm.namespace import SDTMNamespace


@pytest.mark.parametrize(
    ("namespace_cls", "algorithm_enum"),
    [(SDTMNamespace, SDTMAlgorithm), (AdamNamespace, ADAMAlgorithm)],
)
def test_every_algorithm_is_dispatched(namespace_cls: type, algorithm_enum: type) -> None:
    """Each enum value appears as a literal in the from_spec dispatch body."""
    source = inspect.getsource(namespace_cls.from_spec)
    missing = [a.value for a in algorithm_enum if f'"{a.value}"' not in source]
    assert not missing, f"{namespace_cls.__name__}.from_spec does not dispatch: {missing}"


def test_seq_and_pin_merge_from_yaml(tmp_path) -> None:
    """seq + pin-resolved merge (newly wired verbs) run end-to-end from YAML."""
    raw = pl.from_repr("""
    ┌────────────┬─────┐
    │ subject_id ┆ val │
    │ ---        ┆ --- │
    │ str        ┆ str │
    ╞════════════╪═════╡
    │ 1          ┆ a   │
    │ 2          ┆ b   │
    └────────────┴─────┘
    """)
    supp = pl.from_repr("""
    ┌─────────┬───────┐
    │ USUBJID ┆ EXTRA │
    │ ---     ┆ ---   │
    │ str     ┆ str   │
    ╞═════════╪═══════╡
    │ 1       ┆ x     │
    │ 2       ┆ y     │
    └─────────┴───────┘
    """)
    spec = tmp_path / "ae.yaml"
    spec.write_text(
        "domain: AE\n"
        "variables:\n"
        "  - target: USUBJID\n"
        "    algorithm: assign_no_ct\n"
        "    source: subject_id\n"
        "  - target: AESEQ\n"
        "    algorithm: seq\n"
        "    groups: [USUBJID]\n"
        "    order_by: [USUBJID]\n"
        "  - target: EXTRA\n"
        "    algorithm: merge\n"
        "    dataset: SUPP\n"
        "    join_on: USUBJID\n"
    )
    out = raw.sdtm.pin("SUPP", supp, join_on="USUBJID").from_spec(spec, dataset="AE").to_frame()
    assert {"AESEQ", "EXTRA"} <= set(out.columns)
