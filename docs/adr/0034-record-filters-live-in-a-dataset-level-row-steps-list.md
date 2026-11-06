# Record filters live in a dataset-level row_steps list

The alpha audit (finding c1-39) found that `to_spec_yaml()` saw only verbs that add a lineage node. A chain with `whereclauses`, `nodup(keep=...)` or `merge` froze to a define.yaml that kept every row, or lost a merged column, with no stub and no warning. A spec block sits under a variable name, and a record filter has no variable. We decided where a frozen filter lives (Mahdi, 4 November 2026, option B).

## The decision

- **A dataset holds an ordered `row_steps:` list.** Each step is a verb call: `algorithm: whereclauses` with `where:`, or `algorithm: nodup` with `subset:`, `sort_by:`, `keep:` and `descending:`.
- **Each step is anchored `after:` a variable** of the dataset (null: before the first variable). `from_spec` runs the variables in file order and runs a step right after its anchor. The anchor keeps the two ordered lists in one order: ASEQ derived after the filter is numbered on the filtered records, in the chain and in the file.
- **`to_spec_yaml()` writes the steps.** A step it cannot write (a `pl.Expr` filter, `derive_param`, `derive_summary_records`, `derive_locf_records`, `filter_pd`) is written as `algorithm: TODO` with the verb name, and a warning names it. `from_spec` refuses a TODO step, an unknown algorithm and an unknown anchor before it derives anything.
- **Define-XML shows the steps as the dataset comment**: a `def:CommentDef` (`COM.<DATASET>.ROWS`) referenced from the ItemGroupDef, in derivation order.
- **A column that a verb added with no lineage node** (`merge`) gets a TODO stub and the warning, never a Predecessor (c1-40).

## Considered options

- **A block under an invented variable name (`- name: FILT1`).** Rejected: the QC programmer reads a variable that the dataset does not have, and one path that forgets to skip it writes a phantom ItemDef.
- **No block; a stub that makes `from_spec` fail until a programmer writes the filter.** Rejected by the decision: the filter could not round-trip, and no tool checks that the hand-written filter equals the inline one.

## Consequences

- A variable-level `algorithm: whereclauses` block still runs; `to_spec_yaml()` no longer writes one.
- A step anchor moves back to the nearest earlier written variable when its own anchor is not written (a dropped scratch column).
- `merge` and the other row-adding verbs remain TODO steps or stubs until they record their own node (issue #98).
