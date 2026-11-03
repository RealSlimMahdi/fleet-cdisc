"""The comparison engine: pair on keys, match by name, list every difference.

One join, one collect.  Each side gets a position-within-key-group index and
a presence marker, the two are full-joined on the keys plus that index, and
the per-variable inequality flags are evaluated in the same plan.  Every
summary, the duplicate-key check, the per-BY-group breakdowns and the value
listing derive from that single collected frame, so the inputs are scanned
exactly once.  BY variables are simply the first of the keys, which is what
makes sectioning cost nothing extra: the index is already per group and the
listing already sorts by group first.

Pure Polars: no numpy, no pandas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import polars as pl
import polars.selectors as cs

from fleet._version import __version__
from fleet.core.exceptions import ComparisonError, VerbUsageError

from .report import (
    GROUP_OBSERVATIONS,
    GROUP_VALUES,
    LISTING_COLUMNS,
    STATISTICS,
    ComparisonReport,
    ComparisonSettings,
    DatasetSummary,
    MaxPrint,
    ObservationSummary,
    SideSummary,
    ValuesSummary,
    VariableDtypes,
    VariablesSummary,
    _empty,
    _key_label,
    _normalise_flag,
    _normalise_max_print,
    _normalise_tolerance,
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
    by: str | Sequence[str] | None = None,
    pairs: Mapping[str, str] | None = None,
    variables: str | Sequence[str] | None = None,
    abs_tol: float = 0.0,
    rel_tol: float = 0.0,
    ignore_trailing_whitespace: bool = False,
    blank_is_missing: bool = False,
    allow_duplicates: bool = False,
    max_print: MaxPrint = 50,
    base_name: str | None = None,
    candidate_name: str | None = None,
) -> ComparisonReport:
    """Compare a candidate dataset against a base, PROC COMPARE style.

    Observations pair on ``keys``; variables match by name.  Equality is
    exact by default: null equals null, NaN equals NaN, null against NaN
    differs.  ``abs_tol`` and ``rel_tol`` widen it on the numeric variables
    and ``ignore_trailing_whitespace`` on the string ones; nulls and NaN
    keep their rule under both.  Variables of the same kind (numeric,
    string, temporal, boolean) but a different dtype compare by value after
    casting to a common supertype and are listed as dtype differences;
    variables of different kinds are type conflicts, listed and not
    compared.  An all-null column, which Polars types ``Null``, adopts the
    other side's dtype.  Keys of one kind but different dtypes are cast the
    same way before pairing.  Row order and column order are ignored.

    Args:
        base: The reference dataset, as a DataFrame or LazyFrame.
        candidate: The dataset measured against the base.
        keys: Variable(s) that identify one observation on each side.
            Required; the compare refuses to run when a key is missing or
            not unique on either side.
        by: Variable(s) the report is sectioned by.  They are prepended to
            ``keys`` automatically, so they need not be repeated there,
            they label the listing's ``group`` column, and the observation
            and values summaries are additionally reported per group.  A
            group present on one side only raises ``base_only_groups`` or
            ``candidate_only_groups``; the verdict stays global.
        pairs: Base variable names mapped to the candidate names that carry
            them, applied on top of the automatic name matching, so a
            renamed column is compared rather than reported missing.  The
            report names a paired variable by its **base** name.  A pair
            whose candidate name is absent reports the base variable as
            missing from the candidate.
        variables: Restrict the comparison to these variables, in **base**
            names.  A variable outside the restriction is ignored on both
            sides: it is neither compared nor reported as missing.  The
            default compares every variable that is not a key.  A
            restriction that names only keys is refused.
        abs_tol: Absolute tolerance on the numeric variables.  ``0.0`` (the
            default) is exact.
        rel_tol: Relative tolerance on the numeric variables, as a fraction
            of the **base** value.  ``0.0`` (the default) is exact.  A numeric
            pair differs when the absolute difference exceeds
            ``max(abs_tol, rel_tol * abs(base))``; the relative tolerance
            anchors on the base because the base is the reference, as in
            SAS and unlike Polars' testing helper.
            A tolerant comparison is done in ``Float64``, so integers and
            decimals beyond ``2**53`` are compared at that precision;
            the exact default compares them in their own dtype.
        ignore_trailing_whitespace: Strip trailing whitespace from both
            sides of a string before comparing, so SAS's padded character
            values equal Fleet's stripped ones.  Leading whitespace still
            differs.
        blank_is_missing: Read an empty string as null on both sides, keys
            included, as SAS does: SAS has one character missing value, the
            blank.  Use it when one side comes from a tool that kept ``""``
            (an R data frame without ``convert_blanks_to_na``).  Off by
            default, because the two frames then give different
            ``is_null()`` results.
        allow_duplicates: Pair duplicate keys by their position within each
            key group instead of refusing to run.  The observation summary
            then counts the duplicates per side, the ``duplicate_keys`` flag
            is raised and every renderer warns.  Order within a key group
            decides which observations pair, so it is a weaker guarantee
            than pairing on keys.
        max_print: Print limits for the text renderer (differences per
            variable, or a ``(per_variable, total)`` pair, or ``None`` for
            everything).  The listing on the report is never truncated.
        base_name: Label for the base in the report, when known.
        candidate_name: Label for the candidate in the report, when known.

    Returns:
        A :class:`~fleet.comparison.ComparisonReport`.  Differences never
        raise; check ``report.is_equal`` and ``report.flags``.

    Raises:
        ComparisonError: A key or BY variable is missing, duplicated (without
            ``allow_duplicates``) or of an incompatible type on one side, a
            key reuses a listing column name, a pair or a restriction names a
            variable no side carries, a restriction names only keys, or a
            tolerance is negative or not finite.
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

        Section the report by treatment arm, so a difference in one arm
        stands out::

            report = fleet.compare(adsl_prod, adsl_qc, keys="USUBJID", by="TRT01P")
            report.observations.per_group

        Compare a legacy dataset that named two variables differently, on
        the variables that are finished::

            report = fleet.compare(
                advs_legacy,
                advs_wip,
                keys=["USUBJID", "PARAMCD"],
                pairs={"AVAL": "RESULT"},
                variables=["AVAL", "AVISIT"],
            )
    """
    base_lf = _as_lazy(base, "base")
    candidate_lf = _as_lazy(candidate, "candidate")
    by_list = _normalise_by(by)
    key_list = _normalise_keys(keys, by_list)
    _normalise_max_print(max_print)  # validate early, before any work
    base_schema = base_lf.collect_schema()
    candidate_schema = candidate_lf.collect_schema()
    _check_keys_present(key_list, base_schema, candidate_schema)
    # The settings are both the record of the run and the rule the join
    # evaluates, so every option is checked as they are built.
    settings = ComparisonSettings(
        keys=tuple(key_list),
        by=tuple(by_list),
        pairs=_normalise_pairs(pairs, key_list, base_schema),
        variables=_normalise_variables(variables, key_list, base_schema, candidate_schema),
        abs_tol=_normalise_tolerance(abs_tol, "abs_tol"),
        rel_tol=_normalise_tolerance(rel_tol, "rel_tol"),
        ignore_trailing_whitespace=_normalise_flag(
            ignore_trailing_whitespace, "ignore_trailing_whitespace"
        ),
        blank_is_missing=_normalise_flag(blank_is_missing, "blank_is_missing"),
        allow_duplicates=_normalise_flag(allow_duplicates, "allow_duplicates"),
        max_print=max_print,
        base_name=base_name,
        candidate_name=candidate_name,
    )

    key_casts = _key_casts(key_list, base_schema, candidate_schema)
    variables_summary, casts = _classify_variables(
        key_list, base_schema, candidate_schema, settings
    )
    compared = list(variables_summary.compared)
    #: The dtype each compared variable was compared under: the common
    #: supertype where the sides disagreed, the base dtype otherwise.
    compared_dtypes = {c: casts.get(c, base_schema[c]) for c in compared}
    #: The dtype each side stores a compared variable in, before any cast.
    base_dtypes = {c: base_schema[c] for c in compared}
    candidate_dtypes = {c: candidate_schema[settings.pairs.get(c, c)] for c in compared}

    frame = _join(base_lf, candidate_lf, key_list, compared, key_casts, compared_dtypes, settings)
    in_base = pl.col(_IN_BASE).fill_null(False)
    in_candidate = pl.col(_IN_CANDIDATE).fill_null(False)
    duplicates = _duplicates(frame, key_list, in_base, in_candidate, settings.allow_duplicates)

    matched = frame.filter(in_base & in_candidate)
    base_only_keys = frame.filter(in_base & ~in_candidate).select(key_list).sort(key_list)
    candidate_only_keys = frame.filter(~in_base & in_candidate).select(key_list).sort(key_list)
    per_variable, observations_with_differences = _values_summary(matched, compared)
    listing = _listing(
        matched, key_list, by_list, per_variable, compared_dtypes, base_dtypes, candidate_dtypes
    )
    statistics = _statistics(matched, per_variable, compared_dtypes)
    base_only_groups, candidate_only_groups = _one_sided_groups(
        frame, by_list, in_base, in_candidate
    )

    flags = {
        "base_only_variables": bool(variables_summary.base_only),
        "candidate_only_variables": bool(variables_summary.candidate_only),
        "type_conflicts": bool(variables_summary.type_conflicts),
        "base_only_observations": base_only_keys.height > 0,
        "candidate_only_observations": candidate_only_keys.height > 0,
        "values_differ": listing.height > 0,
        "duplicate_keys": any(duplicates),
        "base_only_groups": bool(base_only_groups),
        "candidate_only_groups": bool(candidate_only_groups),
    }
    return ComparisonReport(
        datasets=DatasetSummary(
            base=SideSummary(base_name, frame.filter(in_base).height, len(base_schema)),
            candidate=SideSummary(
                candidate_name, frame.filter(in_candidate).height, len(candidate_schema)
            ),
        ),
        variables=variables_summary,
        observations=ObservationSummary(
            matched=matched.height,
            base_only=base_only_keys.height,
            candidate_only=candidate_only_keys.height,
            base_only_keys=base_only_keys,
            candidate_only_keys=candidate_only_keys,
            base_duplicates=duplicates[0],
            candidate_duplicates=duplicates[1],
            per_group=_observations_per_group(frame, by_list, in_base, in_candidate),
            base_only_groups=base_only_groups,
            candidate_only_groups=candidate_only_groups,
        ),
        values=ValuesSummary(
            per_variable,
            observations_with_differences,
            per_group=_values_per_group(matched, by_list, compared),
        ),
        listing=listing,
        statistics=statistics,
        flags=frozenset(name for name, raised in flags.items() if raised),
        settings=settings,
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


def _normalise_by(by: object) -> list[str]:
    """The BY variables as a list; ``None`` means no sectioning."""
    if by is None:
        return []
    by_list = _as_names(by, "by")
    if not by_list:
        return []
    repeated = sorted({b for b in by_list if by_list.count(b) > 1})
    if repeated:
        raise ComparisonError(f"by repeats a variable: {', '.join(repeated)}")
    return by_list


def _normalise_keys(keys: object, by: list[str]) -> list[str]:
    """The variables observations pair on: the BY variables first, then the keys.

    A BY variable repeated among the keys is dropped rather than refused,
    because prepending is automatic and the user need not know it happened.
    """
    key_list = _as_names(keys, "keys")
    if not key_list:
        raise ComparisonError("keys must name at least one variable; a compare needs keys to run")
    repeated = sorted({k for k in key_list if key_list.count(k) > 1})
    if repeated:
        raise ComparisonError(f"keys repeat a variable: {', '.join(repeated)}")
    pairing = [*by, *(k for k in key_list if k not in by)]
    reserved = [k for k in pairing if k in LISTING_COLUMNS]
    if reserved:
        raise ComparisonError(
            f"keys may not reuse a listing column name: {', '.join(reserved)} "
            f"(reserved: {', '.join(LISTING_COLUMNS)})"
        )
    return pairing


def _as_names(value: object, argument: str) -> list[str]:
    """One variable name or a sequence of them, as a list."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and all(isinstance(name, str) for name in value):
        return list(value)
    raise VerbUsageError(f"{argument} must be a variable name or a sequence of variable names")


