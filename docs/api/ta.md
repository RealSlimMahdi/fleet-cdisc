# Therapeutic-Area Extensions

Fleet ships six TA extensions accessible via `df.adam.<ta>`, mirroring the [admiral TA packages](https://pharmaverse.github.io/admiral/).

Every TA namespace inherits the shared ADaM verbs, so autocomplete shows about
45 names. To list only the verbs a TA namespace adds, filter `verbs()` on its
origin:

```python
import fleet
import polars as pl

df = pl.DataFrame({"x": [1]})
df.adam.vaccine.verbs().filter(pl.col("origin") == "adam.vaccine")
```

A TA verb is a **clinical verb**: it encodes a rule a programmer would otherwise
copy from a standard or a SAP, and its docstring cites that rule under
`References`. A new clinical verb must pass the admission bar of
[ADR-0009](../adr/0009-an-admission-bar-for-clinical-verbs.md): if it were
deleted, a programmer who rewrites it inline must be able to get a wrong answer,
not only type more.

## Oncology — `df.adam.onco`

::: fleet.adam.OncoNamespace
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## Ophthalmology — `df.adam.ophtha`

::: fleet.adam.OphthaNamespace
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## Pediatrics — `df.adam.peds`

::: fleet.adam.PedsNamespace
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## Vaccine — `df.adam.vaccine`

::: fleet.adam.VaccineNamespace
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## Metabolic — `df.adam.metabolic`

::: fleet.adam.MetabolicNamespace
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## Neuroscience — `df.adam.neuro`

::: fleet.adam.NeuroNamespace
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## Pharmacokinetics — `df.adam.pk`

::: fleet.adam.PKNamespace
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## Time-to-event — `df.adam.tte`

::: fleet.adam.TTENamespace
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

::: fleet.adam.tte
options:
show_root_heading: true
heading_level: 3
members_order: source
show_source: false
