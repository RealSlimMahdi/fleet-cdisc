# TLG Namespace

The `df.tlg` namespace produces **Tables, Listings, and Graphs** from ADaM
datasets. Nine domain sub-namespaces expose domain-specific summary and listing
methods, and each mirrors an inline fluent builder ↔ YAML-spec workflow through
an open **template registry**.

The `fleet.tlg.render` sub-module converts ARD DataFrames into pharma-style
**HTML tables**, **RTF** and **PDF** documents (RTF is built-in; PDF via
WeasyPrint), editable **PPTX** slides, and supports pagination (`paginate` /
`paginate_listing`) and **HTML injection** into wrapper templates for embedding
in sponsor portals or Quarto documents.

## Registration

```python
import fleet  # registers df.tlg alongside df.sdtm and df.adam
import polars as pl

df.tlg.ae  # AE overview, SOC/PT, severity, grade, relationship, listing
df.tlg.vs  # Vital-signs summary
df.tlg.catalog()  # every registered template as a DataFrame
```

## Template registry

Every table/listing is a registered **template**: an id, its CDISC class, the
namespace method that builds it, and its output type. `df.tlg.catalog()` (or
`fleet.tlg.catalog()`) returns the live catalog. The `fleet tlg list` CLI command
prints the same table.

<!-- Generated: python -c "import fleet, fleet.tlg as t;
     print(t.catalog().select('id','title','cdisc_class','namespace','method','output_type').sort(['namespace','id']))" -->

| id       | title                                     | cdisc_class   | namespace | method           | output_type |
| -------- | ----------------------------------------- | ------------- | --------- | ---------------- | ----------- |
| `ael01`  | Listing of Adverse Events                 | events        | `ae`      | `l_listing`      | listing     |
| `aet01`  | Overview of Adverse Events                | events        | `ae`      | `t_overview`     | table       |
| `aet02`  | AEs by SOC and PT                         | events        | `ae`      | `t_soc_pt`       | table       |
| `aet03`  | AEs by Greatest Severity                  | events        | `ae`      | `t_severity`     | table       |
| `aet04`  | Adverse Events by Highest NCI CTCAE Grade | events        | `ae`      | `t_grade`        | table       |
| `aet05`  | AEs by SOC and Relationship to Study Drug | events        | `ae`      | `t_relationship` | table       |
| `cmt01a` | Concomitant Medications by Class          | interventions | `cm`      | `t_summary`      | table       |
| `cmt02`  | Concomitant Meds by PT                    | interventions | `cm`      | `t_by_pt`        | table       |
| `dmt01`  | Demographic Characteristics               | demographics  | `dm`      | `t_summary`      | table       |
| `dst01`  | Subject Disposition                       | disposition   | `ds`      | `t_summary`      | table       |
| `dtht01` | Deaths Summary                            | events        | `ds`      | `t_deaths`       | table       |
| `ent01`  | Enrollment by Site                        | disposition   | `ds`      | `t_enrollment`   | table       |
| `pdt01`  | Protocol Deviations                       | disposition   | `ds`      | `t_deviations`   | table       |
| `egt01`  | ECG Summary                               | findings      | `eg`      | `t_summary`      | table       |
| `egt03`  | ECG Change from Baseline                  | findings      | `eg`      | `t_chg`          | table       |
| `egt05`  | QTc Category Counts                       | findings      | `eg`      | `t_qtcat`        | table       |
| `ext01`  | Exposure Summary                          | interventions | `ex`      | `t_summary`      | table       |
| `lbl01`  | Listing of Laboratory Abnormalities       | findings      | `lb`      | `l_listing`      | listing     |
| `lbt01`  | Laboratory Results Summary                | findings      | `lb`      | `t_summary`      | table       |
| `lbt02`  | Lab Mean Change from Baseline             | findings      | `lb`      | `t_chg`          | table       |
| `lbt03`  | Lab Shift Table                           | findings      | `lb`      | `t_shift`        | table       |
| `lbt04`  | Lab Abnormalities                         | findings      | `lb`      | `t_abnormal`     | table       |
| `mht01`  | Medical History                           | events        | `mh`      | `t_summary`      | table       |
| `vst01`  | Vital Signs Summary                       | findings      | `vs`      | `t_summary`      | table       |

`lbt04` reads the ANRIND codes of the directions from `low_values` and
`high_values` (default `LOW`/`LOW LOW`, `HIGH`/`HIGH HIGH`). When ANRIND
holds codes such as `H` and `L`, set them in the spec
(`LBAbnormalSpec(low_values=["L"], high_values=["H"])`): the table stops
when no code of the data is in either list. A cell prints `n/N (%)`, with
N the subjects at risk in that direction.

## Dual-mode API

Fleet TLG supports two equivalent paths to the same ARD output — plus a
YAML-spec front door that reproduces a table from a file alone.