def _normalise_pairs(pairs: object, keys: list[str], base: pl.Schema) -> dict[str, str]:
    """The base names mapped to the candidate names carrying them, checked against the base.

    A pair is stated in the base's vocabulary, so its left-hand side must be
    a base variable that is compared; its right-hand side is checked against
    the candidate later, where an absent one reports the base variable as
    missing rather than stopping the compare.
    """
    if pairs is None:
        return {}
    if not isinstance(pairs, Mapping) or not all(
        isinstance(name, str) for pair in pairs.items() for name in pair
    ):
        raise VerbUsageError(
            "pairs must be a mapping of base variable names to candidate variable names"
        )
    unknown = [b for b in pairs if b not in base]
    if unknown:
        raise ComparisonError(f"pairs names variable(s) absent from the base: {', '.join(unknown)}")
    renamed_keys = [b for b in pairs if b in keys]
    if renamed_keys:
        raise ComparisonError(
            f"pairs may not rename a key: {', '.join(renamed_keys)}; "
            "observations pair on keys of the same name on both sides"
        )
    targets = list(pairs.values())
    repeated = sorted({c for c in targets if targets.count(c) > 1})
    if repeated:
        raise ComparisonError(
            f"pairs maps more than one base variable to candidate variable(s): {', '.join(repeated)}"
        )
    return dict(pairs)


