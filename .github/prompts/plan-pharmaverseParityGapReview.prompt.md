# Plan — Pharmaverse Parity Gap Review

> Fleet gap analysis vs **{sdtm.oak} v0.2.0** and **{admiral} 1.4.2 / 1.5.0-dev**, with proposed fixes in Fleet style.
>
> Reference state (audited 2026-06-11): oak `main@6b5d887` (v0.2.0, current CRAN release), admiral 1.4.2 (CRAN) plus the unreleased 1.5.0 dev branch containing the time-to-event rework (#2952, shipping ~June 2026).

---

## Table of Contents

1. [Axis 1 — Logic gaps vs oak/admiral](#axis-1--logic-gaps-where-fleets-code-diverges-from-oakadmiral)
2. [Axis 2 — Trial Design Domain (TDD) layer gaps](#axis-2--tdd-layer-gaps-with-design-options)
3. [Axis 3 — Testing alignment](#axis-3--testing-alignment-with-oakadmiral)
4. [Axis 4 — Time-to-event (ADTTE) design](#axis-4--admirals-tte-update-and-a-fleet-equivalent)
5. [Axis 5 — Remaining missing pieces](#axis-5--what-is-still-missing)
6. [Priority summary](#priority-summary)

---

## Axis 1 — Logic gaps: where Fleet's code diverges from oak/admiral

Each finding verified directly in Fleet source and, where relevant, empirically against Polars behavior. Ordered by severity.

### 🔴 1. `baseline_flag` / `study_day` silently drop datetime-bearing DTC values

Both parse with exact-format `to_date` (`sdtm/namespace.py:837-838`, `core/_verb_mixin.py:617-619,640-642`):

```python
date_parsed = pl.col(date_col).str.to_date(format="%Y-%m-%d", strict=False)
# "2024-01-15T10:30" → null  ⇒ record silently excluded;
# if RFSTDTC has a time part, the WHOLE SUBJECT loses its reference date
```

Verified empirically: `'2024-01-15T10:30'` → `None`. Real `--DTC`/`RFSTDTC` values routinely carry times — a datetime `RFSTDTC` nulls every `--DY` and baseline flag for that subject, silently. oak's R `as.Date(x, "%Y-%m-%d")` parses the prefix; oak's `derive_blfl` explicitly splits date/time parts.

**Fix** — one shared helper in `sdtm/utils.py`, used by both verbs:

```python
def dtc_datepart(col: str) -> pl.Expr:
    """Extract the date part of an ISO 8601 --DTC value as pl.Date.

    Handles full datetimes ("2024-01-15T10:30") by slicing the date
    component; partial dates (YYYY, YYYY-MM) yield null.
    """
    return pl.col(col).str.slice(0, 10).str.to_date("%Y-%m-%d", strict=False)
```

```python
# baseline_flag / study_day call sites become:
date_parsed = dtc_datepart(date_col)
ref_parsed = dtc_datepart(ref_col_name)
```

Pure expression, stays lazy, fixes both verbs in one line each.

---

### 🔴 2. `nrind` labels null values "NORMAL"

`adam/utils.py:71-80`:

```python
pl.when(pl.col(value) < pl.col(low)).then(pl.lit("LOW"))
  .when(pl.col(value) > pl.col(high)).then(pl.lit("HIGH"))
  .otherwise(pl.lit("NORMAL"))          # null AVAL falls through to here
```

**Fix** — admiral ANRIND semantics (missing value ⇒ missing indicator):

```python
pl.when(pl.col(value).is_null())
  .then(pl.lit(None, dtype=pl.String))
  .when(pl.col(value) < pl.col(low)).then(pl.lit("LOW"))
  .when(pl.col(value) > pl.col(high)).then(pl.lit("HIGH"))
  .when(pl.col(low).is_not_null() | pl.col(high).is_not_null())
  .then(pl.lit("NORMAL"))
  .otherwise(pl.lit(None, dtype=pl.String))   # no range at all ⇒ null, not NORMAL
```

---

### 🔴 3. `_apply_clamp` rewrites observed dates

`adam/utils.py:596-618` clamps unconditionally:

```python
if min_date is not None:
    ...
    expr = pl.when(expr < bound).then(bound).otherwise(expr)   # also fires on complete dates!
```

admiral's `min_dates`/`max_dates` exist solely to keep **imputed** components inside a window — they never alter a complete, observed date.

**Fix** — gate the clamp on the imputation mask already computed for the DTF flag:

```python
def _apply_clamp(target_expr, source_col, min_date, max_date):
    imputed = dtf_expr(source_col).is_not_null()   # mask already computed for the flag
    if min_date is not None:
        bound = _resolve_bound(min_date)
        expr = pl.when(imputed & (target_expr < bound)).then(bound).otherwise(target_expr)
    ...
```

A complete `"2024-03-10"` can now never be moved by `min_date="TRTSDT"`; a partial `"2024-03"` imputed to `2024-03-01` still clamps up to a March 15 treatment start.

---

### 🔴 4. `baseline` silently resolves duplicate baseline records

`adam/utils.py:26-47`:

```python
pl.when(pl.col(flag) == "Y").then(pl.col(aval)).otherwise(None).max().over(groups)
# two ABLFL=="Y" rows per group ⇒ quietly takes the larger AVAL
```

admiral's `derive_var_base` **errors** on multiple baseline records per by-group — that error has caught countless upstream ABLFL bugs.

**Fix** — reuse the existing `fk_policy("warn"|"error")` escalation pattern:

```python
n_baseline = (pl.col(flag) == "Y").sum().over(groups)

base_expr = (
    pl.when(n_baseline > 1)
    .then(pl.lit(None, dtype=pl.Float64))        # poison the group…
    .otherwise(
        pl.when(pl.col(flag) == "Y").then(pl.col(aval)).otherwise(None).max().over(groups)
    )
)
# …and at materialisation (verb level, where we already collect):
dupes = df.filter(pl.col("__n_bl__") > 1)
if dupes.height:
    msg = f"baseline: {dupes['USUBJID'].n_unique()} group(s) have multiple ABLFL=='Y' records"
    if self._fk_policy == "error":
        raise ADAMError(msg)
    warnings.warn(msg, stacklevel=2)
```

---

### 🔴 5. `study_day` picks an arbitrary reference for multi-ref subjects

`core/_verb_mixin.py:628-630`:

```python
ref_slim = source_df.select(...).unique(subset=join_key)   # keeps an unspecified row
```

oak's `derive_study_day` detects subjects with >1 distinct ref date, **warns, and returns NA** for them.

**Fix:**

```python
ref_counts = source_df.group_by(join_key).agg(pl.col(_ref_col).n_unique().alias("__n_ref__"))
ambiguous = ref_counts.filter(pl.col("__n_ref__") > 1)
if ambiguous.height:
    warnings.warn(
        f"study_day: {ambiguous.height} subject(s) have multiple distinct {_ref_col} "
        f"values — {target} set to null for them: "
        f"{ambiguous[join_key[-1]].head(5).to_list()}…",
        stacklevel=2,
    )
ref_slim = (
    source_df.join(ambiguous.select(join_key), on=join_key, how="anti")  # drop them
    .select(...).unique(subset=join_key)
)
# dropped subjects simply miss the left join ⇒ null --DY, matching oak
```

Same treatment for `baseline_flag`'s ref join (`sdtm/namespace.py:819-821`).

---

### 🟠 6. Missing coalesce / no-overwrite contract (oak issue #110)

oak v0.2.0's headline fix: `assign_*`/`hardcode_*` fill **only null** target values — `coalesce(existing, new)` — so multiple raw sources can be layered into one SDTM variable. Fleet's verbs unconditionally overwrite, and `condition_add` sets non-matching rows to null (`sdtm/namespace.py:898-932`):

```python
# oak's most common pattern — multi-source mapping of one variable — today in Fleet:
(raw.sdtm
 .condition_add("CMDOSU", condition='pl.col("src") == "A"', then_value="mg")
 .condition_add("CMDOSU", condition='pl.col("src") == "B"', then_value="mL")
 # second call: rows where src=="A" → otherwise-branch → null. First mapping is GONE.
)
```

**Fix** — in `_chain()`, when a target is already in the accumulated plan (or input frame), coalesce instead of replace:

```python
def _chain(self, *exprs: pl.Expr, overwrite: bool = False) -> Self:
    out = []
    for expr in exprs:
        name = expr.meta.output_name()
        if not overwrite and (name in self._planned_targets or name in self._lazy.columns):
            # oak contract (issue #110): existing non-null values win, new expr fills the gaps
            expr = pl.coalesce([pl.col(name), expr]).alias(name)
        out.append(expr)
    ...
```

After which the chain above just works, and reads exactly like an oak spec:

```python
(raw.sdtm
 .condition_add("CMDOSU", condition='pl.col("src") == "A"', then_value="mg")
 .condition_add("CMDOSU", condition='pl.col("src") == "B"', then_value="mL")
 .assign_no_ct("CMDOSU", source="dose_unit_other")   # fills whatever is still null
)
```

`overwrite=True` stays available as the explicit opt-out. Fully lazy — still one `with_columns` pass.

---

### 🟠 7. `assign_ct`: silent fallback + no oak-style matching

`sdtm/namespace.py:221-236`:

```python
try:
    decode_map = ct_validator.get_decode_map(ct_codelist)
    ...
except Exception:
    pass                                   # ← any CT problem vanishes here
ns = self._chain(pl.col(source).alias(target))   # silent pass-through, looks mapped
```

oak matches with precedence **term_value → collected_value → term_synonyms**, trims whitespace, maps non-matching values to `toupper(x)`, and alerts on unmappable terms.

**Fix** — loud fallback:

```python
except Exception as exc:
    warnings.warn(
        f"assign_ct({target!r}): codelist {ct_codelist} unavailable ({exc}) — "
        "values passed through UNVALIDATED. Load CT or pass ct_mapping=.",
        stacklevel=2,
    )
```

Match-or-uppercase semantics:

```python
mapped = pl.col(source).replace_strict(decode_map, default=None)
expr = pl.coalesce([mapped, pl.col(source).str.to_uppercase()]).alias(target)
```

Three-tier precedence in `CTValidator.get_decode_map`:

```python
# ct/validator.py — order matters: first occurrence wins (oak: distinct(from, .keep_all=TRUE))
decode_map: dict[str, str] = {}
for term in codelist.terms:
    for key in (term.submission_value, term.collected_value, *term.synonyms):
        if key and (k := key.strip()) not in decode_map:
            decode_map[k] = term.submission_value
```

---

### 🟠 8. `baseline_flag`: missing eligibility, time-of-day ties, LOBXFL

vs oak `derive_blfl` (`sdtm/namespace.py:750-892`): no exclusion of `--ORRES` null/`"ND"`/`"NOT DONE"`/`""` or `--STAT == "NOT DONE"` records (Fleet can flag a NOT DONE record as baseline); no time-of-day comparison when the observation date equals the reference date; no `--LOBXFL` variant (SDTMIG v3.4 preference).

**Fix** — additive signature:

```python
def baseline_flag(
    self, target: str, *,
    date_col: str,
    testcd_col: str | None = None,
    result_col: str | None = None,        # e.g. "VSORRES" — auto from domain prefix
    stat_col: str | None = None,          # e.g. "VSSTAT"
    baseline_visits: list[str] | None = None,
    baseline_timepoints: list[str] | None = None,
    ...
)
```

Eligibility as one lazy expression before the max-date logic:

```python
eligible = pl.lit(True)
if result_col:
    eligible &= (
        pl.col(result_col).is_not_null()
        & ~pl.col(result_col).str.strip_chars().is_in(["ND", "NOT DONE", ""])
    )
if stat_col:
    eligible &= pl.col(stat_col).fill_null("") != "NOT DONE"

pre_ref = (
    pl.when(eligible & (pl.col("__bl_date__") <= pl.col("__bl_ref__")))
    .then(pl.col("__bl_date__"))
)
```

Accept `target="VSLOBXFL"` as-is — the algorithm is identical; only the eligibility default differs (pre-treatment only).

---

### 🟠 9. Date ingestion: UNK tokens + a problems report

`sdtm/utils.py:32-59` — the coalesce chain falls back to the raw string, so garbage flows into `--DTC`:

```python
pl.coalesce(*[...six formats...], pl.col(source))   # "2014-13-45" survives untouched
```

oak's `create_iso8601` handles `"UN"/"UNK"` unknown components, partial ISO output with `-` placeholders, 2-digit-year cutoff, and attaches a `problems()` report.

**Fix** — preprocess unknown tokens, report what didn't parse:

```python
UNK_RE = r"(?i)\b(UN|UNK|UNKN?OWN)\b"

cleaned = pl.col(source).str.replace_all(UNK_RE, "")   # "UN-UNK-2019" → parses as "2019"

parsed = pl.coalesce(*format_attempts)                 # NO raw-string fallback
problem = pl.col(source).is_not_null() & (pl.col(source) != "") & parsed.is_null()
```

At `to_frame()`, surface oak's `problems()` through the existing `inspect()` machinery:

```text
⚠ date('VSDTC'): 3 value(s) could not be parsed: ['2014-13-45', '45/45/45', 'TBD']
```

---

### 🟡 Minor alignments

```python
# tmf_expr — admiral 1.4.0: ignore_seconds_flag=TRUE is the new default
def tmf_expr(source, *, ignore_seconds: bool = True) -> pl.Expr:
    ...
    if ignore_seconds:
        expr = expr.replace({"S": None})    # seconds-only imputation ⇒ no flag

# age_from_dates — clinical convention truncates, never rounds
def age_from_dates(..., *, trunc: bool = True):
    years = (ref - birth).dt.total_days() / 365.25
    return years.floor().cast(pl.Int64) if trunc else years.round(round_digits)
```

- **`hardcode_*` with a raw source**: oak assigns the constant only where the raw variable is non-NA; consider a documented `where=` parameter for parity.
- **Invalid imputed dates**: admiral dev now *errors* on impossible imputed dates (2020-02-31, #3014). Fleet's `strict=False` parsing nulls them silently — at minimum count and warn.
- **`duration` months/years**: admiral distinguishes `type="duration"` (fixed factors — matches Fleet) from `type="interval"` (calendar-accurate); consider exposing both.

---

## Axis 2 — TDD layer gaps, with design options

The protocol-reference half (TE/TA/TV/TS/TI: Pydantic rows + collections + validators, `tdd.py:87-372`) is solid and **ahead of pharmaverse** — oak explicitly has nothing for trial design through v0.2.0. Gaps concentrate in the subject-level half and cross-domain glue.

### Gap A — SE/SV are assembled, not derived

`element_boundaries()` / `visit_map()` / `epoch_assign()` (`_tdd_mixin.py:338-575`) require hand-built milestone dicts; the SDTMIG algorithm (assign subjects to elements via TE's TESTRL/TEENRL anchored on DM/EX/DS dates) isn't encoded.

| Option | Approach | Trade-off |
|---|---|---|
| **A1 (recommended)** | `derive_se()` verb: pins DM/EX/DS, maps TESTRL/TEENRL anchor text → date columns, emits one row per subject×element | Reuses pin + fixed-sequence patterns |
| **A2 (recommended, combine with A1)** | Extend `TrialElement` with an `anchor` field — the trial design *is* the spec | Most Fleet-philosophical; slightly more model surface |
| A3 | Spec-driven only: `algorithm: derive_se` in define.yaml | Cheapest, but leaves inline workflow second-class |

```python
class TrialElement(BaseModel):
    etcd: str
    element: str
    testrl: str
    teenrl: str
    epoch: Epoch
    anchor: str | None = None      # NEW: DM/EX/DS column that realises TESTRL per subject
```

```python
# One verb, SDTMIG algorithm: subjects → elements via anchor dates
se = (
    dm.sdtm
    .pin("EX", ex).pin("DS", ds)
    .derive_se(
        te=te_rows,                              # TrialElements (with anchors)
        ta=ta_rows,                              # arm → element path via TAETORD
        milestones={                             # overrides / non-column anchors
            "INFORMED CONSENT": "RFICDTC",
            "RANDOMIZATION": "RFSTDTC",
            "END OF TREATMENT": "RFXENDTC",
        },
    )
    .to_frame()
)   # → STUDYID, USUBJID, SESEQ, ETCD, ELEMENT, SESTDTC, SEENDTC, TAETORD, EPOCH
```

### Gap B — No EPOCH propagation to general domains

| Option | Approach | Trade-off |
|---|---|---|
| **B1 (recommended)** | `epoch_from_se()` shared verb: pin SE, join on USUBJID + date-in-range | SDTMIG-recommended derivation, one chainable line per domain |
| B2 | Overload `epoch_assign(ranges_from="SE")` | Smaller API, less discoverable |
| B3 | `StudyContext.propagate_epoch(domains=[...])` batch step | Good for metadata workflow only; breaks verb paradigm |

```python
ae = (
    raw_ae.sdtm
    .hardcode_no_ct("DOMAIN", value="AE")
    .date("AESTDTC", source="ae_start")
    .pin("SE", se)
    .epoch_from_se("EPOCH", date_col="AESTDTC")    # join: USUBJID + date ∈ [SESTDTC, SEENDTC)
    .to_frame()
)
```

```python
# core join — lazy join_where, no manual ranges dict:
df.join_where(
    se.lazy(),
    pl.col("USUBJID") == pl.col("se.USUBJID"),
    dtc_datepart(date_col) >= pl.col("se.SESTDTC"),
    dtc_datepart(date_col) < pl.col("se.SEENDTC"),
)
```

### Gap C — TSPARMCD not validated against CT

| Option | Approach | Trade-off |
|---|---|---|
| **C1 (recommended)** | Generate `TSPARMCD` codelist class (C66738) via `fleet init ct`, validate in collection validator | Zero new concepts; authoring-time feedback |
| C2 | Built-in custom CORE rule for TSPARMCD/TSPARM | Validation-time only; weaker feedback loop |

```python
from codelists import TSPARMCD     # C66738 — IDE-discoverable, hover shows terms

class TrialParameters(BaseModel):
    @model_validator(mode="after")
    def tsparmcd_in_codelist(self) -> Self:
        valid = CTValidator.get_instance().get_valid_values(TSPARMCD._concept_id)
        if valid and (bad := {p.tsparmcd for p in self.parameters} - valid):
            raise ValueError(f"TSPARMCD value(s) not in CDISC CT C66738: {sorted(bad)}")
        return self
```

### Gap D — TI uniqueness uses the wrong key, no versioning

| Option | Approach | Trade-off |
|---|---|---|
| **D1 (recommended)** | Composite-key validator on `(IETESTCD, TIVERS)` + optional `tivers` field | Five lines, correct |
| D2 | Amendment-aware builder: `add_criteria(..., version="2.0")` with monotonic version validation | Nicer for real amendment workflows, more API |

```python
class TrialCriterion(BaseModel):
    ietestcd: str
    iecat: Literal["INCLUSION", "EXCLUSION"]
    tivers: str | None = None          # NEW — protocol amendment version

class TrialCriteria(BaseModel):
    @model_validator(mode="after")
    def unique_per_version(self) -> Self:
        keys = [(c.ietestcd, c.tivers) for c in self.criteria]   # was: ietestcd alone
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate (IETESTCD, TIVERS) pairs in TI")
        return self
```

### Gap E — TD/TM domains absent

| Option | Approach |
|---|---|
| **E1 (recommended)** | Replicate the existing Pydantic row+collection pattern — marginal cost, completes the "all TDD domains" claim in `docs/concepts/tdd.md` (currently 5/7 modeled) |
| E2 | Defer explicitly and re-word the docs (they currently over-claim) |

### Gap F — No cross-domain reconciliation (TA.ARMCD ↔ DM.ARMCD, TV ↔ SV)

| Option | Approach |
|---|---|
| **F1 (recommended)** | Extend the optional-FK pattern `add_arms` already uses for TE |
| F2 | A `reconcile()` terminal verb producing a structured issue list (matches `DefineValidator.issues` shape) |

```python
ta = (
    builder.study_header("CDISCPILOT01", "TA")
    .add_arms(ta_rows, te=te_rows, dm=dm)     # NEW kwarg
)
# → warns: "TA.ARMCD {'PBO2'} not present in DM.ARMCD {'PBO','TRT'}"
#   escalates to error under .fk_policy('error') — no new concepts
```

---

## Axis 3 — Testing alignment with oak/admiral

**Verdict: partially aligned — and the misses are exactly where the Axis-1 bugs live.** Every bug above (datetime DTC, null→NORMAL, duplicate baselines, multi-ref subjects) would have been caught by the edge-case classes oak/admiral test systematically.

What the references do:

- **admiral**: inline `tribble()` inputs + **hand-written literal expected frames** compared via `expect_dfs_equal(base, compare, keys=...)` — keyed, order-insensitive, full-frame, diff-reporting. Numbered tests, snapshot tests for error messages, systematic edge-case names (*"using order for resolving ties"*, *"produces consistent results regardless of input sort order"*).
- **oak**: same inline style, plus **exhaustive unit tests of low-level datetime internals** (342 lines just for format parsing: 2-digit-year cutoffs, `"--01"` partials, fractional seconds, problems-attribute structure) and a 175-line end-to-end test pinning the coalesce contract to issue #110.

What Fleet does: good determinism/shuffle tests (`test_robustness.py` — genuinely better than oak/admiral), strong Pydantic coverage in TDD, but `test_admiral_parity.py` is **formula transcription** (BSA, QTc, MAP — math that was never going to be wrong) plus spot-checks on single cells. The docs' "400+ admiral parity tests" claim overstates what those 515 lines verify.

### Improvements, in priority order

#### 3.1 Keyed full-frame assertion (admiral's `expect_dfs_equal`)

```python
# tests/assertions.py
def assert_dfs_equal(result: pl.DataFrame, expected: pl.DataFrame, *, keys: list[str]) -> None:
    """Order-insensitive, full-frame comparison keyed on identifying columns."""
    r = result.sort(keys).select(sorted(result.columns))
    e = expected.sort(keys).select(sorted(expected.columns))
    assert r.columns == e.columns, f"column mismatch: {set(r.columns) ^ set(e.columns)}"
    for col in e.columns:
        if not r[col].equals(e[col]):
            diff = r.select(keys + [col]).join(
                e.select(keys + [pl.col(col).alias(f"{col}_expected")]), on=keys
            ).filter(pl.col(col) != pl.col(f"{col}_expected"))
            raise AssertionError(f"{col} differs:\n{diff}")
```

```python
def test_study_day_admiral_test3_dates_before_reference():
    inp = pl.DataFrame({"USUBJID": ["01", "01"], "AESTDTC": ["2013-12-30", "2014-01-03"],
                        "RFSTDTC": ["2014-01-02", "2014-01-02"]})
    expected = inp.with_columns(pl.Series("AESTDY", [-3, 2]))   # hand-computed, SDTMIG 4.4.4
    out = inp.sdtm.study_day("AESTDY", date_col="AESTDTC").to_frame()
    assert_dfs_equal(out, expected, keys=["USUBJID", "AESTDTC"])
```

Rule: expected frames are **literal, never re-derived** with the logic under test.

#### 3.2 Golden cross-language parity fixtures

The one thing transcription can't give you. Run oak/admiral once in R over `pharmaversesdtm`/`pharmaverseadam` inputs, commit input+output pairs as parquet:

```r
# scripts/generate_parity_fixtures.R — run ONCE per admiral release, outputs committed
library(admiral); library(arrow)
input <- pharmaversesdtm::vs |> select(USUBJID, VSTESTCD, VSDTC, VSORRES, VSSTAT)
write_parquet(input, "tests/fixtures/parity/blfl_input.parquet")
expected <- sdtm.oak::derive_blfl(input, dm_domain = pharmaversesdtm::dm,
                                  tgt_var = "VSBLFL", ref_var = "RFSTDTC")
write_parquet(expected, "tests/fixtures/parity/blfl_expected.parquet")
```

```python
# tests/unit/test_parity_golden.py — TRUE parity: same input, byte-compared output
def test_blfl_matches_oak_golden():
    inp = pl.read_parquet(FIXTURES / "parity/blfl_input.parquet")
    expected = pl.read_parquet(FIXTURES / "parity/blfl_expected.parquet")
    out = (inp.sdtm.pin("DM", dm)
           .baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD",
                          result_col="VSORRES", stat_col="VSSTAT")
           .to_frame())
    assert_dfs_equal(out, expected, keys=["USUBJID", "VSTESTCD", "VSDTC"])
```

~10 fixtures (blfl, study_day, dt/dtm imputation × first/mid/last, BASE, extreme flag, seq) anchor the "admiral parity" validation pillar in actual admiral output. This single test style would have caught bugs #1, #5, and #8 in one shot. Optionally: a non-blocking CI job regenerates fixtures against new admiral releases to detect upstream drift.

#### 3.3 Edge-case matrix per algorithmic verb (oak style, parametrized)

```python
@pytest.mark.parametrize("dtc, ref, expected_dy", [
    ("2014-01-05", "2014-01-02", 4),        # after ref: +1 rule
    ("2014-01-02", "2014-01-02", 1),        # on ref: day 1
    ("2013-12-30", "2014-01-02", -3),       # before ref: no day 0
    ("2014-01-05T10:30", "2014-01-02", 4),  # datetime DTC — bug #1 regression
    ("2014-01-05", "2014-01-02T09:20", 4),  # datetime REF — the subject-killer
    ("2014-01", "2014-01-02", None),        # partial: null, not a guess
    (None, "2014-01-02", None),
    ("garbage", "2014-01-02", None),
])
def test_study_day_matrix(dtc, ref, expected_dy): ...
```

Every date verb gets {complete date, datetime, YYYY-MM, YYYY, garbage, null, UN/UNK}; every flag/extreme verb gets {ties, duplicate keys, empty group, all-null group}.

#### 3.4 Property-based tests (hypothesis) for the imputation core

```python
from hypothesis import given, strategies as st

@given(year=st.integers(1990, 2030), month=st.integers(1, 12),
       strategy=st.sampled_from(["first", "mid", "last"]))
def test_imputed_date_stays_inside_partial_range(year, month, strategy):
    dtc = f"{year:04d}-{month:02d}"
    out = pl.select(impute_dtc_to_date(pl.lit(dtc), day_imputation=strategy)).item()
    assert out.year == year and out.month == month   # never escapes the collected components
```

Other invariants: DTF null ⇔ input complete; imputation idempotent on complete dates.

#### 3.5 Snapshot tests for warnings/errors (syrupy)

oak/admiral both pin their user-facing messages; Fleet's feedback-loop philosophy deserves the same.

#### 3.6 Mutation testing as the honesty metric

`mutmut` on `sdtm/utils.py` + `adam/utils.py` beats chasing line coverage — it directly measures whether tests detect logic flips like `>=` → `>`.

---

## Axis 4 — admiral's TTE update and a Fleet equivalent

### What changed (admiral dev 1.5.0, issue #2952 / PR #2988)

`derive_param_tte()` gained `end_dates` (a list of censor sources defining the **end of the observation period**) and `event_type ∈ {"negative", "positive"}`; sources gained `consider_end_dates`. The motivating insight — after rejecting a naive `censor_mode="first"` ("works in some examples but not all") — is that *censoring dates* (last assessment) and *observation-period boundaries* (end of study, death, rescue medication) are different concepts:

- Records after a subject's first end-date are excluded from event/censor selection.
- End-date censor descriptions take precedence via `coalesce(CNSR_end, CNSR_source)`.
- For *positive* events (response), subjects without an event are censored at the **earliest** boundary (conservative) instead of the last assessment.

Stable core semantics worth porting exactly:

| Rule | Semantics |
|---|---|
| Event selection | **first** per subject by `(date, order)` per source |
| Censor selection | **last** per subject |
| Cross-source date ties | broken by **list position** (events: earlier wins; censorings: later wins) |
| Event vs censoring | an event **always beats** a censoring, regardless of dates |
| CNSR coding | `0` for events enforced; positive integers per censor reason |
| Origin clamp | `ADT = pmax(ADT, STARTDT)` |
| Population | **inner join** with the passed ADSL (filter ADSL → restrict population) |
| `by_vars` | one param per group (e.g. AEDECOD), 1:1 PARAMCD check, cartesian extension of sources lacking by-vars |

**Assessment: adopt it.** It's a better decomposition than the pre-2952 model — it removes per-source hacks (duplicating "end of study" into every censor source) and makes positive-event endpoints safe by default. Fleet has no TTE layer, so it can skip admiral's legacy debt and implement the post-#2952 contract from day one — reaching parity with admiral 1.5.0 the month it ships.

### Fleet-native design

Source objects (frozen dataclasses, same role as `pick()`'s event dicts — YAML-serializable):

```python
# src/fleet/adam/tte.py
@dataclass(frozen=True)
class EventSource:
    source: pl.DataFrame | str          # frame inline, or pin name in YAML mode
    date: str
    filter: str | pl.Expr | None = None
    set: dict[str, str] = field(default_factory=dict)
    order: list[str] | None = None
    consider_end_dates: bool = True
    censor: int = field(default=0, init=False)      # admiral: events are ALWAYS CNSR=0

    def _to_pick_event(self) -> dict[str, Any]:
        """Coerce to the event-dict shape pick()'s engine already consumes.

        pick() events are {"when", "set", "source", "mode", "order"} dicts
        (adam/_mixins.py:991-1005). The dataclass exists only for CNSR
        validation and IDE discoverability — the engine sees a pick event.
        """
        return {
            "when": self.filter if self.filter is not None else pl.lit(True),
            "set": {**self.set, "ADT": self.date, "CNSR": pl.lit(self.censor)},
            "source": self.source,
            "order": [self.date, *(self.order or [])],
        }

@dataclass(frozen=True)
class CensorSource(EventSource):
    censor: int = 1
    def __post_init__(self):
        if self.censor <= 0:
            raise ADAMError("censor must be a positive integer (CNSR=0 is reserved for events)")
```

The verb:

```python
adtte = (
    adsl.adam.tte
    .param(
        "TTAE",
        start_date="TRTSDT",                       # STARTDT from the calling ADSL frame
        events=[
            EventSource(source=adae, date="ASTDT", filter='pl.col("TRTEMFL") == "Y"',
                        set={"EVNTDESC": "ADVERSE EVENT", "SRCDOM": "ADAE", "SRCSEQ": "AESEQ"}),
        ],
        censors=[
            CensorSource(source=adsl, date="TRTEDT", censor=1,
                         set={"EVNTDESC": "END OF TREATMENT", "CNSDTDSC": "TREATMENT END"}),
        ],
        end_dates=[                                # observation-period boundaries ≠ censorings
            CensorSource(source=adsl, date="EOSDT", censor=2,
                         set={"CNSDTDSC": "END OF STUDY"}),
        ],
        event_type="negative",
        set={"PARAM": "Time to First Adverse Event", "PARCAT1": "SAFETY"},
    )
    .duration("AVAL", start="STARTDT", end="ADT", add_one=True)
    .to_frame()
)
```

#### Step 0 — extract `pick()`'s engine into a shared helper (no behavior change)

The selection machinery **already exists** in `pick()` (`adam/_mixins.py:970-1182`): per-source filter → apply `set` expressions → stamp a list-position priority marker `__pick_event_nr__` (line 1129) → within-source first/last by `order` (lines 1140-1147) → stack with `pl.concat(how="diagonal_relaxed")` (line 1162) → priority-sorted winner per group (lines 1165-1173). That is exactly admiral's "tie-break by source-list position" rule. Pull pick()'s steps 1-3 into a private helper both verbs call:

```python
# adam/_mixins.py — pick()'s lines 1084-1173 extracted; pick() behaviour unchanged.
def _stack_and_select(
    self,
    events: list[dict[str, Any]],        # pick()'s event-dict shape: when/set/source/mode/order
    *,
    by: list[str],
    targets: list[str],
    mode: str = "first",
    order: list[str] | None = None,
    tie_break: Literal["first", "last"] = "first",   # NEW — censorings need "last in list wins"
    clip_to: pl.DataFrame | None = None,             # NEW — per-group date ceiling (TTE end_dates)
    date_col: str | None = None,                     # NEW — column the ceiling applies to
) -> pl.DataFrame | None:
    candidate_frames: list[pl.DataFrame] = []
    for event_nr, event in enumerate(events):
        source_df = event.get("source", ...)          # ← unchanged: pick() lines 1092-1101
        candidates = source_df.filter(_resolve_expr(event["when"]))

        if clip_to is not None:                       # NEW — drop records after the subject's
            candidates = (                            #       observation-period end (NA dates kept)
                candidates.join(clip_to, on=by, how="left")
                .filter((pl.col(date_col) <= pl.col("__end__")) | pl.col("__end__").is_null())
                .drop("__end__")
            )

        ...                                           # ← unchanged: set-exprs, __pick_event_nr__
                                                      #   stamp, per-event first/last selection —
                                                      #   pick() lines 1106-1154
        candidate_frames.append(candidates)

    if not candidate_frames:
        return None
    stacked = pl.concat(candidate_frames, how="diagonal_relaxed")   # ← line 1162
    stacked = stacked.sort(sort_cols, descending=sort_desc, nulls_last=True)  # ← lines 1165-1172
    grouped = stacked.group_by(by, maintain_order=True)
    return grouped.first() if tie_break == "first" else grouped.last()  # ← line 1173 + tie_break
```

`pick()` becomes a thin wrapper (its existing tests are the regression net for the extraction):

```python
def pick(self, targets, *, events, by=None, order=None, mode="first"):
    df = self.to_frame()
    winners = self._stack_and_select(events, by=by or ["USUBJID"],
                                     targets=target_list, mode=mode, order=global_order)
    if winners is None:                               # pick() lines 1156-1159, unchanged
        return self._materialise_then(df.with_columns([pl.lit(None).alias(t) for t in target_list]))
    return self._materialise_then(
        df.drop(drop_existing).join(winners.select(by_vars + target_list), on=by_vars, how="left")
    )
```

#### The TTE core — three calls to the same engine + TTE-specific resolution

```python
# adam/tte_namespace.py — everything below the comments marked NEW is pick()'s engine
def _select_tte_record(self, events, censors, end_dates, event_type, adsl_pop, by):
    # earliest observation-period boundary per subject (admiral: filter_date_sources mode="first")
    first_end = self._stack_and_select(
        [e._to_pick_event() for e in end_dates],
        by=by, targets=TTE_COLS, mode="first",
    ) if end_dates else None
    clip = (first_end.select(by + [pl.col("ADT").alias("__end__")])
            if first_end is not None else None)

    ev = self._stack_and_select(                      # events: FIRST per source, earlier in list wins
        [e._to_pick_event() for e in events],
        by=by, targets=TTE_COLS, mode="first", tie_break="first",
        clip_to=clip, date_col="ADT",
    )
    cn_sources = censors + (list(end_dates) if event_type == "positive" else [])
    cn = self._stack_and_select(                      # censorings: LAST per source, later in list wins
        [c._to_pick_event() for c in cn_sources],
        by=by, targets=TTE_COLS, mode="last", tie_break="last",
        clip_to=clip, date_col="ADT",
    )

    if first_end is not None and cn is not None:      # NEW — boundary description wins (CNSR coalesce)
        cn = (cn.join(first_end.select(by + ["CNSR", "CNSDTDSC"]), on=by, how="left", suffix="_end")
                .with_columns(pl.coalesce([pl.col("CNSR_end"), pl.col("CNSR")]).alias("CNSR")))

    # NEW — an event ALWAYS beats a censoring, regardless of dates
    winner = (
        pl.concat([f for f in (ev, cn) if f is not None], how="diagonal_relaxed")
        .with_columns((pl.col("CNSR") == 0).cast(pl.Int8).alias("__ev__"))
        .sort("__ev__").group_by(by, maintain_order=True).last()
    )

    # NEW — ADSL controls the population (inner join) + origin clamp; result is APPENDED as
    # new PARAMCD rows (derive_param-style), not joined as columns — the one structural
    # difference from pick()
    return (adsl_pop.join(winner, on=by, how="inner")
            .with_columns(pl.max_horizontal("ADT", "STARTDT").alias("ADT")))
```

So the genuinely **new** logic is exactly four blocks: the `clip_to` filter, the `tie_break="last"` direction, the CNSR coalesce, and event-beats-censor + row-append output. Everything else is `pick()` running three times.

Where Fleet beats admiral — the same endpoint as pure metadata:

```yaml
# define.yaml — TTE endpoints reviewable as metadata
- name: TTAE
  algorithm: tte_param
  start_date: TRTSDT
  events:
    - {source: ADAE, date: ASTDT, filter: 'pl.col("TRTEMFL") == "Y"',
       set: {EVNTDESC: ADVERSE EVENT, SRCDOM: ADAE, SRCSEQ: AESEQ}}
  censors:
    - {source: ADSL, date: TRTEDT, censor: 1, set: {EVNTDESC: END OF TREATMENT}}
  end_dates:
    - {source: ADSL, date: EOSDT, censor: 2, set: {CNSDTDSC: END OF STUDY}}
  set: {PARAM: Time to First Adverse Event, PARCAT1: SAFETY}
```

Discoverable source library, mirroring admiral's `death_event` family:

```python
from fleet.adam.tte_sources import DEATH_EVENT, LASTALIVE_CENSOR, AE_SER_EVENT
# IDE autocomplete shows the filter and date each constant encodes — codelist-class philosophy
```

### Testing — reuse admiral's own TTE test suite

admiral's `tests/testthat/test-derive_param_tte.R` is a ready-made behavioral specification: every test is a `tribble()`-built input plus a **literal expected frame**, compared via keyed `expect_dfs_equal` — which transcribes 1:1 to Polars + `assert_dfs_equal` (Axis 3.1) with no R runtime. admiral is Apache-2.0, so porting test data/cases with attribution is fine. Keep their test numbering so upstream diffs map directly onto Fleet failures:

```python
# tests/unit/test_tte_admiral_suite.py
# Transcribed from admiral tests/testthat/test-derive_param_tte.R
# (pharmaverse/admiral@main, Apache-2.0). Test numbers kept 1:1 with upstream —
# when admiral adds/changes a numbered test, the diff tells us exactly what to re-port.

class TestDeriveParamTTEAdmiralSuite:
    def test_01_one_event_one_censor_source(self):
        adsl = pl.DataFrame({
            "USUBJID": ["01", "02", "03"],
            "TRTSDT": [date(2020, 12, 6), date(2021, 1, 16), date(2021, 1, 9)],
            "EOSDT":  [date(2021, 3, 6),  date(2021, 2, 3),  date(2021, 2, 24)],
        })
        death = pl.DataFrame({"USUBJID": ["01"], "DTHDT": [date(2021, 2, 25)]})

        expected = pl.DataFrame({          # literal — copied from the upstream tribble,
            "USUBJID": ["01", "02", "03"], # NEVER re-derived with the logic under test
            "PARAMCD": ["OS", "OS", "OS"],
            "STARTDT": [date(2020, 12, 6), date(2021, 1, 16), date(2021, 1, 9)],
            "ADT":     [date(2021, 2, 25), date(2021, 2, 3),  date(2021, 2, 24)],
            "CNSR":    [0, 1, 1],
        })

        out = (
            adsl.adam.tte
            .param(
                "OS", start_date="TRTSDT",
                events=[EventSource(source=death, date="DTHDT",
                                    set={"EVNTDESC": "DEATH"})],
                censors=[CensorSource(source=adsl, date="EOSDT", censor=1,
                                      set={"EVNTDESC": "END OF STUDY"})],
                set={"PARAM": "Overall Survival"},
            )
            .to_frame()
        )
        assert_dfs_equal(out.select(expected.columns), expected, keys=["USUBJID", "PARAMCD"])
```

Porting priority (the tests that pin the semantics Fleet must not get wrong):

| Upstream test | Pins |
|---|---|
| *"order for resolving ties"* | date ties broken by `order`, then source-list position |
| *"ensuring ADT is not NA because of missing start_date"* | NA-date handling + origin clamp |
| *"by_vars: one parameter per event group"* | cartesian source extension + 1:1 PARAMCD check |
| *"events take precedence over censorings"* | the `__ev__` resolution rule |
| *"consistent results regardless of input sort order"* | order-invariance (pairs with `test_robustness.py`'s existing shuffle helper) |
| **Test 17: end dates** (dev) | `end_dates` clipping + CNSR coalesce precedence |
| **Test 18: positive events** (dev) | `event_type="positive"` → censor at earliest boundary |
| error/snapshot tests (PARAMCD exists, bad censor value) | typed `ADAMError` messages, via syrupy (Axis 3.5) |

Two layers, complementary (both from Axis 3): the **transcribed suite** above is R-free and runs in every CI; the **golden fixtures** (Axis 3.2, parquet pairs generated once per admiral release) catch transcription mistakes and upstream drift. A numbered upstream test that changes ⇒ re-port; a golden fixture that changes ⇒ admiral's behavior moved.

**Phasing:**
- **Phase 0**: extract `_stack_and_select()` from `pick()` (`adam/_mixins.py:1084-1173`) with `tie_break`/`clip_to`/`date_col` parameters defaulted to today's behavior — `pick()`'s existing tests (`test_pick_verb.py`) are the regression net; zero functional change.
- **Phase 1**: single-param `param()` on top of the shared engine: end_dates, clamping, precedence rules — validated by the transcribed admiral suite (above) plus golden fixtures (Axis 3.2), with admiral-dev's `Test 17: end dates` / `Test 18: positive events` as the acceptance gate.
- **Phase 2**: `by_vars=` (per-AEDECOD parameters, cartesian source extension + 1:1 PARAMCD assertion), `event_type="positive"`, ADTTE template example + docs.

Machinery reuse: `param()` is a materialising verb like `pick` (which the docs already sanction for multi-frame logic), and after Phase 0 both verbs share one selection engine — no duplicated stack/priority/tie-break logic to drift apart. Lesser relatives for reference: `flag(criteria="exists"/"exists_before")` (`_mixins.py:245-278`) scans source datasets but only returns Y/null; `vaccine.event_flag` is a thin condition wrapper — neither has the priority-stacking engine, which is why `pick()` is the extraction point.

---

## Axis 5 — What is still missing

Given what exists (schema validation, define.xml, CORE + custom rules, CLI, discoverable codelists, grading already at CTCAE v5/v6 + USCV parity with admiral 1.4.0):

1. **ADTTE** — Axis 4. The single biggest functional hole; already on the roadmap.
2. **The coalesce/no-overwrite contract** (Axis 1 #6) — a missing semantic foundation, not a feature; unlocks oak-style multi-source mapping.
3. **EPOCH/SE/SV true derivation** (Axis 2) — oak explicitly does *not* have this yet; shipping it puts Fleet *ahead* of pharmaverse on SDTM.
4. **A general windowed/temporal join verb** — admiral's workhorses `derive_vars_joined` / `derive_vars_joined_summary`. Fleet's `flag(criteria="exists_before")` covers the boolean case only, with per-row Python iteration that won't scale:

   ```python
   # "dose at the time of the AE"
   adae = (
       adae.adam
       .join_when(
           "LASTDOSE",
           other=ex,
           by=["USUBJID"],
           join_on='pl.col("EXSTDT") <= pl.col("ASTDT")',   # condition over both frames
           order=["EXSTDT"], mode="last",                    # last dose before onset
           set={"LASTDOSE": "EXDOSE", "LDOSEDT": "EXSTDT"},
       )
       .to_frame()
   )
   # implementation: polars join_where / join_asof — vectorized, returns VALUES, not just a flag
   ```

5. **Cross-language parity fixtures + drift CI** (Axis 3.2) — turns `validation-strategy.md` claims into evidence a sponsor's QA can accept; cheap insurance as admiral's formal phased-deprecation pipeline shifts semantics every 6 months on schedule.
6. **Enhanced validation reporting** (own unchecked roadmap item) — CORE engine output → one aggregated human-readable HTML/markdown issue report per study (P21-report-shaped), fed by `DefineValidator.issues` + CORE + custom rules together.
7. **`merge`/`lookup` relationship guards** — admiral's `derive_vars_merged` errors on unexpected many-to-many matches; Fleet's `merge` (`sdtm/namespace.py:1121-1157`) joins blind:

   ```python
   # sdtm/namespace.py merge() — one new kwarg:
   def merge(self, dataset, *, on, target_cols=None,
             relationship: Literal["many-to-one", "one-to-one", None] = "many-to-one"):
       ...
       df = df.join(dataset, on=on, how="left")
       if relationship and df.height != before:
           raise SDTMError(
               f"merge on {on}: expected {relationship} but row count grew "
               f"{before} → {df.height} — joined dataset has duplicate keys "
               f"(pass relationship=None to allow, or .nodup() the right side)"
           )
   ```

Lower priority: ADPC dataset structure (PK verbs exist; the BDS-PC assembly template doesn't), RELREC generation, `derive_locf_records` parity with admiral 1.3's `imputation="update"/"update_add"/"add"` modes, CT version pinning per study (stamp CT package version into define.xml).

**Strategic note:** admiral's stated future is metadata-driven derivation ("call stores", metacore integration — no admiral 2.0 rewrite coming), and the pharmaverse is pivoting to AI-assisted workflows (AGENTS.md in admiral's test suite, kapa.ai docs assistant, March 2026 blog post). Fleet already has both pillars natively — `define.yaml`-driven pipelines and AI-first design with `llms.txt`. The gaps above are almost all *correctness depth*, not architecture: the foundation is pointed where pharmaverse is trying to go.

---

## Priority summary

| Priority | Item | Axis | Effort |
|---|---|---|---|
| **P0** | `dtc_datepart` fix (datetime DTC silently dropped) | 1.1 | XS — corrupting real output today |
| **P0** | Coalesce / no-overwrite contract in `_chain()` | 1.6 | S — unlocks core oak mapping pattern |
| **P0** | Golden parity fixtures + `assert_dfs_equal` | 3.1–3.2 | M — would have caught the above |
| P1 | `nrind` null, `_apply_clamp`, `baseline` dup check, `study_day` multi-ref | 1.2–1.5 | S each |
| P1 | `assign_ct` loud fallback + oak matching | 1.7 | S |
| P1 | ADTTE `param()` phases 0-1 | 4 | M — selection engine extracted from `pick()` (`_mixins.py:1084-1173`), not rewritten |
| P2 | `baseline_flag` eligibility/LOBXFL, date problems report | 1.8–1.9 | M |
| P2 | `derive_se` + `epoch_from_se` | 2.A–B | M |
| P2 | Edge-case matrices + hypothesis tests | 3.3–3.4 | M |
| P3 | TS/TI/TD/TM/reconcile, `join_when`, relationship guards, validation report | 2.C–F, 5 | M–L |