=== "Inline builder"

    ```python
    ard = (
        adae.tlg.ae.population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
        .by("TRTA")
        .header_rows(
            [
                OverallStat(label="Subjects with any AE"),
                OverallStat(label="Serious AEs", filter=pl.col("AESER") == "Y"),
            ]
        )
        .rows(["AEBODSYS", "AEDECOD"])
        .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
        .pools([GroupPool(label="Total", arms="*")])
        .to_ard()
    )
    ```

=== "Spec object"

    ```python
    spec = AESummarySpec(
        adsl_filter=pl.col("SAFFL") == "Y",
        header_rows=[
            OverallStat(label="Subjects with any AE"),
            OverallStat(label="Serious AEs", filter=pl.col("AESER") == "Y"),
        ],
        pools=[GroupPool(label="Total", arms="*")],
    )
    ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
    ```

=== "YAML spec file"

    ```python
    import fleet.tlg as tlg

    spec = tlg.load_spec("examples/tlg_specs/aet01.yaml")
    ard = tlg.run_spec(spec, adae, adsl=adsl)
    ```

Listings work through the same dual API: `l_listing(spec=...)` or the builder's
`.columns([...]).sort_by([...]).to_listing()`.

---

## Spec runner — YAML as a workflow

`load_spec` reads a YAML file, resolves its `template:` id through the registry,
and returns the right spec model; `run_spec` dispatches the spec to the
template's namespace method (or a user-registered function). `spec_schema`
returns a template's JSON schema for editor auto-complete, and
`register_template` adds a study-specific template to the open registry.

::: fleet.tlg.load_spec
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.run_spec
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.spec_schema
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.register_template
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.catalog
options:
show_root_heading: true
heading_level: 4

---

## Root namespace

::: fleet.tlg.TLGNamespace
options:
show_root_heading: true
heading_level: 3
members_order: source
filters: ["!^_"]

---

## Domain sub-namespaces

### AE — `df.tlg.ae`

::: fleet.tlg.AETLGNamespace
options:
show_root_heading: true
heading_level: 4
members_order: source
filters: ["!^_"]

### VS — `df.tlg.vs`

::: fleet.tlg.VSTLGNamespace
options:
show_root_heading: true
heading_level: 4
members_order: source
filters: ["!^_"]

### LB — `df.tlg.lb`

::: fleet.tlg.LBTLGNamespace
options:
show_root_heading: true
heading_level: 4
members_order: source
filters: ["!^_"]

### EG — `df.tlg.eg`

::: fleet.tlg.EGTLGNamespace
options:
show_root_heading: true
heading_level: 4
members_order: source
filters: ["!^_"]

### CM — `df.tlg.cm`

::: fleet.tlg.CMTLGNamespace
options:
show_root_heading: true
heading_level: 4
members_order: source
filters: ["!^_"]

### EX — `df.tlg.ex`

::: fleet.tlg.EXTLGNamespace
options:
show_root_heading: true
heading_level: 4
members_order: source
filters: ["!^_"]

### DM — `df.tlg.dm`

::: fleet.tlg.DMTLGNamespace
options:
show_root_heading: true
heading_level: 4
members_order: source
filters: ["!^_"]

### DS — `df.tlg.ds`

::: fleet.tlg.DSTLGNamespace
options:
show_root_heading: true
heading_level: 4
members_order: source
filters: ["!^_"]

### MH — `df.tlg.mh`

::: fleet.tlg.MHTLGNamespace
options:
show_root_heading: true
heading_level: 4
members_order: source
filters: ["!^_"]

---

## Fluent builder

::: fleet.tlg.TLGBuilder
options:
show_root_heading: true
heading_level: 3
members_order: source
filters: ["!^_"]

---

## Spec models

!!! tip "Inline builder ↔ YAML spec — same surface, two front doors"
Every field on the spec models below is also settable via the fluent
[`TLGBuilder`][fleet.tlg.TLGBuilder]. The cross-references in each
field's description (e.g. _Set inline via [`TLGBuilder.rows()`]…_)
link straight to the matching builder method, so reviewers can
move freely between the YAML and Python views without grepping.

    The descriptions are sourced from `pydantic.Field(description=...)`
    on the spec classes — the base classes and building blocks in
    [`src/fleet/tlg/_specs.py`](https://github.com/RealSlimMahdi/fleet-cdisc/blob/main/src/fleet/tlg/_specs.py),
    each domain's specs in its own namespace module — so docs, IDE
    tooltips, and JSON-schema exports stay in sync automatically.

!!! note "The spec is the engine contract"
    A summary spec carries every argument the shared engine takes, three
    record rules included: `uncoded` (the label a null coding term gets),
    `missing` (the "Missing" row of a null category, ADR-0038)
    and `prefilter` (the template's own record filter, applied after
    `dataset_filter`; every column it names is required). Each template
    sets its own defaults and `null` switches a rule off. A row field
    that the data does not hold stops the table. Decision record:
    [ADR-0005](https://github.com/RealSlimMahdi/fleet-cdisc/blob/main/docs/adr/0005-summary-specs-are-the-engine-contract.md).

!!! note "Two arm columns"
    ADaMIG puts the actual arm on ADSL as `TRT01A` and on ADAE as `TRTA`.
    Name the ADSL arm with `adsl_group_col` (YAML), `population(adsl,
    group_col="TRT01A")` (builder) or `--adsl-groupby TRT01A` (CLI). In a
    crossover the N is then the period 1 count. The CLI, the explorer and
    the MCP tool group by the spec's `columns:` when it declares one.

### TLGSpec (base)

::: fleet.tlg.TLGSpec
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]

### SummarySpecBase

::: fleet.tlg.SummarySpecBase
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]