def _normalise_variables(
    variables: object, keys: list[str], base: pl.Schema, candidate: pl.Schema
) -> tuple[str, ...] | None:
    """The variables the comparison is restricted to; ``None`` compares them all.

    A name no side carries, or a restriction of keys only, is refused,
    because a restriction that silently compares nothing would report a
    dataset as equal.
    """
    if variables is None:
        return None
    names = _as_names(variables, "variables")
    if not names:
        raise ComparisonError(
            "variables must name at least one variable; omit it to compare them all"
        )
    unknown = [v for v in names if v not in base and v not in candidate]
    if unknown:
        raise ComparisonError(
            f"variables names variable(s) present on neither side: {', '.join(unknown)}"
        )
    if all(v in keys for v in names):
        raise ComparisonError(
            f"variables names only key variables ({', '.join(names)}); "
            "keys pair the observations and are never compared"
        )
    return tuple(dict.fromkeys(names))


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
    keys: list[str], base: pl.Schema, candidate: pl.Schema, settings: ComparisonSettings
) -> tuple[VariablesSummary, dict[str, pl.DataType]]:
    """Sort the variables into common, one-sided, conflicting and differently typed.

    The universe is the base's variables less the keys, narrowed to the
    restriction when one was given: what is outside it is ignored on both
    sides and raises no flag.  A variable is common when the candidate
    carries the name the pairs give it, its own otherwise, and is named
    after the base throughout the report.
    """
    restriction, pairs = settings.variables, settings.pairs
    universe = [c for c in base if c not in keys and (restriction is None or c in restriction)]
    common = [c for c in universe if pairs.get(c, c) in candidate]
    paired = {pairs.get(c, c) for c in common}
    conflicts: list[VariableDtypes] = []
    dtype_differences: list[VariableDtypes] = []
    casts: dict[str, pl.DataType] = {}
    for c in common:
        a, b = base[c], candidate[pairs.get(c, c)]
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
        base_only=tuple(c for c in universe if c not in common),
        candidate_only=tuple(
            c
            for c in candidate
            if c not in base and c not in paired and (restriction is None or c in restriction)
        ),
        type_conflicts=tuple(conflicts),
        dtype_differences=tuple(dtype_differences),
    )
    return summary, casts


