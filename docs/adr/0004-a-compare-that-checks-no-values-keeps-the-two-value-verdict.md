# A compare that checks no values keeps the two-value verdict and warns

When the two sides share only their keys, or both have no observations, a compare checks no values. Before this decision, `fleet.compare` and the `.compare()` verb returned a verdict, but `fleet compare` exited 2 ("could not run"), because the CLI held its own check. ADR-0002 makes the CLI, the function and the verb thin callers over one engine, so we decided that the engine alone gives the verdict and the callers only translate it. The verdict keeps its two values, EQUAL and NOT EQUAL. A key-only compare follows the observations: the same key values on both sides are EQUAL, and a one-sided key or variable is NOT EQUAL. Two empty sides are EQUAL. In both cases the report warns that no values were checked. The warning does not change the verdict and does not trigger `on_fail`. A `variables=` restriction that names only keys is an argument mistake, so the engine refuses it with `ComparisonError`.

## Considered options

- **Raise `ComparisonError` whenever nothing is compared.** This breaks a subject-list check (`USUBJID` only on both sides), and it hides the variables summary that shows why nothing matched. PROC COMPARE lists the common and the one-sided variables in this case, and does not stop.
- **A third verdict, NOT COMPARABLE.** Every caller, `on_fail`, the JSON consumers and the VS Code extension would need to learn a third state, and `is_equal` would no longer answer the whole question.
- **A new flag, for example `no_observations`.** An empty domain early in a study (ADAE with no AEs yet) would fail on every rerun. Programmers would learn to ignore the flag, and that hides the real flags next to it.

## Consequences

- `fleet compare` now exits 1, and prints the full report, when the sides share only keys but carry other variables. Before, it exited 2 with a message on stderr only.
- A script that checks only the verdict or the exit code passes a key-only or an empty compare. The warning is the only signal, so a QC reviewer reads it.
