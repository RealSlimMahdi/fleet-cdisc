# The SDTM define states the ItemRef Role, and CORE checks a define only on request

The alpha audit of November 2026 (c1-268) found that Fleet cannot give a Define-XML to CORE, and that the define YAML has no key for the SDTM role of a variable. When the audit ran CORE with `-dxp` and Fleet's pilot define, rule CG0010 (CORE-001081) reported "define role null" 19 times on DM alone. We decided that `fleet init define` fills the role of each SDTM variable from the CDISC Library, that the Define-XML writes it as the ItemRef `Role`, and that `fleet validate` passes a define to CORE only when the user names it.

## The decision

- **Role from the CDISC Library** (Mahdi, option A). `fleet init define` writes `sdtm_role:` on each SDTM variable from the `role` of the SDTMIG variable in the CDISC Library (`Identifier`, `Topic`, `Timing`, `Grouping Qualifier`, `Result Qualifier`, `Synonym Qualifier`, `Record Qualifier`, `Variable Qualifier`, `Rule`). The key is new: the existing `role: qualifier` keeps its one meaning (a Non-Standard Variable for `supp()`) and never reaches the Define-XML.
- **ItemRef Role.** `DefineSpecGenerator` writes `Role="<sdtm_role>"` on the ItemRef of each variable that has the key. A variable without the key gets no `Role`, as before.
- **CORE checks a define on request only.** `fleet validate --define PATH` (and `ValidationService.validate_datasets(..., define_xml=PATH)`) passes `-dxp PATH` to each engine run. The path goes through the run setup, is resolved against the working directory and is printed in the report header. A path that does not exist refuses the run (exit 2). Without the flag, no define is passed.

## Considered options

- **B: leave Role out and do not pass the define by default.** Rejected: an agency or sponsor checker that runs CG0010 reports the same warnings there first, on each variable.
- **C: leave Role out and pass the define by default.** Rejected: about 19 CG0010 warnings on DM alone hide the real findings in each report.

## Consequences

- The role in a define is a value nobody typed: a sponsor-specific role can differ from the Library fill, so QC must check `sdtm_role:` like any other define value.
- Defines written before this change have no `sdtm_role:`. Rerun `fleet init define --force`, or add the key by hand, before passing the define to CORE.
- References: CDISC Define-XML 2.1 specification (ItemRef, attribute Role); SDTM variable roles in the SDTMIG; CORE rule CG0010.
