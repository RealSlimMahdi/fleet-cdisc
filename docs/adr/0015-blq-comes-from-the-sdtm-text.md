# BLQ comes from the SDTM text

The alpha audit of 2 November 2026 (package E) found that `blq_flag`, `blqfn` and `blq_impute` read only the number in PCSTRESN. SDTM keeps a BLQ result only as text in PCSTRESC, with PCSTRESN null, so each SDTM-coded BLQ record was skipped with no message: not flagged, not imputed. `avalcat` did the opposite and called every record with no number BLQ, a missed sample and an above-range result included. We decided that the four verbs share one BLQ rule, on positive evidence only.

## The decision

- **One rule.** A record is BLQ when its number is below the LLOQ, or it has no number and its text matches a BLQ text. PCSTAT is not read: NOT DONE means no result, not a low one.
- **The text list is a default** (Mahdi, Q2 A). A text that starts with `<`, or is `BLQ`, `BQL`, `BLOQ` or `LLOQ` (any case). `ALQ` and `>1000` never match. `blq_text=` replaces the list, because the data transfer agreement decides it.
- **A number below the LLOQ is BLQ** (Mahdi, Q3 A), as the ADaM popPK 1.0 BLQFL text supports. `numeric_below_lloq=False` lets only the text decide, as admiral does, for a SAP that wants it.
- **The text column is expected** (Mahdi, Q4 A). `text_col="PCSTRESC"` by default; a frame without it stops, and `text_col=None` states that the frame holds numeric results only, as `evid_col` and `dtype_col` do in the same namespace.
- **AVALCAT1 keeps the source text** (Mahdi, Q1 A). A record with no number that is not BLQ gets its PCSTRESC text (`>1000`), or null for a missed sample.

## Considered options

- **AVALCAT1 always null for such records** (Q1 B). Rejected: the listing shows the same blank for an above-range result and a missed sample.
- **A short text list, or no default** (Q2 B, C). Rejected: `BQL` and `BLOQ` would pass with no sign, or every call would need the list.
- **Only the text decides** (Q3 B) as the default. Rejected: a value below the LLOQ would enter the analysis as a measured number.

## Consequences

- Existing calls on a frame without PCSTRESC must add `text_col=None` once.
- `adnca_example.py` now flags and imputes its 4 BLQ records, and its popPK DV comes from PCSTRESN, so a BLQ record keeps DV null and MDV 1.
