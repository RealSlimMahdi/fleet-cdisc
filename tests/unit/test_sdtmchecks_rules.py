"""c2-918: each sponsor rule in metadata/custom_rules follows its sdtmchecks R function.

One CORE run checks every rule on a bad frame (the rule fires) and a good frame
(the rule is silent). The frames are built in a loop from the case table below,
one subject per case, so the rules do not see each other's records. The test is
skipped when the CDISC Rules Engine is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import polars as pl
import pytest

from fleet.validation.engine import find_engine
from fleet.validation.official import OfficialCDISCValidator

RULES = Path(__file__).resolve().parents[2] / "metadata" / "custom_rules"
NUMERIC = {"AGE", "EXDOSE", "VISITNUM", "LBSTRESN", "LBSTNRLO", "LBSTNRHI", "VSSTRESN", "TRSTRESN"}
DEATH = ("DM", {"DTHDTC": "2020-01-15"})

# rule -> [(subject, domain, row)]; subject "B..." must be flagged, "G..." must not.
CASES: dict[str, list[tuple[str, str, dict]]] = {
    "AE-001": [("B1", "AE", {"AEDECOD": ""}), ("G1", "AE", {"AEDECOD": "HEADACHE"})],
    "AE-002": [
        ("B1", "AE", {"AEDTHDTC": "2020-01-01", "AESDTH": "N"}),
        ("G1", "AE", {"AEDTHDTC": "2020-01-01", "AESDTH": "Y"}),
    ],
    "AE-003": [
        ("B1", "AE", {"AESDTH": "Y", "AEDTHDTC": ""}),
        ("G1", "AE", {"AESDTH": "Y", "AEDTHDTC": "2020-01-01"}),
    ],
    "AE-004": [
        ("B1", "AE", {"AEDTHDTC": "2020-01-01", "AEOUT": "RECOVERED/RESOLVED"}),
        ("G1", "AE", {"AEDTHDTC": "2020-01-01", "AEOUT": "FATAL"}),
    ],
    "AE-005": [
        ("B1", "AE", {"AEOUT": "FATAL", "AEDTHDTC": ""}),
        ("G1", "AE", {"AEOUT": "FATAL", "AEDTHDTC": "2020-01-01"}),
    ],
    "AE-006": [
        ("B1", "AE", {"AETOXGR": "5", "AEOUT": "FATAL", "AEDTHDTC": "2020-01-01", "AESDTH": "N"}),
        ("G1", "AE", {"AETOXGR": "5", "AEOUT": "FATAL", "AEDTHDTC": "2020-01-01", "AESDTH": "Y"}),
    ],
    "AE-007": [
        ("B1", "AE", {"AEOUT": "FATAL", "AEDTHDTC": "2020-01-01", "AESDTH": "Y", "AESEV": "MILD"}),
        (
            "B2",
            "AE",
            {"AEOUT": "FATAL", "AEDTHDTC": "2020-01-01", "AESDTH": "N", "AESEV": "SEVERE"},
        ),
        (
            "G1",
            "AE",
            {"AEOUT": "FATAL", "AEDTHDTC": "2020-01-01", "AESDTH": "Y", "AESEV": "SEVERE"},
        ),
    ],
    "AE-008": [
        ("B1", "AE", {"AEOUT": "RECOVERED/RESOLVED", "AEENDTC": ""}),
        ("G1", "AE", {"AEOUT": "RECOVERED/RESOLVED", "AEENDTC": "2020-01-05"}),
    ],
    "AE-009": [
        ("B1", "AE", {"AEOUT": "RECOVERING/RESOLVING", "AEENDTC": "2020-01-05"}),
        ("B2", "AE", {"AEOUT": "UNKNOWN", "AEENDTC": "2020-01-05"}),
        ("G1", "AE", {"AEOUT": "RECOVERED/RESOLVED", "AEENDTC": "2020-01-05"}),
    ],
    "AE-010": [
        ("B1", "AE", {"AEOUT": "FATAL", "AEENDTC": "", "AEDTHDTC": "2020-01-01"}),
        ("B2", "AE", {"AEOUT": "FATAL", "AEENDTC": "2020-01-02", "AEDTHDTC": "2020-01-01"}),
        ("G1", "AE", {"AEOUT": "FATAL", "AEENDTC": "2020-01-01", "AEDTHDTC": "2020-01-01"}),
        ("G2", "AE", {"AEOUT": "FATAL", "AEENDTC": "2020-01-01", "AEDTHDTC": ""}),
    ],
    "AE-011": [
        ("B1", "AE", {"AETOXGR": "", "AESEV": ""}),
        ("G1", "AE", {"AETOXGR": "", "AESEV": "MILD"}),
    ],
    "AE-012": [
        ("B1", "AE", {"AESOC": "Eye disorders", "AELAT": ""}),
        ("B2", "AE", {"AESOC": "EYE DISORDERS", "AELAT": "X"}),
        ("G1", "AE", {"AESOC": "EYE DISORDERS", "AELAT": "left"}),
    ],
    "AE-013": [
        ("B1", "AE", {"AESTDTC": "2020-02-01"}),
        ("B1", *DEATH),
        ("G1", "AE", {"AESTDTC": "2020-01-10"}),
        ("G1", *DEATH),
        ("G2", "AE", {"AESTDTC": "2020-02-01"}),
        ("G2", "DM", {"DTHDTC": ""}),
    ],
    "AE-014": [
        (
            "B1",
            "AE",
            {
                "AETERM": "NAUSEA",
                "AEDECOD": "Nausea",
                "AESTDTC": "2020-01-01",
                "AEENDTC": "2020-01-02",
                "AESEV": "MILD",
            },
        ),
        (
            "B1",
            "AE",
            {
                "AETERM": "NAUSEA",
                "AEDECOD": "Nausea",
                "AESTDTC": "2020-01-01",
                "AEENDTC": "2020-01-02",
                "AESEV": "MILD",
            },
        ),
        (
            "G1",
            "AE",
            {
                "AETERM": "NAUSEA",
                "AEDECOD": "Nausea",
                "AESTDTC": "2020-01-01",
                "AEENDTC": "2020-01-02",
                "AESEV": "MILD",
            },
        ),
        (
            "G1",
            "AE",
            {
                "AETERM": "NAUSEA",
                "AEDECOD": "Nausea",
                "AESTDTC": "2020-01-01",
                "AEENDTC": "2020-01-02",
                "AESEV": "SEVERE",
            },
        ),
    ],
    "AE-015": [
        (
            "B1",
            "DS",
            {"DSDECOD": "DEATH", "DSTERM": "DEATH DUE TO ADVERSE EVENT", "DSSTDTC": "2020-01-01"},
        ),
        ("B1", "AE", {"AEDTHDTC": ""}),
        (
            "G1",
            "DS",
            {"DSDECOD": "DEATH", "DSTERM": "DEATH DUE TO ADVERSE EVENT", "DSSTDTC": "2020-01-01"},
        ),
        ("G1", "AE", {"AEDTHDTC": "2020-01-01"}),
    ],
    "AE-016": [
        ("B1", "AE", {"AEDTHDTC": "2020-01-01"}),
        ("B1", "DS", {"DSDECOD": "DEATH", "DSSTDTC": "2020-01-05"}),
        ("G1", "AE", {"AEDTHDTC": "2020-01-05"}),
        ("G1", "DS", {"DSDECOD": "DEATH", "DSSTDTC": "2020-01-05"}),
    ],
    "AE-017": [("B1", "AE", {"AEDTHDTC": "2020-01"}), ("G1", "AE", {"AEDTHDTC": "2020-01-01"})],
    "AE-021": [("B1", "AE", {"AEREL": ""}), ("G1", "AE", {"AEREL": "NOT RELATED"})],
    "AE-022": [
        ("B1", "AE", {"AEACNOTH": "MULTIPLE", "AEACNOT1": "X", "AEACNOT2": ""}),
        ("G1", "AE", {"AEACNOTH": "MULTIPLE", "AEACNOT1": "X", "AEACNOT2": "Y"}),
    ],
    "CE-001": [("B1", "CE", {"CESTDTC": "2020---05"}), ("G1", "CE", {"CESTDTC": "2020-05"})],
    "CM-001": [
        ("B1", "CM", {"CMCAT": "CONCOMITANT MEDICATION", "CMDECOD": ""}),
        ("G1", "CM", {"CMCAT": "CONCOMITANT MEDICATION", "CMDECOD": "ASPIRIN"}),
    ],
    "CM-002": [("B1", "CM", {"CMSTDTC": "2020---15"}), ("G1", "CM", {"CMSTDTC": "2020-03"})],
    "DM-001": [("B1", "DM", {"AGE": ""}), ("G1", "DM", {"AGE": "40"})],
    "DM-002": [
        ("B1", "DM", {"ARM": "A", "ACTARM": ""}),
        ("B2", "DM", {"ARM": "A", "ACTARM": "B"}),
        ("G1", "DM", {"ARM": "A", "ACTARM": "A"}),
    ],
    "DS-001": [
        ("B1", "DS", {"DSDECOD": "DEATH", "DSSTDTC": ""}),
        ("G1", "DS", {"DSDECOD": "DEATH", "DSSTDTC": ""}),
        ("G1", "DS", {"DSDECOD": "DEATH", "DSSTDTC": "2020-01-01"}),
        # c2-887: a null date (not "") must not stop the rule for the whole DS.
        ("G2", "DS", {"DSDECOD": "DEATH", "DSSTDTC": None}),
        ("G2", "DS", {"DSDECOD": "DEATH", "DSSTDTC": "2020-02-01"}),
    ],
    "DS-002": [
        ("B1", "DS", {"DSTERM": "DEATH DUE TO"}),
        ("G1", "DS", {"DSTERM": "DEATH DUE TO ADVERSE EVENT"}),
    ],
    "DS-003": [
        ("B1", "DS", {"DSDECOD": "RANDOMIZED"}),
        ("B1", "DS", {"DSDECOD": "RANDOMIZED"}),
        ("G1", "DS", {"DSDECOD": "RANDOMIZED"}),
        ("G1", "DS", {"DSDECOD": "INFORMED CONSENT OBTAINED"}),
    ],
    "DS-004": [
        ("B1", "DS", {"DSDECOD": "DEATH", "DSSTDTC": "2020-01-01"}),
        ("B1", "DS", {"DSDECOD": "DEATH", "DSSTDTC": "2020-01-02"}),
        ("G1", "DS", {"DSDECOD": "DEATH", "DSSTDTC": "2020-01-01"}),
        ("G1", "DS", {"DSDECOD": "DEATH", "DSSTDTC": "2020-01-01"}),
        ("G1", "DS", {"DSDECOD": "COMPLETED", "DSSTDTC": "2019-12-01"}),
    ],
    "DS-007": [
        (
            "B1",
            "DS",
            {"DSCAT": "DISPOSITION EVENT", "DSSPID": "DISCTX-1", "DSDECOD": "ADVERSE EVENT"},
        ),
        ("B1", "AE", {"AEACN": "DOSE NOT CHANGED"}),
        (
            "G1",
            "DS",
            {"DSCAT": "DISPOSITION EVENT", "DSSPID": "DISCTX-1", "DSDECOD": "ADVERSE EVENT"},
        ),
        ("G1", "AE", {"AEACN": "DRUG WITHDRAWN"}),
    ],
    "EX-001": [
        ("B1", "EX", {"EXOCCUR": "Y", "EXDOSE": ""}),
        ("G1", "EX", {"EXOCCUR": "Y", "EXDOSE": "10"}),
    ],
    "EX-002": [
        ("B1", "EX", {"EXOCCUR": "N", "EXDOSE": "10"}),
        ("G1", "EX", {"EXOCCUR": "Y", "EXDOSE": "10"}),
    ],
    "EX-003": [
        ("B1", "EX", {"EXOCCUR": "Y", "EXDOSU": ""}),
        ("G1", "EX", {"EXOCCUR": "Y", "EXDOSU": "mg"}),
    ],
    "EX-004": [
        ("B1", "EX", {"EXOCCUR": "Y", "EXTRT": ""}),
        ("G1", "EX", {"EXOCCUR": "Y", "EXTRT": "DRUG"}),
    ],
    "EX-005": [
        ("B1", "EX", {"EXOCCUR": "Y", "VISIT": ""}),
        ("G1", "EX", {"EXOCCUR": "Y", "VISIT": "DAY 1"}),
    ],
    "EX-006": [
        ("B1", "EX", {"EXOCCUR": "", "EXDOSE": "10"}),
        ("G1", "EX", {"EXOCCUR": "Y", "EXDOSE": "10"}),
    ],
    "EX-007": [
        ("B1", "EX", {"EXOCCUR": "Y", "EXTRT": "DRUG", "EXDOSE": "10", "EXSTDTC": "2020-01-01"}),
        ("B1", "EX", {"EXOCCUR": "Y", "EXTRT": "DRUG", "EXDOSE": "10", "EXSTDTC": "2020-01-01"}),
        ("G1", "EX", {"EXOCCUR": "Y", "EXTRT": "DRUG", "EXDOSE": "10", "EXSTDTC": "2020-01-01"}),
        ("G1", "EX", {"EXOCCUR": "Y", "EXTRT": "DRUG", "EXDOSE": "10", "EXSTDTC": "2020-01-02"}),
    ],
    "EX-008": [
        ("B1", "EX", {"EXOCCUR": "Y", "EXSTDTC": "2020-02-01"}),
        ("B1", *DEATH),
        ("G1", "EX", {"EXOCCUR": "N", "EXSTDTC": "2020-02-01"}),
        ("G1", *DEATH),
    ],
    "EX-010": [
        (
            "B1",
            "EX",
            {
                "EXROUTE": "INTRAVENOUS",
                "EXSTDTC": "2020-01-01T10:00",
                "EXENDTC": "2020-01-02T10:00",
            },
        ),
        ("B2", "EX", {"EXROUTE": "INTRAVENOUS", "EXSTDTC": "2020-01-01T10:00", "EXENDTC": ""}),
        (
            "G1",
            "EX",
            {
                "EXROUTE": "INTRAVENOUS",
                "EXSTDTC": "2020-01-01T10:00",
                "EXENDTC": "2020-01-01T11:00",
            },
        ),
    ],
    "EX-011": [
        ("B1", "EX", {"EXOCCUR": "Y", "EXTRT": "DRUG", "EXDOSE": "0", "EXSTDTC": "2020-01-01"}),
        ("B2", "EX", {"EXOCCUR": "Y", "EXTRT": "DRUG", "EXDOSE": "5", "EXSTDTC": "2020"}),
        ("G1", "EX", {"EXOCCUR": "Y", "EXTRT": "PLACEBO", "EXDOSE": "0", "EXSTDTC": "2020-01-01"}),
        ("G2", "EX", {"EXOCCUR": "N", "EXTRT": "DRUG", "EXDOSE": "0", "EXSTDTC": ""}),
    ],
    "LB-001": [
        ("B1", "LB", {"LBORRES": "5", "LBSTRESN": "", "LBSTRESC": ""}),
        ("G1", "LB", {"LBORRES": "5", "LBSTRESN": "", "LBSTRESC": "5"}),
    ],
    "LB-002": [
        ("B1", "LB", {"LBORRES": "5", "LBSTRESU": "", "LBTESTCD": "ALT"}),
        ("G1", "LB", {"LBORRES": "Negative", "LBSTRESU": "", "LBTESTCD": "ALT"}),
        (
            "G2",
            "LB",
            {"LBORRES": "5", "LBSTRESU": "", "LBTESTCD": "ALT", "LBMETHOD": "QUALITATIVE"},
        ),
    ],
    "LB-003": [
        ("B1", "LB", {"LBORRES": "<5", "LBSTRESC": "<5", "LBSTRESN": ""}),
        ("G1", "LB", {"LBORRES": "<LLOQ", "LBSTRESC": "<LLOQ", "LBSTRESN": ""}),
    ],
    "LB-005": [("B1", "LB", {"LBDTC": "2020---05"}), ("G1", "LB", {"LBDTC": "2020-05"})],
    "LB-006": [
        ("B1", "LB", {"LBDTC": "2020-02-01", "LBORRES": "5"}),
        ("B1", *DEATH),
        ("G1", "LB", {"LBDTC": "2020-02-01", "LBORRES": ""}),
        ("G1", *DEATH),
    ],
    "LB-007": [
        ("B1", "LB", {"LBSTRESN": "5", "LBSTNRLO": "", "LBSTNRHI": "10"}),
        ("G1", "LB", {"LBSTRESN": "5", "LBSTNRLO": "1", "LBSTNRHI": "10"}),
    ],
    "MH-001": [("B1", "MH", {"MHSTDTC": "2020---05"}), ("G1", "MH", {"MHSTDTC": "2020"})],
    "MI-001": [("B1", "MI", {"MISPEC": ""}), ("G1", "MI", {"MISPEC": "LIVER"})],
    "PR-001": [("B1", "PR", {"PRSTDTC": "2017---01"}), ("G1", "PR", {"PRSTDTC": "2017-01"})],
    "QS-001": [
        ("B1", "QS", {"QSSTAT": "not done", "QSREASND": ""}),
        ("G1", "QS", {"QSSTAT": "NOT DONE", "QSREASND": "TIRED"}),
    ],
    "QS-003": [
        ("B1", "QS", {"QSDTC": "2020-02-01", "QSORRES": "1"}),
        ("B1", *DEATH),
        ("G1", "QS", {"QSDTC": "2020-02-01", "QSORRES": "1", "QSSTAT": "NOT DONE"}),
        ("G1", *DEATH),
    ],
    "QS-004": [
        (
            "B1",
            "QS",
            {
                "QSCAT": "DLQI",
                "QSTESTCD": "Q1",
                "VISIT": "WEEK 1",
                "VISITNUM": "1",
                "QSDTC": "2020-01-01",
            },
        ),
        (
            "B1",
            "QS",
            {
                "QSCAT": "DLQI",
                "QSTESTCD": "Q2",
                "VISIT": "WEEK 1",
                "VISITNUM": "1",
                "QSDTC": "2020-01-02",
            },
        ),
        (
            "G1",
            "QS",
            {
                "QSCAT": "DLQI",
                "QSTESTCD": "Q1",
                "VISIT": "WEEK 1",
                "VISITNUM": "1",
                "QSDTC": "2020-01-01",
            },
        ),
        (
            "G1",
            "QS",
            {
                "QSCAT": "DLQI",
                "QSTESTCD": "Q1",
                "VISIT": "WEEK 1",
                "VISITNUM": "1",
                "QSDTC": "2020-01-01",
            },
        ),
    ],
    "QS-005": [
        (
            "B1",
            "QS",
            {
                "QSTESTCD": "QSALL",
                "QSSTAT": "NOT DONE",
                "QSCAT": "BFI",
                "VISIT": "WEEK 1",
                "QSDTC": "2020-01-01",
                "QSSTRESC": "",
            },
        ),
        (
            "B1",
            "QS",
            {
                "QSTESTCD": "Q01",
                "QSCAT": "BFI",
                "VISIT": "WEEK 1",
                "QSDTC": "2020-01-01",
                "QSSTRESC": "3",
            },
        ),
        (
            "G1",
            "QS",
            {
                "QSTESTCD": "QSALL",
                "QSSTAT": "NOT DONE",
                "QSCAT": "BFI",
                "VISIT": "WEEK 1",
                "QSDTC": "2020-01-01",
                "QSSTRESC": "",
            },
        ),
        (
            "G1",
            "QS",
            {
                "QSTESTCD": "Q01",
                "QSCAT": "BFI",
                "VISIT": "WEEK 2",
                "QSDTC": "2020-01-08",
                "QSSTRESC": "3",
            },
        ),
    ],
    "RS-001": [
        ("B1", "RS", {"RSSCAT": "X", "RSCAT": ""}),
        ("G1", "RS", {"RSSCAT": "X", "RSCAT": "RECIST"}),
    ],
    "RS-003": [
        ("B1", "RS", {"RSDTC": "2020-06-01", "VISITNUM": "2", "RSEVAL": "INVESTIGATOR"}),
        ("B1", "RS", {"RSDTC": "2020-06-01", "VISITNUM": "3", "RSEVAL": "INVESTIGATOR"}),
        ("G1", "RS", {"RSDTC": "2020-06-01", "VISITNUM": "2", "RSEVAL": "INVESTIGATOR"}),
        ("G1", "RS", {"RSDTC": "2020-06-02", "VISITNUM": "2", "RSEVAL": "INVESTIGATOR"}),
    ],
    "RS-004": [
        (
            "B1",
            "RS",
            {
                "RSDTC": "",
                "VISIT": "C1D1",
                "RSORRES": "PR",
                "RSSTAT": "DONE",
                "RSEVAL": "INVESTIGATOR",
            },
        ),
        (
            "G1",
            "RS",
            {
                "RSDTC": "",
                "VISIT": "C1D1",
                "RSORRES": "PR",
                "RSSTAT": "NOT DONE",
                "RSEVAL": "INVESTIGATOR",
            },
        ),
    ],
    "SS-001": [
        ("B1", "SS", {"SSSTAT": "NOT DONE", "SSORRES": "ALIVE"}),
        ("G1", "SS", {"SSSTAT": "", "SSORRES": "ALIVE"}),
    ],
    "SS-002": [
        ("B1", "SS", {"SSTESTCD": "SURVSTAT", "SSORRES": "ALIVE", "SSDTC": "2020-02-01"}),
        ("B1", *DEATH),
        ("G1", "SS", {"SSTESTCD": "SURVSTAT", "SSORRES": "ALIVE", "SSDTC": "2020-01-10"}),
        ("G1", *DEATH),
    ],
    "SS-003": [
        ("B1", "SS", {"SSSTRESC": "DEAD", "SSDTC": "2020-01-10"}),
        ("B1", *DEATH),
        ("G1", "SS", {"SSSTRESC": "DEAD", "SSDTC": "2020-01-20"}),
        ("G1", *DEATH),
    ],
    "SS-004": [
        ("B1", "SS", {"SSSTRESC": "DEAD", "SSDTC": "2020-01-20"}),
        ("G1", "SS", {"SSSTRESC": "DEAD", "SSDTC": "2020-01-20"}),
        ("G1", "DS", {"DSDECOD": "DEATH", "DSCAT": "DISPOSITION EVENT", "DSSTDTC": "2020-01-15"}),
    ],
    "TR-001": [
        ("B1", "TR", {"TRTESTCD": "LDIAM", "TRSTRESN": "", "TREVAL": "INVESTIGATOR"}),
        ("G1", "TR", {"TRTESTCD": "LDIAM", "TRSTRESN": "", "TREVAL": "INDEPENDENT ASSESSOR"}),
    ],
    "TR-003": [
        (
            "B1",
            "TR",
            {
                "TRCAT": "T",
                "TRTESTCD": "LDIAM",
                "TRLINKID": "T01",
                "TRSPID": "1",
                "TRDTC": "2020-01-01",
                "TRSTRESC": "10",
            },
        ),
        (
            "B1",
            "TR",
            {
                "TRCAT": "T",
                "TRTESTCD": "LDIAM",
                "TRLINKID": "T01",
                "TRSPID": "1",
                "TRDTC": "2020-01-01",
                "TRSTRESC": "10",
            },
        ),
        (
            "G1",
            "TR",
            {
                "TRCAT": "T",
                "TRTESTCD": "LDIAM",
                "TRLINKID": "T01",
                "TRSPID": "1",
                "TRDTC": "2020-01-01",
                "TRSTRESC": "10",
            },
        ),
        (
            "G1",
            "TR",
            {
                "TRCAT": "T",
                "TRTESTCD": "LDIAM",
                "TRLINKID": "T01",
                "TRSPID": "1",
                "TRDTC": "2020-01-01",
                "TRSTRESC": "12",
            },
        ),
    ],
    "TR-004": [
        ("B1", "TR", {"TRTESTCD": "LDIAM", "TRDTC": "2020-06-01", "VISITNUM": "2"}),
        ("B1", "TR", {"TRTESTCD": "LDIAM", "TRDTC": "2020-06-01", "VISITNUM": "3"}),
        ("G1", "TR", {"TRTESTCD": "LDIAM", "TRDTC": "2020-06-01", "VISITNUM": "2"}),
        ("G1", "TR", {"TRTESTCD": "LDIAM", "TRDTC": "2020-06-02", "VISITNUM": "2"}),
    ],
    "TU-001": [
        ("B1", "TU", {"TUDTC": "", "TUEVAL": ""}),
        ("G1", "TU", {"TUDTC": "", "TUEVAL": "INDEPENDENT ASSESSOR"}),
    ],
    "TU-002": [
        ("B1", "TU", {"TUORRES": "Target", "TULOC": ""}),
        ("G1", "TU", {"TUORRES": "TARGET", "TULOC": "LIVER"}),
    ],
    "TU-004": [
        ("B1", "TU", {"TUDTC": "2020-06-01", "VISITNUM": "2"}),
        ("B1", "TU", {"TUDTC": "2020-06-01", "VISITNUM": "3"}),
        ("G1", "TU", {"TUDTC": "2020-06-01", "VISITNUM": "2"}),
        ("G1", "TU", {"TUDTC": "2020-06-02", "VISITNUM": "2"}),
    ],
    "VS-002": [
        ("B1", "VS", {"VSDTC": "2020-02-01", "VSORRES": "120"}),
        ("B1", *DEATH),
        ("G1", "VS", {"VSDTC": "2020-02-01", "VSORRES": ""}),
        ("G1", *DEATH),
    ],
    "VS-003": [
        ("B1", "DM", {}),
        ("G1", "DM", {}),
        ("G1", "VS", {"VSTESTCD": "HEIGHT", "VSSTRESN": "170"}),
    ],
}

# Columns every record of a domain needs, so a case row stays short.
BASE = {
    "AE": {"AETERM": "X", "AEDECOD": "X"},
    "CE": {"CETERM": "X"},
    "CM": {"CMTRT": "X"},
    "DS": {"DSTERM": "X", "DSDECOD": "X"},
    "EX": {"EXTRT": "DRUG"},
    "LB": {"LBTESTCD": "X"},
    "MH": {"MHTERM": "X"},
    "MI": {"MITESTCD": "X"},
    "PR": {"PRTRT": "X"},
    "QS": {"QSTESTCD": "X", "QSCAT": "X"},
    "RS": {"RSTESTCD": "OVRLRESP"},
    "SS": {"SSTESTCD": "SURVSTAT"},
    "TR": {"TRTESTCD": "X"},
    "TU": {"TUTESTCD": "X"},
    "VS": {"VSTESTCD": "X"},
    "DM": {},
}


def _frames() -> dict[str, pl.DataFrame]:
    rows: dict[str, list[dict]] = {}
    for rule, cases in CASES.items():
        for subject, domain, row in cases:
            rows.setdefault(domain, []).append(
                {**BASE[domain], **row, "USUBJID": f"{rule}-{subject}"}
            )
    frames = {}
    for domain, records in rows.items():
        cols = list(dict.fromkeys(k for r in records for k in r))
        data = {}
        for col in cols:
            values = [r.get(col) for r in records]
            if col in NUMERIC:
                data[col] = [None if v in (None, "") else float(v) for v in values]
            else:
                # A missing text value stays null: the engine-input writer writes it as "".
                data[col] = values
        frame = pl.DataFrame(
            data, schema={c: pl.Float64 if c in NUMERIC else pl.String for c in cols}
        )
        frame = frame.with_columns(
            pl.lit("T01").alias("STUDYID"),
            pl.lit(domain).alias("DOMAIN"),
            pl.int_range(1, pl.len() + 1).over("USUBJID").cast(pl.Float64).alias(f"{domain}SEQ"),
        )
        front = ["STUDYID", "DOMAIN", "USUBJID"]
        frames[domain] = frame.select(front + [c for c in frame.columns if c not in front])
    return frames


@pytest.fixture(scope="module")
def hits(tmp_path_factory) -> dict[str, set[str]]:
    found = find_engine()
    if found is None:
        pytest.skip("CDISC Rules Engine not installed")
    exe = found[0]
    tmp = tmp_path_factory.mktemp("sdtmchecks")
    data, rules = tmp / "data", tmp / "rules"
    data.mkdir()
    shutil.copytree(RULES, rules, ignore=shutil.ignore_patterns("*.md"))
    for domain, frame in _frames().items():
        OfficialCDISCValidator._write_dataset_json(frame, data / f"{domain}.json", domain=domain)
    out = tmp / "report"
    cmd = [
        str(exe),
        "validate",
        "-s",
        "sdtmig",
        "-v",
        "3-4",
        "-d",
        str(data),
        "-o",
        str(out),
        "-of",
        "JSON",
        "-lr",
        str(rules),
    ]
    subprocess.run(cmd, cwd=exe.parent, capture_output=True, text=True, timeout=900, check=True)
    report = json.loads(out.with_suffix(".json").read_text())
    result: dict[str, set[str]] = {}
    for item in report.get("Issue_Details", []):
        result.setdefault(item["core_id"], set()).add(item.get("USUBJID") or "")
    return result


def test_every_rule_file_has_a_case():
    ids = {p.stem.removeprefix("SDTMCHK-") for p in RULES.glob("SDTMCHK-*.yaml")}
    assert ids == set(CASES)


@pytest.mark.parametrize("rule", sorted(CASES))
def test_rule_fires_on_the_bad_frame_only(rule, hits):
    own = {u for u in hits.get(f"SDTMCHK-{rule}", set()) if u.startswith(f"{rule}-")}
    bad = {f"{rule}-{s}" for s, _, _ in CASES[rule] if s.startswith("B")}
    assert own == bad
