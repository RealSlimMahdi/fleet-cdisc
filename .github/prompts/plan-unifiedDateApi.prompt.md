# Plan: Unified Date API — `.date()` + `.duration()`

## TL;DR

Replace 6 fragmented date verbs (`assign_dtc`, `derive_dt`, `derive_dtm`, `study_day`, `duration`, `actual_time`) with **2 unified verbs**: `.date()` (parse/convert/impute/flag) and `.duration()` (any two-dates→number/ISO operation including study day). Both verbs use CDISC target suffix conventions to auto-dispatch behavior by default, with an explicit `output=` override for non-standard variable names. `.date()` supports both column references (`source=`) and literal values (`value=`). `.duration()` accepts `str | pl.Expr` for `start`/`end`, enabling literal reference dates. Available on both SDTM and ADaM namespaces.

---

## API Reference

### `.date()` — parse / convert / impute / flag

```python
def date(self, target: str, *,
         source: str | None = None,        # column name — mutually exclusive with value
         value: str | date | datetime | None = None,  # literal — mutually exclusive with source
         output: str | None = None,        # "dtc"|"dt"|"dtm" — explicit override for suffix dispatch
         time: str | None = None,          # time column or "HH:MM:SS" literal to combine with source
         impute: str = "first",            # "first"|"mid"|"last"|"none"|literal
         impute_time: str | None = None,   # override time-part: "first"|"last"|"HH:MM:SS"
         highest: str | None = None,       # ceiling: "D"|"M"|"Y"|"h"|"m"|"s"
         flag: bool | str = True,          # auto DTF/TMF, or explicit flag name
         min_date: str | None = None,      # clamp lower bound (column or literal)
         max_date: str | None = None,      # clamp upper bound
         format: str | None = None,        # strptime format (SDTM raw only)
) -> Self
```

**`source=` vs `value=` — column reference or literal:**

Exactly one of `source` or `value` must be provided. Supplying both (or neither) raises `ValueError`.

| Parameter | Accepts                   | Behavior                                                   |
| --------- | ------------------------- | ---------------------------------------------------------- |
| `source=` | `str` (column name)       | Reads values from the named column (existing behavior)     |
| `value=`  | `str`, `date`, `datetime` | Broadcasts a scalar literal across all rows via `pl.lit()` |

When `value=` is used: imputation parameters are irrelevant (literal is already complete) and silently ignored. Flags default to `False` (no imputation occurred). `output=` is required unless the target suffix is recognizable.

**Suffix dispatch rules (default when `output=None`):**

| Target suffix       | Output type                 | Behavior                                                                                       |
| ------------------- | --------------------------- | ---------------------------------------------------------------------------------------------- |
| `*DTC`              | `pl.Utf8` (ISO 8601 string) | Parse raw → ISO 8601 char. No imputation (partial preserved). `format` param relevant.         |
| `*DT` (not DTM/DTC) | `pl.Date`                   | DTC → Date. Imputation applies. Auto-flag: `{prefix}DTF`.                                      |
| `*DTM`              | `pl.Datetime`               | DTC → Datetime. Imputation + `impute_time` applies. Auto-flags: `{prefix}DTF` + `{prefix}TMF`. |

**Explicit `output=` override (escapes suffix dispatch):**

When `output=` is provided, it takes precedence over suffix inference. This enables arbitrary target names.

| `output=` | Output type   | Equivalent suffix |
| --------- | ------------- | ----------------- |
| `"dtc"`   | `pl.Utf8`     | `*DTC`            |
| `"dt"`    | `pl.Date`     | `*DT`             |
| `"dtm"`   | `pl.Datetime` | `*DTM`            |

When both a recognizable suffix and `output=` are provided, `output=` wins (explicit beats implicit).

**Prefix extraction:** strip the matched suffix → `"ASTDT"` → prefix = `"AST"` → flag = `"ASTDTF"`.

**Non-standard targets (no suffix, no `output=`):** → `ValueError("Cannot infer output type … use output= to specify explicitly")`.

**`flag=` parameter — `bool | str`:**

| `flag` value     | Behavior                                                                                                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `True` (default) | Auto-name from prefix: `{prefix}DTF` (+ `{prefix}TMF` for dtm). Requires recognizable suffix or `output=`.                                                                |
| `False`          | No flag columns created.                                                                                                                                                  |
| `str`            | Use the given string as the DTF flag name. For dtm output, TMF is derived by replacing `DTF` → `TMF` in the string; if no `DTF` substring exists, TMF flag is suppressed. |

**Flag auto-naming when `output=` is used without a CDISC suffix:**

If `flag=True` and the target has no recognizable suffix but `output=` is set, flag auto-naming cannot extract a prefix → raises `ValueError("Cannot auto-name flag for target 'XYZ'. Use flag='XYZDTF' or flag=False.")`. The user must supply an explicit flag name or disable flags.

**`time` parameter — combining date + time sources into DTM:**

