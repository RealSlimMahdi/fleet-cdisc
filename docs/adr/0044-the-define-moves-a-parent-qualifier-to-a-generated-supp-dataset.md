# The define moves a parent qualifier to a generated SUPP-- dataset

The alpha audit found that the spec path makes no SUPP-- dataset (`c1-105`). Step A of the fix made `fleet run` write `SUPP<domain>` for each SDTM variable with `role: qualifier` or `algorithm: nsv`. ADR-0041 (`c1-562` B) made `fleet define-xml` and `fleet check` refuse the same variable in its parent domain up to SDTMIG 3.4. So one define.yaml could not drive `fleet run` and also pass `fleet define-xml`. We decided that the parent dataset of the spec keeps the qualifier for the derivation, and that the generator describes it in a generated `SUPP<domain>` dataset.

## The decision

- **The spec form.** The qualifier stays a variable of its parent dataset in define.yaml (`role: qualifier` or `algorithm: nsv`), with its label, type, length, origin and derivation. `fleet run` derives it there and writes it to `SUPP<domain>` (step A).
- **The Define-XML form.** For `standard: SDTMIG` and `standard_version` 3.4 or earlier, the generator leaves the qualifier out of the parent ItemGroupDef and adds an ItemGroupDef `SUPP<domain>` after it:
  - `Domain` is the parent, `def:Class` is `RELATIONSHIP`, the structure is "One record per IDVAR, IDVARVAL, and QNAM value per subject".
  - The variables are STUDYID, RDOMAIN, USUBJID, IDVAR, IDVARVAL, QNAM, QLABEL, QVAL, QORIG, QEVAL. The keys are STUDYID, RDOMAIN, USUBJID, IDVAR, IDVARVAL, QNAM.
  - STUDYID and USUBJID are `Predecessor` of the parent variables.
  - QVAL has one ValueListDef. Each qualifier gives one WhereClauseDef `QNAM EQ <name>` and one value-level ItemDef with the label, type, length, codelist, origin and method of the qualifier.
  - The leaf is `supp<domain>` with the format of the parent, the file that `fleet run` writes.
- **IDVAR is stated.** IDVAR is `<DOMAIN>SEQ`, the rule of `fleet run`. The IDVAR ItemDef names it in its origin text, and IDVARVAL has a method. For DM, IDVAR and IDVARVAL are null, and the origin text says so.
- **The refusal of ADR-0041 stays for a qualifier that cannot move.** The generator and `fleet check` refuse the define and name `SUPP<domain>` when the parent has no STUDYID or USUBJID, a parent other than DM has no `<DOMAIN>SEQ`, the spec also declares `SUPP<domain>`, a qualifier name has more than 8 characters (QNAM), its label has more than 40 characters (QLABEL), or a qualifier is a key of the parent.
- A spec may still declare `SUPP<domain>` itself, with no qualifier in the parent. The generator writes it as declared.

## Considered options

- **Declare `SUPP<domain>` in define.yaml and move the qualifier there** (the ADR-0041 form). Rejected: `fleet run` builds the qualifier in the parent derivation, so the variable must be in the parent dataset. Two declarations of one variable can disagree.
- **Keep the qualifier in the parent ItemGroupDef.** Rejected: SDTMIG 3.2 to 3.4 do not allow a non-standard variable in the parent domain (c1-562 B).
- **IDVAR from a new spec key.** Rejected for now: `fleet run` uses `<DOMAIN>SEQ`, and the define states it. A sponsor that needs another IDVAR (for example `--GRPID`) declares `SUPP<domain>` by hand.

The concern of ADR-0041 against generated SUPP-- metadata (an IDVAR that the spec does not state) is answered: the IDVAR rule is fixed and shared with `fleet run`, and the define names it.

## Consequences

- One define.yaml serves `fleet run`, `fleet define-xml` and `fleet check`.
- A page map key `AE.AETRTEM` of the external page map does not reach the moved qualifier. Put the pages under `crf_pages:` of the variable; they go to the value-level item.
- The value-level ItemDef is named QVAL. Its description is the label of the qualifier.

## References

- SDTMIG 3.4, section 8.4 (Relating Non-Standard Variable Values to a Parent Domain).
- CDISC Define-XML 2.1, example `defineV21-SDTM.xml` (SUPPAE with value-level metadata on QVAL by QNAM).
- ADR-0041 (the define follows the IG for dataset defaults and qualifiers).
