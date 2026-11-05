# The define follows the IG for dataset defaults and qualifiers

The alpha audit of 2 November 2026 (package define) found two dataset-level defaults in the Define-XML path that disagree with the CDISC examples. Every dataset was `IsReferenceData="No"`, so TS was described as subject data, and a dataset with no `repeating:` key was `Repeating="Yes"`, also DM and ADSL (`c1-561`). In an SDTMIG 3.4 spec, a `role: qualifier` variable was described as a variable of its parent domain, with no SUPP-- dataset and no message (`c1-562`). We decided that the defaults follow the official Define-XML 2.1 SDTM example, and that the generator refuses a qualifier in its parent domain up to SDTMIG 3.4.

## The decision

- **Repeating.** With no `repeating:` key, DM, ADSL and the trial design datasets (TA, TE, TV, TI, TS, TD, TM) are `Repeating="No"`. Every other dataset is `Repeating="Yes"`. `fleet init define` writes the same rule.
- **IsReferenceData.** With no `is_reference_data:` key (a new dataset key), TA, TE, TV, TI, TS, TD, TM and a dataset of class `TRIAL DESIGN` are `IsReferenceData="Yes"`. Every other dataset is `No`.
- **An explicit key wins** over both defaults.
- **A qualifier in its parent domain is refused** (Mahdi, c1-562 B). For `standard: SDTMIG` and `standard_version` 3.4 or earlier, a variable with `role: qualifier` (or `algorithm: nsv`) in a dataset that is not SUPP-- gives a `SpecError` that names `AE.AETRTEM` and `SUPPAE`. The author declares SUPPAE and moves the variable there. Changed by ADR-0044: the generator now moves such a variable to a generated `SUPPAE`, and refuses only a qualifier that cannot move.
- **A SUPP-- dataset describes its parent.** A dataset named `SUPPAE` gets `Domain="AE"`, as in the official example.

## Considered options

- **Build SUPP-- automatically with QVAL value-level items** (c1-562 A). Rejected: generated metadata with an IDVAR that the spec does not state can pass review with a wrong IDVAR.
- **Keep the qualifier in its parent and warn** (c1-562 C). Rejected: the warning can be missed, and the define still shows a non-standard variable in its parent for IG 3.4.
- **Keep `Repeating="Yes"` as the default.** Rejected: DM and ADSL have one record per subject; a reviewer reads `Yes` as a wrong structure.

## Consequences

- A spec that runs `export_supp(spec=...)` from `role: qualifier` variables in the parent dataset could not give an SDTMIG 3.4 define from the same file. ADR-0044 removes this conflict: the define describes the qualifier in a generated `SUPP<domain>` ItemGroupDef, so one define.yaml serves `fleet run`, `fleet define-xml` and `fleet check`. The refusal stays for a qualifier that cannot move (for example a parent with no `--SEQ`, or a declared `SUPP<domain>` as well). No qualifier is described as a parent-domain variable.
- Specs that relied on the old `Repeating="Yes"` default for DM, ADSL or a trial design dataset now give `No`. Set `repeating: true` to keep the old value.

## References

- CDISC Define-XML 2.1, example `defineV21-SDTM.xml` (TS: `Repeating="No" IsReferenceData="Yes"`; SUPPAE: `Domain="AE"`).
- SDTMIG 3.4, section 8.4 (Relating Non-Standard Variable Values to a Parent Domain).