The `time` parameter lets you supply a separate time source (column name or `"HH:MM:SS"` literal) that is combined with the date from `source` to produce a `pl.Datetime`.

| `source` type               | `time` value                  | Behavior                                                         |
| --------------------------- | ----------------------------- | ---------------------------------------------------------------- |
| DTC string (e.g. `AESTDTC`) | Column name (e.g. `"AESTTM"`) | Parse date from `source`, time from `time` column, combine → DTM |
| DTC string                  | Literal `"08:00:00"`          | Parse date from `source`, append literal time → DTM              |
| DT column (`pl.Date`)       | Column name                   | Cast date + time column → DTM                                    |
| DT column                   | Literal `"14:30:00"`          | Cast date + literal time → DTM                                   |
| DTC with embedded time      | `None` (default)              | Parse full datetime from `source` as before                      |

**Rules:**

- `time` is only meaningful when the target suffix is `*DTM`. Raises `ValueError` if used with `*DT` or `*DTC` targets.
- When `time` is provided and the time column has nulls, `impute_time` serves as the fallback for those null rows.
- When `time` is `None` and target is `*DTM`, the time part is extracted from `source` (existing behavior) or imputed via `impute_time`.
- TMF flag reflects what actually happened: if time came from the `time` column → `TMF = null` (no imputation); if time was null and imputed → flag set accordingly.

**`impute_time` interaction table:**

| `impute`  | `impute_time` | Date part          | Time part                        |
| --------- | ------------- | ------------------ | -------------------------------- |
| `"first"` | `None`        | 01/Jan             | 00:00:00                         |
| `"last"`  | `None`        | end-of-month/Dec   | 23:59:59                         |
| `"mid"`   | `None`        | 15/Jun             | 12:00:00                         |
| `"first"` | `"last"`      | 01/Jan             | 23:59:59                         |
| `"last"`  | `"first"`     | end-of-month/Dec   | 00:00:00                         |
| `"first"` | `"12:00:00"`  | 01/Jan             | 12:00:00                         |
| `"none"`  | `"first"`     | null if incomplete | 00:00:00 (only if date complete) |

`impute_time` is only relevant for DTM targets — silently ignored for DT/DTC targets.

### `.duration()` — any two-dates → number or ISO string

```python
def duration(self, target: str, *,
             start: str | pl.Expr,         # column name or Polars expression (incl. pl.lit())
             end: str | pl.Expr,           # column name or Polars expression (incl. pl.lit())
             unit: str = "days",           # seconds|minutes|hours|days|weeks|months|years
             add_one: bool | None = None,  # None=auto (DY→study_day, else True)
             out: str = "numeric",         # "numeric"|"iso8601"
) -> Self
```

**`start` / `end` — column reference or expression:**

| Type      | Interpretation                                                                      |
| --------- | ----------------------------------------------------------------------------------- |
| `str`     | Column name (existing behavior) — internally wrapped as `pl.col(start)`             |
| `pl.Expr` | Any Polars expression, e.g. `pl.lit(date(2024, 1, 1))`, `pl.col("X").cast(pl.Date)` |

This lets users supply fixed reference dates without needing a column:

```python
# Fixed reference date as literal
.duration("ELAPSED", start=pl.lit(date(2024, 1, 15)), end="ADT", unit="days", add_one=False)
# Column reference (unchanged)
.duration("ASTDY", start="TRTSDT", end="ASTDT")
```

**Suffix-driven `add_one` auto-resolution:**

| Target suffix            | `add_one=None` resolves to | Rationale                             |
| ------------------------ | -------------------------- | ------------------------------------- |
| `*DY`                    | Custom rule: +1 if ≥0 only | CDISC study day convention            |
| Anything else            | `True`                     | CDISC duration convention (inclusive) |
| Explicit `add_one=False` | `False`                    | Raw difference (PK elapsed time)      |

**Unit conversion table:**

| Unit        | Calculation            | Precision | Typical use       |
| ----------- | ---------------------- | --------- | ----------------- |
| `"seconds"` | `.dt.total_seconds()`  | `Int64`   | PK microsampling  |
| `"minutes"` | `total_seconds / 60`   | `Float64` | PK                |
| `"hours"`   | `total_seconds / 3600` | `Float64` | PK (APTS, NTIME)  |
| `"days"`    | `.dt.total_days()`     | `Int32`   | TRTDURD, ASTDY    |
| `"weeks"`   | `total_days / 7`       | `Float64` | Some TA endpoints |
| `"months"`  | `total_days / 30.4375` | `Float64` | Long-term studies |
| `"years"`   | `total_days / 365.25`  | `Float64` | Age, survival     |

**ISO 8601 formatting (`out="iso8601"`):**

- `unit="days"` → `P14D`
- `unit="hours"` → `PT336H` or `P14DT0H`
- `unit="weeks"` → `P2W`
- `unit="years"` → decompose into Y/M/D components

