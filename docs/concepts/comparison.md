# Comparing Datasets

Every QC step ends with the same question: is this dataset the same as that
one, and if not, where exactly does it differ? SAS answers it with
`PROC COMPARE`. Fleet answers it with **compare** — one engine in pure Polars,
reachable as a Python function, as a pipeline verb, and as a CLI command.

A compare pairs two datasets observation by observation on their **keys** and
variable by variable on their names, then reports where they differ. It is
distinct from [validation](validation-core.md), which checks one dataset
against CDISC conformance rules.

| Term | Meaning |
| --- | --- |
| **Base** | The reference dataset the comparison is measured against (production, legacy SAS, last release). |
| **Candidate** | The dataset being measured against the base (the independent QC programming, the migrated output). |
| **Keys** | The variables that together identify one observation on each side. Mandatory; never looked up. |
| **Comparison report** | The outcome: which variables and observations were common or one-sided, and every value that differed. |

## Three surfaces, one engine

From Python, `fleet.compare` takes DataFrames or LazyFrames on either side and
returns a [`ComparisonReport`](../api/comparison.md). Differences never
raise — the report says what was found:

```python
import fleet

report = fleet.compare(adae_prod, adae_qc, keys=["USUBJID", "AESEQ"])
report.print_report()
assert report.is_equal, report.raised_flags
```

At the end of a pipeline, the `.compare()` verb is available on `df.sdtm`,
`df.adam`, `df.adam.adsl` and `df.adam.occds`. The chain is the candidate and
the argument is the base; the verb prints the report, keeps it on the namespace
as `last_comparison`, and returns a namespace copy so the chain continues:

```python
adae_qc = (
    ae_df.adam.occds.source("USUBJID")
    .source("AESEQ")
    .compare(adae_prod, keys=["USUBJID", "AESEQ"])
    .to_frame()
)
```

From a shell, `fleet compare` loads both files through the raw-data loader
(parquet, CSV, and XPT or sas7bdat with the `io` extra), prints the report,
and turns the verdict into the exit code:

```bash
uv run fleet compare adae_prod.parquet adae_qc.parquet --keys USUBJID,AESEQ
uv run fleet compare legacy/adae.xpt outputs/adam/adae.parquet --keys USUBJID,AESEQ --all
```

| Exit code | Meaning |
| --- | --- |
| `0` | The datasets are equal. |
| `1` | The datasets differ; the report on stdout says where. |
| `2` | The comparison could not run: unreadable file, missing or duplicate keys, a negative tolerance, a `--variables` list that names only keys, or an `--out` or `--report` path that cannot be written. The reason is on stderr. |

A compare that checks no values still gives a verdict. When the two sides
share only their keys, the verdict follows the observations: the same key
values on both sides are EQUAL, a one-sided key or variable is NOT EQUAL.
When both sides have no observations, the verdict is EQUAL. In both cases the
report warns above the first number, so an EQUAL that checked no values
never reads as a full pass ([ADR-0004](../adr/0004-a-compare-that-checks-no-values-keeps-the-two-value-verdict.md)).

