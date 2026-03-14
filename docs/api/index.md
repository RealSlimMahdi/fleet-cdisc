# API Reference

Pymaverse's public API is reachable from a single import:

```python
import pymaverse
```

## Modules

| Module                        | Description                                                                 |
| ----------------------------- | --------------------------------------------------------------------------- |
| [`sdtm`](sdtm.md)             | SDTM namespace — 14 derivation verbs                                        |
| [`adam`](adam.md)             | ADaM BDS namespace — 16 derivation verbs                                    |
| [`adsl`](adsl.md)             | ADSL namespace — 6 patient-level verbs                                      |
| [`occds`](occds.md)           | OCCDS namespace — 5 occurrence verbs                                        |
| [`ta`](ta.md)                 | Therapeutic-area extensions (onco, ophtha, peds, vaccine, metabolic, neuro) |
| [`define_xml`](define_xml.md) | Define-XML generation, validation, spec generation                          |
| [`ct`](ct.md)                 | Controlled terminology loading and validation                               |
| [`core`](core.md)             | `StudyContext`, `PipelineDAG`, exceptions                                   |

## Namespace registration

Importing `pymaverse` registers all namespace extensions on every `polars.DataFrame`.
You never need to import individual submodules:

```python
import pymaverse          # registers df.sdtm, df.adam, df.adsl, df.occds
import polars as pl

pl.DataFrame({"x": [1]}).sdtm  # works immediately
```
