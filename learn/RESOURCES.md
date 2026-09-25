# Polars (in the context of Fleet) Resources

Every link below was fetched and read before it was listed. Nothing here is from
memory. Checked against **Polars 1.41.0**, the version pinned in this repo.

## Knowledge

### Primary: the Polars user guide

- [Expressions and contexts](https://docs.pola.rs/user-guide/concepts/expressions-and-contexts/)
  The single most important page for Fleet. Defines an expression as "a lazy
  representation of a data transformation", and names the four contexts that run one:
  `select`, `with_columns`, `filter`, `group_by`. Also covers expression expansion.
  Use for: anything about why Fleet functions return `pl.Expr` instead of a DataFrame.
- [Lazy API](https://docs.pola.rs/user-guide/concepts/lazy-api/)
  Why `collect()` exists, and what predicate pushdown and projection pushdown do.
  Shows `explain()` output. Use for: understanding Fleet's `_lazy` attribute and
  why `to_frame()` is the only place work happens.
- [Window functions](https://docs.pola.rs/user-guide/expressions/window-functions/)
  The `over()` function, and the `mapping_strategy` options `group_to_rows`,
  `explode`, `join`. States the rule plainly: `group_by` returns one row per group,
  `over` returns one row per input row. Use for: reading `baseline()` and any
  `.over(["USUBJID", "PARAMCD"])` in Fleet.
- [Missing data](https://docs.pola.rs/user-guide/expressions/missing-data/)
  `null` versus `NaN`, the validity bitmap, `fill_null` strategies. Confirms that
  aggregations such as `mean` and `sum` skip `null` but propagate `NaN`.
  Use for: every question about SAS missing values versus Polars nulls.
- [Aggregation](https://docs.pola.rs/user-guide/expressions/aggregation/)
  Use for: `group_by().agg()` patterns, the shape of the result.
- [Data types and structures](https://docs.pola.rs/user-guide/concepts/data-types-and-structures/)
  Use for: dtype questions, and the floating point section behind `NaN`.
- [User guide index](https://docs.pola.rs/)
  Entry point when the topic is not yet known.

### Primary: the Python API reference

- [Python API reference](https://docs.pola.rs/api/python/stable/reference/index.html)
  The authoritative signature list. Use for: exact arguments and defaults. Always
  check here before trusting an example, including an example from a lesson here.
- [`Expr.over`](https://docs.pola.rs/api/python/stable/reference/expressions/api/polars.Expr.over.html)
  Use for: the full `over()` signature, including `mapping_strategy`.

### Primary: the source

- [pola-rs/polars on GitHub](https://github.com/pola-rs/polars)
  39.7k stars, 749 contributors, MIT licensed. Use for: settling a behaviour
  question that the docs leave open, by reading the Rust or Python source.
- [Polars issue tracker](https://github.com/pola-rs/polars/issues)
  Use for: checking whether surprising behaviour is a known bug before assuming
  a misunderstanding.

### Primary: Fleet itself

The best Polars textbook available for this mission is the repo this file sits in.

- `src/fleet/adam/utils.py`
  Pure expression factories. Every function returns `pl.Expr` and touches no data.
  The densest, most readable Polars in the repo. Use for: `when/then/otherwise`,
  `over()`, `cast()`, `alias()`, null guards.
- `src/fleet/core/_verb_mixin.py`
  `_chain()`, `_materialise_then()`, `to_frame()`. Use for: how Fleet holds a lazy
  plan and when it collects.
- `src/fleet/sdtm/utils.py`
  Date and datetime parsing, `parse_expression()`. Use for: string and temporal
  expression work.
- `examples/`
  Six runnable pipelines, all of which must pass after any change. Use for: seeing
  a full SDTM to ADaM flow end to end.

## Wisdom (Communities)

- [Polars Discord](https://discord.gg/4UfP5cfBE7)
  The official server, linked from the project README and the pola.rs footer.
  Core maintainers are present. Use for: "is this the idiomatic way to express X",
  and performance questions where the answer depends on the engine.
- [Polars GitHub issues and discussions](https://github.com/pola-rs/polars/issues)
  Use for: reproducible behaviour disputes. High signal, heavily triaged.

Note: no preference against joining communities has been expressed. Ask before
recommending any paid course or conference.

## Gaps

Areas the mission needs, where no trusted resource has been verified yet:

- **Pharma-specific Polars.** No verified community or reference exists for CDISC
  work in Polars. `pharmaverse` and PHUSE are R and SAS shaped. This gap is part
  of why Fleet exists. Needs a dedicated search session.
- **SAS to Polars translation table.** Nothing verified. The `RETAIN`, `BY`-group,
  `LAG`, and `FIRST.`/`LAST.` idioms have Polars equivalents, but no trusted
  published mapping has been found. Build one as a reference card instead.
- **Polars migration guides.** The user guide has a "Migrating" section in its
  navigation, but the specific pages have not been fetched and checked. Do not cite
  them until they have been.
- **A book.** No Polars book has been verified. Do not recommend one from memory.
