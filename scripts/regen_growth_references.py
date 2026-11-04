"""Download the CDC 2000 and WHO 2007 BMI-for-age LMS tables into package data.

The CDC file is stored byte for byte. The two WHO workbooks are converted to one
CSV (columns Sex, Month, L, M, S; Sex 1 = boys, 2 = girls) with the standard
library only. The script prints the SHA-256 of each download, for
``src/fleet/adam/data/growth/README.md``.

Usage::

    uv run python scripts/regen_growth_references.py
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "fleet" / "adam" / "data" / "growth"
CDC_URL = "https://www.cdc.gov/growthcharts/data/zscore/bmiagerev.csv"
WHO_URL = (
    "https://cdn.who.int/media/docs/default-source/child-growth/growth-reference-5-19-years/"
    "bmi-for-age-(5-19-years)/bmi-{sex}-z-who-2007-exp.xlsx"
)
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _get(url: str) -> bytes:
    # The WHO CDN refuses the default urllib User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(request, timeout=60) as resp:  # noqa: S310 (fixed https URLs)
        data = resp.read()
    print(f"{hashlib.sha256(data).hexdigest()}  {url}")
    return data


def _xlsx_rows(data: bytes) -> list[dict[str, str]]:
    book = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in book.namelist():
        root = ET.fromstring(book.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(f"{_NS}t")) for si in root.iter(f"{_NS}si")]
    sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    table = []
    for row in sheet.iter(f"{_NS}row"):
        cells = {}
        for cell in row.iter(f"{_NS}c"):
            value = cell.find(f"{_NS}v")
            if value is None:
                continue
            col = re.match(r"[A-Z]+", cell.get("r", "")).group(0)
            cells[col] = shared[int(value.text)] if cell.get("t") == "s" else value.text
        table.append(cells)
    header = table[0]
    return [{header[k]: v for k, v in r.items()} for r in table[1:]]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cdc2000_bmiagerev.csv").write_bytes(_get(CDC_URL))
    rows = []
    for code, sex in (("1", "boys"), ("2", "girls")):
        for r in _xlsx_rows(_get(WHO_URL.format(sex=sex))):
            rows.append([code, str(int(r["Month"]))] + [repr(float(r[k])) for k in ("L", "M", "S")])
    with (OUT / "who2007_bmi_for_age.csv").open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["Sex", "Month", "L", "M", "S"])
        writer.writerows(rows)


if __name__ == "__main__":
    main()