### AESummarySpec

::: fleet.tlg.AESummarySpec
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]

### AEListingSpec

::: fleet.tlg.AEListingSpec
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]

### VSSummarySpec

::: fleet.tlg.VSSummarySpec
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]

### OverallStat

::: fleet.tlg.OverallStat
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]

### Uncoded

::: fleet.tlg.Uncoded
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]
### MissingLevel

::: fleet.tlg.MissingLevel
options:
show_root_heading: true
heading_level: 4
filters: ["!^\_"]
---

## Building blocks

### Statistic

::: fleet.tlg.Statistic
options:
show_root_heading: true
heading_level: 4

### GroupPool

::: fleet.tlg.GroupPool
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]

### Row

::: fleet.tlg.Row
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]

### Column

::: fleet.tlg.Column
options:
show_root_heading: true
heading_level: 4
filters: ["!^_"]

---

## Engine seam

Every summary table is one call on the shared engine. The forwarding
tables call `summarize_spec(df, spec, groupby=, adsl=)`, which resolves
the group column, validates the frame, runs `prepare_frame` (uncoded
rule, dataset filter, prefilter, in that order) and reads every other
engine argument from the spec. Composite tables, such as deaths and the
lab shift table, call `prepare_frame` and then `summarize_ard` with
keyword arguments. User-registered templates may call either.

::: fleet.tlg
options:
show_root_heading: false
heading_level: 3
members:

- summarize_spec
- prepare_frame
- summarize_ard

---

## ARD utilities

The ARD keeps every statistic unrounded. `format_ard` and `apply_fmt_fn`
round only for display. A tie rounds half away from zero, as SAS `ROUND`
and the {cards} default: 5/16 = 31.25 % prints `31.3` at `xx.x`. A value
that rounds to zero prints `0.0`, never `-0.0` (ADR-0037).

<!-- mkdocstrings: reference public re-exports, not the private _ard module -->

::: fleet.tlg
options:
show_root_heading: false
heading_level: 3
members:

- ARD_SCHEMA
- ARD_COLUMNS
- ARD_COLUMN_ORDER
- ARD_REQUIRED_COLUMNS
- ARD_GROUP_COLUMNS
- build_ard_row
- validate_ard
- format_ard
- apply_fmt_fn
- default_fmt_fn

---

## Render sub-module

The `fleet.tlg.render` sub-module converts ARD DataFrames into display-ready
artifacts: HTML tables, PDF documents, and editable PPTX slide decks.

### RenderMetadata

::: fleet.tlg.render.RenderMetadata
options:
show_root_heading: true
heading_level: 4

### TableModel

::: fleet.tlg.render.TableModel
options:
show_root_heading: true
heading_level: 4

### ListingModel

::: fleet.tlg.render.ListingModel
options:
show_root_heading: true
heading_level: 4

### Shaping functions

::: fleet.tlg.render.ard_to_table_model
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.render.listing_to_model
options:
show_root_heading: true
heading_level: 4

### HTML renderer

::: fleet.tlg.render.html.render_html
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.render.html.render_listing_html
options:
show_root_heading: true
heading_level: 4

### RTF renderer

Built-in (no optional dependency). `paginate` / `paginate_listing` split a long
table across pages for RTF/PDF output.

::: fleet.tlg.render.rtf.render_rtf
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.render.rtf.render_listing_rtf
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.render.paginate
options:
show_root_heading: true
heading_level: 4

### PDF renderer

::: fleet.tlg.render.pdf.render_pdf
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.render.pdf.render_listing_pdf
options:
show_root_heading: true
heading_level: 4

### PPTX renderer

::: fleet.tlg.render.slides.render_pptx
options:
show_root_heading: true
heading_level: 4

::: fleet.tlg.render.slides.render_listing_pptx
options:
show_root_heading: true
heading_level: 4
