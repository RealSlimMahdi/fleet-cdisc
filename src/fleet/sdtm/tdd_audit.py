"""Trial Design conformance pre-check — a P21-style dry run, offline.

Encodes the published, machine-checkable conformance rules that hit Trial
Design domains hardest: the SD-series cross-domain structural checks and the
FDA Technical Conformance Guide TS parameter profile (TS is the only
rejection-level dataset — eCTD Technical Rejection Criterion 1734).

Rule IDs reference the public Pinnacle 21 Community / FDA business rule
identifiers so findings can be cross-checked against a real P21 report.
Sources: FDA TCG TS parameter list (fda.gov/media/153632), PHUSE US Connect
2026 paper DS22, PharmaSUG 2023 DS-149.

ponytail: a curated high-signal subset, not the full 100+ TDM rule catalog —
`fleet validate` runs the CDISC Rules Engine for exhaustive coverage.
"""

from __future__ import annotations

from typing import Any

import polars as pl

_FINDING_SCHEMA = {
    "rule_id": pl.String,
    "severity": pl.String,
    "domain": pl.String,
    "message": pl.String,
}

# Reserved ARMCDs that must exist only in DM, never in TA/TV (SD1053).
_RESERVED_ARMCDS = ("SCRNFAIL", "NOTASSGN")

#: FDA-required TS parameters (TCG): TSPARMCD → P21 rule ID.
TS_REQUIRED: dict[str, str] = {
    "TITLE": "SD2213",
    "TPHASE": "SD2214",
    "TTYPE": "SD2215",
    "STYPE": "SD2230",
    "OBJPRIM": "SD2217",
    "OBJSEC": "SD2275",
    "OUTMSPRI": "SD2222",
    "PLANSUB": "SD2205",
    "NARMS": "SD2229",
    "AGEMIN": "SD2203",
    "AGEMAX": "SD2202",
    "SEXPOP": "SD2207",
    "TBLIND": "SD2209",
    "TCNTRL": "SD2210",
    "ADAPT": "SD2225",
    "EXTTIND": "SD2273",
    "SSTDTC": "SD2232",
    "SDTIGVER": "SD2280",
    "SDTMVER": "SD2281",
    "SPONSOR": "SD2218",
    "REGID": "SD2221",
    "FCNTRY": "SD2224",
}

#: Conditionally-required TS parameters: (trigger parm, trigger value, required parm, rule ID).
TS_CONDITIONAL: list[tuple[str, str, str, str]] = [
    ("STYPE", "INTERVENTIONAL", "INTMODEL", "SD1310"),
    ("STYPE", "INTERVENTIONAL", "INTTYPE", "SD1311"),
    ("STYPE", "INTERVENTIONAL", "PCLAS", "SD1312"),
    ("ADDON", "Y", "CURTRT", "SD2216"),
    ("HLTSUBJI", "N", "TDIGRP", "SD1307"),
]


def _to_df(frame: Any) -> pl.DataFrame | None:
    """Accept a DataFrame, LazyFrame, or a TDD collection with ``to_polars``."""
    if frame is None:
        return None
    if isinstance(frame, pl.LazyFrame):
        return frame.collect()
    if isinstance(frame, pl.DataFrame):
        return frame
    return frame.to_polars()


