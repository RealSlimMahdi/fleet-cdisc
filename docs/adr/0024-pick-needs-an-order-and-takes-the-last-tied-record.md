# pick needs an order and takes the last tied record

The alpha audit (findings c1-125 and c1-207) found two defects in the record that `pick` selects inside an event. With no `order`, `pick` took the first input record, in both modes, so DTHCAUS for a subject with two fatal AEs depended on row order. With `order` and a tie, `mode="last"` took the first tied record, where SAS `LAST.` and admiral `filter_extreme(mode = "last")` take the last one. No warning appeared. We decided to raise on the first case and to follow SAS on the second (Mahdi, 4 November 2026).

## The decision

- **An event with more than one matching record in a group needs an order**, its own or the top-level one. Without it, `pick` raises `DerivationError` and names the event and the first group. admiral `derive_vars_extreme_event` makes `order` a required argument.
- **A tie on the order keeps input order.** `mode="first"` takes the first tied record and `mode="last"` the last, as SAS `FIRST.` and `LAST.` after PROC SORT EQUALS.
- **A tie whose records set different values gives a warning**, as admiral does with its duplicate check.
- **A missing order value loses in both modes**, as before: it is taken only when every record of the group misses it.

## Considered options

- **Warn on no order and keep the first record.** Rejected: a row-order result has no safe reading, and the docstring already called the order required.
- **A missing order value last in both modes, as ADR-0020 for the flag verbs.** Rejected for this change: tests/unit/test_pick_verb.py pins the present rule (a fatal AE with an end date wins over one with no end date under `mode="last"`), and the audit asked to keep it.

## Consequences

- A `pick` call with no order whose source has two records for one subject now raises. Add the order, for example `"order": ["AESTDTC", "AESEQ"]`.
- `mode="last"` can now give a different record on a tie. Add a sequence variable to the order to remove the dependence on input order.
- The rule across events does not change: with a top-level order, a tie between events goes to the first listed event.
