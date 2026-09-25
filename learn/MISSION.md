# Mission: Polars, in the context of Fleet

## Why

Mahdi owns Fleet, but agents write most of the Polars in it. He wants to stop
being a reviewer who nods at code he cannot fully read, and become the person who
can write the verb, judge the expression, and defend the choice of Polars at
PHUSE. Four concrete pulls, all live at once:

1. **Review.** Read a diff in `src/fleet/adam/_mixins.py` and know it is right.
2. **Author.** Add a new Fleet verb end to end, without an agent.
3. **Escape hatch.** Write raw Polars when no Fleet verb exists yet.
4. **Advocate.** Answer "why not Pandas, why not SAS" with mechanics, not vibes.

## Success looks like

- **Rewrite a real SAS DATA step in Polars, unaided.** Given a `BY USUBJID; RETAIN;`
  carry-forward that sets `ABLFL`, produce working Polars without asking anyone.
- **Read `src/fleet/adam/utils.py` top to bottom and explain every expression.**
  Every line of `baseline()`, `chg()`, `nrind()`, `qtc()`, `bsa()`, out loud, including
  why each one is shaped the way it is.
- **Build one ADaM dataset in raw Polars, no Fleet verbs.** To prove he knows what
  Fleet is hiding, not just how to call it.

## Constraints

- **30 to 45 minutes per sitting, a few times a week.** One lesson fits one sitting.
- **Starting point:** advanced SAS and CDISC, intermediate R, beginner Python and Polars.
  Clinical examples need no explanation. Python idioms do.
- **Language:** ASD-STE100 Simplified Technical English. No emoji, no em dashes.
- **Every lesson must cite Fleet source or a primary Polars doc.** No parametric claims.
- **Every code output in a lesson must be run before it is published.** No invented tables.

## Out of scope

- **Fleet-first, footnote the rest.** Core teaching maps to a line of Fleet source.
  Polars surface Fleet never touches gets a one-line "this also exists" note, no more.
- `pl.SQLContext`, the streaming engine, Rust plugins, `scan_iceberg`, GPU execution:
  named only, never drilled.
- Pandas. Fleet forbids it. Lessons mention it only to explain a Polars design choice.
- Python language fundamentals as a subject in their own right. Taught only where a
  Polars idiom depends on one (for example: why `and` fails but `&` works).