---

## Usage Examples

```python
from datetime import date, datetime

# ── SDTM: raw → DTC ──────────────────────────────────────────
ae = (
    raw.sdtm
    .date("AESTDTC", source="ae_start_date")
    .date("AEENDTC", source="ae_end_date", format="%d/%m/%Y")
    .date("BRTHDTC", source="dob")
    .to_frame()
)

# ── ADaM: DTC → Date (imputation + flags) ────────────────────
adae = (
    ae_sdtm.adam
    .date("ASTDT", source="AESTDTC")
    #  → impute="first" → partial "2024-03" becomes 2024-03-01
    #  → flag=True → creates ASTDTF
    .date("AENDT", source="AEENDTC", impute="last")
    #  → partial "2024-03" becomes 2024-03-31
    #  → creates AENDTF
    .to_frame()
)

# ── Non-standard target with explicit output= ────────────────
df = (
    raw.adam
    .date("XYZ", source="raw_date_col", output="dt", flag="XYZDTF")
    #  → output="dt" overrides suffix dispatch → pl.Date
    #  → flag="XYZDTF" names the flag explicitly
    .date("CUTOFF", value="2024-06-30", output="dt", flag=False)
    #  → literal broadcast, no imputation, no flag
    .to_frame()
)

# ── Literal value= for fixed reference dates ─────────────────
adsl = (
    dm.adam.adsl
    .date("RFSTDT", value="2024-01-15", output="dt", flag=False)
    #  → every row gets 2024-01-15 as pl.Date
    .date("RFENDTM", value=datetime(2024, 12, 31, 23, 59, 59), output="dtm", flag=False)
    #  → every row gets the literal datetime
    .to_frame()
)

# ── ADaM: DTC → Datetime (asymmetric imputation) ─────────────
adae = (
    ae_sdtm.adam
    .date("ASTDTM", source="AESTDTC", impute="first", impute_time="last")
    #  → date: 01/Jan, time: 23:59:59
    #  → creates ASTDTF + ASTTMF
    .date("AENDTM", source="AEENDTC", impute="last")
    #  → date: end-of-month/Dec, time: 23:59:59
    #  → creates AENDTF + AENTMF
    .to_frame()
)

# ── ADaM: Combine separate date + time columns → DTM ─────────
adae = (
    ae_sdtm.adam
    .date("ASTDTM", source="AESTDTC", time="AESTTM")
    #  → date from AESTDTC, time from AESTTM
    #  → if AESTTM is null → falls back to impute_time (default: "first" → 00:00:00)
    #  → ASTTMF = null when AESTTM present, "H" when imputed
    .to_frame()
)

# ── ADaM: DT + time column → DTM ─────────────────────────────
adae = (
    ae_sdtm.adam
    .date("ASTDT", source="AESTDTC")
    .date("ASTDTM", source="ASTDT", time="AESTTM", impute_time="last")
    #  → already-typed ASTDT (pl.Date) + AESTTM column → Datetime
    #  → nulls in AESTTM → 23:59:59
    .to_frame()
)

# ── ADaM: DT + literal time → DTM ────────────────────────────
advs = (
    vs_sdtm.adam
    .date("ADTM", source="VSDTC", time="12:00:00")
    #  → every row gets noon as the time component
    #  → ASTTMF set to "H" (time was not collected, always imputed)
    .to_frame()
)

# ── SDTM: Combine date + time into a DTC with time ───────────
ae = (
    raw.sdtm
    .date("AESTDTC", source="ae_start_date", time="ae_start_time")
    #  → "2024-03-15" + "14:30" → "2024-03-15T14:30"
    .to_frame()
)

# ── Imputation ceiling ────────────────────────────────────────
adae = (
    ae_sdtm.adam
    .date("ASTDT", source="AESTDTC", highest="D")
    #  → "2024-03" → 2024-03-01 (day imputed, OK)
    #  → "2024" → null (month missing, exceeds ceiling)
    .to_frame()
)

# ── Clamping ──────────────────────────────────────────────────
adae = (
    ae_sdtm.adam
    .date("ASTDT", source="AESTDTC", min_date="TRTSDT")
    .date("AENDT", source="AEENDTC", impute="last", max_date="DTHDT")
    .to_frame()
)

# ── Study day (auto from DY suffix) ──────────────────────────
adae = (
    ae.adam
    .date("ASTDT", source="AESTDTC")
    .duration("ASTDY", start="TRTSDT", end="ASTDT")
    #  → DY suffix → no-day-0: 2024-03-15 vs 2024-03-15 → 1
    .to_frame()
)

# ── Standard duration in days ─────────────────────────────────
adsl = (
    dm.adam.adsl
    .duration("TRTDURD", start="TRTSDT", end="TRTEDT")
    #  → (TRTEDT - TRTSDT).days + 1
    .to_frame()
)

# ── Duration in months / years ────────────────────────────────
adsl = (
    dm.adam.adsl
    .duration("TRTDURM", start="TRTSDT", end="TRTEDT", unit="months")
    .duration("AVAL", start="TRTSDT", end="ADT", unit="years", add_one=False)
    .to_frame()
)

# ── Duration with literal reference date (pl.Expr) ───────────
adsl = (
    dm.adam.adsl
    .duration("ELAPSED", start=pl.lit(date(2024, 1, 15)), end="TRTEDT", unit="days", add_one=False)
    #  → fixed start date as literal, end from column
    .duration("RFSDY", start=pl.lit(date(2024, 1, 1)), end="RFSTDT")
    #  → DY suffix → study day convention
    .to_frame()
)

# ── PK elapsed time in hours ─────────────────────────────────
adpc = (
    pc.adam.pk
    .duration("APTS", start="EXSTDTM", end="PCDTM", unit="hours", add_one=False)
    .to_frame()
)

# ── SDTM ISO 8601 duration ───────────────────────────────────
ex = (
    raw.sdtm
    .date("EXSTDTC", source="dose_start")
    .date("EXENDTC", source="dose_end")
    .duration("EXDUR", start="EXSTDTC", end="EXENDTC", out="iso8601")
    #  → "P14D"
    .to_frame()
)
```

