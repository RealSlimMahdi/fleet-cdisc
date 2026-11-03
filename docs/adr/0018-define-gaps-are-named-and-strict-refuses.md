# Define-XML gaps are named, and strict refuses

The alpha audit of 2 November 2026 (package H) found three defects in the Define-XML path. A Derived variable with no method text got no `MethodOID`, with no message (`c1-557`). Numeric items had no `Length` and float items no `SignificantDigits`, and the spec had no key for `SignificantDigits` (`c1-776`). `DefineXMLGenerator` and `DefineValidator` read a retired YAML dialect: every documented call failed, and `fleet check` used that validator, so it passed specs that the real generator refused (`c1-774`). We decided that the generator names each gap, that a strict mode refuses, and that `fleet check` runs that strict mode.

## The decision

- **A gap is named, not hidden** (Mahdi, Q2 B). Define-XML 2.1 requires a `MethodOID` on each Derived `ItemRef`, a `Length` on `text`, `integer` and `float` items, and `SignificantDigits` on `float` items. The generator lists each item that misses one, as `DM.SAFFL: no method text (add a comment: or a derivation: block)`, or `VS.AVAL (PARAMCD = SYSBP): no SignificantDigits (required on float)` for a value-level entry.
- **The default writes and warns.** `fleet define-xml` and `DefineSpecGenerator(spec)` write the file and give one warning with the list. A draft define for a review is still possible.
- **Strict refuses.** `fleet define-xml --strict` and `DefineSpecGenerator(spec, strict=True)` raise `SpecError`, exit with code 1 and write nothing.
- **`fleet check` is strict.** It runs the real generator with `strict=True` and writes no file. A new study can be red there; each message names the fields to fill (as decided for `c1-533`).
- **Methods are on by default.** `enrich_methods=True` is the default; `--enrich-methods` is kept and does nothing. A method from a `comment:` only has no `FormalExpression`.
- **`significant_digits:`** is a new key on a variable and on a value-level entry. The schema refuses it on a type other than `float`, and refuses `length:` on `date` and `datetime`.
- **The retired classes are removed**: `DefineXMLGenerator`, `DefineValidator`, `StudyContext.define_schema()` and `define_xml_2_1_schema.json`.

## Considered options

- **Refuse by default** (Q2 A). Rejected: a programmer who wants a draft define for a spec review gets nothing until every method is written.
- **Warn only, with no strict mode** (Q2 C). Rejected: CI cannot stop a define with a Derived variable and no method.
- **Keep `DefineValidator` and port it to the current dialect.** Rejected: two validators of one spec drift again. The generator already validates the schema, the codelist references, the CDISC XSDs and the semantic lint.

## Consequences

- The CDISC pilot specs now hold a `length:` on each numeric variable, `significant_digits:` on each float, a `comment:` with the method text for the seven derivations made inline (SAFFL, ITTFL, TRTEMFL, ANL01FL, the two ASEQ, EXDURD), and `origin: Predecessor` for the ADSL variables copied into ADVS, ADAE and ADEX. Four variables that the pipeline does not make (ADSL.DTHFL, ADVS.DTHFL, ADVS.DTYPE, ADVS.ANL01FL) are removed from the ADaM spec.
- Code that imported `DefineXMLGenerator` or `DefineValidator` must use `DefineSpecGenerator(spec).generate(out)` and `fleet check`.
