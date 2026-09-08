# Comparison

`fleet.compare` pairs a **candidate** dataset against a **base** on **keys**, matches variables by name and returns a comparison report; differences never raise. The `.compare()` verb on every namespace ([`SharedVerbsMixin`](core.md#sharedverbsmixin)) wraps it for pipelines, and `fleet compare` wraps it for the shell. See [Comparing Datasets](../concepts/comparison.md) for the rules of equality and the exit codes. A comparison that cannot run raises [`ComparisonError`][fleet.core.exceptions.ComparisonError], documented with the other [exceptions](core.md#exceptions).

## compare

::: fleet.comparison.compare
options:
show_root_heading: true
heading_level: 3

## ComparisonReport

::: fleet.comparison.ComparisonReport
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## Summaries

::: fleet.comparison.DatasetSummary
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

::: fleet.comparison.VariablesSummary
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

::: fleet.comparison.ObservationSummary
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

::: fleet.comparison.ValuesSummary
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

## Settings

The options a comparison ran with, so a run can be reproduced. `abs_tol`, `rel_tol` and `ignore_trailing_whitespace` are the three that change what counts as equal — see [tolerances and trailing whitespace](../concepts/comparison.md#tolerances-and-trailing-whitespace).

::: fleet.comparison.ComparisonSettings
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]
