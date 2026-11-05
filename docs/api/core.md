# Core

## StudyContext

::: fleet.core.StudyContext
    options:
        show_root_heading: true
        heading_level: 3
        filters: ["!^_"]

## load_study_context

::: fleet.core.load_study_context
    options:
        show_root_heading: true
        heading_level: 3

## PipelineDAG

::: fleet.core.PipelineDAG
    options:
        show_root_heading: true
        heading_level: 3
        filters: ["!^_"]

## Derivation

::: fleet.core.derivation.Derivation
    options:
        show_root_heading: true
        heading_level: 3
        filters: ["!^_"]

## derivation (decorator)

::: fleet.core.derivation.derivation
    options:
        show_root_heading: true
        heading_level: 3

## to_repr

::: fleet.core.repr_utils.to_repr
    options:
        show_root_heading: true
        heading_level: 3

## SharedVerbsMixin

Verbs available on every namespace (`df.sdtm`, `df.adam`, `df.adam.adsl`, …).

::: fleet.core._verb_mixin.SharedVerbsMixin
    options:
        show_root_heading: false
        heading_level: 3
        members_order: source
        filters: ["!^_"]

## PinMixin

Verbs that pin a reference dataset to a chain (`pin`, `repin`, `pins`,
`fk_policy`). They are on `df.sdtm` and `df.adam`.

::: fleet.core._pin_mixin.PinMixin
    options:
        show_root_heading: false
        heading_level: 3
        members_order: source
        filters: ["!^_"]

## Exceptions

::: fleet.core.exceptions
    options:
        show_root_heading: true
        heading_level: 3
        filters: ["!^_"]
