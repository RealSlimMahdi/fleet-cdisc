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
| `2` | The comparison could not run: unreadable file, missing or duplicate keys, no comparable variables. The reason is on stderr. |

`--keys` is required. `--all` lifts the print limits so every unequal value is
listed. See the [CLI reference](../getting-started/cli.md#fleet-compare) for
the full usage.

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
- **Print limits only affect the text.** By default the report prints 50
  differences per variable and 500 overall; `max_print=None` (or `--all`)
  prints everything. The listing frame always holds every difference.

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
duplicate-key pairing, summary statistics, and the HTML, JSON and parquet
renderers are specified and tracked in the
[compare spec](https://github.com/RealSlimMahdi/fleet-cdisc/issues/99); they
build on the same engine and report without changing what is documented here.
