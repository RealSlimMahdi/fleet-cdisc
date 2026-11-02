# The verb is the algorithm: one vocabulary for inline code and define.yaml

**Status: accepted, 2026-10-16.** Proposed and decided the same day in #146. Supersedes ADR-0007.

A derivation has two notations in Fleet. The inline notation is a verb call, `.assign("SEX", source="sex", ct=SEX)`. The spec notation is a `derivation:` block in a define.yaml, `algorithm: assign_ct`, `source: sex`, `ct_codelist: C66731`. Today the two notations use two vocabularies. The spec registry maps the spec names onto the verbs with a hand-written `Param` table per algorithm, and ADR-0007 made the table take its `default` and `required` facts from the verb signature. The table still exists, and so do the renamed keys, the aliases and the legacy keys.

We decided that the `algorithm:` value is the verb name and the YAML keys are the keyword arguments of the verb. The rule for the programmer: remove `.verb("TARGET", ` and the last `)`. What stays is the YAML block. Fleet builds the strict Pydantic model from the verb signature. A short declaration per verb says only what a signature cannot say: which arguments stay out of the spec, which arguments exclude each other, and the Define-XML method text. Lineage already records `(verb, target, kwargs)`. `from_spec` calls the verb with them, and `to_spec_yaml()` writes them back unchanged.

## Measured on 2026-10-16, on `main` at bb4b878

| Fact | Value |
| --- | --- |
| Registered algorithms | 46 (16 SDTM, 30 ADaM) |
| Distinct verbs behind them | 39 (13 SDTM, 26 ADaM) |
| Verbs with more than one spec name | `assign` (4 names in SDTM, 3 in ADaM), `derivation` (2), `duration` (2) |
| Spec names that differ from their only verb | `if_then_else`, `condderivation` (`case_when`), `lookup` (`merge`), `callable` (`derivation`) |
| Renamed keys | 13 distinct renames on 22 fields, for example `ct_codelist` for `ct`, `groups` for `by`, `else_value` for `else_` |
| Algorithm aliases | 4: `assign_dtc`, `dataset_level`, `count`, `mean_arterial_pressure` |
| Legacy key maps | 8 |
| Custom dispatch | 4: `date` (SDTM), `nsv`, `pick`, `callable` |
| Registration code in `spec_registry.py` | 941 lines (lines 960 to 1900) |
| Shipped define.yaml files with derivations | 4 files, 174 blocks |
| Blocks whose `algorithm:` value changes | 160 of 174 |
| Blocks where a key changes | 18 of 174 |

The 160 name changes are mostly `source` and `assign_no_ct` to `assign` (108 blocks) and `assign_dtc` to `date` (14 blocks).

## Before and after

The DM block for SEX, today and under this proposal. The inline call is `.assign("SEX", source="sex", ct=SEX, ct_map={"F": "F", "M": "M"})`.

```yaml
# today
- name: SEX
  codelist: C66731
  derivation:
    algorithm: assign_ct
    source: sex
    ct_codelist: C66731
    ct_mapping: { "F": "F", "M": "M" }
```

```yaml
# proposed
- name: SEX
  codelist: C66731
  derivation:
    algorithm: assign
    source: sex
    ct_map: { "F": "F", "M": "M" }
```

`ct:` is absent in the proposed block. It defaults to the `codelist:` of the variable. More examples:

