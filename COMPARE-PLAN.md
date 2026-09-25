# Fleet Compare — Spec

> **Status:** spec, pre-implementation. Produced from the grilling session of 2026-09-08. Tracker: [RealSlimMahdi/fleet-cdisc#99](https://github.com/RealSlimMahdi/fleet-cdisc/issues/99), labelled `ready-for-agent`. Nothing here is built. Vocabulary follows `CONTEXT.md` (compare, base, candidate, comparison report, keys, variable pair). Decision record: `docs/adr/0002-own-comparison-engine-in-pure-polars.md`.

## Problem Statement

A statistical programmer who has produced a dataset with Fleet has no way to ask the one question every QC step ends with: is this dataset the same as that one, and if not, where exactly does it differ? SAS answers it with PROC COMPARE. Polars answers only "yes" or "no" through `DataFrame.equals`, or raises a unit-test assertion that stops at the first mismatching column and prints both whole columns. The programmer is left writing ad-hoc joins by hand, differently every time, and the reviewer gets no report to sign off on.

The gap shows up in three moments: a QC programmer comparing an independently programmed candidate against the production base; a migration programmer comparing Fleet output against a legacy SAS dataset; and a CI job or an AI agent that needs a pass or fail with a machine-readable list of differences.

## Solution

Fleet gains a compare capability with one engine and three surfaces. The engine pairs two datasets on keys, matches variables by name plus any declared variable pairs, applies exact or tolerance-based equality, and produces a comparison report with the sections a SAS programmer expects: dataset summary, variables summary, observation summary, values summary, value listing and summary statistics.

The report is reachable as a Python object from `fleet.compare(base, candidate, keys=...)`, as a pipeline verb `.compare(base, keys=...)` on the sdtm, adam, adsl and occds namespaces, and as a command `fleet compare base candidate --keys ...`. It renders as plain text in PROC COMPARE order, as a self-contained HTML page that highlights mismatched cells side by side, as JSON for agents and editors, and as a parquet file holding the long value listing. The engine is pure Polars and adds no dependency.

## User Stories

1. As a QC programmer, I want to compare my candidate ADAE against the production ADAE on USUBJID and AESEQ, so that I can prove independent programming reached the same result.
2. As a QC programmer, I want the report to list the variables present only in the base and only in the candidate, so that I catch a dropped or extra column before I look at values.
3. As a QC programmer, I want the report to list observations present only in the base and only in the candidate by their key values, so that I can open the source and see which subject or record was lost or invented.
4. As a QC programmer, I want every differing cell listed with its keys, the variable, the base value, the candidate value and the numeric difference, so that I can fix the right line of code.
5. As a QC programmer, I want the value listing sorted by keys and grouped per observation, so that one subject's differences read together instead of being scattered per variable.
6. As a QC programmer, I want the compare to refuse to run when keys are not unique and tell me which key values are duplicated on which side, so that a broken key is the first thing I fix.
7. As a QC programmer, I want a switch to force the comparison despite duplicate keys, pairing duplicates by their position within each key group and flagging them, so that I can still see the value differences when the duplication is expected.
8. As a QC programmer, I want the terminal report truncated to 50 differences per variable and 500 overall by default, with a flag to print everything, so that a badly broken dataset does not flood my terminal.
9. As a QC programmer, I want to restrict the comparison to a list of variables, so that a work-in-progress candidate can be checked on the columns that are finished.
10. As a QC programmer, I want to declare variable pairs where the base and candidate use different names, on top of the automatic name matching, so that a renamed column is compared rather than reported missing.
11. As a QC programmer, I want summary statistics per numeric variable that differs, so that I can tell a systematic offset from random noise.
12. As a production programmer, I want to add `.compare(base)` at the end of my pipeline chain and keep chaining, so that comparison lives in the same script as the derivation.
13. As a production programmer, I want the chained verb to warn by default, raise on demand, or stay silent, exactly as `.validate()` does, so that I do not learn a second failure vocabulary.
14. As a production programmer, I want the last comparison report kept on the namespace, so that I can gate a script on it without breaking the chain.
15. As a migration programmer, I want to compare a Fleet parquet against a legacy XPT or sas7bdat file directly from the command line, so that I do not write a loader first.
16. As a migration programmer, I want dtype differences between compatible types reported as information rather than failures, so that an Int64 next to a Float64 with identical values does not fail the migration.
17. As a migration programmer, I want an option to ignore trailing whitespace in strings, so that SAS's padded character values compare equal to Fleet's stripped ones.
18. As a migration programmer, I want absolute and relative tolerances for numeric variables, so that floating-point noise between engines does not count as a difference.
19. As a migration programmer, I want null to equal null and NaN to equal NaN, but null and NaN to differ, so that a missing value that became a NaN is surfaced.
20. As a study lead reviewer, I want a self-contained HTML report with only the mismatched observations, base and candidate side by side and changed cells highlighted, so that I can review without a Python environment.
21. As a study lead reviewer, I want the missing variables and missing observations shown at the top of the HTML report, so that structural problems are visible before value details.
22. As a study lead reviewer, I want the HTML report to open one collapsible block per variable that differs, so that a report with fifty differing variables stays navigable.
23. As a reviewer with BY groups, I want the report sectioned per group with its own observation and value counts, so that a difference in one treatment arm stands out.
24. As a reviewer with BY groups, I want groups present on only one side listed, so that a missing arm is reported as such rather than as a thousand missing observations.
25. As a CI pipeline, I want `fleet compare` to exit 0 when the datasets are equal, 1 when they differ, and 2 when the comparison could not run, so that the job status is the verdict.
26. As a CI pipeline, I want the parquet value listing written to a path I choose, so that differences can be archived alongside the build.
27. As an AI agent, I want `fleet compare --format json` to print a stable, documented structure with the verdict, a set of named flags, every summary section and the listing, so that I can reason about differences without parsing prose.
28. As an AI agent, I want the JSON to record the settings used (keys, by, pairs, tolerances, switches), so that I can reproduce or adjust the run.
29. As an editor extension developer, I want the JSON field names to be additive-only within a major version, so that a diff view built on them does not break on a Fleet upgrade.
30. As a Fleet user, I want `fleet compare` to work on LazyFrames and DataFrames alike and to build a single lazy plan, so that comparing large datasets does not materialise both sides twice.
31. As a Fleet user, I want the compare to ignore row order and column order under keyed matching, so that a re-sorted or re-ordered dataset is not reported as different.
32. As a Fleet user, I want a variable listed as a type conflict when it is numeric on one side and string on the other, with its values not compared, so that the report does not drown in false differences.
33. As a Fleet user, I want the report to name the dataset on each side when it knows it, so that a report over two files says which is which.
34. As a Fleet user, I want the verb to reject an unknown `on_fail` value with the same error class as `.validate()`, so that mistakes fail fast.
35. As a Fleet maintainer, I want one engine function tested exhaustively and the three surfaces tested as thin callers, so that behaviour is defined in one place.
36. As a Fleet maintainer, I want the new verb picked up by the API-shape sweep with one positional parameter, so that it conforms to the verb grammar without a grandfather entry.
37. As a Fleet maintainer, I want the concepts page, the CLI reference, `STRUCTURE.md` and `llms.txt` updated in the same change, so that the feature is discoverable by humans and agents.
38. As a Fleet maintainer, I want no new runtime dependency and no pandas or numpy import anywhere on the compare path, so that the pure-Polars promise holds.

## Implementation Decisions

### Package and surfaces

- A new package `fleet.comparison` holds the engine, the report model and the four renderers. It is named after the noun because a package named `compare` would shadow the public function.
- The public function is `fleet.compare(base, candidate, *, keys, by=None, pairs=None, variables=None, abs_tol=0.0, rel_tol=0.0, ignore_trailing_whitespace=False, allow_duplicates=False, max_print=50, base_name=None, candidate_name=None)`. It accepts DataFrames or LazyFrames on either side and returns a comparison report. It never raises on differences.
- The pipeline verb `compare(base, *, keys, ..., on_fail="warn")` is added to the shared verbs mixin, so sdtm, adam, adsl and occds receive it at once. The chain is the candidate, the argument is the base. The verb collects the chain, calls the engine, stores the report on the namespace as `last_comparison`, applies `on_fail` with the same three values and the same error class family as `validate`, and returns a namespace copy so the chain continues.
- The CLI verb is `fleet compare BASE CANDIDATE --keys K1,K2 [--by ...] [--pairs BASE=CAND,...] [--variables ...] [--abs-tol] [--rel-tol] [--ignore-trailing-whitespace] [--allow-duplicates] [--all] [--report out.html] [--out differences.parquet] [--format text|json]`. Files load through the existing raw-data loader, so every format it supports is accepted, including XPT and sas7bdat through the `io` extra. Keys are required; the command does not compute without them and does not look them up anywhere.
- Exit codes: 0 equal, 1 differences, 2 comparison impossible. Duplicate keys without the override, unreadable files, keys absent from either side, and a `--variables` list of keys only are all exit 2. A compare that checks no values keeps its verdict and warns (ADR-0004).

### Matching

- Observations pair on the keys through an inner join; base-only and candidate-only observations come from the two anti-joins. BY variables are prepended to the keys automatically and additionally section the report; groups present on one side only are listed. The verdict stays global.
- Duplicate keys on either side stop the compare with an error listing the duplicated key values per side. With `allow_duplicates`, a position-within-group index is added to the keys, duplicates pair in order, and the observation summary carries duplicate counts per side and a warning line.
- Variables match by name. `pairs` maps base names to candidate names and is applied on top of name matching. `variables` restricts the universe, in base names. A paired base variable whose candidate name is absent is reported as missing from the candidate.
- Variables are classified into kinds: numeric (integers, floats, decimals), string (string, categorical, enum), temporal (date, datetime, time, duration), boolean, other. Two variables of the same kind but different dtypes are compared by value after casting to a common supertype and listed as a dtype difference in the variables summary, which is information and never a failure. Two variables of different kinds are a type conflict: listed, not compared. Kind "other" is compared only when dtypes are identical.

### Equality

- Exact by default. With tolerances, a numeric pair differs when the absolute difference exceeds `max(abs_tol, rel_tol × |base|)`. The relative tolerance anchors on the base because the base is the reference; this deliberately follows SAS rather than Polars' testing helper, which anchors on the right-hand frame.
- Null equals null. NaN equals NaN. Null versus NaN differs. Exact and tolerant equality promise the same four answers, and no tolerance changes one of them:

  | `l` | `r` | Verdict |
  | --- | --- | --- |
  | `null` | `null` | equal |
  | `NaN` | `NaN` | equal |
  | `NaN` | `1.0` | differs |
  | `1.0` | `NaN` | differs |

- The null half is settled once per variable, outside the equality mode, so no mode has to carry it:

  ```python
  neq = pl.when(l.is_null() & r.is_null()).then(False).otherwise(neq.fill_null(True))
  ```

  Polars' `!=` yields false for NaN against NaN and null for null against anything, so exact equality needs nothing further: `fill_null(True)` is what makes null versus non-null, including NaN, a difference, and the outer `when` is what keeps two nulls equal.
- Tolerant equality needs NaN settled *before* the subtraction, because Polars orders NaN as the largest float: `NaN - NaN` is NaN and `NaN > tol` is true, so an unguarded `(l - r).abs() > tol` reports NaN against NaN as differing under every tolerance, contradicting the second row above. The guard restores it:

  ```python
  neq = (
      pl.when(l.is_nan() & r.is_nan())
      .then(False)
      .when(l.is_nan() | r.is_nan())
      .then(True)
      .otherwise((l - r).abs() > tol)
  )
  ```

  The second branch states the other half of the rule, that a NaN is never within a tolerance of a number. The same ordering happens to give it anyway; it is written out so the guarantee does not rest on how Polars chooses to order NaN.
- Strings compare exactly; `ignore_trailing_whitespace` strips the right side of both before comparing.
- Row order and column order are ignored. Listings are always sorted by keys, BY variables first.

### Comparison report

- The report is a frozen dataclass in the style of `ValidationResult`, holding: dataset summary (name, rows, variables per side), variables summary (common, base-only, candidate-only, type conflicts, dtype differences), observation summary (matched, base-only, candidate-only, duplicates per side, per BY group when applicable), values summary (per common variable: number of differing observations), the value listing as a Polars frame, summary statistics as a Polars frame, the set of named flags, the settings used, and the Fleet version.
- Named flags replace SAS's SYSINFO integer: `base_only_variables`, `candidate_only_variables`, `type_conflicts`, `base_only_observations`, `candidate_only_observations`, `values_differ`, `duplicate_keys`, `base_only_groups`, `candidate_only_groups`. The verdict `is_equal` is true only when the flag set is empty. Dtype differences do not raise a flag.
- The value listing is a long frame: keys and BY variables, variable, base value and candidate value cast to string, difference and percent difference for numeric kinds, null otherwise. Percent difference is `(candidate − base) / base × 100` and null when the base is zero or null. The full listing is always computed lazily; `max_print` only governs the text renderer.
- Summary statistics, for numeric variables with at least one difference: the count of differing observations, and for base, candidate, difference and percent difference each the n, mean, standard deviation, minimum and maximum over matched observations where both sides are non-null. Strings get only the count of differences. No correlation, no R squared, no t statistic.
- Renderers are methods on the report: `print_report()` and `to_text()` for the terminal in PROC COMPARE section order with the listing per observation; `save_html_report(path)` producing one self-contained page with no external assets, structural findings as chips at the top, side-by-side mismatched observations with changed cells highlighted, one collapsible block per differing variable; `to_json()` and `save_json(path)`; `save_listing(path)` for the parquet.
- The JSON contract is additive-only within a major version, in the spirit of ADR 0001, because the editor extension will consume it. Field names mirror the report attributes. The listing inside the JSON is truncated with a `truncated` marker; the parquet is never truncated.

### Housekeeping

- Export `compare` from the package root. Add a concepts page for comparison, extend the CLI reference, add the package row to `STRUCTURE.md`, and rebuild `llms.txt` since a verb and a command are added.
- The verb has one positional parameter, so the API-shape sweep accepts it without a grandfather entry.
- Logging goes through the same logger convention as validation so the terminal report can be silenced or captured.

## Testing Decisions

A good test builds two small frames in memory, calls the engine, and asserts on the comparison report: its flags, its verdict, the rows of its summary frames and the rows of its listing. It never asserts on join strategy, expression shape or internal column names, and never on HTML markup structure beyond the presence of the values it must show.

Seams, highest first:

1. **The engine function** is the primary seam and carries nearly every behaviour: keyed matching, anti-join lists, BY sectioning, duplicates with and without the override, variable pairs and restriction, kind classification and type conflicts, exact and tolerant numerics with the base-anchored relative rule, null and NaN semantics, string whitespace, order insensitivity, summary statistics, flags and verdict, LazyFrame input. One test module, table-driven where the cases are enumerable.
2. **The renderers** are tested through the report object: text output contains the section headers in order and honours `max_print`; JSON round-trips through the standard library and carries the documented keys; the parquet listing reloads with the documented schema; HTML contains the base and candidate values of every mismatched cell and no external references.
3. **The CLI** is tested in-process by calling the entry point with an argument list and capturing output and `SystemExit`, as the existing CLI tests do: exit codes 0, 1 and 2, required keys, each flag reaching the engine, files of at least parquet and CSV.
4. **The verb** is tested through a two-step chain on the sdtm and adam namespaces: `last_comparison` populated, `on_fail` warn, raise and ignore, the chain continuing after the verb, and the unknown-value error.

Prior art: the CLI tests for exit codes and captured output; the validation verb tests for `on_fail` and `last_validation`; the API-shape sweep, which will cover the new verb automatically; the TLG registry tests, which compare against golden frames with tolerances and show the fixture style; the study fixtures for small CDISC-shaped frames.

SAS parity is asserted against hand-built fixtures that encode the documented PROC COMPARE semantics (missing equals missing, the tolerance formula, the listing counts), because no SAS engine runs in CI.

## Out of Scope

- Metadata comparison: labels, formats, lengths. A Polars frame carries none of them. A later define.yaml-aware mode may add it.
- Positional matching without keys. Keys are mandatory on all three surfaces.
- Looking up keys from define.yaml or the study configuration. The user always states them.
- Correlation, R squared and t statistics from SAS's STATS table.
- A diff view in the VS Code extension. It belongs to the extension backlog and consumes the JSON contract this spec makes stable.
- An MCP tool wrapping the compare. A natural follow-up once the JSON contract has shipped.
- Comparing more than two datasets, or two directories in batch.
- Streaming the HTML renderer for listings beyond a few thousand rows. The parquet output is the path for very large listings.

## Further Notes

- A feasibility prototype ran during exploration: keyed matching, anti-joins, per-variable tolerance flags, the long listing and the flag set in about eighty lines of expressions, comparing one million rows by twenty variables in well under a second on a laptop. It lives in the session scratchpad and should be committed to a `prototype/compare` branch as the primary source for the implementation ticket.
- The ecosystem survey behind ADR 0002: Polars offers only `DataFrame.equals` and the unit-test asserts; upstream issue pola-rs/polars#14373 is accepted but unimplemented since 2024; datacompy hard-requires pandas and numpy; diffly is pure Polars but key-only and adds `rich`; pl_compare is unmaintained.
- The PHUSE paper's stat-programmer workflow gains its QC step from this feature: the traditional `adae_qc.sas` becomes a `.compare(base)` line at the end of the candidate chain.
