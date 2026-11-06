# Tooling Introspection

`fleet.introspect` is the surface for **editor and tooling integrations** — a language
server offering `algorithm:` completions, a hover card, a `define.yaml` linter. If you
are writing derivations rather than tooling, you want the
[SDTM](sdtm.md) and [ADaM](adam.md) namespaces instead.

The module is **additive-only within a major version**: names and return fields may be
added, but nothing is removed or renamed except on a major. A client therefore declares a
_minimum_ Fleet version — read from `serverInfo.version` in the language-server
handshake — and never a maximum. See
[ADR-0001](https://github.com/RealSlimMahdi/fleet-cdisc/blob/main/docs/adr/0001-introspection-surface-for-protocol-adapters.md)
for the reasoning.

```python
from fleet import introspect

items = [
    {"label": algo.name, "documentation": algo.description}
    for algo in introspect.algorithms("adam")
]
```

---

## algorithms

::: fleet.introspect.algorithms
    options:
        show_root_heading: true
        heading_level: 3

## get_algorithm

::: fleet.introspect.get_algorithm
    options:
        show_root_heading: true
        heading_level: 3

## suggest_algorithm

::: fleet.introspect.suggest_algorithm
    options:
        show_root_heading: true
        heading_level: 3

## renamed_algorithm

::: fleet.introspect.renamed_algorithm
    options:
        show_root_heading: true
        heading_level: 3

## check_derivation

::: fleet.introspect.check_derivation
    options:
        show_root_heading: true
        heading_level: 3

## standard_of

::: fleet.introspect.standard_of
    options:
        show_root_heading: true
        heading_level: 3

## algorithm_doc

::: fleet.introspect.algorithm_doc
    options:
        show_root_heading: true
        heading_level: 3

## define_schema

::: fleet.introspect.define_schema
    options:
        show_root_heading: true
        heading_level: 3

## load_spec_yaml

::: fleet.introspect.load_spec_yaml
    options:
        show_root_heading: true
        heading_level: 3

## Standard

`Standard` is the type of the *standard* argument: `Literal["sdtm", "adam"]`.
Any other value raises `ValueError`.

---

## AlgorithmInfo

::: fleet.introspect.AlgorithmInfo
    options:
        show_root_heading: true
        heading_level: 3
        filters: ["!^_"]

## ParamInfo

::: fleet.introspect.ParamInfo
    options:
        show_root_heading: true
        heading_level: 3
        filters: ["!^_"]

## AlgorithmDoc

::: fleet.introspect.AlgorithmDoc
    options:
        show_root_heading: true
        heading_level: 3
        filters: ["!^_"]

## DerivationProblem

::: fleet.introspect.DerivationProblem
    options:
        show_root_heading: true
        heading_level: 3
        filters: ["!^_"]
