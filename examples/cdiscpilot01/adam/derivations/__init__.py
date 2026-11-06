"""Confirmed Best Overall Response (CBOR): a complex event derivation.

This demonstrates Option B: using ``@derivation(kind="frame")`` for
complex cross-record logic that exceeds what ``pick()`` handles in a
single call.  CBOR compares records *within* a subject to confirm that a
response was sustained, so it is a frame-level operation.

The rules follow admiralonco ``derive_param_confirmed_bor`` with the
Fleet confirmation default of ADR-0030 (``max_nr_ne=1``, no SD between,
no PR after a CR). The SAP decides the windows.

Usage in a pipeline::

    from examples.cdiscpilot01.adam.derivations import CBOR, confirmed_bor

    adrs = rs_sdtm.adam.onco.source("USUBJID").derivation(CBOR).to_frame()

    # One row per subject, with MISSING for an ADSL subject with no response:
    cbor = confirmed_bor(adrs, adsl=adsl, sd_window_days=28)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from fleet.core.derivation import derivation

_EVALUABLE = ("CR", "PR", "SD", "NON-CR/NON-PD", "NE")


def _best_response(
    responses: list[str],
    dates: list[date | None],
    trtsdt: date | None,
    *,
    confirmation_days: int,
    sd_window_days: int,
    max_nr_ne: int,
) -> tuple[str, date | None]:
    """Return (CBOR, CBORDT) for one subject's records, in date order."""

    def days(a: date | None, b: date | None) -> int | None:
        return None if a is None or b is None else (b - a).days

    def confirmed(i: int, confirmers: tuple[str, ...], allowed: tuple[str, ...]) -> bool:
        # The window ends at the first later record that can confirm (ADR-0030).
        for j in range(i + 1, len(responses)):
            gap = days(dates[i], dates[j])
            if responses[j] in confirmers and gap is not None and gap >= confirmation_days:
                window = responses[i : j + 1]
                between = responses[i + 1 : j]
                pr_after_cr = any(r == "PR" and "CR" in window[:k] for k, r in enumerate(window))
                return (
                    all(r in allowed for r in between)
                    and between.count("NE") <= max_nr_ne
                    and not pr_after_cr
                )
        return False

    def first(match: tuple[str, ...], *, after_window: bool) -> int | None:
        for i, r in enumerate(responses):
            if r not in match:
                continue
            gap = days(trtsdt, dates[i])
            if not after_window or (gap is not None and gap >= sd_window_days):
                return i
        return None

    for i, r in enumerate(responses):
        if r == "CR" and confirmed(i, ("CR",), ("CR", "NE")):
            return "CR", dates[i]
    for i, r in enumerate(responses):
        if r == "PR" and confirmed(i, ("CR", "PR"), ("CR", "PR", "NE")):
            return "PR", dates[i]
    for value, match, after_window in (
        ("SD", ("CR", "PR", "SD"), True),
        ("NON-CR/NON-PD", ("NON-CR/NON-PD",), True),
        ("PD", ("PD",), False),
        ("NE", _EVALUABLE, False),
    ):
        i = first(match, after_window=after_window)
        if i is not None:
            return value, dates[i]
    return "NE", None


def confirmed_bor(
    df: pl.DataFrame,
    *,
    adsl: pl.DataFrame | None = None,
    confirmation_days: int = 28,
    sd_window_days: int = 28,
    max_nr_ne: int = 1,
) -> pl.DataFrame:
    """Derive the confirmed best overall response, one row per subject.

    Rules, in this order of preference:

    1. CR: a CR confirmed by a later CR at least *confirmation_days* later;
       only CR and at most *max_nr_ne* NE in between.
    2. PR: a PR confirmed by a later CR or PR at least *confirmation_days*
       later; only CR, PR and at most *max_nr_ne* NE in between, and no PR
       after a CR.
    3. SD: a CR, PR or SD at least *sd_window_days* after TRTSDT.
    4. NON-CR/NON-PD: a NON-CR/NON-PD at least *sd_window_days* after TRTSDT.
    5. PD: a PD.
    6. NE: any other evaluable record.
    7. MISSING: an ADSL subject with no response record. Pass *adsl*, or
       such a subject has no row.

    The records after the first PD of a subject are not used.

    Args:
        df: Response records with USUBJID, AVALC, ADT (date) and TRTSDT (date).
        adsl: ADSL with USUBJID, to give MISSING to a subject with no record.
        confirmation_days: Minimum days between a response and its confirmation.
        sd_window_days: Minimum days from TRTSDT for SD and NON-CR/NON-PD.
        max_nr_ne: Maximum NE records between a response and its confirmation.

    Returns:
        pl.DataFrame: Columns USUBJID, CBOR, CBORDT, sorted by USUBJID.

    References:
        admiralonco 1.4.1 ``derive_param_confirmed_bor`` (``accept_sd=FALSE``);
        Fleet ADR-0030 (response confirmation follows admiralonco by default).
    """
    rows: list[dict] = []
    records = df.filter(pl.col("AVALC").is_not_null()).sort("USUBJID", "ADT")
    for (subj_id,), g in records.group_by("USUBJID", maintain_order=True):
        responses = g["AVALC"].to_list()
        dates = g["ADT"].to_list()
        if "PD" in responses:
            stop = responses.index("PD") + 1
            responses, dates = responses[:stop], dates[:stop]
        trtsdt = g["TRTSDT"][0] if "TRTSDT" in g.columns else None
        cbor, cbordt = _best_response(
            responses,
            dates,
            trtsdt,
            confirmation_days=confirmation_days,
            sd_window_days=sd_window_days,
            max_nr_ne=max_nr_ne,
        )
        rows.append({"USUBJID": subj_id, "CBOR": cbor, "CBORDT": cbordt})

    schema = {"USUBJID": pl.String, "CBOR": pl.String, "CBORDT": pl.Date}
    out = pl.DataFrame(rows, schema=schema)
    no_record = df.select("USUBJID").unique().join(out, on="USUBJID", how="anti")
    if adsl is not None:
        no_record = pl.concat(
            [no_record, adsl.select("USUBJID").join(out, on="USUBJID", how="anti")]
        ).unique()
    missing = no_record.with_columns(
        pl.lit("MISSING").alias("CBOR"), pl.lit(None, dtype=pl.Date).alias("CBORDT")
    )
    return pl.concat([out, missing.select(list(schema))]).sort("USUBJID")


@derivation(targets=["CBOR", "CBORDT"])
def CBOR(df: pl.DataFrame) -> pl.DataFrame:
    """Add CBOR and CBORDT to every record, with the defaults of ``confirmed_bor``.

    Args:
        df: Response records with USUBJID, AVALC, ADT (date) and TRTSDT (date).

    Returns:
        pl.DataFrame: *df* with CBOR and CBORDT added.
    """
    cbor = confirmed_bor(df)
    return df.drop([c for c in ("CBOR", "CBORDT") if c in df.columns]).join(
        cbor, on="USUBJID", how="left"
    )