# ── The single plan ───────────────────────────────────────────────────────────


def _prepare(
    lf: pl.LazyFrame,
    keys: list[str],
    compared: Mapping[str, str],
    key_casts: dict[str, pl.DataType],
    marker: str,
    blank_is_missing: bool,
) -> pl.LazyFrame:
    """One side, presenting every compared variable under its base name; *compared* maps that name to this side's column."""
    columns = [pl.col(k).cast(key_casts[k]) if k in key_casts else pl.col(k) for k in keys]
    columns += [pl.col(source).alias(name) for name, source in compared.items()]
    side = lf.select(columns)
    if blank_is_missing:
        side = side.with_columns(cs.string().replace("", None))
    return side.with_columns(
        pl.int_range(pl.len()).over(keys).alias(_IDX),
        pl.lit(True).alias(marker),
    )


def _join(
    base: pl.LazyFrame,
    candidate: pl.LazyFrame,
    keys: list[str],
    compared: list[str],
    key_casts: dict[str, pl.DataType],
    compared_dtypes: dict[str, pl.DataType],
    settings: ComparisonSettings,
) -> pl.DataFrame:
    """Full-join both sides on the keys and evaluate the inequality flags; the one collect."""
    joined = _prepare(
        base, keys, {c: c for c in compared}, key_casts, _IN_BASE, settings.blank_is_missing
    ).join(
        _prepare(
            candidate,
            keys,
            {c: settings.pairs.get(c, c) for c in compared},
            key_casts,
            _IN_CANDIDATE,
            settings.blank_is_missing,
        ),
        on=[*keys, _IDX],
        how="full",
        coalesce=True,
        suffix=_SUFFIX,
        nulls_equal=True,
    )
    unequal = [_unequal(c, compared_dtypes[c], settings) for c in compared]
    return joined.with_columns(unequal).collect()


