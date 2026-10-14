# TLG Spec Seam — Plan

> **Status:** plan, pre-implementation. Produced from the grilling session of 2026-10-14 on case 1 of the architecture review of 2026-08-30. Nothing here is built. Vocabulary follows `CONTEXT.md` (template, spec, ARD, population filter, dataset filter, prefilter, uncoded). Decision record: `docs/adr/0005-summary-specs-are-the-engine-contract.md`. Timing: first change after the 0.2.0a1 tag.

## Problem statement

Nine `df.tlg.<domain>` modules hold 24 public methods that call one engine, `summarize_ard`, and forward 13 to 16 keyword arguments each. There are 21 such calls in 8 different keyword shapes. The spec already holds every one of those arguments. Two template rules are hidden in method bodies, not in the spec: the fill of uncoded MedDRA or ATC terms with "No Coding Available", and the exclusion of the baseline record on change-from-baseline tables. An analyst cannot see them in the YAML and cannot change them.

The review's figures still hold on branch `chore/pre-alpha-release`: 21 engine calls, 9 modules, 2,863 lines.

## Three families of callers

| Family | Methods | Treatment |
|---|---|---|
| Forwarders | ae.t_summary, ae.t_overview, ae.t_soc_pt, cm.t_summary, cm.t_by_pt, mh.t_summary, vs.t_summary, lb.t_summary, eg.t_summary, eg.t_qtcat, ds.t_summary, ds.t_enrollment, ds.t_deviations | Call the seam |
| Forwarders with a prefilter | lb.t_chg, eg.t_chg, ex.t_summary | Call the seam; the guard becomes the spec's default prefilter |
| Composites | ae.t_severity, ae.t_grade, ae.t_relationship, ds.t_deaths, lb.t_shift, lb.t_abnormal, dm.t_summary | Call the preparation step, then the keyword engine |

The uncoded fill on AE, CM and MH is a transform, not a filter. It is counted with the forwarders.

## Solution

### The seam

One new function in the engine module, next to `summarize_ard`:

```python
summarize_spec(df, spec, *, groupby=None, adsl=None) -> pl.DataFrame
```

It does, in order:

1. Resolve the group column: `groupby`, else `spec.columns[0]`, else `"TRTA"`.
2. `spec.validate_dataframe(df, group_col=...)`.
3. Prepare the frame (see below).
4. Call `summarize_ard` with every argument read from the spec's fields, plus `context` and `nested` read from the spec class.

`summarize_ard` keeps its keyword signature for the composites and for user templates.

### The preparation step

One helper, used by the seam and by the seven composites:

```python
prepare_frame(df, spec) -> pl.DataFrame
```

Order is fixed: uncoded fill, then dataset filter, then prefilter. A composite that calls it passes no `dataset_filter` to the engine afterwards.

### Two new spec fields on the summary base

- `uncoded: Uncoded | None`. `Uncoded` is a Pydantic model with `columns: list[str]` and `label: str`. Default per domain spec class, for example `Uncoded(columns=["AEBODSYS", "AEDECOD"], label="No Coding Available")` on AE, `None` on LB. `uncoded: null` in YAML switches it off.
- `prefilter: str | pl.Expr | None`. Same format and parser as `dataset_filter`. Default per spec class, for example `'pl.col("ABLFL").ne_missing("Y") & pl.col("CHG").is_not_null()'` on the change tables and `'pl.col("PARCAT1") == "OVERALL"'` on exposure. Every column the default names joins that spec's `required_columns`. The docstring of each spec class states the default rule in plain words next to the expression.

### Two class attributes on each spec class

- `context: ClassVar[str]`, for example `"t_mh_summary"`. Replaces `_builder_context` on the namespace class and the literal in each call.
- `nested: ClassVar[bool]`.

They are not YAML fields. One spec class serves one template method, verified on the current tree.

### Builder

Two new verbs, `.uncoded(columns, label)` and `.prefilter(expr)`, mapped to the two fields. The existing consumed-field check applies.

### Spec class homes

A domain's spec classes live in that domain's namespace module. `AESummarySpec`, `AEListingSpec` and `VSSummarySpec` move out of the shared specs module, which keeps only `TLGSpec`, `SummarySpecBase`, `Row`, `Column`, `Statistic`, `GroupPool`, `OverallStat`, the interactive block, `Uncoded`, and `resolve_filter`.

### Module shape after the change

Each namespace module keeps its class and public methods, so `df.tlg.mh.t_summary(groupby=, adsl=, spec=)` is unchanged. A forwarder becomes:

```python
def t_summary(self, *, groupby=None, adsl=None, spec=None):
    return summarize_spec(self._df, spec or MHSummarySpec(), groupby=groupby, adsl=adsl)
```

The `check()` loop over spec rows, identical in nine modules, moves into `TLGSpec.check`.

## Behaviour changes

Only two, and both turn a silent result into a refusal:

1. `lb.t_chg` and `eg.t_chg` on a dataset without ABLFL raise `SchemaError`. Before, baseline records were counted without a message.
2. `ex.t_summary` on a dataset without PARCAT1 raises `SchemaError`. Before, every record was counted.

Every other ARD must be identical.

## Verification

1. Before any code change, write the ARD of every DONE template on the CDISC pilot data to parquet under a fixture directory.
2. After the change, regenerate and compare each pair with the compare verb. Expected verdict: EQUAL for every template. The two refusals above are tested as raised errors, not as differences.
3. Keep the parquet snapshots as a regression fixture.
4. The usual order: `ruff check`, `ruff format --check`, `pytest`, the six examples, `build_llms.py --check` (new verbs and a new public function), docs build.

## Out of scope

- Deleting the per-domain modules or generating methods from the registry. Candidate for a later case, with its own question on IDE autocomplete.
- The ONTRTFL and ABLFL conditionals inside `lb.t_shift` and `lb.t_abnormal`. They are composite logic and keep their current behaviour.
- The listings (`ae.l_listing`, `lb.l_listing`). They do not call the engine.

## Decisions taken on Mahdi's behalf

- Group-column fallback and `validate_dataframe` move into the seam.
- Preparation order: uncoded, dataset filter, prefilter.
- `check()` row loop moves into the spec base class.
- Default prefilter rule stated in plain words in each spec class docstring.
- Seam named `summarize_spec`, helper named `prepare_frame`, model named `Uncoded`.