`--keys` is required. `--by TRT01P` sections the report per
[BY group](#by-groups) and `--allow-duplicates` pairs
[duplicate keys](#duplicate-keys) by position. `--pairs` and `--variables`
[rename and restrict](#variable-pairs-and-restriction) what is compared.
`--abs-tol`, `--rel-tol` and
`--ignore-trailing-whitespace` widen equality (see
[tolerances and whitespace](#tolerances-and-trailing-whitespace)). `--all`
lifts the print limits so every unequal value is
listed. `--report adae_compare.html` writes the
[HTML report](#the-html-report) for a reviewer. `--format json` prints one
JSON document and nothing else on stdout, and `--out differences.parquet`
writes the complete value listing; both are described under
[machine-readable outputs](#machine-readable-outputs). See the
[CLI reference](../getting-started/cli.md#fleet-compare) for the full usage.

## What the report contains

The text report follows the `PROC COMPARE` section order, so a SAS programmer
reads it without a legend:

1. **Data set summary** — name, observations and variables per side, the keys, and the settings line naming the equality rule in effect (`exact`, or the tolerances and the whitespace rule).
2. **Variables summary** — variables in common, in the base only, in the candidate only, type conflicts, dtype differences.
3. **Observation summary** — matched observations and the key values of the ones found on one side only.
4. **Values summary** — how many values differ, per variable.
5. **Summary statistics** — for each differing numeric variable, how far apart the two sides are (see [summary statistics](#summary-statistics)).
6. **Value listing** — every unequal value, grouped per observation so one subject's differences read together, with the base value, the candidate value, and the difference and percent difference for numeric variables.
7. **Verdict** — `EQUAL`, or `NOT EQUAL` followed by the raised flags.

The report object carries the same content as data: `report.listing` is a long
Polars frame (keys, `group`, `variable`, `base`, `candidate`, `difference`,
`percent_difference`) that is never truncated, `report.statistics` is the
[summary statistics](#summary-statistics) frame, and `report.flags` replaces
SAS's `SYSINFO` integer with names — `base_only_variables`,
`candidate_only_variables`, `type_conflicts`, `base_only_observations`,
`candidate_only_observations`, `values_differ`, `duplicate_keys`,
`base_only_groups`, `candidate_only_groups`. `report.is_equal` is true only
when no flag is raised. `report.warnings` holds the lines every renderer
prints above the report — today only the
[duplicate-key](#duplicate-keys) one.

## Summary statistics

Counting differences says *how many*, not whether the candidate runs
systematically a little high or scatters at random. `report.statistics` says
which: one row per differing variable and, for a numeric one, the shape of
both sides, of their difference, and of that difference as a percentage of the
base.

```python
report = fleet.compare(advs_prod, advs_qc, keys=["USUBJID", "PARAMCD", "AVISITN"])
offset = report.statistics.filter(pl.col("difference_mean").abs() > 0.5)
```

| Column | Content |
| --- | --- |
| `variable` | The differing variable, by its base name, in compared order. |
| `differences` | How many matched observations differ on it. |
| `base_n`, `base_mean`, `base_std`, `base_min`, `base_max` | The base values. |
| `candidate_n` … `candidate_max` | The same five, of the candidate values. |
| `difference_n` … `difference_max` | The same five, of `candidate − base`. |
| `percent_difference_n` … `percent_difference_max` | The same five, of `(candidate − base) ÷ base × 100`. |

Two things decide what the numbers mean:

- **The measures span every matched observation, not only the unequal ones.**
  A mean difference near zero over a thousand observations with three
  differences reads as noise; a mean difference of exactly `0.5` across all of
  them reads as an offset. Only observations **null, NaN or infinite on either
  side** are dropped, because a difference needs two finite values — which is
  why `n` can be smaller than the matched count, and smaller again for the
  percent, which drops a zero base as the listing does. No measure is ever NaN
  or infinite, so the text report, the HTML page and the JSON document show
  the same numbers.
- **Only numeric variables carry them.** A string, a date or a boolean
  contributes its `differences` count and nulls for the rest; there is no mean
  of `"F"` against `"M"`.

The statistics are on every surface: their own section in the text report
after the values summary, the `statistics` key of the JSON document, and a
table at the top of each variable's block in the HTML page. An equal
comparison has an empty frame and an empty section.

Deliberately absent are `PROC COMPARE`'s correlation, R² and t statistic: they
answer a modelling question rather than a QC one, and the value listing
answers the QC one exactly.

## The HTML report

A study lead reviews without a Python environment. `report.to_html()` renders
one self-contained page and `report.save_html_report(path)` writes it; from
the shell, `fleet compare --report adae_compare.html` does the same next to
the text report:

```bash
uv run fleet compare adae_prod.parquet adae_qc.parquet --keys USUBJID,AESEQ --report build/adae_compare.html
```

The page opens offline: its style is embedded and it fetches no script, font
or image. It reads top-down the way a review goes:

1. **Verdict** — `EQUAL` or `NOT EQUAL`, with the one-line summary and the raised flags.
2. **Chips** — one per raised flag, so structural problems are visible before value details: the variables found on one side only, the type conflicts with their dtypes, the observations on one side only (the first few named by their key values), how many values differ. Dtype differences appear as an information chip, never as a finding.
3. **Summary** — name, observations and variables per side, the keys, the equality rule in effect, and how many observations matched.
4. **Observations on one side only** — the key values of every observation found only in the base or only in the candidate.
5. **Unequal values** — only the mismatched observations, one collapsible block per differing variable. Each block opens on the variable's [summary statistics](#summary-statistics), then lists every unequal row: the key values, the base value and the candidate value side by side with both cells highlighted, and the difference and percent difference for numeric variables. Blocks start open when there are five or fewer, closed beyond that, so a report over fifty variables stays navigable.

The page is never truncated: every unequal value is on it, whatever
`max_print` the comparison ran with. With [BY groups](#by-groups) it gains a
**Groups** section with the per-group counts and sections the unequal values
per group. The summary statistics span all groups, so the page then draws them
once per variable, above the group sections, with the caption "over all
groups". A listed value that would read the same as another one is quoted:
`"M "` against `M`, `"null"` against a missing `null`, `""` against `null`.
The text report quotes the same way; the JSON document and the parquet keep
the raw values. For listings beyond a few thousand rows, the
[parquet listing](#the-parquet-listing) is the better archive.

## Machine-readable outputs

An agent or a CI job consumes the comparison without parsing prose.
`report.to_json()` renders one JSON document, `report.save_json(path)` writes
it, and `report.save_listing(path)` writes the complete value listing as
parquet. From the shell, `fleet compare --format json` prints the document and
nothing else on stdout (the exit code is still the verdict, and a comparison
that could not run still leaves stdout empty with the reason on stderr), and
`--out` writes the listing:

```bash
uv run fleet compare adae_prod.parquet adae_qc.parquet --keys USUBJID,AESEQ --format json > adae_compare.json
uv run fleet compare adae_prod.parquet adae_qc.parquet --keys USUBJID,AESEQ --out build/adae_differences.parquet
```

### The JSON contract

Field names mirror the report attributes. The document is **additive-only
within a major version**, in the spirit of
[ADR 0001](../adr/0001-introspection-surface-for-protocol-adapters.md): keys
may be added, never removed or renamed, so a comparison view built on them
(the editor extension is the intended consumer) declares a minimum Fleet
version and no ceiling. The top-level keys, in order (`fleet.comparison.JSON_KEYS`):

| Key | Content |
| --- | --- |
| `is_equal` | The verdict: `true` only when no flag is raised. |
| `summary` | The one-line summary, as `report.summary`. |
| `flags` | The raised flags, in their documented order. |
| `warnings` | The lines every renderer prints above the report; empty on an ordinary comparison. |
| `datasets` | `base` and `candidate`, each with `name`, `rows` and `variables`. |
| `variables` | `common`, `compared`, `base_only`, `candidate_only`, then `type_conflicts` and `dtype_differences` as `{variable, base_dtype, candidate_dtype}` with the dtypes as text. |
| `observations` | `matched`, `base_only`, `candidate_only`, the one-sided key values as `base_only_keys` and `candidate_only_keys` (capped at the per-variable print limit; `truncated` says whether a cap applied), `base_duplicates` and `candidate_duplicates`, the per-group counts as `per_group`, and the one-sided group labels as `base_only_groups` and `candidate_only_groups`. |
| `values` | `per_variable` as `{variable, differences}`, `variables_with_differences`, `observations_with_differences`, `total_differences`, `per_group`, and `within_tolerance` (values equal under a tolerance or `ignore_trailing_whitespace` but not exactly equal). |
| `statistics` | One object per differing variable, with the columns of `fleet.comparison.STATISTICS_COLUMNS`; the measures are `null` for a variable that is not numeric. See [summary statistics](#summary-statistics). |
| `listing` | `columns`, `rows` (one object per differing value, within the print limits), `shown`, `total` and `truncated`. |
| `settings` | Every option the comparison ran with: `keys`, `by`, `pairs`, `variables`, `abs_tol`, `rel_tol`, `ignore_trailing_whitespace`, `allow_duplicates`, `max_print`, `base_name`, `candidate_name`. |
| `version` | The Fleet version that produced the report. |

The document is strict JSON: non-finite numbers are `null` and temporal key
values are ISO 8601 strings. `max_print` governs the listing inside the
document exactly as it governs the text (`--all` or `max_print=None` lifts
it); the parquet listing is never truncated.

```python
import json

document = json.loads(report.to_json())
if not document["is_equal"]:
    for row in document["listing"]["rows"]:
        print(row["USUBJID"], row["variable"], row["base"], "->", row["candidate"])
```

### The parquet listing

`save_listing` writes `report.listing` as is: the key columns in their own
dtypes, then `group` (`String`, the [BY group](#by-groups) label or null),
`variable`, `base` and `candidate` (`String`), `difference` and
`percent_difference` (`Float64`). An equal comparison writes an empty frame
with the same schema, so a downstream `scan_parquet` always finds the
documented columns.

## Rules of equality

- **Keys are mandatory and must be unique** on each side. A missing or
  duplicated key stops the compare with a `ComparisonError` that names the side
  and the offending key values, because a broken key is the first thing to fix.
  [`allow_duplicates`](#duplicate-keys) is the deliberate way past it.
- **Equality is exact by default.** Null equals null, NaN equals NaN, and null
  against NaN differs, so a missing value that became a NaN is surfaced.
  [Tolerances](#tolerances-and-trailing-whitespace) widen it on the numeric
  variables and trailing-whitespace stripping on the strings; the null and NaN
  rule holds under both.
- **Same kind, different dtype is information, not a failure.** An `Int64`
  next to a `Float64`, a `String` next to a `Categorical`, or a `Date` next to
  a `Datetime` is compared by value after casting to a common type and listed
  as a dtype difference. A numeric next to a string is a **type conflict**:
  listed, not compared.
- **A blank is not a missing value unless you say so.** A SAS file reads a
  blank as null, so XPT against Parquet needs nothing. A file from another
  tool can keep `""` (an R data frame without `convert_blanks_to_na`), and
  `""` against null differs by default. `blank_is_missing=True` (or
  `--blank-is-missing`) reads `""` as null on both sides, keys included, and
  the settings line says `blank equals missing`.
- **A CSV file holds no types.** `fleet compare` reads a CSV side as text and
  types each column across both sides: the other side's type when that side
  is not a CSV file; otherwise text when a value on either side has a leading
  zero or is not a number, and a number in every other case. So SITEID `001`
  against `1` differs, and AVAL `1.10` against `1.1` is equal, as in PROC
  COMPARE. `--text LBORRES` keeps a column text, the `$` informat. The text
  report starts with the type each CSV column was read as.
- **Row order and column order are ignored.** A re-sorted or re-ordered
  dataset is not a different dataset.
- **Print limits only affect what is rendered.** By default the text report
  and the JSON document show 50 differences per variable and 500 overall;
  `max_print=None` (or `--all`) shows everything. The listing frame and the
  parquet always hold every difference.

## Tolerances and trailing whitespace

A migration programmer comparing Fleet output against a legacy SAS dataset has
to absorb engine noise without hiding a real difference. Three options do that,
and they are the same three on every surface:

| Option | Applies to | Effect |
| --- | --- | --- |
| `abs_tol` / `--abs-tol` | Numeric variables | Absolute tolerance. Default `0.0` — exact. |
| `rel_tol` / `--rel-tol` | Numeric variables | Relative tolerance, as a fraction of the **base** value. Default `0.0` — exact. |
| `ignore_trailing_whitespace` / `--ignore-trailing-whitespace` | String variables and string keys | Strip trailing whitespace from both sides before comparing. Default `False`. |

A numeric pair differs when the absolute difference exceeds
`max(abs_tol, rel_tol × |base|)`, so the wider of the two tolerances is the one
that decides. The relative tolerance **anchors on the base**, because the base
is the reference the candidate is measured against — this follows
`PROC COMPARE` and deliberately not Polars' testing helper, which anchors on
its right-hand frame. The choice is visible: at `rel_tol=0.095` a base of `100`
against a candidate of `110` differs (`10 > 9.5`), while the same pair with the
sides swapped is equal (`10 ≤ 10.45`).

```python
report = fleet.compare(
    advs_legacy,
    advs_fleet,
    keys=["USUBJID", "PARAMCD", "AVISITN"],
    rel_tol=1e-9,
    ignore_trailing_whitespace=True,
)
```

```bash
uv run fleet compare legacy/advs.xpt outputs/adam/advs.parquet \
  --keys USUBJID,PARAMCD,AVISITN --rel-tol 1e-9 --ignore-trailing-whitespace
```

What the options do **not** change:

- **Exact stays the default.** Both tolerances are `0.0` and whitespace counts
  until you say otherwise.
- **Tolerances only reach the numeric variables.** A string, a date or a
  boolean is compared exactly however wide `abs_tol` is, and stripping only
  reaches the string ones.
- **Nulls and NaN keep their rule.** Null still equals null, NaN still equals
  NaN, and null against NaN — or NaN against a number — still differs, however
  wide the tolerance. A NaN is never *within* a tolerance of a number.
  Infinity follows R `all.equal`: `inf` equals `inf`, and `inf` against a
  number or against `-inf` differs in every mode.
- **Only trailing whitespace is ignored.** `"M "` equals `"M"` when asked;
  `" M"` never does.
- **The listing shows the values as they are.** A difference that survives the
  tolerance is reported with the original base and candidate values, unstripped.
- **What the rule absorbed is counted.** `report.values.within_tolerance` (and
  `within_tolerance` in the JSON `values` block) counts the values equal under
  the rule but not exactly equal, as the `PROC COMPARE` note does. The text
  report then says `All compared values are within the rule in effect; 3 of
  them are not exactly equal.`
- **A tolerant comparison is arithmetic in `Float64`.** Integers and decimals
  beyond `2**53` are therefore compared at that precision; the exact default
  compares them in their own dtype.

The rule in effect is on every surface: the settings line of the text report
(`Settings:  abs_tol=1e-09, rel_tol=0, ignoring trailing whitespace`, or
`Settings:  exact`), the header of the HTML report, and the `settings` block of
the JSON document as the three raw fields.

The option also strips the string keys, before the duplicate-key check. A
SAS-padded USUBJID `"01-701-1015 "` then pairs with `"01-701-1015"` from Fleet.
Two keys that differ only in trailing blanks are duplicates. The listing
shows the keys stripped.

## Duplicate keys

Keys that do not identify one observation per side stop the compare, because a
broken key is usually the bug. When the duplication is expected — a dataset
with no sequence variable, a legacy extract — `allow_duplicates` forces the
comparison through:

```python
report = fleet.compare(adae_prod, adae_qc, keys=["USUBJID"], allow_duplicates=True)
```

```bash
uv run fleet compare adae_prod.parquet adae_qc.parquet --keys USUBJID --allow-duplicates
```

Duplicates then pair by **their position within each key group**: the first
base observation for `USUBJID=01` against the first candidate one, the second
against the second, and so on. An unpaired one — three on the base, two on the
candidate — is reported as an observation found on one side only.

That is a weaker guarantee than pairing on keys, so it is never silent:

- the observation summary counts the duplicates per side;
- the `duplicate_keys` flag is raised, so the comparison is never `is_equal`;
- `report.warnings` carries a line every renderer prints above the report, and
  the JSON document repeats it under `warnings`.

Row order stops being irrelevant under the override, and only within a
duplicated key group: which base observation meets which candidate one is
decided by the order the two datasets arrive in.

## BY groups

A reviewer looking at a study with several treatment arms wants to know
*where* the differences are, not just how many. `by` sections the report:

```python
report = fleet.compare(adsl_prod, adsl_qc, keys="USUBJID", by="TRT01P")
report.observations.per_group  # group, matched, base_only, candidate_only
report.values.per_group  # group, variables_with_differences, observations_with_differences, differences
```

```bash
uv run fleet compare adsl_prod.parquet adsl_qc.parquet --keys USUBJID --by TRT01P
```

The BY variables are **prepended to the keys automatically**, so they need not
be repeated in `keys` (repeating them is harmless). Everything else follows
from that:

- Every difference carries its group in the listing's `group` column, labelled
  `TRT01P=A` (and `TRT01P=A, AVISIT=2` with several BY variables), and the
  listing is sorted by group first.
- The observation summary and the values summary are reported per group as
  well as in total, in the text report, the JSON document and the HTML page.
- A group present on one side only raises `base_only_groups` or
  `candidate_only_groups` and is listed by name, so a missing arm reads as a
  missing arm rather than as a thousand missing observations.
- **The verdict stays global.** `is_equal` is still true only when no flag is
  raised anywhere.

## Variable pairs and restriction

Two datasets rarely line up by name alone. A legacy extract calls a variable
`WEIGHT` where the candidate calls it `WT`, and a candidate that is still
being written has columns nobody wants compared yet. `pairs` and `variables`
say so:

```python
report = fleet.compare(
    advs_legacy,
    advs_wip,
    keys=["USUBJID", "PARAMCD"],
    pairs={"WEIGHT": "WT"},  # base name: candidate name
    variables=["WEIGHT", "AVISIT"],  # base names
)
```

```bash
uv run fleet compare legacy/advs.xpt outputs/adam/advs.parquet \
  --keys USUBJID,PARAMCD --pairs WEIGHT=WT --variables WEIGHT,AVISIT
```

**`pairs` maps base names to candidate names**, on top of the automatic name
matching rather than instead of it: everything not named in `pairs` still
matches by name. A paired variable is compared by value and no longer reported
missing on either side, and the report — the values summary, the listing, the
HTML blocks — names it by its **base** name throughout. A pair is otherwise an
ordinary common variable: same kind but a different dtype is a dtype
difference, a different kind is a type conflict.

A pair whose candidate variable is **absent** reports the base one as missing
from the candidate, exactly as an unpaired variable would. A pair whose base
variable the base does not carry, one that renames a key, and two pairs
pointing at the same candidate variable are refused with a `ComparisonError`:
the pairing could not be honoured as written. So is a pair whose candidate
variable a base variable of the same name also matches by name: with base `A`
and `B`, `pairs={"A": "B"}` is refused, and the swap
`pairs={"A": "B", "B": "A"}` is legal. A candidate variable that no pair uses
and that no base variable matches by name is reported as extra: with
`pairs={"AVAL": "RESULT"}`, a candidate `AVAL` is a candidate-only variable.

**`variables` restricts the universe**, in base names. What is outside the list
is ignored entirely, on both sides: not compared, and not reported as missing
or extra either — a work-in-progress candidate is checked on the columns that
are finished without its unfinished ones raising a flag. What *is* on the list
still is: a restricted variable the candidate does not carry is still reported
as missing from it. Keys are never restricted; they pair observations whatever
the list says. A restriction naming a variable neither side carries is refused,
because a comparison that silently compares nothing would report two datasets
as equal.

Both options are recorded in `report.settings` (`pairs` and `variables`) and
shown wherever a run is described: the data set summary of the text report,
the header of the HTML page, and the `settings` block of the JSON document.

## Gating a pipeline on the outcome

The verb speaks the same failure vocabulary as `.validate()`:

| `on_fail` | Behaviour when the datasets differ |
| --- | --- |
| `"warn"` (default) | Emit a `UserWarning` and continue the chain. |
| `"raise"` | Raise `ComparisonFailed`, a subclass of `ComparisonError` (a `FleetError`). |
| `"ignore"` | No warning and no error. The report is still printed and stays on `last_comparison`. |

```python
adsl = (
    dm_df.adam.adsl.source("USUBJID")
    .assign("STUDYID", value="MYSTUDY01")
    .compare(adsl_prod, keys="USUBJID", on_fail="raise")
    .to_frame()
)
```

Any other value fails fast with a `DerivationError`, exactly as `.validate()`
does.

## Where it stops today

The engine compares **values**, not metadata: a Polars frame carries no
labels, formats or lengths, so comparing those would need a define.yaml-aware
mode. Keys are mandatory on all three surfaces — there is no positional
matching, and no lookup of keys from define.yaml or the study configuration.
A comparison takes exactly two datasets, never a batch of directories. A SAS
special missing value (`.A` to `.Z` and `._`) in an XPT or SAS7BDAT file reads
as null and its letter is lost, so `.A` against `.R` compares equal, which
SAS PROC COMPARE reports as unequal. The
[compare spec](https://github.com/RealSlimMahdi/fleet-cdisc/issues/99) tracks
what is deliberately left out and what may follow it, including an MCP tool
and a diff view in the editor extension built on the JSON contract above.
