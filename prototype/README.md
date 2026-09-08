# Prototype: pure-Polars PROC COMPARE

Feasibility spike behind spec issue #99 (`COMPARE-PLAN.md` on main once merged).
Throwaway code, kept as a primary source for the implementation tickets.

What it demonstrates: keyed matching through inner and anti joins, duplicate
key detection, variables summary with base-only, candidate-only and
type-conflict lists, per-variable difference flags with absolute and relative
tolerance and SAS missing-equals-missing semantics, a long value listing with
difference and percent difference, and a SYSINFO-style flag mask.

Run: `uv run python prototype/pl_compare_proto.py` (worked example, then a
1M-row by 20-column benchmark that completed in about 0.14 s on a laptop).

Naming in the prototype predates the glossary: `comp` there is the
**candidate** in `CONTEXT.md`.