---

## Phases

### Phase 1 — Core `.date()` implementation

#### Step 1.1 — New utility layer (`src/fleet/adam/utils.py` refactor)

Refactor existing imputation functions to support the new unified `impute` parameter. Keep existing functions as internal engines.

**New internal function:**

```python
def _resolve_impute(impute: str, component: str) -> str:
    """Map unified impute keyword to component-level strategy."""
```

**New public function:**

```python
def impute_and_flag(
    source: str | None,
    target: str,
    *,
    value: str | date | datetime | None = None,
    output_type: Literal["dtc", "dt", "dtm"],
    time: str | None = None,
    impute: str = "first",
    impute_time: str | None = None,
    highest: str | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
    flag: bool | str = True,
) -> list[pl.Expr]:
    """Unified imputation engine. Returns list of expressions (target + flag columns).

    When value= is provided, broadcasts a literal and skips imputation.
    When flag is a str, uses it as the explicit DTF flag name.
    """
```

**New helpers:**

- `_apply_highest(source, highest)` → expression that nullifies when imputation exceeds ceiling
- `_apply_clamp(target, min_date, max_date)` → clamp expression applied post-imputation
- `_extract_prefix(target: str) -> str` — strip DTC/DTM/DT suffix (raises `ValueError` if no suffix)
- `_infer_output_type(target: str) -> Literal["dtc", "dt", "dtm"]` — suffix dispatch
- `_resolve_output_type(target: str, output: str | None) -> Literal["dtc", "dt", "dtm"]` — combines suffix inference with explicit `output=` override
- `_resolve_flag_name(target: str, flag: bool | str, output_type: str) -> str | None` — resolves flag column name from `flag` parameter

#### Step 1.2 — `.date()` on `SharedADaMVerbsMixin`

**File:** `src/fleet/adam/_mixins.py`

Add `.date()` method. Dispatch logic:

1. Validate `source` / `value` mutual exclusivity (exactly one must be provided)
2. Resolve output type: `output=` if given, else infer from suffix (`_resolve_output_type`)
3. `output_type == "dtc"` → raise `ValueError` (DTC targets belong in SDTM)
4. `output_type == "dtm"` → datetime mode
5. `output_type == "dt"` → date mode
6. If `time` is provided and `output_type != "dtm"` → raise `ValueError`
7. Resolve `flag`: if `True` + no extractable prefix → `ValueError` (suggest explicit name). If `str` → use as-is.
8. If `value=` is provided → broadcast literal, skip imputation, flags default to `False` (user can override)

Delegate to `impute_and_flag()`. Return `self._chain(*exprs)` or `self._materialise_then(...)` for partial-date DTM cases.

When `time` is provided (DTM targets):

- If `source` is a `pl.Date` column → combine with `time` column/literal directly
- If `source` is a string/DTC column → parse date first, then combine with `time`
- Null values in the `time` column → fall back to `impute_time` strategy
- TMF flag logic: `null` when time came from the column, flag value when imputed

#### Step 1.3 — `.date()` on `SDTMNamespace`

**File:** `src/fleet/sdtm/namespace.py`

Add `.date()` method. Same `source`/`value` mutual exclusivity and `output=` override as ADaM.

Behavior by resolved output type:

- `"dtc"` → raw string parsing (delegates to `dtc_date_expr`/`dtc_datetime_expr`). Imputation params ignored. `format` active. When `time` is provided, concatenates date + time into a DTC string with `T` separator. When `value=` is provided, broadcasts the literal as a DTC string.
- `"dt"` / `"dtm"` → delegates to same `impute_and_flag()` engine (allowed for edge cases).

#### Step 1.4 — Flag auto-naming logic