def _unequal(variable: str, dtype: pl.DataType, settings: ComparisonSettings) -> pl.Expr:
    """True where the base and candidate values differ under *settings*.

    Null equals null, NaN equals NaN, null against anything else (NaN
    included) differs.  The rule survives every equality mode because it is
    settled here rather than inside them: ``fill_null(True)`` is what makes
    a one-sided null a difference, and the outer ``when`` is what keeps two
    nulls equal.
    """
    base_value = pl.col(variable).cast(dtype)
    candidate_value = pl.col(variable + _SUFFIX).cast(dtype)
    kind = _kind(dtype)
    if kind == "numeric" and settings.tolerant:
        unequal = _outside_tolerance(base_value, candidate_value, settings)
    elif kind == "string" and settings.ignore_trailing_whitespace:
        unequal = _stripped(base_value) != _stripped(candidate_value)
    else:
        unequal = base_value != candidate_value
    return (
        pl.when(base_value.is_null() & candidate_value.is_null())
        .then(False)
        .otherwise(unequal.fill_null(True))
        .alias(_NEQ + variable)
    )


def _outside_tolerance(
    base_value: pl.Expr, candidate_value: pl.Expr, settings: ComparisonSettings
) -> pl.Expr:
    """True where two numbers differ by more than ``max(abs_tol, rel_tol * |base|)``.

    The relative tolerance anchors on the base because the base is the
    reference; this follows SAS and deliberately not Polars' testing helper,
    which anchors on the right-hand frame.

    NaN is settled before the subtraction, because Polars orders NaN as the
    largest float: ``NaN - NaN`` is NaN and ``NaN > tol`` is *true*, so
    without the first branch two NaNs would be reported as differing, against
    the rule that NaN equals NaN.  The second branch states the other half of
    that rule — a NaN is never within a tolerance of a number — which the same
    ordering happens to give anyway; it is written out so the guarantee does
    not rest on how Polars chooses to order NaN.
    """
    # Float64 is the arithmetic a tolerance is expressed in; an integer or a
    # decimal beyond 2**53 loses precision on the way in (see the compare docstring).
    base_number, candidate_number = base_value.cast(pl.Float64), candidate_value.cast(pl.Float64)
    tolerance = pl.max_horizontal(
        pl.lit(settings.abs_tol, pl.Float64), base_number.abs() * settings.rel_tol
    )
    base_nan, candidate_nan = base_number.is_nan(), candidate_number.is_nan()
    return (
        pl.when(base_nan & candidate_nan)
        .then(False)
        .when(base_nan | candidate_nan)
        .then(True)
        .otherwise((base_number - candidate_number).abs() > tolerance)
    )