def audit(
    *,
    te: Any = None,
    ta: Any = None,
    tv: Any = None,
    ts: Any = None,
    ti: Any = None,
    dm: Any = None,
) -> pl.DataFrame:
    """Cross-check Trial Design domains against published conformance rules.

    Every argument is optional — checks run only when the domains they need
    are present.  Inputs may be DataFrames, LazyFrames, or the TDD
    collection models (``TrialElements``, ``TrialArms``, ...).

    Args:
        te: Trial Elements domain.
        ta: Trial Arms domain.
        tv: Trial Visits domain.
        ts: Trial Summary domain.
        ti: Trial Inclusion/Exclusion domain.
        dm: Demographics domain, for ARMCD cross-checks.

    Returns:
        pl.DataFrame: One row per finding with ``rule_id``, ``severity``
            (``error``/``warning``), ``domain``, and ``message``; empty
            (schema preserved) when everything passes.

    Examples:
        Pre-validate before shipping to P21::

            findings = fleet.sdtm.tdd_audit.audit(te=te, ta=ta, ts=ts)
            assert findings.filter(pl.col("severity") == "error").is_empty()
    """
    te, ta, tv, ts, ti, dm = (_to_df(f) for f in (te, ta, tv, ts, ti, dm))
    findings: list[dict[str, str]] = []

    def add(rule_id: str, severity: str, domain: str, message: str) -> None:
        findings.append(
            {"rule_id": rule_id, "severity": severity, "domain": domain, "message": message}
        )

    # -- TE structural ------------------------------------------------- #
    if te is not None:
        for etcd in te.filter(pl.col("ETCD").str.len_chars() > 8)["ETCD"].to_list():
            add("SD1009", "error", "TE", f"ETCD '{etcd}' exceeds 8 characters")
        if {"TEENRL", "TEDUR"}.issubset(te.columns):
            unbounded = te.filter(
                pl.col("TEENRL").fill_null("").eq("") & pl.col("TEDUR").fill_null("").eq("")
            )
            for etcd in unbounded["ETCD"].to_list():
                add("SD0089", "error", "TE", f"Element '{etcd}' has neither TEENRL nor TEDUR")
        dup = te.group_by("ETCD").len().filter(pl.col("len") > 1)["ETCD"].to_list()
        for etcd in dup:
            add("SD1271", "error", "TE", f"Duplicate ETCD '{etcd}' in TE")

    # -- TA structural ------------------------------------------------- #
    if ta is not None:
        for armcd in ta.filter(pl.col("ARMCD").str.len_chars() > 20)["ARMCD"].unique().to_list():
            add("SD1004", "error", "TA", f"ARMCD '{armcd}' exceeds 20 characters")
        dup_ord = ta.group_by("ARMCD", "TAETORD").len().filter(pl.col("len") > 1)["ARMCD"].unique()
        for armcd in dup_ord.to_list():
            add("SD1052", "error", "TA", f"TAETORD values not unique within ARMCD '{armcd}'")
        for col, rule in (("ARMCD", "SD1033"), ("ARM", "SD1034")):
            other = "ARM" if col == "ARMCD" else "ARMCD"
            bad = ta.group_by(col).agg(pl.col(other).n_unique().alias("n")).filter(pl.col("n") > 1)
            for value in bad[col].to_list():
                add(rule, "error", "TA", f"{col} '{value}' maps to multiple {other} values")
        for armcd in _RESERVED_ARMCDS:
            if armcd in ta["ARMCD"].to_list():
                add("SD1053", "error", "TA", f"Reserved ARMCD '{armcd}' must not appear in TA")

    # -- TA ↔ TE consistency ------------------------------------------- #
    if ta is not None and te is not None:
        te_pairs = te.select("ETCD", "ELEMENT").unique()
        stray = (
            ta.filter(pl.col("ETCD") != "UNPLAN")
            .select("ETCD", "ELEMENT")
            .unique()
            .join(te_pairs, on=["ETCD", "ELEMENT"], how="anti")
        )
        for row in stray.iter_rows(named=True):
            add(
                "SD0067",
                "error",
                "TA",
                f"(ETCD '{row['ETCD']}', ELEMENT '{row['ELEMENT']}') in TA does not match TE",
            )
        unused = te.join(ta.select("ETCD").unique(), on="ETCD", how="anti")["ETCD"].to_list()
        for etcd in unused:
            add("SD1378", "warning", "TE", f"Element '{etcd}' defined in TE but used by no arm")

    # -- TV ------------------------------------------------------------- #
    if tv is not None:
        dup = tv.group_by("VISITNUM").len().filter(pl.col("len") > 1)["VISITNUM"].to_list()
        for num in dup:
            add("SD1064", "error", "TV", f"Duplicate VISITNUM {num} in TV")
        if "ARMCD" in tv.columns:
            for armcd in _RESERVED_ARMCDS:
                if armcd in tv["ARMCD"].to_list():
                    add("SD1053", "error", "TV", f"Reserved ARMCD '{armcd}' must not appear in TV")
            if ta is not None:
                known = set(ta["ARMCD"].to_list())
                stray_arms = {a for a in tv["ARMCD"].to_list() if a and a not in known}
                for armcd in stray_arms:
                    add("FLEETTD01", "error", "TV", f"TV.ARMCD '{armcd}' not defined in TA")

    # -- TI ------------------------------------------------------------- #
    if ti is not None:
        for code in ti.filter(
            pl.col("IETESTCD").str.len_chars().gt(8) | pl.col("IETESTCD").str.contains(r"^\d")
        )["IETESTCD"].to_list():
            add("SD0018", "error", "TI", f"IETESTCD '{code}' invalid (>8 chars or leading digit)")
        vers = ["TIVERS"] if "TIVERS" in ti.columns else []
        dup = ti.group_by("IETESTCD", *vers).len().filter(pl.col("len") > 1)["IETESTCD"].to_list()
        for code in dup:
            add("SD1286", "error", "TI", f"Duplicate IETESTCD '{code}' within protocol version")

    # -- Char values over the XPT V5 limit ------------------------------- #
    for domain, frame in (("TE", te), ("TA", ta), ("TV", tv), ("TS", ts), ("TI", ti)):
        if frame is None:
            continue
        for col, dtype in frame.schema.items():
            if dtype != pl.String or (domain == "TS" and col.startswith("TSVAL")):
                continue
            long = frame.filter(pl.col(col).str.len_chars() > 200).height
            if long:
                add(
                    "FLEETTD03",
                    "warning",
                    domain,
                    f"{domain}.{col} holds {long} value(s) over 200 characters, the XPT V5 "
                    "limit. Reword the text; only TSVAL splits into TSVAL1-TSVALn.",
                )

    # -- DM ↔ TA -------------------------------------------------------- #
    if dm is not None and ta is not None and "ARMCD" in dm.columns:
        ta_arms = set(ta["ARMCD"].to_list())
        dm_arms = {a for a in dm["ARMCD"].to_list() if a}
        for armcd in sorted(dm_arms - ta_arms - set(_RESERVED_ARMCDS)):
            add("FLEETTD02", "error", "DM", f"DM.ARMCD '{armcd}' not defined in TA")
        for armcd in sorted(ta_arms - dm_arms):
            add("SD1354", "warning", "TA", f"ARMCD '{armcd}' in TA has no subjects in DM")

    # -- TS FDA profile -------------------------------------------------- #
    if ts is not None:
        # An empty TS frame (no rows / no columns) still runs the profile:
        # every required parameter is then missing.
        if "TSPARMCD" in ts.columns:
            present = set(ts["TSPARMCD"].to_list())
            values = {
                row["TSPARMCD"]: row["TSVAL"]
                for row in ts.select("TSPARMCD", "TSVAL").iter_rows(named=True)
            }
        else:
            present, values = set(), {}
        for parm, rule in TS_REQUIRED.items():
            if parm not in present:
                extra = " (FDA rejection criterion 1734)" if parm == "SSTDTC" else ""
                add(rule, "error", "TS", f"Required TS parameter '{parm}' is missing{extra}")
        for trigger, value, required, rule in TS_CONDITIONAL:
            if values.get(trigger, "").upper() == value and required not in present:
                add(
                    rule,
                    "error",
                    "TS",
                    f"TS parameter '{required}' is required when {trigger}={value}",
                )
        randqt = values.get("RANDQT")
        if randqt is not None:
            try:
                ok = 0.0 <= float(randqt) <= 1.0
            except ValueError:
                ok = False
            if not ok:
                add("SD1269", "error", "TS", f"RANDQT '{randqt}' is not a number in [0, 1]")

    return pl.DataFrame(findings, schema=_FINDING_SCHEMA)
