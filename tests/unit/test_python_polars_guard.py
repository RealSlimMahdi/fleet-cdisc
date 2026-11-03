"""``import fleet`` refuses Python 3.15 with Polars 1.x (c1-154).

On that pair, Polars 1.x Series methods return None, so Dataset-JSON, every
TLG table and the trial design audit crash. Remove this guard with the
``polars<2`` pin.
"""

from __future__ import annotations

import pytest

from fleet import _check_python_and_polars


def test_python_315_with_polars_1_refuses_with_a_working_command() -> None:
    with pytest.raises(ImportError, match=r"uv init --python 3\.12"):
        _check_python_and_polars((3, 15), "1.44.2")


@pytest.mark.parametrize(
    ("python", "polars"),
    [((3, 12), "1.41.0"), ((3, 14), "1.44.2"), ((3, 15), "2.1.0")],
)
def test_supported_pairs_pass(python: tuple[int, int], polars: str) -> None:
    _check_python_and_polars(python, polars)
