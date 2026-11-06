"""The CBOR example follows admiralonco derive_param_confirmed_bor (c1-681).

The expected values are the output of admiralonco 1.4.1
``derive_param_confirmed_bor(ref_start_window=28, ref_confirm=28,
max_nr_ne=1, accept_sd=FALSE)`` on the same grid, after the records after
the first PD were removed (run on 5 Nov 2026).
"""

from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
pytestmark = pytest.mark.skipif(not EXAMPLES.exists(), reason="examples/ is not shipped here")

T0 = date(2024, 1, 1)

# subject: (responses, study days from TRTSDT, admiralonco CBOR, CBORDT day)
GRID = {
    "S01": (["CR", "CR"], [42, 84], "CR", 42),
    "S03": (["NON-CR/NON-PD", "NON-CR/NON-PD"], [42, 84], "NON-CR/NON-PD", 42),
    "S06": (["PD", "PR", "PR"], [42, 84, 126], "PD", 42),
    "S07": (["PR", "SD", "PR"], [42, 84, 126], "SD", 42),
    "S09": (["PR", "NE", "NE", "PR"], [42, 84, 126, 168], "SD", 42),
    "S10": (["PR", "PR"], [42, 84], "PR", 42),
    "S11": (["PR", "NE", "PR"], [42, 56, 84], "PR", 42),
    "S12": (["PD", "SD"], [42, 84], "PD", 42),
    "S14": (["SD"], [14], "NE", 14),
    "S15": (["CR", "PR"], [42, 84], "SD", 42),
    "S16": (["PR", "PR", "PD"], [42, 56, 84], "SD", 42),
    "S17": (["CR", "NE", "CR"], [42, 56, 84], "CR", 42),
    "S18": (["NE", "NE"], [14, 42], "NE", 14),
}


def _records() -> pl.DataFrame:
    rows = [
        {"USUBJID": s, "AVALC": r, "ADT": T0 + timedelta(days=d), "TRTSDT": T0}
        for s, (resp, days, _, _) in GRID.items()
        for r, d in zip(resp, days, strict=True)
    ]
    return pl.DataFrame(rows)


def test_confirmed_bor_matches_admiralonco():
    from examples.cdiscpilot01.adam.derivations import confirmed_bor

    adsl = pl.DataFrame({"USUBJID": [*GRID, "S13"]})
    out = confirmed_bor(_records(), adsl=adsl)

    expected = {s: (v, T0 + timedelta(days=d)) for s, (_, _, v, d) in GRID.items()}
    expected["S13"] = ("MISSING", None)
    assert {r[0]: (r[1], r[2]) for r in out.rows()} == expected


def test_the_derivation_adds_cbor_to_each_record():
    import fleet  # noqa: F401
    from examples.cdiscpilot01.adam.derivations import CBOR

    out = _records().adam.derivation(CBOR).to_frame()
    s06 = out.filter(pl.col("USUBJID") == "S06")
    assert s06["CBOR"].to_list() == ["PD", "PD", "PD"]
