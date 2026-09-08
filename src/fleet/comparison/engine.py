"""The comparison engine: pair on keys, match by name, list every difference.

One join, one collect.  Each side gets a position-within-key-group index and
a presence marker, the two are full-joined on the keys plus that index, and
the per-variable inequality flags are evaluated in the same plan.  Every
summary, the duplicate-key check and the value listing derive from that
single collected frame, so the inputs are scanned exactly once.

Pure Polars: no numpy, no pandas.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import polars as pl

from fleet._version import __version__
from fleet.core.exceptions import ComparisonError, VerbUsageError

from .report import (
    LISTING_COLUMNS,
    ComparisonReport,
    ComparisonSettings,
    DatasetSummary,
    MaxPrint,
    ObservationSummary,
    SideSummary,
    ValuesSummary,
    VariableDtypes,
    VariablesSummary,
    _key_label,
    _normalise_max_print,
)

# Internal column names.  Tests never see them; the listing never carries them.
_IDX = "__fleet_compare_idx"
_IN_BASE = "__fleet_compare_in_base"
_IN_CANDIDATE = "__fleet_compare_in_candidate"
_SUFFIX = "__fleet_compare_candidate"
_NEQ = "__fleet_compare_neq_"

#: How many duplicated key values an error message lists per side.
_MAX_REPORTED_DUPLICATES = 10

_TIME_UNITS = ("ns", "us", "ms")  # finest first


def compare(
    base: pl.DataFrame | pl.LazyFrame,
    candidate: pl.DataFrame | pl.LazyFrame,
    *,
    keys: str | Sequence[str],
    max_print: MaxPrint = 50,
    base_name: str | None = None,
    candidate_name: str | None = None,
) -> ComparisonReport:
    """Compare a candidate dataset against a base, PROC COMPARE style.

    Observations pair on ``keys``; variables match by name.  Equality is
    exact: null equals null, NaN equals NaN, null against NaN differs.
    Variables of the same kind (numeric, string, temporal, boolean) but a
    different dtype compare by value after casting to a common supertype
    and are listed as dtype differences; variables of different kinds are
    type conflicts, listed and not compared.  An all-null column, which
    Polars types ``Null``, adopts the other side's dtype.  Keys of one kind
    but different dtypes are cast the same way before pairing.  Row order
    and column order are ignored.

    Args:
        base: The reference dataset, as a DataFrame or LazyFrame.
        candidate: The dataset measured against the base.
        keys: Variable(s) that identify one observation on each side.
            Required; the compare refuses to run when a key is missing or
            not unique on either side.
        max_print: Print limits for the text renderer (differences per
            variable, or a ``(per_variable, total)`` pair, or ``None`` for
            everything).  The listing on the report is never truncated.
        base_name: Label for the base in the report, when known.
        candidate_name: Label for the candidate in the report, when known.

    Returns:
        A :class:`~fleet.comparison.ComparisonReport`.  Differences never
        raise; check ``report.is_equal`` and ``report.flags``.

    Raises:
        ComparisonError: A key is missing, duplicated or of an incompatible
            type on one side, or a key reuses a listing column name.
        VerbUsageError: An input is not a Polars frame, or an argument has
            the wrong type.

    Examples:
        Prove an independently programmed ADAE reached the production result::

            report = fleet.compare(
                adae_prod,
                adae_qc,
                keys=["USUBJID", "AESEQ"],
                base_name="adae (prod)",
                candidate_name="adae (qc)",
            )
            report.print_report()
            assert report.is_equal, report.raised_flags
    """
    base_lf = _as_lazy(base, "base")
    candidate_lf = _as_lazy(candidate, "candidate")
    key_list = _normalise_keys(keys)
    _normalise_max_print(max_print)  # validate early, before any work

    base_schema = base_lf.collect_schema()
    candidate_schema = candidate_lf.collect_schema()
    _check_keys_present(key_list, base_schema, candidate_schema)
    key_casts = _key_casts(key_list, base_schema, candidate_schema)
    variables, casts = _classify_variables(key_list, base_schema, candidate_schema)
    compared = list(variables.compared)

    frame = _join(base_lf, candidate_lf, key_list, compared, key_casts, casts)
    in_base = pl.col(_IN_BASE).fill_null(False)
    in_candidate = pl.col(_IN_CANDIDATE).fill_null(False)
    _check_duplicates(frame, key_list, in_base, in_candidate)

    matched = frame.filter(in_base & in_candidate)
    base_only_keys = frame.filter(in_base & ~in_candidate).select(key_list).sort(key_list)
    candidate_only_keys = frame.filter(~in_base & in_candidate).select(key_list).sort(key_list)
    per_variable, observations_with_differences = _values_summary(matched, compared)
    compared_dtypes = {c: casts.get(c, base_schema[c]) for c in compared}
    listing = _listing(
        matched, key_list, per_variable, compared_dtypes, base_schema, candidate_schema
    )

    flags = {
        "base_only_variables": bool(variables.base_only),
        "candidate_only_variables": bool(variables.candidate_only),
        "type_conflicts": bool(variables.type_conflicts),
        "base_only_observations": base_only_keys.height > 0,
        "candidate_only_observations": candidate_only_keys.height > 0,
        "values_differ": listing.height > 0,
    }
    return ComparisonReport(
        datasets=DatasetSummary(
            base=SideSummary(base_name, frame.filter(in_base).height, len(base_schema)),
            candidate=SideSummary(
                candidate_name, frame.filter(in_candidate).height, len(candidate_schema)
            ),
        ),
        variables=variables,
        observations=ObservationSummary(
            matched=matched.height,
            base_only=base_only_keys.height,
            candidate_only=candidate_only_keys.height,
            base_only_keys=base_only_keys,
            candidate_only_keys=candidate_only_keys,
        ),
        values=ValuesSummary(per_variable, observations_with_differences),
        listing=listing,
        flags=frozenset(name for name, raised in flags.items() if raised),
        settings=ComparisonSettings(
            keys=tuple(key_list),
            max_print=max_print,
            base_name=base_name,
            candidate_name=candidate_name,
        ),
        version=__version__,
    )


# ── Inputs ────────────────────────────────────────────────────────────────────


def _as_lazy(frame: object, side: str) -> pl.LazyFrame:
    if isinstance(frame, pl.LazyFrame):
        return frame
    if isinstance(frame, pl.DataFrame):
        return frame.lazy()
    raise VerbUsageError(
        f"{side} must be a polars DataFrame or LazyFrame, got {type(frame).__name__}"
    )


def _normalise_keys(keys: object) -> list[str]:
    if isinstance(keys, str):
        key_list = [keys]
    elif isinstance(keys, Sequence) and all(isinstance(k, str) for k in keys):
        key_list = list(keys)
    else:
        raise VerbUsageError("keys must be a variable name or a sequence of variable names")
    if not key_list:
        raise ComparisonError("keys must name at least one variable; a compare needs keys to run")
    repeated = sorted({k for k in key_list if key_list.count(k) > 1})
    if repeated:
        raise ComparisonError(f"keys repeat a variable: {', '.join(repeated)}")
    reserved = [k for k in key_list if k in LISTING_COLUMNS]
    if reserved:
        raise ComparisonError(
            f"keys may not reuse a listing column name: {', '.join(reserved)} "
            f"(reserved: {', '.join(LISTING_COLUMNS)})"
        )
    return key_list


def _check_keys_present(keys: list[str], base: pl.Schema, candidate: pl.Schema) -> None:
    problems = []
    for side, schema in (("base", base), ("candidate", candidate)):
        missing = [k for k in keys if k not in schema]
        if missing:
            problems.append(f"{side} is missing key(s): {', '.join(missing)}")
    if problems:
        raise ComparisonError("; ".join(problems))


def _key_casts(keys: list[str], base: pl.Schema, candidate: pl.Schema) -> dict[str, pl.DataType]:
    """Common dtype per key whose dtype differs between sides; incompatible keys raise."""
    casts: dict[str, pl.DataType] = {}
    for k in keys:
        a, b = base[k], candidate[k]
        if a == b:
            continue
        supertype = _supertype(a, b)
        if supertype is None:
            raise ComparisonError(
                f"key {k!r} is {a} in base and {b} in candidate; keys must be of one kind"
            )
        casts[k] = supertype
    return casts


# ── Variable classification ───────────────────────────────────────────────────


def _kind(dtype: pl.DataType) -> str:
    """Classify a dtype: numeric, string, temporal, boolean or other."""
    if dtype.is_numeric():
        return "numeric"
    if dtype == pl.String or isinstance(dtype, (pl.Categorical, pl.Enum)):
        return "string"
    if dtype.is_temporal():
        return "temporal"
    if dtype == pl.Boolean:
        return "boolean"
    return "other"


def _supertype(a: pl.DataType, b: pl.DataType) -> pl.DataType | None:
    """Common dtype two variables of one kind are cast to before comparing; None if none."""
    if a == b:
        return a
    if a == pl.Null:  # an all-null column carries no kind of its own
        return b
    if b == pl.Null:
        return a
    a_kind, b_kind = _kind(a), _kind(b)
    if a_kind != b_kind:
        return None
    if a_kind == "numeric":
        if not (a.is_integer() and b.is_integer()):
            return pl.Float64()
        if pl.UInt64 in (a, b):
            return pl.Int128()
        return pl.Int64()
    if a_kind == "string":
        return pl.String()
    if a_kind == "temporal":
        return _temporal_supertype(a, b)
    return None  # boolean is a single dtype; kind "other" compares only when identical


def _temporal_supertype(a: pl.DataType, b: pl.DataType) -> pl.DataType | None:
    if all(t == pl.Date or isinstance(t, pl.Datetime) for t in (a, b)):
        datetimes = [t for t in (a, b) if isinstance(t, pl.Datetime)]
        zones = {t.time_zone for t in datetimes}
        if len(zones) > 1:
            return None  # two different time zones: no unambiguous common instant
        zone = zones.pop()
        if zone is not None and len(datetimes) == 1:
            return None  # a date against a zone-aware datetime has no midnight to pick
        return pl.Datetime(_finest(t.time_unit for t in datetimes), zone)
    if all(isinstance(t, pl.Duration) for t in (a, b)):
        return pl.Duration(_finest(t.time_unit for t in (a, b)))
    return None


def _finest(units: Iterable[str]) -> str:
    present = set(units)
    return next(u for u in _TIME_UNITS if u in present)


def _classify_variables(
    keys: list[str], base: pl.Schema, candidate: pl.Schema
) -> tuple[VariablesSummary, dict[str, pl.DataType]]:
    common = [c for c in base if c in candidate and c not in keys]
    conflicts: list[VariableDtypes] = []
    dtype_differences: list[VariableDtypes] = []
    casts: dict[str, pl.DataType] = {}
    for c in common:
        a, b = base[c], candidate[c]
        if a == b:
            continue
        supertype = _supertype(a, b)
        if supertype is None:
            conflicts.append(VariableDtypes(c, a, b))
        else:
            dtype_differences.append(VariableDtypes(c, a, b))
            casts[c] = supertype
    summary = VariablesSummary(
        common=tuple(common),
        base_only=tuple(c for c in base if c not in candidate),
        candidate_only=tuple(c for c in candidate if c not in base),
        type_conflicts=tuple(conflicts),
        dtype_differences=tuple(dtype_differences),
    )
    return summary, casts


# ── The single plan ───────────────────────────────────────────────────────────


def _prepare(
    lf: pl.LazyFrame,
    keys: list[str],
    compared: list[str],
    key_casts: dict[str, pl.DataType],
    marker: str,
) -> pl.LazyFrame:
    columns = [pl.col(k).cast(key_casts[k]) if k in key_casts else pl.col(k) for k in keys]
    columns += [pl.col(c) for c in compared]
    return lf.select(columns).with_columns(
        pl.int_range(pl.len()).over(keys).alias(_IDX),
        pl.lit(True).alias(marker),
    )


def _join(
    base: pl.LazyFrame,
    candidate: pl.LazyFrame,
    keys: list[str],
    compared: list[str],
    key_casts: dict[str, pl.DataType],
    casts: dict[str, pl.DataType],
) -> pl.DataFrame:
    """Full-join both sides on the keys and evaluate the inequality flags; the one collect."""
    joined = _prepare(base, keys, compared, key_casts, _IN_BASE).join(
        _prepare(candidate, keys, compared, key_casts, _IN_CANDIDATE),
        on=[*keys, _IDX],
        how="full",
        coalesce=True,
        suffix=_SUFFIX,
        nulls_equal=True,
    )
    return joined.with_columns([_unequal(c, casts.get(c)) for c in compared]).collect()


def _unequal(variable: str, cast_to: pl.DataType | None) -> pl.Expr:
    """True where the base and candidate values differ.

    Null equals null, NaN equals NaN, null against anything else (NaN
    included) differs: ``!=`` is false for NaN against NaN and null when
    either side is null, so ``fill_null(True)`` is what makes a one-sided
    null a difference.
    """
    base_value, candidate_value = pl.col(variable), pl.col(variable + _SUFFIX)
    if cast_to is not None:
        base_value, candidate_value = base_value.cast(cast_to), candidate_value.cast(cast_to)
    unequal = base_value != candidate_value
    unequal = (
        pl.when(base_value.is_null() & candidate_value.is_null())
        .then(False)
        .otherwise(unequal.fill_null(True))
    )
    return unequal.alias(_NEQ + variable)


# ── Derived from the collected frame ──────────────────────────────────────────


def _check_duplicates(
    frame: pl.DataFrame, keys: list[str], in_base: pl.Expr, in_candidate: pl.Expr
) -> None:
    duplicated = pl.col(_IDX) > 0
    problems = []
    for side, present in (("base", in_base), ("candidate", in_candidate)):
        dups = frame.filter(present & duplicated).select(keys).unique().sort(keys)
        if dups.height == 0:
            continue
        shown = "; ".join(
            _key_label(keys, row) for row in dups.head(_MAX_REPORTED_DUPLICATES).iter_rows()
        )
        more = (
            f"; ... {dups.height - _MAX_REPORTED_DUPLICATES} more"
            if dups.height > _MAX_REPORTED_DUPLICATES
            else ""
        )
        problems.append(f"{side} has {dups.height} duplicated key value(s): {shown}{more}")
    if problems:
        raise ComparisonError(
            "keys must identify one observation per side, but " + " | ".join(problems)
        )


def _values_summary(matched: pl.DataFrame, compared: list[str]) -> tuple[pl.DataFrame, int]:
    if not compared:
        return pl.DataFrame(schema={"variable": pl.String, "differences": pl.Int64}), 0
    counts = matched.select([pl.col(_NEQ + c).sum().cast(pl.Int64).alias(c) for c in compared])
    per_variable = counts.unpivot(variable_name="variable", value_name="differences")
    with_differences = matched.select(
        pl.any_horizontal([pl.col(_NEQ + c) for c in compared]).sum()
    ).item()
    return per_variable, int(with_differences or 0)


def _listing(
    matched: pl.DataFrame,
    keys: list[str],
    per_variable: pl.DataFrame,
    compared_dtypes: dict[str, pl.DataType],
    base_schema: pl.Schema,
    candidate_schema: pl.Schema,
) -> pl.DataFrame:
    """Long frame of every differing value, sorted by keys; ``compared_dtypes`` is the dtype each variable was compared under."""
    differing = per_variable.filter(pl.col("differences") > 0)["variable"].to_list()
    parts = []
    for c in differing:
        base_value, candidate_value = pl.col(c), pl.col(c + _SUFFIX)
        if _kind(compared_dtypes[c]) == "numeric":
            base_number = base_value.cast(pl.Float64)
            difference = candidate_value.cast(pl.Float64) - base_number
            percent = (
                pl.when(base_number.is_null() | (base_number == 0))
                .then(pl.lit(None, pl.Float64))
                .otherwise(difference / base_number * 100)
            )
        else:
            difference = percent = pl.lit(None, pl.Float64)
        parts.append(
            matched.filter(pl.col(_NEQ + c)).select(
                *[pl.col(k) for k in keys],
                pl.lit(None, pl.String).alias("group"),
                pl.lit(c, pl.String).alias("variable"),
                _as_string(base_value, base_schema[c]).alias("base"),
                _as_string(candidate_value, candidate_schema[c]).alias("candidate"),
                difference.cast(pl.Float64).alias("difference"),
                percent.cast(pl.Float64).alias("percent_difference"),
            )
        )
    if not parts:
        schema = {k: matched.schema[k] for k in keys}
        schema.update(
            group=pl.String,
            variable=pl.String,
            base=pl.String,
            candidate=pl.String,
            difference=pl.Float64,
            percent_difference=pl.Float64,
        )
        return pl.DataFrame(schema=schema)
    return pl.concat(parts).sort(keys, maintain_order=True)


def _as_string(expr: pl.Expr, dtype: pl.DataType) -> pl.Expr:
    """Render a value as text for the listing; nested values as JSON."""
    if dtype.is_nested():
        encoded = (
            pl.struct(expr.alias("v"))
            .struct.json_encode()
            .str.strip_prefix('{"v":')
            .str.strip_suffix("}")
        )
        return pl.when(expr.is_null()).then(pl.lit(None, pl.String)).otherwise(encoded)
    return expr.cast(pl.String, strict=False)


__all__ = ["compare"]
