# The bootstrap pins two CT packages and invents no text

The alpha audit of 2 November 2026 (package H, part 3) found that a study made by the documented bootstrap could not pass `fleet check` when it had ADaM datasets (`c1-297`). CDISC publishes ADaM CT on its own dates, and some codelists are only in ADaM CT: DTYPE (C81224) is not in any SDTM CT package. `fleet init ct` asked only the SDTM package, dropped the ADaM-only codelists with no message, and `fleet check` then advised a command that could not help. The scaffold also wrote an empty `study.description` and `study.originator`, and `fleet define-xml` ended in a traceback (`c1-533`). We decided that a study pins an SDTM and an ADaM CT package, and that the bootstrap never invents metadata text.

## The decision

- **Two pins.** `study_config.yaml` holds `ct.package` (SDTM CT) and `ct.adam_package` (ADaM CT). `fleet init cfg` and `fleet new` with ADaM datasets pin `adamct-2023-06-30`, the latest ADaM package on or before the default `sdtmct-2023-12-15` (Mahdi, `c1-297` A). With another `--package`, they need `--adam-package`, because `fleet init cfg` has no network to find the date.
- **One resolver.** `fleet init ct` takes each codelist from the first pinned package that holds it, SDTM CT first. Only a 404 moves to the next package; a 401 or a network error stops the command.
- **A missing codelist stops.** When no pinned package holds a codelist, `fleet init ct` names its ID, writes no file and exits with code 1.
- **Two-package marker.** A `codelists.py` with codelists from both pins has `__ct_packages__`. The stale checks compare it with both pins. Two dates of one product (two SDTM CT packages) still fail.
- **Terms in define.yaml.** `fleet init ct` writes the terms and decodes (NCI preferred term) into each `codelists:` entry of the `define.yaml` files that has no terms; with `--force`, into every entry. The generator names each codelist that has no terms.
- **Both CT standards in an ADaM define.** The ADaM `define.yaml` has `ct_version` (SDTM CT) and `adam_ct_version` (ADaM CT). Its Define-XML lists two CT standards, with the publishing sets SDTM and ADaM.
- **No invented text** (Mahdi, `c1-533` C). The scaffold leaves `study.description` and `study.originator` empty when the user gave none. One clean message names the empty fields; `--description` and `--company` fill them at creation.

## Considered options

- **The first ADaM package after the SDTM date** (`c1-297` B). Rejected: the define.xml then states an ADaM CT newer than the SDTM CT.
- **`fleet init ct` finds the ADaM package and writes it into the config.** Rejected: a later command changes the config, so a reviewer can miss the pin.
- **Write the codelists found and name the rest.** Rejected: a partial `codelists.py` stays in the study.
- **The generator reads the terms from `codelists.py`.** Rejected: the define.xml then depends on a second file that a reviewer of `define.yaml` does not see.
- **A placeholder description** (`c1-533` A, B). Rejected: placeholder text can reach a define.xml as if it were real metadata.

## Consequences

- A study made before this change has no `ct.adam_package`. `fleet check` names the missing pin for each ADaM-only codelist.
- `fleet init ct --force` rewrites the `define.yaml` files through YAML, so only their header comment stays.
- The committed CDISC pilot ADaM define now states its `ct_version` with the publishing set SDTM.
- The first `fleet check` after `fleet new` is red until the user fills the description, the company and the Define-XML gaps of ADR-0018. Each row names what to fill.
