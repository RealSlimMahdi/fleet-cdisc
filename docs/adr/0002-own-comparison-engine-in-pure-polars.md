# The comparison engine is Fleet's own, written in pure Polars

Fleet needs a PROC COMPARE equivalent: pair two datasets on keys, report common and missing variables and observations, list every differing value with tolerances, and give a pass or fail. Polars itself only offers `DataFrame.equals` and the unit-test assert in `polars.testing`, and upstream issue pola-rs/polars#14373 has been accepted but unimplemented since February 2024. We decided to write the engine ourselves as Polars expressions in a dedicated comparison package, with the CLI verb, the top-level `fleet.compare` function and the namespace verb as thin callers over it, and to take no new runtime dependency.

## Considered options

- **datacompy** (Capital One) accepts Polars input but hard-requires pandas and numpy, runs its numeric comparison through `np.isclose`, and pins polars below the current release. Adopting it would put pandas back into Fleet's core dependency set and tie our polars upgrades to theirs.
- **diffly** (QuantCo) is pure Polars and actively maintained, but it requires a primary key, has no BY groups, no variable pairing and no pass/fail code in the SAS sense, and brings `rich` with it. The SAS-shaped layer we need is most of the work, so wrapping it saves little and leaves a small third-party package on the QC-critical path that Fleet's qualification strategy would then have to cover.
- **Contributing upstream** to Polars is the right long-term home, but two and a half years of open API debate rule it out of Fleet's critical path.

## Consequences

- The comparison engine is qualified as Fleet code, with its own SAS-parity fixtures, rather than as an inherited dependency.
- Fleet keeps its promise of a pure-Polars core: pandas and numpy stay confined to the optional `io` extra. Amended by ADR-0010: the `io` extra now reads and writes SAS files through the Polars route of pyreadstat, with no pandas.
- If Polars ships a native compare later, `fleet.compare` can delegate to it behind the same three surfaces without changing the comparison report.
