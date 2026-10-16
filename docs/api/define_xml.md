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

When constructed with `enrich_methods=True`, `DefineSpecGenerator` emits one
Define-XML 2.1 `<MethodDef>` per **Derived** variable (named
`Algorithm for <VARIABLE>`), referenced from the variable's `<ItemRef>` via
`MethodOID`. Variables with any other origin — Collected, Assigned, Protocol,
Predecessor — never reference a method: a collected column is not a
computation.

The `<Description>` is submission text, resolved as: the variable's
`comment:` → the study callable's docstring (`callable:` derivations) → the
algorithm registry's submission-facing template with the spec params filled
in (`fleet.core.spec_registry.render_method_text`). Fleet verb docstrings are
never emitted. `<FormalExpression Context="Python/Fleet">` records the
faithful call (dotted verb path + spec params), so identical specs produce
identical text across Fleet versions.

### Validation of generated documents

Every generated document is validated before it is written: structurally
against the vendored CDISC ODM 1.3.2 + Define-XML 2.1 XSDs
(`validate_define_xml`), and semantically by a reviewer-facing lint
(`semantic_errors`) that rejects a `MethodOID` on a non-Derived variable, API
markup in `TranslatedText`, algorithm ids as MethodDef names, and
`Predecessor` origins that do not name a `DATASET.VARIABLE`. Pass
`validate_xml=False` to bypass both (e.g. to inspect a failing document).

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
  algorithm: assign
  source: sex
  ct: C66731

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
