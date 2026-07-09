# Interactive Explorer — One Definition, Two Run Modes

Interactive exploration apps and batch TLG programs usually drift apart because
the table definition lives twice — once in the app's modules, once in the
production scripts. Fleet avoids that structurally: the TLG spec YAML **is** the
definition, and both run modes consume the same file through the same engine.

## Declare degrees of freedom on the spec

Add an `interactive:` block to a TLG spec. Every choice is just a value for an
existing spec field — a widget is a spec-field selector, nothing more:

```yaml
template: aet01
schema_version: 1
adsl_filter: 'pl.col("SAFFL") == "Y"'
statistics: [n_subjects, n_pct]

interactive:
  population:                            # -> adsl_filter
    - {label: Safety, filter: 'pl.col("SAFFL") == "Y"', default: true}
    - {label: All subjects, filter: null}
  dataset_filter:                        # -> dataset_filter
    - {label: All AEs, filter: null, default: true}
    - {label: Serious only, filter: 'pl.col("AESER") == "Y"'}
  stats:                                 # -> statistics
    - {label: "n (%)", statistics: [n_subjects, n_pct], default: true}
    - {label: "+ events", statistics: [n_subjects, n_pct, n_events]}
```

Axes: `groupby` (arm column), `population` (ADSL filter presets),
`dataset_filter`, and `stats`. Each axis needs exactly one `default: true`;
an absent axis stays fixed at the spec value.

## Two run modes, same artifact

```bash
# Batch — renders the default variant (submission output):
fleet tlg run examples/tlg_specs/aet01.yaml --data adae.parquet --adsl adsl.parquet -o out/

# Interactive — one self-contained HTML file, no server, no new dependencies:
fleet tlg explore examples/tlg_specs/aet01.yaml --data adae.parquet --adsl adsl.parquet -o explorer.html
```

The explorer pre-renders **every declared variant** through the identical
`spec → ARD → render` path and embeds, per variant: the HTML fragment, the ARD
as downloadable JSON (for QC), and the exact spec YAML in a "show definition"
panel. The embedded JavaScript only shows/hides pre-rendered fragments — no
statistics or layout logic exists client-side, so there is no second
implementation that could drift. Works from a shared drive; makes no network
requests.

## Why drift is impossible

- The batch output **is** the explorer's default variant — same functions, same
  build. A golden test pins them byte-identical.
- Promotion needs no transcription: the "show definition" panel displays the
  current view's spec YAML; adopting it means saving that YAML into your specs
  directory, which the batch run then consumes.

## Limits

- Variant space is the cartesian product of declared choices: hard error above
  500 variants, warning above 100.
- Views are sanctioned-only (declared choices, not free-form filtering) — every
  number a reviewer sees was produced by the validated engine at build time.
