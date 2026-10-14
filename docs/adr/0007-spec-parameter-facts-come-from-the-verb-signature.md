# Spec parameter facts come from the verb signature, and the spec may be stricter than the verb but never looser

Every spec algorithm in `fleet.core.spec_registry` restated its verb's parameters in a hand-written `Param` table: the name, the type, the default, and whether the field is required. The parity test checked that the algorithm names and the JSON schema matched the registry, but it never compared the parameter tables with the verb signatures. A renamed keyword or a changed default on the verb passed green, and the inline form and the define.yaml form of one derivation then produced different numbers. On 2026-10-14 we measured the two sides: 48 algorithms, 24 of them with a Param table equal to the signature, 73 individual differences on the other 24. Most of the differences were deliberate, so "the signature is the declaration" was not true of the registry as it stood, and we had to decide what the registry is allowed to say that the signature does not.

We decided that the registry keeps two vocabularies (the spec algorithm names a data-standards reviewer reads, `assign_ct`, `hardcode_no_ct`, mapped onto one verb per intent) and that within one algorithm the spec fields take their `default` and `required` facts from the verb signature. A `Param` declares only what a signature cannot say: the spec field name when it differs from the keyword (`kwarg`), the YAML type (`annotation`), a legacy alias, a dispatch-time conversion (`convert`), whether the target name is the default (`default_to_target`), and `required=True` where the spec is stricter than the verb. The registry reads the signature on first lookup, not at import, so `spec_registry` never imports the namespace classes at module load. The `description` falls back to the `Args:` line of the verb docstring when the Param does not state one.

The rule the parity test enforces, for every algorithm with default dispatch and every Param:

1. The keyword exists in the verb signature.
2. A Param marked default-to-target skips the default check.
3. The spec may be stricter than the verb: `required=True` where the signature has a default. The spec may never be looser: no spec-only default where the signature requires a value, and no spec-only default that differs from the signature's.
4. When both sides are optional, the defaults are equal.
5. Verb arguments absent from the registry are ignored. The spec surface is a curated subset of the signature, widened when a Define-XML method template exists for the new field.

Custom-dispatch algorithms (`date`, `nsv`, `callable`, `pick`) have no verb signature to derive from and are outside the rule.

## Considered options

- **The verb is the algorithm (#146).** One name, one declaration, one record: the `algorithm:` value is the verb name and the YAML keys are its keyword arguments, so the Param tables disappear. This reverses the recorded choice "Two vocabularies, one mapping" in `docs/concepts/define-yaml.md`, changes the vocabulary a reviewer reads in a define.yaml, and cannot make `ct_codelist` required for a CT assignment while leaving it absent for a plain copy, because one signature cannot produce five strict models. It stays open as its own decision. If it is taken, it deletes the Param tables and this ADR with them.
- **Keep spec-only defaults as CDISC conventions.** `nrind` in YAML defaulted `low` to LBSTNRLO while the Python call required `low=`; `merge` and `lookup` in YAML defaulted `on` to USUBJID while the Python verb raises without it. A submission artefact should name its inputs, and a merge that silently joins on USUBJID when the author meant USUBJID and VISITNUM duplicates rows with no trace in the spec. All ten spec-only defaults go, and the keys become required in YAML. No shipped example, doc or test spec omitted any of them.
- **Derive the YAML type from the Python type.** The two type systems differ on purpose: `ct` is `str | type | None` in Python and a codelist id in YAML, `agg` is a list of Polars expressions in Python and a list of strings in YAML. The `convert` field exists because of that gap. The annotation is a declaration, not a restatement, so it stays written.
- **A test only, no derivation.** The classified parity test closes the live bug on its own. Derivation is what makes drift impossible instead of tested-for, and it turns each of the 48 registrations planned in #90 into one `Param` per field plus a method template. The test lands first, then derivation.
- **Resolve at import through a `finalize()` call in `fleet/__init__`, or a hook on namespace class creation.** Both make the import order of `fleet/__init__` a hidden contract, or couple the registry to the namespace mixin. Resolution on first lookup follows `fleet.introspect.algorithms()`, which refuses to cache for the same reason.

## Consequences

- `ct_codelist` becomes required on `assign_ct` and `hardcode_ct`. The concept doc already claimed that a CT derivation missing its codelist is a load-time error, and the registry now makes that true.
- A define.yaml must state `low`, `high` and `aval` for `nrind`, the three dates for `on_treatment`, `term_var` for `atoxgr`, and `on` for `merge` and `lookup`. A missing key is a load-time error with a suggestion.
- A misspelled keyword in a registration surfaces at first lookup, not at import. The parity test touches every entry, so it is still a red test.
- The review's count "5 of Param's 10 fields become derived" is corrected to 2: `default` and `required`. `description` has a fallback, not a derivation.
- `fleet.introspect.ParamInfo` does not change. A `default` field may be added later under ADR-0001's additive rule.
- `SpecAlgorithm.verb` stays the attribute name on the standard's top-level namespace. Sub-namespace verbs need a dotted path, which is #90's design.
