# TLG Namespace

The `df.tlg` namespace produces **Tables, Listings, and Graphs** from ADaM
datasets. Sub-namespaces expose domain-specific summary methods and an
inline fluent builder that mirrors the spec-driven workflow.

The `fleet.tlg.render` sub-module converts ARD DataFrames into pharma-style
**HTML tables**, **PDF documents** (via WeasyPrint), and supports **HTML
injection** into wrapper templates for embedding in sponsor portals or Quarto
documents.

## Registration

```python
import fleet          # registers df.tlg alongside df.sdtm and df.adam
import polars as pl

df.tlg.ae             # AE summary tables and listings
df.tlg.vs             # Vital-signs summary tables
```

## Dual-mode API

Fleet TLG supports two equivalent paths to the same ARD output:

=== "Inline builder"

    ```python
    ard = (
        adae.tlg.ae
        .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
        .by("TRTA")
        .header_rows([
            OverallStat(label="Subjects with any AE"),
            OverallStat(label="Serious AEs", filter=pl.col("AESER") == "Y"),
        ])
        .rows(["AEBODSYS", "AEDECOD"])
        .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
        .pools([GroupPool(label="Total", arms="*")])
        .to_ard()
    )
    ```

=== "Spec-driven"

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

---

## Root namespace

::: fleet.tlg.TLGNamespace
options:
show*root_heading: true
heading_level: 3
members_order: source
filters: ["!^*"]

---

## AE sub-namespace — `df.tlg.ae`

::: fleet.tlg.AETLGNamespace
options:
show*root_heading: true
heading_level: 3
members_order: source
filters: ["!^*"]

---

## VS sub-namespace — `df.tlg.vs`

::: fleet.tlg.VSTLGNamespace
options:
show*root_heading: true
heading_level: 3
members_order: source
filters: ["!^*"]

---

## Fluent builder

::: fleet.tlg.TLGBuilder
options:
show*root_heading: true
heading_level: 3
members_order: source
filters: ["!^*"]

---

## Spec models

### TLGSpec (base)

::: fleet.tlg.TLGSpec
options:
show*root_heading: true
heading_level: 4
filters: ["!^*"]

### AESummarySpec

::: fleet.tlg.AESummarySpec
options:
show*root_heading: true
heading_level: 4
filters: ["!^*"]

### AEListingSpec

::: fleet.tlg.AEListingSpec
options:
show*root_heading: true
heading_level: 4
filters: ["!^*"]

### VSSummarySpec

::: fleet.tlg.VSSummarySpec
options:
show*root_heading: true
heading_level: 4
filters: ["!^*"]

### OverallStat

::: fleet.tlg.OverallStat
options:
show*root_heading: true
heading_level: 4
filters: ["!^*"]

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
show*root_heading: true
heading_level: 4
filters: ["!^*"]

### Row

::: fleet.tlg.Row
options:
show*root_heading: true
heading_level: 4
filters: ["!^*"]

### Column

::: fleet.tlg.Column
options:
show*root_heading: true
heading_level: 4
filters: ["!^*"]

---

## ARD utilities

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
