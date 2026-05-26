"""Confirmed Best Overall Response (CBOR) — complex event derivation.

This demonstrates Option B: using ``@derivation(kind="frame")`` for
complex cross-record logic that exceeds what ``pick()`` handles in a
single call.  CBOR requires comparing records *within* a subject to
confirm that a response was sustained for ≥28 days — this is inherently
a frame-level operation.

Usage in a pipeline::

    from examples.cdiscpilot01.adam.derivations.CBOR import CBOR

    adrs = (
        rs_sdtm.adam.onco
        .source("USUBJID")
        .derivation(CBOR)
        .to_frame()
    )
"""

from __future__ import annotations

import polars as pl

from fleet.core.derivation import derivation


@derivation(targets=["CBOR", "CBORDT"])
def CBOR(df: pl.DataFrame) -> pl.DataFrame:
    """Derive Confirmed Best Overall Response per subject.

    Logic (RECIST 1.1 confirmation rules):
    1. CR confirmed: two CR assessments ≥28 days apart, with only CR/NE between.
    2. PR confirmed: CR or PR ≥28 days after first PR, with only CR/PR/NE between.
    3. SD: any CR/PR/SD occurring ≥28 days after treatment start.
    4. PD: first progressive disease.
    5. NE: any evaluable response that doesn't meet above.
    6. MISSING: subject has no response records at all.

    Args:
        df: Upstream DataFrame with columns USUBJID, AVALC (response text),
            ADT (assessment date), TRTSDT (treatment start date).

    Returns:
        pl.DataFrame: Frame with CBOR and CBORDT columns added.
    """
    # Response rank: lower = more favourable
    # CR=1, PR=2, SD=3, NON-CR/NON-PD=4, PD=5, NE=6

    subjects = df.select("USUBJID").unique()
    results: list[dict] = []

    for subj_id in subjects["USUBJID"].to_list():
        subj_df = (
            df.filter(pl.col("USUBJID") == subj_id)
            .filter(pl.col("AVALC").is_not_null())
            .sort("ADT")
        )

        if subj_df.is_empty():
            results.append({"USUBJID": subj_id, "CBOR": "MISSING", "CBORDT": None})
            continue

        responses = subj_df["AVALC"].to_list()
        dates = subj_df["ADT"].to_list()
        trtsdt = subj_df["TRTSDT"][0] if "TRTSDT" in subj_df.columns else None

        cbor = None
        cbordt = None

        # 1. Check confirmed CR
        cr_indices = [i for i, r in enumerate(responses) if r == "CR"]
        for i in cr_indices:
            for j in range(i + 1, len(responses)):
                if dates[j] is not None and dates[i] is not None:
                    gap = (dates[j] - dates[i]).days
                    if gap >= 28 and responses[j] == "CR":
                        # Check all between are CR or NE
                        between = responses[i + 1 : j]
                        if all(r in ("CR", "NE") for r in between):
                            if sum(1 for r in between if r == "NE") <= 1:
                                cbor = "CR"
                                cbordt = dates[i]
                                break
            if cbor:
                break

        # 2. Check confirmed PR
        if cbor is None:
            pr_indices = [i for i, r in enumerate(responses) if r == "PR"]
            for i in pr_indices:
                for j in range(i + 1, len(responses)):
                    if dates[j] is not None and dates[i] is not None:
                        gap = (dates[j] - dates[i]).days
                        if gap >= 28 and responses[j] in ("CR", "PR"):
                            between = responses[i + 1 : j]
                            if all(r in ("CR", "PR", "NE") for r in between):
                                if sum(1 for r in between if r == "NE") <= 1:
                                    cbor = "PR"
                                    cbordt = dates[i]
                                    break
                if cbor:
                    break

        # 3. Check SD (≥28 days after treatment start)
        if cbor is None and trtsdt is not None:
            for i, (r, d) in enumerate(zip(responses, dates)):
                if r in ("CR", "PR", "SD") and d is not None:
                    if (d - trtsdt).days >= 28:
                        cbor = "SD"
                        cbordt = d
                        break

        # 4. Check PD
        if cbor is None:
            for i, (r, d) in enumerate(zip(responses, dates)):
                if r == "PD":
                    cbor = "PD"
                    cbordt = d
                    break

        # 5. NE fallback
        if cbor is None:
            cbor = "NE"
            cbordt = dates[0] if dates else None

        results.append({"USUBJID": subj_id, "CBOR": cbor, "CBORDT": cbordt})

    cbor_df = pl.DataFrame(results)

    # Ensure CBORDT is date type
    if "CBORDT" in cbor_df.columns:
        cbor_df = cbor_df.with_columns(pl.col("CBORDT").cast(pl.Date, strict=False))

    # Drop existing CBOR/CBORDT if present, then join
    drop_cols = [c for c in ["CBOR", "CBORDT"] if c in df.columns]
    if drop_cols:
        df = df.drop(drop_cols)

    return df.join(cbor_df, on="USUBJID", how="left")