```python
def _extract_prefix(target: str) -> str:
    if target.endswith("DTM"):   return target[:-3]
    elif target.endswith("DTC"): return target[:-3]
    elif target.endswith("DT"):  return target[:-2]
    raise ValueError(f"Cannot extract prefix from '{target}'")

def _resolve_flag_name(target: str, flag: bool | str, output_type: str) -> tuple[str | None, str | None]:
    """Returns (dtf_name, tmf_name) or (None, None)."""
    if flag is False:
        return None, None
    if isinstance(flag, str):
        dtf = flag
        tmf = flag.replace("DTF", "TMF") if "DTF" in flag and output_type == "dtm" else None
        return dtf, tmf
    # flag is True → auto-name
    try:
        prefix = _extract_prefix(target)
    except ValueError:
        raise ValueError(
            f"Cannot auto-name flag for target '{target}'. "
            f"Use flag='<name>DTF' or flag=False."
        )
    dtf = f"{prefix}DTF"
    tmf = f"{prefix}TMF" if output_type == "dtm" else None
    return dtf, tmf
```

Flag columns: Date mode → `{prefix}DTF`. Datetime mode → `{prefix}DTF` + `{prefix}TMF`.

Deduplication: if flag column already in expression list, later call supersedes.

---

### Phase 2 — Core `.duration()` implementation (parallel with Phase 1)

#### Step 2.1 — Unified `duration()` on `SharedADaMVerbsMixin`

**File:** `src/fleet/adam/_mixins.py`

Move from `ADSLNamespace`-only to the shared mixin. New expanded signature with all units, `add_one` auto, `out="iso8601"`, and `str | pl.Expr` for `start`/`end`.

Implementation logic:

1. Normalise `start`/`end`: if `str` → `pl.col(start)`; if `pl.Expr` → use directly
2. Auto-detect column dtype: `pl.Utf8` → parse ISO string; `pl.Date`/`pl.Datetime` → use directly
3. Compute difference using appropriate temporal method
4. Apply unit scaling
5. Apply `add_one`:
   - `True` → `diff + 1`
   - `False` → `diff`
   - `"study_day"` (auto from DY suffix) → `when(diff >= 0).then(diff + 1).otherwise(diff)`
6. If `out="iso8601"` → format as ISO 8601 duration string
7. Return `self._chain(expr)`

#### Step 2.2 — `.duration()` on `SDTMNamespace`

**File:** `src/fleet/sdtm/namespace.py`

Add same `duration()` method for SDTM `--DUR` variables. Same `str | pl.Expr` support for `start`/`end`.

#### Step 2.3 — Retire `actual_time()` from PK namespace

**File:** `src/fleet/adam/pk_namespace.py`

Remove `actual_time()`. It becomes:

```python
.duration("APTS", start="EXSTDTM", end="PCDTM", unit="hours", add_one=False)
```

Keep `nominal_time()` — it's numeric conversion, not a date operation.

---

### Phase 3 — Deprecation & Retirement (depends on Phase 1+2)

#### Step 3.1 — Add deprecation wrappers

All old verbs become thin wrappers that emit `DeprecationWarning` and delegate.

**`src/fleet/adam/_mixins.py`:**

```python
def derive_dt(self, target, *, source, dtf=None, day_imputation="first", month_imputation="first") -> Self:
    warnings.warn("derive_dt() is deprecated, use .date() instead", DeprecationWarning, stacklevel=2)
    return self.date(target, source=source, impute=day_imputation, flag=(dtf is not None))

def derive_dtm(self, target, *, source, dtf=None, tmf=None,
               day_imputation="first", month_imputation="first", time_imputation="first") -> Self:
    warnings.warn("derive_dtm() is deprecated, use .date() instead", DeprecationWarning, stacklevel=2)
    return self.date(target, source=source, impute=day_imputation,
                     impute_time=time_imputation, flag=(dtf is not None or tmf is not None))

def format_iso(self, target, *, source) -> Self:
    warnings.warn("format_iso() is deprecated. Use .derivation() with .dt.to_string().",
                  DeprecationWarning, stacklevel=2)
    ...
```

**`src/fleet/sdtm/namespace.py`:**

```python
def assign_dtc(self, target, *, source, mode="date", input_format=None) -> SDTMNamespace:
    warnings.warn("assign_dtc() is deprecated, use .date() instead", DeprecationWarning, stacklevel=2)
    return self.date(target, source=source, format=input_format)
```

**`src/fleet/adam/namespace.py`:**

```python
def study_day(self, target, *, analysis_date, reference_date) -> Self:
    warnings.warn("study_day() is deprecated, use .duration() instead", DeprecationWarning, stacklevel=2)
    return self.duration(target, start=reference_date, end=analysis_date)
```

**`src/fleet/sdtm/_tdd_mixin.py`:**