def _stripped(value: pl.Expr) -> pl.Expr:
    """A string without its trailing whitespace; what leads it still counts."""
    return value.cast(pl.String).str.strip_chars_end()


# ── Derived from the collected frame ──────────────────────────────────────────


def _duplicates(
    frame: pl.DataFrame,
    keys: list[str],
    in_base: pl.Expr,
    in_candidate: pl.Expr,
    allowed: bool,
) -> tuple[int, int]:
    """Duplicated observations per side; without ``allow_duplicates`` they stop the compare.

    A duplicate is an observation beyond the first in its key group.  The
    join already pairs them by that position, so allowing them is only a
    matter of counting instead of refusing.
    """
    duplicated = pl.col(_IDX) > 0
    counts, problems = [], []
    for side, present in (("base", in_base), ("candidate", in_candidate)):
        rows = frame.filter(present & duplicated)
        counts.append(rows.height)
        if allowed or rows.height == 0:
            continue
        dups = rows.select(keys).unique().sort(keys)
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
            "keys must identify one observation per side, but "
            + " | ".join(problems)
            + " (pass allow_duplicates=True to pair them by position instead)"
        )
    return counts[0], counts[1]


def _group_label(by: list[str]) -> pl.Expr:
    """The ``group`` column: ``B1=v1, B2=v2`` over the BY variables, ``null`` for a null value."""
    return pl.concat_str(
        [pl.concat_str(pl.lit(f"{b}="), pl.col(b).cast(pl.String).fill_null("null")) for b in by],
        separator=", ",
    )


def _observations_per_group(
    frame: pl.DataFrame, by: list[str], in_base: pl.Expr, in_candidate: pl.Expr
) -> pl.DataFrame:
    """How observations paired within each BY group, in group order."""
    if not by:
        return _empty(GROUP_OBSERVATIONS)
    return (
        frame.group_by(by)
        .agg(
            (in_base & in_candidate).sum().alias("matched"),
            (in_base & ~in_candidate).sum().alias("base_only"),
            (~in_base & in_candidate).sum().alias("candidate_only"),
        )
        .sort(by)
        .select(_group_label(by).alias("group"), pl.exclude(by).cast(pl.Int64))
    )


