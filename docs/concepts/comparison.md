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
| `2` | The comparison could not run: unreadable file, missing or duplicate keys, no comparable variables, or an `--out` or `--report` path that cannot be written. The reason is on stderr. |

`--keys` is required. `--all` lifts the print limits so every unequal value is
listed. `--report adae_compare.html` writes the
[HTML report](#the-html-report) for a reviewer. `--format json` prints one
JSON document and nothing else on stdout, and `--out differences.parquet`
writes the complete value listing; both are described under
[machine-readable outputs](#machine-readable-outputs). See the
[CLI reference](../getting-started/cli.md#fleet-compare) for the full usage.

## What the report contains

The text report follows the `PROC COMPARE` section order, so a SAS programmer
reads it without a legend:

1. **Data set summary** — name, observations and variables per side, and the keys.
2. **Variables summary** — variables in common, in the base only, in the candidate only, type conflicts, dtype differences.
3. **Observation summary** — matched observations and the key values of the ones found on one side only.
4. **Values summary** — how many values differ, per variable.
5. **Value listing** — every unequal value, grouped per observation so one subject's differences read together, with the base value, the candidate value, and the difference and percent difference for numeric variables.
6. **Verdict** — `EQUAL`, or `NOT EQUAL` followed by the raised flags.

The report object carries the same content as data: `report.listing` is a long
Polars frame (keys, `group`, `variable`, `base`, `candidate`, `difference`,
`percent_difference`) that is never truncated, and `report.flags` replaces
SAS's `SYSINFO` integer with names — `base_only_variables`,
`candidate_only_variables`, `type_conflicts`, `base_only_observations`,
`candidate_only_observations`, `values_differ`. `report.is_equal` is true only
when no flag is raised.

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
3. **Summary** — name, observations and variables per side, the keys, and how many observations matched.
4. **Observations on one side only** — the key values of every observation found only in the base or only in the candidate.
5. **Unequal values** — only the mismatched observations, one collapsible block per differing variable, each row showing the key values, the base value and the candidate value side by side with both cells highlighted, and the difference and percent difference for numeric variables. Blocks start open when there are five or fewer, closed beyond that, so a report over fifty variables stays navigable.

The page is never truncated: every unequal value is on it, whatever
`max_print` the comparison ran with. Once BY groups land, the listing's
`group` column is populated and the unequal values are sectioned per group
with their own counts. For listings beyond a few thousand rows, the
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
| `datasets` | `base` and `candidate`, each with `name`, `rows` and `variables`. |
| `variables` | `common`, `compared`, `base_only`, `candidate_only`, then `type_conflicts` and `dtype_differences` as `{variable, base_dtype, candidate_dtype}` with the dtypes as text. |
| `observations` | `matched`, `base_only`, `candidate_only`, the one-sided key values as `base_only_keys` and `candidate_only_keys` (capped at the per-variable print limit; `truncated` says whether a cap applied). |
| `values` | `per_variable` as `{variable, differences}`, `variables_with_differences`, `observations_with_differences`, `total_differences`. |
| `statistics` | Summary statistics per numeric variable that differs; an empty list until they land. |
| `listing` | `columns`, `rows` (one object per differing value, within the print limits), `shown`, `total` and `truncated`. |
| `settings` | Every option the comparison ran with: `keys`, `max_print`, `base_name`, `candidate_name`. |
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
dtypes, then `group` (`String`, reserved for BY groups), `variable`, `base`
and `candidate` (`String`), `difference` and `percent_difference`
(`Float64`). An equal comparison writes an empty frame with the same schema,
so a downstream `scan_parquet` always finds the documented columns.

## Rules of equality

- **Keys are mandatory and must be unique** on each side. A missing or
  duplicated key stops the compare with a `ComparisonError` that names the side
  and the offending key values, because a broken key is the first thing to fix.
- **Equality is exact.** Null equals null, NaN equals NaN, and null against
  NaN differs, so a missing value that became a NaN is surfaced.
- **Same kind, different dtype is information, not a failure.** An `Int64`
  next to a `Float64`, a `String` next to a `Categorical`, or a `Date` next to
  a `Datetime` is compared by value after casting to a common type and listed
  as a dtype difference. A numeric next to a string is a **type conflict**:
  listed, not compared.
- **Row order and column order are ignored.** A re-sorted or re-ordered
  dataset is not a different dataset.
- **Print limits only affect what is rendered.** By default the text report
  and the JSON document show 50 differences per variable and 500 overall;
  `max_print=None` (or `--all`) shows everything. The listing frame and the
  parquet always hold every difference.

## Gating a pipeline on the outcome

The verb speaks the same failure vocabulary as `.validate()`:

| `on_fail` | Behaviour when the datasets differ |
| --- | --- |
| `"warn"` (default) | Emit a `UserWarning` and continue the chain. |
| `"raise"` | Raise `ComparisonError` (a `FleetError`). |
| `"ignore"` | Continue silently; the report is still on `last_comparison`. |

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

The engine compares by name with exact equality. Tolerances, BY groups,
variable pairs for renamed columns, restriction to a list of variables,
duplicate-key pairing and summary statistics are specified and tracked in the
[compare spec](https://github.com/RealSlimMahdi/fleet-cdisc/issues/99); they
build on the same engine and report without changing what is documented here,
and they only add keys to the JSON document.
