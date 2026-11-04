# Response confirmation follows admiralonco by default

Alpha audit finding c1-406 found that `confirmed_response_flag` only checked that two CR or PR records were 28 days apart. A PR after the first PD confirmed a response, and SD or NE between the two records had no limit. RECIST 1.1 Table 3 has two time points only, so no standard fixes the rule for SD and NE in between. We decided on the strict admiralonco default (Mahdi, 4 November 2026).

## The decision

- **The window.** For each CR or PR record, the window holds the later records up to and including the first that confirms it: a CR at least `confirmation_days` later for a CR, a CR or PR for a PR.
- **The default is `max_nr_ne=1`, `max_nr_sd=0`**, as the admiralonco `crsp_y_cr` and `crsp_y_pr` events. For a CR the window holds only CR and NE. For a PR it holds CR, PR and NE (and SD when `max_nr_sd` is not 0), and no PR follows a CR. `None` removes a limit.
- **The verb stops at the first PD of a group.** Records after it confirm nothing and are not confirmed.
- **Only the confirmed record is flagged.**
- **The verb warns** on a null response, on two assessments on one date, and on a CR followed by a PR or SD, with the group values.
- **`responses` is CR, PR or a subset.** Another value raises.

admiralonco 1.4.1, run on the rows of `tests/unit/test_onco_response_rules.py`, gives the subjects that the test holds, for the default and for `accept_sd=TRUE` of the deprecated `derive_param_confirmed_resp` (`max_nr_sd=1`).

## Considered options

- **Lenient default, as SWOG S0819 section 10.3** (no SD or NE limit, stop at first PD). Rejected: on a strict SAP the response rate is above the QC value, and if QC also uses the Fleet default, nobody sees the overstated endpoint.
- **No default, both arguments required.** Rejected: each existing call stops until two values are added, and a wrong reading of the SAP still passes.

## Consequences

- On a SWOG-type SAP the response rate is below the SAS QC value until the programmer sets `max_nr_ne=None, max_nr_sd=None`. The first PROC COMPARE shows it.
- The verb now materialises the pipeline, because it joins the records of a group to each other.
- A subject with PR, SD, PR (C07) or PR, NE, NE, PR (C09) is no longer flagged by default.
