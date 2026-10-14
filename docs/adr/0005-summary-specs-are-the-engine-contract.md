# Summary specs are the engine contract

Every summary table in `fleet.tlg` goes through one engine, `summarize_ard`, and before this decision 21 namespace methods restated its contract by forwarding 13 to 16 keyword arguments each, in 8 different shapes, with two template rules hidden in method bodies: the fill of uncoded terms and the exclusion of the baseline record. We decided that the summary spec is the engine contract. A seam function, `summarize_spec(df, spec, *, groupby, adsl)`, resolves the group column, validates the frame, prepares it from the spec, and calls the engine from the spec's fields. The two hidden rules become spec fields, `uncoded` and `prefilter`, with a default per template, visible in the YAML and settable through the builder. The cards context string and the nested flag are class attributes of the spec class, not YAML fields, because one spec class serves exactly one template method.

## Considered options

- **Route every method through the seam, composites included.** Seven methods do real work between the filter and the engine: the deaths table calls the engine twice on different populations, the shift table builds its own worst-case frame, the demographics table adds a continuous block, and the AE severity, grade and relationship tables reduce to the worst record per subject before counting. Pushing that logic into a spec hides an algorithm in data. These seven keep the keyword engine and share only the preparation step.
- **Keep the uncoded fill and the baseline guard as template facts in code.** An SAP can specify the uncoded label and whether baseline is excluded. A spec that cannot say so is not a spec of the table.
- **Typed switches instead of a prefilter expression.** `exclude_baseline: true` reads well, but every new template would add a boolean to the shared base, and a QC programmer still could not see the exact rule. The expression uses the same whitelisted parser as `dataset_filter` and the SDTM specs.
- **Concentrate every spec class in the shared specs module.** The review's deletion test pointed there. With the domain modules kept as the typed public surface, a domain's spec next to its three-line method is the smaller file to open, so the shared module keeps only the base classes and the building blocks.

## Consequences

- Every column a prefilter names is a required column of the template. A change-from-baseline table on an ADLB or ADEG without ABLFL, and an exposure table on an ADEX without PARCAT1, now refuse to run. Before, the guard was skipped without a message and baseline or per-period records were counted. `prefilter: null` in the spec is the visible escape hatch.
- The order of the preparation step is fixed: uncoded fill, then dataset filter, then prefilter. A dataset filter may therefore reference the uncoded label.
- A composite applies the dataset filter before its own reduction. On the lab shift table the filter used to run after the worst-case reduction, so a filtered-out record could decide a subject's worst range indicator; it no longer can.
- Every column a prefilter names is required through `prefilter_columns()`, read from the expression at validation time, not through the static `required_columns` list. Setting `prefilter=None` lifts the requirement with the rule.
- A user-registered template keeps its signature, `fn(df, *, adsl, spec, groupby)`, and may call the seam or the engine.