```python
def study_day(self, target, *, date_col, ref_date_col) -> Self:
    warnings.warn("study_day() is deprecated, use .duration() instead", DeprecationWarning, stacklevel=2)
    return self.duration(target, start=ref_date_col, end=date_col)
```

**`src/fleet/adam/adsl_namespace.py`:**

- Remove `duration()` from `ADSLNamespace` (now lives in shared mixin)

**`src/fleet/adam/pk_namespace.py`:**

```python
def actual_time(self, target, *, sample_dtm, dose_dtm, unit="h") -> Self:
    warnings.warn("actual_time() is deprecated, use .duration() instead", DeprecationWarning, stacklevel=2)
    unit_map = {"s": "seconds", "min": "minutes", "h": "hours", "d": "days"}
    return self.duration(target, start=dose_dtm, end=sample_dtm, unit=unit_map[unit], add_one=False)
```

#### Step 3.2 — Retired verbs summary

| Old Verb           | Location             | Replacement                                           | Breaking?                                            |
| ------------------ | -------------------- | ----------------------------------------------------- | ---------------------------------------------------- |
| `assign_dtc`       | SDTMNamespace        | `.date("AESTDTC", source=...)`                        | Deprecation wrapper                                  |
| `derive_dt`        | SharedADaMVerbsMixin | `.date("ASTDT", source=...)`                          | Deprecation wrapper                                  |
| `derive_dtm`       | SharedADaMVerbsMixin | `.date("ASTDTM", source=...)`                         | Deprecation wrapper                                  |
| `study_day` (ADaM) | AdamNamespace        | `.duration("ASTDY", start=..., end=...)`              | Deprecation wrapper                                  |
| `study_day` (SDTM) | TrialDesignMixin     | `.duration("SVSTDY", start=..., end=...)`             | Deprecation wrapper                                  |
| `duration`         | ADSLNamespace        | `.duration(...)` on SharedMixin (new signature)       | Param rename: `start_date`→`start`, `end_date`→`end` |
| `actual_time`      | PKNamespace          | `.duration("APTS", ..., unit="hours", add_one=False)` | Deprecation wrapper                                  |
| `format_iso`       | SharedADaMVerbsMixin | Deprecated (use `.derivation()`)                      | Deprecation wrapper                                  |

---

### Phase 4 — Spec-Driven Workflow Updates (depends on Phase 1+2)

#### Step 4.1 — Update algorithm registry

**Files:** `src/fleet/sdtm/namespace.py` (~L867), `src/fleet/adam/namespace.py` (~L883)

Add new algorithm names to spec dispatcher:

- `"date"` → calls `self.date(target, source=..., ...)`
- `"duration"` → calls `self.duration(target, start=..., end=..., ...)`

Keep old algorithm names (`assign_dtc`, `derive_dt`, `derive_dtm`, `study_day`) as aliases.

#### Step 4.2 — Update define.yaml fixtures

- `specs/cdiscpilot01/sdtm/define.yaml` — update 8× `assign_dtc` → `date`
- `specs/cdiscpilot01/adam/define.yaml` — update `study_day` → `duration`
- `tests/fixtures/specs/define_sdtm.yaml` — update 6× `assign_dtc` → `date`
- `tests/fixtures/specs/define_adam.yaml` — update `study_day` → `duration`

#### Step 4.3 — Update Pydantic schema models

Add `"date"` and `"duration"` as valid algorithm values. Keep old values as deprecated aliases.

---

### Phase 5 — Tests (depends on Phase 1-4)

#### Step 5.1 — New `tests/unit/test_date_api.py`

- Suffix dispatch (DTC, DT, DTM, invalid)
- Explicit `output=` override (dt, dtm, dtc)
- `output=` with non-standard target name (e.g. `"XYZ"`)
- `output=` + recognizable suffix (output wins)
- No suffix + no output → `ValueError`
- `source=` / `value=` mutual exclusivity (both → `ValueError`, neither → `ValueError`)
- `value=` with string literal, `date` object, `datetime` object
- `value=` skips imputation, flags default to `False`
- `value=` with explicit `flag="XYZDTF"`
- All impute strategies (first, mid, last, none, literal)
- `impute_time` override (asymmetric)
- `time` parameter: column name, literal, with DT source, with DTC source, null fallback
- `time` + `impute_time` interaction (fallback for null time values)
- `time` with non-DTM target → `ValueError`
- `highest` ceiling (D, M, Y, h, m, s)
- `flag=True` auto-naming (standard suffix)
- `flag=True` + non-standard target → `ValueError`
- `flag=False` suppression
- `flag="MYCUSTOMDTF"` explicit naming
- `flag=str` with DTM → TMF derived via replacement
- Flag deduplication
- `min_date` / `max_date` clamping (column + literal)
- `format` parameter (SDTM)
- Edge cases: null source, empty string, partial dates at each length (4, 7, 10, 13, 16, 19)

#### Step 5.2 — New `tests/unit/test_duration_api.py`

