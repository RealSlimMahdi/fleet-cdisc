# An admission bar for clinical verbs, and `verbs()` as the discovery seam

The architecture review of 30 August 2026 (candidate 3, #160) found two problems on the therapeutic-area surface. No written rule said when a verb earns its place, so `metabolic.waist_hip_ratio` (one division) sat next to `vaccine.seroconversion_flag` (a four-fold threshold and a guard against division by zero). And every TA namespace inherits about 41 shared verbs, so autocomplete shows 45 names for the 4 a namespace adds. We decided that a new clinical verb must pass one test, that the test applies forwards only, and that `verbs()` is the discovery seam, not autocomplete.

## The decision

- **Two kinds of verb.** A *chain verb* supplies a mechanism and encodes no clinical rule (`derivation`, `case_when`, `merge`, `pin`). A *clinical verb* encodes a rule a programmer would otherwise copy from a standard or an SAP: a threshold, a constant, a guard, a mapping or an ordering. The terms are in `CONTEXT.md`.
- **The admission bar.** A new clinical verb is added only if this holds: if the verb were deleted, a programmer who rewrites it inline must be able to get a wrong answer, not only type more. A constant typed by hand qualifies, because a typo in `10.8` gives a wrong answer silently. A threshold the caller supplies does not qualify, because the verb is then `case_when` with a shorter name.
- **The citation is part of the bar.** A clinical verb's docstring names the rule it encodes under a `References:` section: the standard or guidance, the year, and the convention when no standard fixes the value. The citation is what a QC programmer checks against the SAP.
- **The bar applies to every clinical verb, in every namespace.** It is about what a verb encodes, not where it lives. It applies to new verbs only.
- **`verbs()` is the discovery seam.** It gains an `origin` column: the path a programmer types to reach the namespace that defines the verb (`sdtm`, `adam`, `adam.metabolic`), or `core` for the verbs every namespace shares. Every row stays, so nothing that reads the frame today breaks.

## Considered options

- **Delete the weak verbs.** Rejected: the shared verbs fill the completion list, not the TA verbs, so deleting four names changes 45 completions into 41. The `fleet migrate` precedent (six spellings of `assign` became one) stays available if the surface keeps growing.
- **Filter autocomplete.** Rejected: Pylance builds completions statically and never calls `__dir__`, and a TA verb must chain into `.derivation()` and `.to_frame()`, so the inherited verbs must stay visible.
- **An `inherited=False` parameter on `verbs()`.** Rejected: the same call would return a different row count depending on a flag. A column and a plain Polars filter do the same work with no new behaviour.
- **A unit test that fails on a docstring without `References:`.** Deferred: the rule costs nothing in prose, and a fake citation passes a format check anyway. Revisit if the surface keeps growing.
- **Admit a verb when a published standard fixes a constant, with no wrong-answer test.** Rejected: it admits every formula the SAP already gives, and the surface grows with verbs that save typing only.

## Grandfathered verbs

These eight fail the bar today and are kept, because the bar applies forwards only. Nothing depends on their removal.

| Verb | Why it fails |
| --- | --- |
| `metabolic.waist_hip_ratio` | One division, one rounding. |
| `metabolic.waist_height_ratio` | One division, one rounding. |
| `neuro.cdrsob_total` | A sum of columns. |
| `neuro.panss_total` | A sum of three columns. |
| `peds.age_days` | One date difference. |
| `vaccine.seroresponse_flag` | The caller supplies the threshold. |
| `ophtha.bcva_criterion` | The caller supplies the threshold and the direction. |
| `onco.tumor_response_flag` | The caller supplies the response list; the default is `is_in(["CR", "PR"])`. |

## Consequences

- Writing the references for the 20 TA verbs that pass exposed what the bar is for. `vaccine.fever_flag` flags strictly above 38.0 °C, while the FDA toxicity grading scale (2007) and the Brighton Collaboration define fever from 38.0 °C. `peds.bmi_category` applies the WHO adult cut-offs from the pediatrics namespace, where age- and sex-specific percentiles apply. `neuro.mmse_category` used severity bands (27, 18, 10) that no published scheme fixes; it now defaults to Tombaugh and McIntyre (1992) and takes the cut-offs as arguments, since admiralneuro ships no MMSE rule. The first two are tracked issues, not a change in this decision.
- A verb whose threshold comes from the SAP rather than a standard can still pass, when the verb adds a guard or an ordering the programmer would get wrong. Its `References:` then names the convention and says "check the SAP".
- `fleet.introspect` is unchanged. `verbs()` is a namespace method, not part of the introspection surface, and the new column is additive.
- The `docs/adr/0006` on the study-run branch keeps its number; this ADR takes 0005, the next free number on `main`.
