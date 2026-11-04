# visit_map numbers an unscheduled visit and counts study days

Alpha audit findings c1-222 and c2-950 found two gaps in `visit_map`. The window
arithmetic subtracted study-day numbers across the missing Day 0, and the
docstring said calendar days. A dated record outside every window got a null
VISITNUM with no warning, and SV.VISITNUM is Req. We decided both rules with
Mahdi (4 November 2026): c1-222 option B, c2-950 option C.

## The decision

- **The distance is the difference of study-day numbers.** It is
  `abs(SVSTDY - VISITDY)`, as a SAS QC program computes it. Across the missing
  Day 0, Day -1 is 2 days from VISITDY 1. The docstring and the TVSTRL text of
  `TrialVisits.from_schedule()` now say "study days, no Day 0".
- **A dated record outside every window is an unscheduled visit.** It gets the
  VISITNUM of the last planned visit whose VISITDY is on or before its study
  day, plus .1, .2, ... in study-day order within the subject. VISIT is
  `UNSCHEDULED <VISITNUM>`, for example `UNSCHEDULED 5.1`. A record before the
  first planned visit counts from 0.
- **The verb refuses a number it cannot give.** A tenth unscheduled visit after
  one planned visit, or a number that repeats a planned VISITNUM, raises a
  DerivationError: map these visits by hand.
- **A record with no study day keeps a null.** One UserWarning gives the count
  of null records and of unscheduled records. For DOMAIN SV, a second
  UserWarning gives the USUBJID + VISITNUM keys that repeat.

## Considered options

- **Calendar days across Day 0 (c1-222 option A).** Rejected: a SAS QC program
  that computes `abs(SVSTDY - VISITDY)` gets a different window and reports a
  false mismatch.
- **Keep the null and warn only (c2-950 option A).** Rejected: VISITNUM stays
  null until someone fixes it by hand.
- **An `unmatched=` flag column (c2-950 option B).** Rejected: the extra column
  is not SDTM and must be dropped before export.

## Consequences

- The decimal numbering is a sponsor convention (the CDISC pilot uses
  `UNSCHEDULED 5.1`). The number can differ from the collected data and from an
  independent program: state the rule in the SDRG.
- With no `tolerance=`, every dated record takes the nearest planned visit, so
  no record is unscheduled. Give a window to use the rule.
- VISITNUM becomes Float64 when a record is unscheduled. With no unscheduled
  record it keeps the TV type.