- DY suffix → study day auto-behavior
- All 7 units
- `add_one=None/True/False`
- `out="iso8601"` formatting
- `start`/`end` as column names (str)
- `start`/`end` as `pl.Expr` (e.g. `pl.lit(date(...))`)
- Mixed: one `str`, one `pl.Expr`
- String vs typed date columns
- Datetime columns
- Edge cases: null dates, same start/end

#### Step 5.3 — Update existing tests

- `tests/unit/test_date_derivation.py` — add deprecation warning suppression or migrate
- `tests/unit/test_sdtm_namespace.py` — update `assign_dtc` tests
- `tests/unit/test_adsl_namespace.py` — update `duration` tests for new signature
- `tests/unit/test_pk_namespace.py` — update `actual_time` tests
- `tests/unit/test_tdd_workflow.py` — update SDTM `study_day` tests

---

### Phase 6 — Example Scripts (depends on Phase 1-3)

| Script                                 | Changes                                                                        |
| -------------------------------------- | ------------------------------------------------------------------------------ |
| `examples/cdiscpilot01_inline.py`      | `assign_dtc` → `.date()`, `derive_dt` → `.date()`, `study_day` → `.duration()` |
| `examples/cdiscpilot01_spec_driven.py` | Works via alias (update for clarity)                                           |
| `examples/full_pipeline_example.py`    | `assign_dtc` → `.date()`                                                       |
| `examples/r2r_ae_example.py`           | `derive_dt` → `.date()`, `study_day` → `.duration()`                           |
| `examples/tlg_ae_example.py`           | `derive_dt` → `.date()`                                                        |
| `examples/tlg_vs_example.py`           | `assign_dtc` → `.date()`, `derive_dt` → `.date()`                              |
| `examples/tdd_example.py`              | SDTM `study_day` → `.duration()`                                               |
| `examples/adnca_example.py`            | `actual_time` → `.duration(..., unit="hours", add_one=False)`                  |

---

### Phase 7 — Documentation (depends on Phase 1-6)

| File                                          | Scope                                          |
| --------------------------------------------- | ---------------------------------------------- |
| `GUIDE.md`                                    | Major rewrite of date section; migration guide |
| `README.md`                                   | Auto-synced via `build_llms.py`                |
| `docs/api/cheat_sheet.md`                     | Complete rewrite of date section               |
| `docs/api/adam.md`                            | mkdocstrings picks up new methods              |
| `docs/api/adsl.md`                            | Note `duration` moved to shared                |
| `docs/api/sdtm.md`                            | New `.date()` and `.duration()`                |
| `docs/api/tdd.md`                             | `study_day` → `.duration()`                    |
| `docs/concepts/pipeline.md`                   | Update examples                                |
| `docs/concepts/advanced.md`                   | Update examples                                |
| `docs/getting-started/quickstart.md`          | Update examples                                |
| `docs/examples/01_code_driven_pipeline.ipynb` | Update cells                                   |
| `docs/examples/02_spec_driven_pipeline.ipynb` | Update cells                                   |

---

### Phase 8 — Build System (depends on Phase 7)

#### Step 8.1 — `scripts/build_llms.py`

Update verb lists:

- `_README_SHARED_VERBS` — remove `derive_dt`, `derive_dtm`, `format_iso`; add `date`, `duration`
- `_README_SDTM_VERBS` — replace `assign_dtc` with `date`; add `duration`
- `_README_ADSL_VERBS` — remove `duration` (now shared)
- `_README_PK_VERBS` — remove `actual_time`

#### Step 8.2 — Regenerate

```bash
uv run python scripts/build_llms.py
uv run python scripts/build_llms.py --check
```

---

### Phase 9 — Copilot Instructions

Update `.github/copilot-instructions.md` §4 to show `.date()` and `.duration()` instead of old verbs.

---

## Verification Checklist

```bash
# 1. Lint
uv run ruff check
uv run ruff format --check

# 2. Tests
uv run pytest

# 3. All example scripts
uv run python examples/full_pipeline_example.py
uv run python examples/cdiscpilot01_inline.py
uv run python examples/cdiscpilot01_spec_driven.py
uv run python examples/adnca_example.py
uv run python examples/tdd_example.py
uv run python examples/r2r_ae_example.py
uv run python examples/tlg_ae_example.py
uv run python examples/tlg_vs_example.py

# 4. LLM context
uv run python scripts/build_llms.py --check

# 5. Docs build
uv run --extra docs mkdocs build --clean
```

---

## Decisions Made

