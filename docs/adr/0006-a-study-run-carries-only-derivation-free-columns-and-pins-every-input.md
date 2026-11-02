# A study run carries only derivation-free columns from its inputs, and pins every input

`fleet run` left-joined every column a dataset declares from its extra inputs on USUBJID, and pinned nothing, so a define that uses `merge`, `lookup`, `first_date`, `last_date` or `count_events` ran from Python and failed from the CLI (#86). We decided that a study run pins every input under its dataset name, and that the implicit join brings only the carry-through columns: the declared variables that have no derivation. A variable with a derivation comes from its algorithm alone.

## Considered options

- **Keep the join of every declared column, and pin as well.** Rejected: a variable declared with `lookup` from ADSL would arrive twice, and the overwrite guard in `from_spec` would stop the run on the second arrival.
- **No implicit join, pins only.** Rejected: every carried column would need a derivation line. The pilot study alone has 41 such columns across ADVS, ADAE and ADEX, and the Define-XML would gain 41 methods that say "copied".

## Consequences

- "No derivation" has one meaning in a define: carried from an input, unchanged. The glossary entry is "carry-through column".
- A define that declares a column with no derivation and expects Python code to compute it later gets the input's value instead. The column must be left out of the define or given a derivation.
- The join on USUBJID runs only when a step has carry-through columns to bring, so a step with none needs no USUBJID.
