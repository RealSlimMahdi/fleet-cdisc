# An arm path entry is an element or a step

Alpha audit findings c1-247 and c1-781 found that `StudyDesign` derived every
TA value of a position from the element alone. An element had one EPOCH, so a
crossover arm (`BA`: SCRN, B, WO, A) wrote TREATMENT 2 for its first treatment
period. TABRANCH was always `Randomized to <arm>` at the branch point, also
when the branch was a responder extension, and no input reached TATRANS. We
decided the input shape with Mahdi (4 November 2026): the engineering
recommendation for c1-247, and option A for c1-781.

## The decision

- **A path entry is an ETCD string or a step.** A step is
  `{"etcd": ..., "epoch": ..., "tabranch": ..., "tatrans": ...}`. Every key but
  `etcd` is optional, and an unknown key raises. A plain string keeps the
  element's own epoch and the default TABRANCH.
- **EPOCH is the epoch of the position.** A step's `epoch` replaces the
  element's epoch for that row of TA (SDTMIG 3.4 TA.EPOCH: the epoch of "this
  element of the arm"). `from_usdm` writes a step when the epoch of a study
  cell differs from the element's first epoch.
- **TABRANCH keeps its default (c1-781 option A).** It is `Randomized to <arm>`
  on the last element that every arm shares, or on the `randomized_at` element
  when it is given. A step's `tabranch` replaces the text, and its `tatrans`
  gives TATRANS.
- **The audit warns, it does not refuse.** `design.audit()` reports FLEETTD04
  when two arms have the same path and FLEETTD05 when an element repeats in an
  arm with no per-position epoch. A repeated cycle with one epoch stays
  possible.

## Considered options

- **A ValueError on a repeated element.** Rejected: repeated treatment cycles in
  one epoch are a valid design.
- **TABRANCH blank with a warning (c1-781 option B), or an error until
  `randomized_at` is given (option C).** Rejected by the decision: every
  existing randomized design would need a new input.
- **A separate per-arm epoch map.** Rejected: the epoch belongs to a position,
  and an element can appear twice in one arm.

## Consequences

- A non-randomized branch still gets `Randomized to <arm>` until the author
  writes the rule on the step. The QC programmer must check TABRANCH against
  the protocol for each non-randomized study.
- `to_mermaid` cannot draw a per-position epoch, and it warns.
- The YAML round trip keeps the steps.