1. **Proposal 1 selected** — single `.date()` verb with suffix-driven dispatch
2. **`study_day` absorbed into `duration()`** — DY suffix triggers no-day-0 rule
3. **`actual_time` absorbed into `duration()`** — just `unit="hours", add_one=False`
4. **`format_iso` deprecated with no replacement** — typed dates don't need string formatting
5. **Deprecation wrappers** — old verbs stay as warnings for one major version cycle
6. **`impute_time` for asymmetric control** — overrides time-part separately from date-part
7. **`flag=bool|str`** — `True` for auto-naming (requires CDISC suffix), `False` to suppress, `str` for explicit flag name. Replaces previous `bool`-only design.
8. **Same verb name `.date()` on both SDTM and ADaM** — context determines behavior
9. **`duration()` moves to shared mixin** — all ADaM namespaces get it
10. **Units include months and years** — average-month (30.4375d), average-year (365.25d)
11. **Spec-driven aliases preserved** — old algorithm names still work
12. **`output=` kwarg (`"dtc"|"dt"|"dtm"`)** — explicit override for suffix dispatch, enabling non-standard target names like `XYZ`. Values use short CDISC suffixes for consistency.
13. **`value=` kwarg (mutually exclusive with `source=`)** — broadcasts a literal scalar across all rows. Mirrors Fleet's existing `hardcode_no_ct(value=)` / `assign_no_ct(source=)` duality. When used, imputation is irrelevant and flags default to `False`.
14. **`start`/`end` in `.duration()` accept `str | pl.Expr`** — string = column name (wrapped to `pl.col()`), expression = any Polars expr including `pl.lit(date(...))`. Simpler than adding `start_value`/`end_value` kwargs.

---

## Scope Boundaries

**In scope:**

- `.date()` verb (SDTM + ADaM)
- `.duration()` verb (SDTM + ADaM, shared mixin)
- `output=` suffix escape for non-standard variable names
- `value=` literal broadcast (mutually exclusive with `source=`)
- `start`/`end` as `str | pl.Expr` in `.duration()`
- `flag=bool|str` for explicit flag naming
- Deprecation of 7 old verbs
- Imputation, flags, clamping, suffix dispatch
- ISO 8601 duration output
- All tests, examples, docs

**Out of scope:**

- `first_date()` / `last_date()` — aggregation verbs, unchanged
- `age_from_dates()` / `age_years()` — unchanged
- `derive_period()` — unchanged
- `nominal_time()` — numeric conversion, unchanged
- ISO 8601 duration _parsing_ (P14D → integer) — near-zero frequency
- `preserve` parameter (admiral feature) — v2
- Calendar-month precision — v2

---

## Full File Impact List

### Source code (modify)

- `src/fleet/adam/_mixins.py` — add `.date()`, move+rewrite `.duration()`, deprecate `derive_dt`/`derive_dtm`/`format_iso`
- `src/fleet/adam/utils.py` — add `impute_and_flag()`, `_resolve_impute()`, `_apply_highest()`, `_apply_clamp()`, `_extract_prefix()`, `_infer_output_type()`
- `src/fleet/adam/namespace.py` — deprecate ADaM `study_day()`
- `src/fleet/adam/adsl_namespace.py` — remove `duration()` (now in shared mixin)
- `src/fleet/adam/pk_namespace.py` — deprecate `actual_time()`
- `src/fleet/sdtm/namespace.py` — add `.date()`, `.duration()`, deprecate `assign_dtc()`
- `src/fleet/sdtm/_tdd_mixin.py` — deprecate SDTM `study_day()`
- `src/fleet/sdtm/utils.py` — minor (existing functions stay)

### Tests (modify + create)

- `tests/unit/test_date_api.py` — **NEW**
- `tests/unit/test_duration_api.py` — **NEW**
- `tests/unit/test_date_derivation.py` — update
- `tests/unit/test_sdtm_namespace.py` — update
- `tests/unit/test_adsl_namespace.py` — update
- `tests/unit/test_pk_namespace.py` — update
- `tests/unit/test_tdd_workflow.py` — update

### Examples (modify)

- `examples/cdiscpilot01_inline.py`
- `examples/cdiscpilot01_spec_driven.py`
- `examples/full_pipeline_example.py`
- `examples/r2r_ae_example.py`
- `examples/tlg_ae_example.py`
- `examples/tlg_vs_example.py`
- `examples/tdd_example.py`
- `examples/adnca_example.py`

### Specs (modify)

- `specs/cdiscpilot01/sdtm/define.yaml`
- `specs/cdiscpilot01/adam/define.yaml`
- `tests/fixtures/specs/define_sdtm.yaml`
- `tests/fixtures/specs/define_adam.yaml`

### Documentation (modify)

- `GUIDE.md`
- `README.md`
- `docs/api/cheat_sheet.md`
- `docs/api/adam.md`
- `docs/api/adsl.md`
- `docs/api/sdtm.md`
- `docs/api/tdd.md`
- `docs/concepts/pipeline.md`
- `docs/concepts/advanced.md`
- `docs/getting-started/quickstart.md`
- `docs/examples/01_code_driven_pipeline.ipynb`
- `docs/examples/02_spec_driven_pipeline.ipynb`

### Build system (modify)

- `scripts/build_llms.py`
- `llms.txt` (regenerated)
- `.github/copilot-instructions.md`
