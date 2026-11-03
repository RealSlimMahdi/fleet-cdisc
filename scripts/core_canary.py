"""CORE canary: does a CDISC Rules Engine release still work with Fleet?

Builds a small study (a clean DM, an AE without the Permissible AESDTH, an
ADSL) and runs ``fleet validate`` on it with the engine given.  The engine
passes when no dataset "could not run" and the SDTM run executed at least
one rule.  The weekly workflow ``.github/workflows/core-canary.yml`` runs
it on the newest CORE release; add a version to
``fleet.validation.engine.TESTED_ENGINE_VERSIONS`` only after it passes.

Usage::

    uv run python scripts/core_canary.py --engine ~/.fleet/cdisc-rules-engine/core/core
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parent.parent


def _study(root: Path, engine: Path) -> None:
    sdtm, adam = root / "data" / "sdtm", root / "data" / "adam"
    sdtm.mkdir(parents=True)
    adam.mkdir(parents=True)
    pl.DataFrame(
        {
            "STUDYID": ["S1", "S1"],
            "DOMAIN": ["DM", "DM"],
            "USUBJID": ["S1-001", "S1-002"],
            "SUBJID": ["001", "002"],
            "SITEID": ["01", "01"],
            "SEX": ["M", "F"],
            "COUNTRY": ["USA", "USA"],
            "ARMCD": ["A", "A"],
            "ARM": ["Drug", "Drug"],
        }
    ).write_parquet(sdtm / "dm.parquet")
    pl.DataFrame(
        {
            "STUDYID": ["S1"],
            "DOMAIN": ["AE"],
            "USUBJID": ["S1-001"],
            "AESEQ": [1],
            "AETERM": ["HEADACHE"],
            "AEDECOD": ["HEADACHE"],
            "AESTDTC": ["2024-01-02"],
        }
    ).write_parquet(sdtm / "ae.parquet")
    pl.DataFrame(
        {
            "STUDYID": ["S1", "S1"],
            "USUBJID": ["S1-001", "S1-002"],
            "SUBJID": ["001", "002"],
            "SITEID": ["01", "01"],
            "SAFFL": ["Y", "Y"],
            "TRT01P": ["Drug", "Drug"],
            "TRT01A": ["Drug", "Drug"],
        }
    ).write_parquet(adam / "adsl.parquet")
    (root / "study_config.yaml").write_text(
        f"study_id: S1\nvalidation:\n  engine_path: {engine}\n  timeout: 900\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", type=Path, required=True, help="CORE executable.")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _study(root, args.engine.expanduser().resolve())
        run = subprocess.run(
            ["uv", "run", "--project", str(REPO), "fleet", "validate"],
            cwd=root,
            capture_output=True,
            text=True,
        )
    out = run.stdout + run.stderr
    print(out)

    problems = []
    if run.returncode == 2 or "Status: COULD NOT RUN" in out:
        problems.append("a dataset could not run (exit 2)")
    executed = [int(n) for n in re.findall(r"Rules executed: (\d+)", out)]
    if not executed or max(executed) == 0:
        problems.append("no rule executed")
    if problems:
        print("CORE canary FAILED: " + "; ".join(problems), file=sys.stderr)
        return 1
    print("CORE canary passed: every dataset ran.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
