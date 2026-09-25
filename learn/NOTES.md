# Teaching Notes

Working scratchpad. Preferences and observations that shape lesson design.

## Stated preferences

- **Session shape:** 30 to 45 minutes, a few times a week. One lesson per sitting.
- **Scope:** Fleet-first. Footnote anything Fleet does not use.
- **Workspace:** `learn/` inside the Fleet repo, gitignored. Lessons may therefore
  link to Fleet source by relative path and stay correct.
- **Prose style:** ASD-STE100 Simplified Technical English. Brief, plain words, one
  idea per sentence. Commas and full stops. No emoji, no em dashes.

## Working assumptions about the learner

- **SAS and CDISC are the anchor.** A comparison to a DATA step, `PROC SQL`, or
  `RETAIN` lands instantly. A comparison to Pandas or NumPy does not.
- **R is intermediate.** `dplyr` mental models are available but are a trap: Polars
  `group_by` returns one row per group, `over()` does not. Flag the difference rather
  than leaning on the similarity.
- **Python is the beginner surface, not Polars alone.** When a Polars idiom depends on
  a Python idiom, teach the Python idiom in one line, in place.

## Lesson design rules for this workspace

- **Never publish unverified output.** Run every snippet with `uv run python` first and
  paste the real table. Polars formats output precisely; a fabricated table is obvious
  and destroys trust.
- **Cite Fleet source, not toy examples.** The mission is Fleet. Use `src/fleet/adam/utils.py`
  and friends as the worked example wherever possible.
- **One new idea per lesson.** Anything else is a hook to the next lesson.
- **Record the Polars version.** Currently 1.41.0. The API moves; lessons should say
  what they were checked against.

## Observations

- 2026-09-12: Workspace created. Lesson 01 written on expressions and contexts.
  No evidence of understanding yet, only exposure. Next session should open with
  retrieval, not new material.
