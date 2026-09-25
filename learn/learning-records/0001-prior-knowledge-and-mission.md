# Prior knowledge and mission established

Mahdi is a statistical programmer: advanced in SAS and CDISC, intermediate in R,
beginner in Python and Polars. He owns Fleet but agents write most of its Polars,
so his goal is to stop being a reviewer who cannot fully read the diff. All four
drivers are live at once: review, author verbs, drop to raw Polars, and defend the
choice at PHUSE.

## Evidence

Stated directly in the mission interview on 2026-09-12, and corroborated by
`AGENTS.md`, which describes the same skill profile.

## Implications

- **Anchor every new concept to SAS, not to Pandas or NumPy.** A comparison to a DATA
  step or `PROC SQL` remerge lands immediately. A comparison to `df.groupby().transform()`
  means nothing to him.
- **Do not assume Python fluency.** When a Polars idiom depends on a Python idiom
  (decorators, `Self` return types, `&` versus `and`), teach the Python part inline in
  one sentence.
- **Fleet source is the textbook.** He chose "read `src/fleet/adam/utils.py` and explain
  every expression" as a success test. That file should be the worked example in most
  lessons, not invented toy data.
- **He did not choose "catch a bug in a Fleet PR" as the success test**, although he did
  choose reviewing as a driver. Read this as: he wants competence first, and will treat
  bug-catching as a by-product rather than a training target. Do not build lessons around
  planted bugs yet.
- **Sessions are 30 to 45 minutes.** One lesson can carry one concept plus a hands-on
  run plus a drill. That is more room than the default 15-minute lesson assumes.