def _one_sided_groups(
    frame: pl.DataFrame, by: list[str], in_base: pl.Expr, in_candidate: pl.Expr
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Labels of the BY groups present in one dataset only, in group order."""
    if not by:
        return (), ()
    presence = (
        frame.group_by(by)
        .agg(in_base.any().alias("base"), in_candidate.any().alias("candidate"))
        .sort(by)
        .select(_group_label(by).alias("group"), "base", "candidate")
    )
    return (
        tuple(presence.filter(pl.col("base") & ~pl.col("candidate"))["group"]),
        tuple(presence.filter(~pl.col("base") & pl.col("candidate"))["group"]),
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


def _values_per_group(matched: pl.DataFrame, by: list[str], compared: list[str]) -> pl.DataFrame:
    """What differed within each BY group, over its matched observations, in group order.

    Only groups with matched observations appear: a group present on one
    side only has nothing to compare and is reported as a one-sided group
    instead.
    """
    if not by:
        return _empty(GROUP_VALUES)
    zero = pl.lit(0, pl.Int64)
    unequal = [pl.col(_NEQ + c) for c in compared]
    grouped = (
        matched.group_by(by)
        .agg(
            *[u.sum().alias(_NEQ + c) for u, c in zip(unequal, compared)],
            (pl.any_horizontal(unequal).sum() if compared else zero).alias(
                "observations_with_differences"
            ),
        )
        .sort(by)
    )
    return grouped.select(
        _group_label(by).alias("group"),
        pl.sum_horizontal([u > 0 for u in unequal] or [zero])
        .cast(pl.Int64)
        .alias("variables_with_differences"),
        pl.col("observations_with_differences").cast(pl.Int64),
        pl.sum_horizontal(unequal or [zero]).cast(pl.Int64).alias("differences"),
    )


def _listing(
    matched: pl.DataFrame,
    keys: list[str],
    by: list[str],
    per_variable: pl.DataFrame,
    compared_dtypes: dict[str, pl.DataType],
    base_dtypes: dict[str, pl.DataType],
    candidate_dtypes: dict[str, pl.DataType],
) -> pl.DataFrame:
    """Long frame of every differing value, sorted by keys (BY variables first); ``compared_dtypes`` is the dtype each variable was compared under, ``base_dtypes`` and ``candidate_dtypes`` the dtypes the sides store it in."""
    group = _group_label(by) if by else pl.lit(None, pl.String)
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
                group.alias("group"),
                pl.lit(c, pl.String).alias("variable"),
                _as_string(base_value, base_dtypes[c]).alias("base"),
                _as_string(candidate_value, candidate_dtypes[c]).alias("candidate"),
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


def _statistics(
    matched: pl.DataFrame, per_variable: pl.DataFrame, compared_dtypes: dict[str, pl.DataType]
) -> pl.DataFrame:
    """One row per differing variable: how many observations differ, and how far apart they are.

    A numeric variable also carries the distribution of both sides, of their
    difference and of that difference as a percentage of the base, so a
    systematic offset reads differently from random noise.  Every other kind
    contributes its count alone.  All of it is aggregated in one pass.
    """
    counts = dict(per_variable.filter(pl.col("differences") > 0).iter_rows())
    numeric = [c for c in counts if _kind(compared_dtypes[c]) == "numeric"]
    measured = (
        matched.select(_variable_statistics(c).alias(c) for c in numeric).row(0, named=True)
        if numeric
        else {}
    )
    rows = [{"variable": c, "differences": n, **measured.get(c, {})} for c, n in counts.items()]
    return pl.DataFrame(rows, schema=STATISTICS)


def _variable_statistics(variable: str) -> pl.Expr:
    """The measures of one numeric variable as a struct, over the observations both sides carry.

    An observation null, NaN or infinite on either side has no finite
    difference to describe, so it is dropped from all four series at once,
    and every measure stays finite; the percent drops a zero base as well,
    exactly as the listing does.  ``count`` is what makes each ``n`` its own
    number rather than the height of the frame.
    """
    base = pl.col(variable).cast(pl.Float64)
    candidate = pl.col(variable + _SUFFIX).cast(pl.Float64)
    # is_finite() is null on a null value, and filter() drops null as well as false.
    both = base.is_finite() & candidate.is_finite()
    difference = candidate - base
    percent = pl.when(base == 0).then(pl.lit(None, pl.Float64)).otherwise(difference / base * 100)
    fields = []
    for side, value in (
        ("base", base),
        ("candidate", candidate),
        ("difference", difference),
        ("percent_difference", percent),
    ):
        kept = value.filter(both)
        fields += [
            kept.count().cast(pl.Int64).alias(f"{side}_n"),
            kept.mean().alias(f"{side}_mean"),
            kept.std().alias(f"{side}_std"),
            kept.min().alias(f"{side}_min"),
            kept.max().alias(f"{side}_max"),
        ]
    return pl.struct(fields)


__all__ = ["compare"]
