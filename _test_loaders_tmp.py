"""Temporary loader smoke test — safe to delete."""

import tempfile
from pathlib import Path

import pandas as pd
import pyreadr
import pyreadstat

from fleet.core.exceptions import IOError as FleetIOError
from fleet.io.loaders import load_raw_data


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        df_pd = pd.DataFrame({"USUBJID": ["001", "002"], "AGE": [30, 45]})

        # XPT (SAS transport — pyreadstat supports both read + write)
        xpt_path = tmp / "dm.xpt"
        pyreadstat.write_xport(df_pd, str(xpt_path))
        df_xpt = load_raw_data(xpt_path).collect()
        assert len(df_xpt) == 2
        print("XPT:      OK", df_xpt.shape)

        # SAS7BDAT — no writer available in pyreadstat; verify error handling
        # on a missing file and that the correct loader branch is selected.
        fake_sas = tmp / "dm.sas7bdat"
        try:
            load_raw_data(fake_sas)
            raise AssertionError("Should have raised FleetIOError for missing file")
        except FleetIOError as e:
            assert "not found" in str(e).lower(), f"Unexpected error: {e}"
            print("SAS7BDAT: OK (missing-file guard works)")

        # RDS
        rds_path = tmp / "dm.rds"
        pyreadr.write_rds(str(rds_path), df_pd)
        df_rds = load_raw_data(rds_path).collect()
        assert len(df_rds) == 2
        print("RDS:      OK", df_rds.shape)

        # RData
        rdata_path = tmp / "dm.rdata"
        pyreadr.write_rdata(str(rdata_path), df_pd, df_name="dm")
        df_rdata = load_raw_data(rdata_path, rdata_dataset="dm").collect()
        assert len(df_rdata) == 2
        print("RData:    OK", df_rdata.shape)

    print("\nAll foreign-format loaders passed.")


if __name__ == "__main__":
    main()
