# A printed tie rounds half away from zero

The audit found that `apply_fmt_fn` printed the stored value with a Python f-string. An f-string rounds the exact binary value, so a printed tie went down or up by chance: 5/16 = 31.25 % printed `31.2`, and 1.005 at `xx.xx` printed `1.00`. SAS `ROUND` and the {cards} default print `31.3` and `1.01`, so a SAS QC program failed PROC COMPARE on these cells. Fleet did not state its rule. We decided to round half away from zero as the only rule (Mahdi, 4 November 2026).

## The decision

- **A tie rounds half away from zero**: 31.25 at `xx.x` prints `31.3`, 2.5 at `xx` prints `3`, -2.25 prints `-2.3`.
- **The value is read at 15 significant digits first**, so a binary artefact such as 31.249999999999996 still counts as the tie 31.25.
- **A value that rounds to zero prints `0.0`**, never `-0.0`.
- **The ARD keeps the unrounded value.** Only `stat_fmt` and the rendered cells change.

The rule is in `apply_fmt_fn`, `format_ard` and `docs/api/tlg.md`.

## Considered options

- **Keep the f-string rule and document it.** Rejected: a SAS QC program fails PROC COMPARE on the tie cells, and neither `ROUND` nor `ROUNDE` gives the same cells.
- **Half away from zero by default, with a spec field for the other rule.** Rejected: two tables of one study could use different rules, and the cell does not show it.

## Consequences

- A QC programmer who uses tern with default settings sees 31.2 where Fleet prints 31.3. Set `round_type = "sas"` in the QC program.
- No golden table changed: the pilot fixture has no tie at the printed precision.
