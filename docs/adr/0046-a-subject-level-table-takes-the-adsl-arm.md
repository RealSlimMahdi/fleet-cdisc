# A subject-level table takes the ADSL arm

The alpha audit of November 2026 (c1-432) found that the TLG templates asked for `TRTA` on ADSL. ADaMIG 1.3 puts the arm on ADSL as `TRTxxP` and `TRTxxA`, and `TRTA` on BDS and OCCDS datasets. A conformant ADSL has no `TRTA`, so the demographics and disposition tables stopped ("requires columns [..., 'TRTA', ...]"), and the examples added the planned arm under the actual-arm name: `adsl.with_columns(pl.col("TRT01P").alias("TRTA"))`. For an AE table, ADAE holds `TRTA` and ADSL holds `TRT01A`: the CLI gave no route and no hint. We decided (Mahdi, option A) that the CLI stops with an error that names `--adsl-groupby TRT01A`, and that the user states the ADSL arm column. No column is mapped automatically.

## The decision

```python
# Subject-level table: the arm is TRT01A, else TRT01P.
ard = adsl.tlg.dm.t_summary()

# Event-level table: ADAE by TRTA, big N from ADSL by TRT01A.
ard = adae.tlg.ae.population(adsl, group_col="TRT01A").by("TRTA").template("aet02").to_ard()
```

```bash
fleet tlg run aet01.yaml --data ADAE=adae.parquet --adsl adsl.parquet --adsl-groupby TRT01A
```

- **Subject-level templates** (`dmt01`, `dst01`, `dtht01`, `ent01`: one record per subject, ADSL) default to `TRT01A`. When ADSL has no `TRT01A`, they take `TRT01P`. The spec declares `columns: [TRT01A]` and `arm_fallback = ("TRT01A", "TRT01P")`.
- The fallback applies only when `columns` is not set. A spec or call that names the arm (`columns: [TRT01A]`, `groupby=`, `.by()`, `--groupby`) gets that column or an error, never the planned arm in its place.
- **Event-level templates** (AE, CM, MH, VS, LB, EG, EX, the deviations table on ADDV) keep `TRTA`. Their big N reads ADSL by the same name, or by `adsl_group_col` (`population(adsl, group_col=)`, `--adsl-groupby`, MCP `adsl_groupby`) when ADSL has the arm under another name.
- The CLI and the MCP tool do not auto-detect the arm of a subject-level spec: the template does it, with the same rule as `run_spec`.

## Considered options

- **B: map TRTA to TRT01A for the big N automatically, with a note.** Rejected: in a crossover the N is then the period 1 count, the table looks valid, and a PROC FREQ by period does not match.
- **C: auto-pick a column that is in both frames.** Rejected: the numerators then stop using `TRTA`, so a period 2 AE is counted under the period 1 arm.
- **Default the subject-level templates to TRT01P.** Rejected: the safety tables count subjects by the treatment they received. `TRT01P` is the fallback for an ADSL without `TRT01A` (a study before first dose, or a planned-arm analysis set).

## Consequences

- A table on ADSL now shows `TRT01A` as `group1`, not `TRTA`. The golden ARDs of `dmt01`, `dst01`, `dtht01` and `ent01` changed in that column only.
- Code that passed `groupby="TRTA"` on an ADSL with a `TRTA` alias still runs. The alias is no longer needed.
- In a crossover, `adsl_group_col: TRT01A` gives the period 1 N. The SAP must support it; for a by-period N, derive a period-level denominator.
- References: CDISC ADaMIG 1.3, section 3.1.4 (ADSL treatment variables `TRTxxP`, `TRTxxA`) and section 3.3.2 (BDS `TRTP`, `TRTA`); CDISC ADaM OCCDS 1.1 (`TRTA` on OCCDS).
