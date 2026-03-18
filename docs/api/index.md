# API Reference

Fleet's public API is reachable from a single import:

```python
import fleet
```

## Modules

| Module                        | Description                                                  |
| ----------------------------- | ------------------------------------------------------------ |
| [`sdtm`](sdtm.md)             | SDTM namespace — 14 derivation verbs                         |
| [`adam`](adam.md)             | ADaM BDS namespace — 22 derivation verbs                     |
| [`adsl`](adsl.md)             | ADSL namespace (`df.adam.adsl`) — 8 patient-level verbs      |
| [`occds`](occds.md)           | OCCDS namespace (`df.adam.occds`) — 5 occurrence verbs       |
| [`ta`](ta.md)                 | Therapeutic-area extensions (`df.adam.<ta>`, including `pk`) |
| [`define_xml`](define_xml.md) | Define-XML generation, validation, spec generation           |
| [`ct`](ct.md)                 | Controlled terminology — CDISC Library API, code generation, validation |
| [`core`](core.md)             | `StudyContext`, `PipelineDAG`, exceptions                    |

## Namespace registration

Importing `fleet` registers two core namespace extensions on every `polars.DataFrame`.
All ADaM sub-structures and TA extensions are accessed as nested properties of `df.adam`:

```python
import fleet          # registers df.sdtm, df.adam
import polars as pl

pl.DataFrame({"x": [1]}).sdtm         # SDTM verbs
pl.DataFrame({"x": [1]}).adam         # ADaM BDS verbs
pl.DataFrame({"x": [1]}).adam.adsl    # ADSL verbs
pl.DataFrame({"x": [1]}).adam.occds   # OCCDS verbs
pl.DataFrame({"x": [1]}).adam.onco    # TA extensions via df.adam.<ta>
pl.DataFrame({"x": [1]}).adam.pk      # PK (pharmacokinetics) verbs
```
