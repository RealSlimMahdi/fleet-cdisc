# A trial design arm needs its protocol name

Alpha audit finding c1-786 found that `StudyDesign` made TA.ARM from the ARMCD
when `arm_names` had no entry for an arm: ARMCD `XAN_HI` gave ARM `Xan Hi`.
SDTMIG 3.4 defines TA.ARM as the name of the arm in the protocol, and CDISC
CORE-000047 requires each DM.ARM to be a TA.ARM. An invented name passes every
Fleet check and then fails against DM.

## The decision

- **Each arm needs an entry in `arm_names`.** `StudyDesign` raises a
  `ValueError` that names the arms with no name. There is no fallback.
- **The audit compares DM with TA.** When DM has ARM, each DM (ARMCD, ARM) pair
  must be a TA pair. A pair that TA does not hold gives the warning
  `FLEETTD07`. The reserved codes (SCRNFAIL, NOTASSGN) and an ARMCD that TA does
  not hold (already `FLEETTD02`) are not checked again.

## Considered options

- **Keep the fallback and warn.** Rejected: the dataset is still written with a
  name that no protocol holds.
- **Make the DM check an error.** Rejected: in a multistage design DM.ARM can
  name a path that TA builds from more than one ARMCD, so a warning is safer.

## Consequences

- A `trial_design.yaml` or a Python design with no `arm_names` raises: add the
  protocol names.
- `from_mermaid` and `from_usdm` give names (the diagram label or the USDM arm
  label), so they do not change.