| Inline call | Spec block today | Spec block proposed |
| --- | --- | --- |
| `.assign("DOMAIN", value="DM")` | `algorithm: hardcode_no_ct`, `value: DM` | `algorithm: assign`, `value: DM` |
| `.case_when("ARMCD", when=[...], else_="X")` | `algorithm: if_then_else`, `when:`, `else_value: X` | `algorithm: case_when`, `when:`, `else: X` |
| `.duration("ADY", start="TRTSDT", end="ASTDT")` | `algorithm: study_day`, `reference_date:`, `analysis_date:` | `algorithm: duration`, `start:`, `end:` |
| `.seq("AESEQ", by=["USUBJID"])` | `algorithm: seq`, `groups: [USUBJID]` | `algorithm: seq`, `by: [USUBJID]` |
| `.merge(dataset=adsl, on=["USUBJID"])` | `algorithm: lookup`, `dataset: ADSL`, `on:` | `algorithm: merge`, `dataset: ADSL`, `on:` |
| `.onco.best_overall_response("BOR", ...)` | none (#90) | `algorithm: onco.best_overall_response` |

## The rule

1. **One name.** The `algorithm:` value is the verb name. Sub-namespace verbs use a dotted name, `pk.blq_flag`. No aliases, no legacy keys.
2. **One declaration.** The verb signature is the spec schema. Every keyword argument of the verb is a YAML key, except the arguments the verb declaration excludes. `required` and `default` come from the signature, as in ADR-0007.
3. **One type table.** The YAML type comes from the Python type through a fixed table. A `pl.Expr` is an expression string. A `pl.DataFrame | pl.LazyFrame` is the name of a pinned dataset. A codelist class (`str | type`) is a codelist id. A `@derivation` object is its registered name or dotted path. Every other type is written as is.
4. **One trailing underscore.** A keyword that ends in `_` because it shadows a Python word loses the underscore in YAML. `else_` is `else:`.
5. **One record.** The lineage node's verb and kwargs are the block. `derivation_from_lineage` has one candidate, not a ranked list. The static converter (#139) is the same mapping on literal arguments.

The declaration per verb is short. A sketch:

```python
spec_verb(
    "assign",
    standard="sdtm",
    exclude=("ct_validator", "validate_values"),
    one_of=("source", "value"),
    method_text=[
        ({"value", "ct"}, "Set to the controlled terminology value '{value}' for all records."),
        ({"value"}, "Set to '{value}' for all records."),
        ({"source", "ct"}, "Value of {source} mapped to controlled terminology."),
        ({"source"}, "Direct copy of {source}."),
    ],
)
```

The `method_text` list is where the reviewer vocabulary survives. The Define-XML `MethodDef` still reads "Value of SEX mapped to controlled terminology", chosen by the keys the block gives. The reviewer reads the Define-XML. The YAML names move to the programmer's vocabulary.

## What one signature cannot say, and the answer

- **`assign` needs exactly one of `source` and `value`.** A `one_of` group on the declaration, enforced by a model validator. A block with both, or neither, is a load-time error.
- **A CT copy without its codelist.** Today `assign_ct` requires `ct_codelist`, and `assign_no_ct` has none. Under one verb `ct` is optional. The proposal moves the strictness to the variable: `ct:` defaults to the variable's `codelist:`, and a `ct_map` on a variable without `codelist:` and without `ct:` is a load-time error, because a mapping needs a codelist. This also closes the drift between `ct_codelist` and `codelist:` that #96 reports.
- **Copy-through where the source is the target.** `source` keeps its default-to-target behaviour. It is one flag on the declaration, as today.
- **`study_day` in YAML runs `duration` today.** Under the rule `study_day` names the pin-based `study_day` verb, which is inline-only. The migration rewrites the three shipped `study_day` blocks to `duration`.
- **Four verbs whose call shape is not a flat kwargs dict.** `date` (SDTM), `nsv`, `pick` and the `callable` form of `derivation` keep a custom dispatch. `callable:` stays the YAML key for a `@derivation` object, under `algorithm: derivation`, and the shorthand `callable:` alone still injects the algorithm.

## Considered options

- **Keep two vocabularies (ADR-0007, the status quo).** The spec reads `assign_ct` where a data-standards reviewer expects it. The cost is the 941-line table, the five parity rules that guard it, 13 renamed keys to learn, and every new verb paid twice: #90 plans 48 more `Param` tables. The static converter must rank candidates for one verb, and `to_spec_yaml()` relabels lineage nodes to the spec name. Rejected: the inline verbs and the spec-driven derivations must match, and the reviewer reads the Define-XML, where the method text keeps the standards vocabulary.
- **Rename the verbs to the spec names.** `.assign_ct(...)`, `.hardcode_no_ct(...)`, `.if_then_else(...)` as inline verbs. One vocabulary, but four verbs for one intent, and the inline API becomes the define dialect. Rejected.
- **Verb names in YAML, old names kept as aliases for one minor version.** The table stays alive to serve the aliases, so nothing is deleted until the next version. Fleet is pre-alpha at 0.2.0a1, #146 states that no compatibility is owed, and `fleet migrate` already exists for the Python side. Rejected in favour of a hard cut with a spec migration.
- **Rename the key `algorithm:` to `verb:`.** Honest, but it changes the JSON schema root, the LSP completions, every doc and every shipped spec for a word. The key stays `algorithm:`.
- **Derive the YAML type from the Python type.** ADR-0007 rejected this, because `ct` and `agg` differ between Python and YAML on purpose. The proposal keeps that difference, but as a fixed four-row table instead of a per-field `annotation` and `convert`. The table is the declaration.

## Consequences

Deleted:

- The `Param` tables, `annotation`, `kwarg`, `alias`, `convert`, `legacy_keys` and `aliases`. About 941 lines become an estimated 200.
- The five parity rules of ADR-0007 and the kwarg renames. The remaining test is one rule: the YAML model of a verb equals its signature minus the excluded arguments.
- The `SDTMAlgorithm` and `ADAMAlgorithm` enums in `fleet.sdtm.models` and `fleet.adam.models`. They are exported from `fleet` and hold the spec names. They go, or they are generated from the verb list.
- The rules ALG01 to ALG05 in `fleet.define_xml.validator`. They check `source_variable`, `constant_value`, `merge_dataset` and `merge_key` under `item_defs`, keys the current dialect does not have. No shipped define.yaml uses them.
- ADR-0007, marked superseded.

Changed:

- Every shipped define.yaml: 174 blocks in 4 files, plus the YAML in `docs/` and the inline dicts in `tests/`. `define_spec_schema.json` is regenerated, `llms.txt` is rebuilt.
- `fleet migrate` gains a spec mode. It rewrites a define.yaml with a frozen old-to-new table kept as a data file, so a study moves in one command and the mapping does not depend on the deleted registry.
- `fleet.introspect` keeps its DTOs. `AlgorithmInfo.name` now holds verb names. ADR-0001's additive-only rule covers the names and shapes of the surface, not the catalogue values. The VS Code client reads the catalogue from the LSP at run time; `fleet-vscode/src/server.ts` hard-codes no algorithm name (checked 2026-10-16).
- `_attach_spec_lineage` no longer relabels nodes. The verb on the node is the algorithm.
- `docs/concepts/define-yaml.md` replaces "Two vocabularies, one mapping" with the one rule.

Risks:

- The define.yaml reads like Python. `by`, `ct_map`, `when`. A programmer who knows SAS and CDISC but not Fleet learns the verb vocabulary once, in both notations instead of two.
- A verb signature change is now a spec dialect change. A renamed keyword breaks every study's define.yaml. The signature becomes a contract: a rename needs a `fleet migrate` entry and a `fleet_spec_version` note. ADR-0007 already made a default change a spec change, so this is one step further on the same path.
- The strict CT check moves from the algorithm name to the variable's `codelist:`. A variable without `codelist:` and without `ct:` gets no CT check, as today for `assign_no_ct`.

## Decided on 2026-10-16

The five questions of the proposal and their answers.

1. **Who reads the define.yaml? Domain.** The inline verbs and the spec-driven derivations must match. The `algorithm:` value is the verb name, `assign`. A QC programmer reads the same name in the program and in the spec.
2. **`ct:` defaults to the variable's `codelist:`. Domain.** Yes. For DM.SEX with `codelist: C66731`, a derivation `algorithm: assign`, `source: sex` and no `ct:` checks the raw values against C66731. A `ct_map` on a variable without `codelist:` and without `ct:` is a load-time error.
3. **`else_` is written `else:` in YAML. Engineering.** Yes. A trailing underscore that avoids a Python keyword is dropped in YAML.
4. **Hard cut or aliases. Engineering.** Hard cut. Fleet is pre-alpha. An old define.yaml fails at load with a message that names `fleet migrate --spec`.
5. **The key stays `algorithm:`. Engineering.** Yes.

## Decisions taken without a question

- The ADR number is 0008. ADR-0006 is on PR #175 and may move this number.
- The four custom-dispatch algorithms stay as they are.
- Sub-namespace verbs use the dotted verb name. This answers the blocker in #90.
- The Define-XML method text is chosen per verb by the keys given in the block, in declared order, first match wins.
- The type table has four rows: expression, pinned dataset, codelist, derivation object.
- `callable:` stays as a key under `algorithm: derivation`, and the shorthand without `algorithm:` stays.
- The `study_day` blocks in YAML migrate to `duration`.

## Implementation phases

Each phase is one PR. The next phase starts when the previous one is green.

1. **`spec_verb()` next to `spec_algorithm()`.** The new declaration registers the 39 verbs under their verb names, with the type table, `exclude`, `one_of` and `method_text`. The old names resolve to the new entries. A new parity test checks that each YAML model equals its signature. `from_spec`, `to_spec_yaml()`, the static converter and the schema builder all pass on the old shipped YAML.
2. **Migration.** `fleet migrate --spec` with the frozen table. The 4 shipped specs, the docs YAML, the tests and `define_spec_schema.json` move to the verb names. The six examples pass.
3. **Deletion.** `spec_algorithm`, `Param`, the aliases, the legacy keys, the enums, the ALG rules, the five ADR-0007 rules and `_attach_spec_lineage` go. ADR-0007 is marked superseded. `define-yaml.md` and `llms.txt` are rewritten.
4. **Follow-ups.** #90 becomes 48 one-line registrations. #89 extends the parity test to the sub-namespaces. #137 and #138 shrink, because the converter is the one mapping.

Verification for every phase: `uv run ruff check && uv run ruff format --check`, `uv run pytest`, the six examples, `uv run python scripts/build_llms.py --check`, and `uv run python -m fleet.define_xml.schema_builder` with a clean diff.
