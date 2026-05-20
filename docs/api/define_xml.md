# Define-XML

Fleet generates and validates CDISC Define-XML 2.1 documents from `define.yaml` specs.

## DefineXMLGenerator

::: fleet.define_xml.DefineXMLGenerator
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## DefineSpecGenerator

::: fleet.define_xml.DefineSpecGenerator
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

### Method enrichment (`enrich_methods=True`)

When constructed with `enrich_methods=True`, `DefineSpecGenerator` walks each
variable's `derivation:` block and emits a Define-XML 2.1 `<MethodDef>` element
linked to the corresponding `<ItemDef>` via a `MethodOID` attribute. The
`<Description>` of the method is taken from the **Python docstring** of the
referenced verb (`algorithm:`) or callable (`callable:` — full dotted path),
and a `<FormalExpression Context="Python/Fleet">` records the verb signature.

This makes the docstring of every Fleet verb the single source of truth for
the regulatory description in Define-XML — no duplicated prose.

```python
from fleet import DefineSpecGenerator

DefineSpecGenerator(
    "examples/cdiscpilot01/sdtm/define.yaml",
    enrich_methods=True,
).generate("outputs/define_sdtm.xml")
```

CLI equivalent:

```bash
uv run fleet define-xml \
  --spec examples/cdiscpilot01/sdtm/define.yaml \
  --output outputs/define_sdtm.xml \
  --enrich-methods
```

The derivation block accepts either form:

```yaml
# Standard verb — resolves against fleet.sdtm / fleet.adam namespaces
derivation:
  algorithm: assign_ct
  source: sex
  ct_codelist: C66731

# Study-specific callable — full dotted path importable at generation time
derivation:
  callable: examples.cdiscpilot01.adam.derivations.derive_aval
```

## DefineValidator

::: fleet.define_xml.DefineValidator
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## DatasetChecker

::: fleet.define_xml.DatasetChecker
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]
