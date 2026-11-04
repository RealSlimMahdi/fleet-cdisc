# Verb Cheat Sheet

This cheat sheet summarises the most common verbs across Fleet namespaces. **Every verb name in this page is a clickable link to its docstring**, rendered directly from the source code in the corresponding namespace page.

!!! tip "Single source of truth"
Fleet's documentation is generated directly from Python docstrings via [mkdocstrings](https://mkdocstrings.github.io/) and cross-linked with [autorefs](https://mkdocstrings.github.io/autorefs/). The verb name you click here resolves to the exact method signature, parameters, and examples that the runtime executes — there is no separately maintained reference that can drift out of sync. Renaming a parameter in the source automatically updates this page on the next build.

## Core verbs (available everywhere)

| Verb                                                   | Description                                                                   | Example                                                             |
| ------------------------------------------------------ | ----------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| [`.to_frame()`][fleet.core._verb_mixin.SharedVerbsMixin.to_frame]     | Materialises the pipeline into a Polars DataFrame. Must be called at the end. | `.to_frame()`                                                       |
| [`.derivation()`][fleet.core._verb_mixin.SharedVerbsMixin.derivation] | Injects an arbitrary Polars expression.                                       | `.derivation("AGE", expression="pl.col('AGE_RAW').cast(pl.Int64)")` |
| [`.source()`][fleet.adam.AdamNamespace.source]         | Passes a column through (renaming if `from_col` is provided).                 | `.source("USUBJID")`                                                |
| [`.assign()`][fleet.core._verb_mixin.SharedVerbsMixin.assign]         | Copy a column (`source=`) or hardcode a literal (`value=`).                   | `.assign("DOMAIN", value="DM")`                                     |
| [`.inspect()`][fleet.core._verb_mixin.SharedVerbsMixin.inspect]       | Hard checkpoint — materialises and prints schema/shape/head.                  | `.inspect("after rename")`                                          |
| [`.explain()`][fleet.core._verb_mixin.SharedVerbsMixin.explain]       | Prints the Polars query plan without materialising.                           | `.explain()`                                                        |
| [`.compare()`][fleet.core._verb_mixin.SharedVerbsMixin.compare]       | Compares the chain (candidate) against a base on keys; keeps chaining.        | `.compare(adsl_prod, keys="USUBJID", on_fail="raise")`              |

## SDTM namespace (`df.sdtm`)

| Verb                                                           | Description                                                                 | Example                                                                      |
| -------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| [`.assign()`][fleet.core._verb_mixin.SharedVerbsMixin.assign]  | Copy (`source=`) or hardcode (`value=`) a variable.                         | `.assign("USUBJID", source="patient_id")`                                    |
| [`.assign()`][fleet.core._verb_mixin.SharedVerbsMixin.assign]  | CT-validated assignment: add `ct=` and optional `ct_map=`.                  | `.assign("SEX", source="sex_raw", ct=SEX, ct_map={"M":"M"})`                 |
| [`.date()`][fleet.sdtm.SDTMNamespace.date]                     | Normalise dates to ISO 8601 strings or parse to Date/Datetime.              | `.date("RFSTDTC", source="first_dose_dt")`                                   |
| [`.duration()`][fleet.core._verb_mixin.SharedVerbsMixin.duration]             | Compute elapsed time or CDISC study day.                                    | `.duration("SVSTDY", start="RFSTDTC", end="SVSTDTC")`                        |
| [`.case_when()`][fleet.core._verb_mixin.SharedVerbsMixin.case_when] | Derive a value conditionally over multiple branches.                   | `.case_when("AGEGR1", when=[...], else_="OTHER")`                            |
| [`.condition_add()`][fleet.sdtm.SDTMNamespace.condition_add]   | Single-condition assignment.                                                | `.condition_add("FLAG", condition=..., then_value="Y")`                      |
| [`.ae_aerel()`][fleet.sdtm.SDTMNamespace.ae_aerel]             | AE causality mapping.                                                       | `.ae_aerel("AEREL", source="rel_raw", aerel_map={...})`                      |
| [`.merge()`][fleet.core._verb_mixin.SharedVerbsMixin.merge]    | Join supplementary dataset on key columns.                                  | `.merge(other, on="USUBJID")`                                                |
| [`.nodup()`][fleet.core._verb_mixin.SharedVerbsMixin.nodup]    | Detect/remove duplicates with diagnostics.                                  | `.nodup(subset=["USUBJID","VISIT"])`                                         |
| [`.group_by()`][fleet.sdtm.SDTMNamespace.group_by]             | Aggregate rows by group columns.                                            | `.group_by(by=["USUBJID"], agg=[...])`                                       |
| [`.seq()`][fleet.sdtm.SDTMNamespace.seq]                       | Generate sequence number per group.                                         | `.seq("AESEQ", by=["USUBJID"])`                                              |
| [`.nsv()`][fleet.sdtm.SDTMNamespace.nsv]                       | Derive a Non-Standard Variable with qualifier metadata.                     | `.nsv("SAFETY", source="safety_flag", label="Safety Population Flag")`       |
| [`.export_supp()`][fleet.sdtm.SDTMNamespace.export_supp]       | Export NSV columns as vertical SUPPQUAL (IG ≤3.4).                          | `.export_supp(spec="define.yaml", dataset="DM")`                             |
| [`.from_spec()`][fleet.core._verb_mixin.SharedVerbsMixin.from_spec] | Build the entire pipeline from a `define.yaml` spec.                   | `df.sdtm.from_spec("define.yaml", dataset="DM")`                             |
| [`.validate()`][fleet.core._verb_mixin.SharedVerbsMixin.validate]             | Run CDISC Rules Engine on the resulting frame.                              | `.validate("DM")`                                                            |

## ADaM BDS namespace (`df.adam`)

| Verb                                                                           | Description                                                          | Example                                                                 |
| ------------------------------------------------------------------------------ | -------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| [`.derivation()`][fleet.core._verb_mixin.SharedVerbsMixin.derivation]                         | Arbitrary Polars expression.                                         | `.derivation("AVAL", expression="pl.col('vsorres').cast(pl.Float64)")`  |
| [`.recode()`][fleet.adam.AdamNamespace.recode]                                 | Value remapping with default.                                        | `.recode("PARAM", source="vstest", recode_map={...})`                   |
| [`.assign()`][fleet.core._verb_mixin.SharedVerbsMixin.assign]                  | Copy/rename a column, or hardcode a literal.                         | `.assign("PARAMCD", source="vstestcd")`                                 |
| [`.case_when()`][fleet.core._verb_mixin.SharedVerbsMixin.case_when]            | Multi-branch conditional derivation.                                 | `.case_when("EOSSTT", when=[...])`                                      |
| [`.pick()`][fleet.adam.SharedADaMVerbsMixin.pick]                              | Derive targets from the event with the latest (or first) value across sources. | `.pick("LSTALVDT", events=[...], by=["USUBJID"], order=["LSTALVDT"], mode="last")`   |
| [`.date()`][fleet.adam.AdamNamespace.date]                                     | Parse `--DTC` to analysis date or datetime with optional imputation. | `.date("ADT", source="VSDTC")`                                          |
| [`.duration()`][fleet.core._verb_mixin.SharedVerbsMixin.duration]                             | CDISC study day, elapsed time, or ISO 8601 duration.                 | `.duration("ADY", start="TRTSDT", end="ADT")`                           |
| [`.merge_adsl()`][fleet.adam.AdamNamespace.merge_adsl]                         | Bring ADSL columns onto a BDS dataset.                               | `.merge_adsl(adsl, keep=["TRTSDT","SAFFL"])`                            |
| [`.baseline()`][fleet.adam.AdamNamespace.baseline]                             | Find baseline record per group, broadcast to target.                 | `.baseline("BASE", aval="AVAL", baseline_flag="ABLFL")`                 |
| [`.chg()`][fleet.adam.AdamNamespace.chg]                                       | Change from baseline (`AVAL - BASE`).                                | `.chg("CHG", aval="AVAL", base="BASE")`                                 |
| [`.pchg()`][fleet.adam.AdamNamespace.pchg]                                     | Percent change `(CHG / BASE) * 100`.                                 | `.pchg("PCHG", aval="AVAL", base="BASE")`                               |
| [`.flag()`][fleet.adam.FlagCriterionMixin.flag]                                     | Assign `"Y"` per criteria (expression / `first` / `last`).           | `.flag("ANL01FL", criteria="last", order_by="ADT")`                     |
| [`.bmi()`][fleet.adam.AdamNamespace.bmi]                                       | BMI = weight / (height/100)².                                        | `.bmi("BMI", weight="WEIGHT", height="HEIGHT")`                         |
| [`.bsa()`][fleet.adam.AdamNamespace.bsa]                                       | Body Surface Area (Mosteller / DuBois / Haycock / Gehan-George).     | `.bsa("BSA", weight="WEIGHT", height="HEIGHT")`                         |
| [`.map()`][fleet.adam.AdamNamespace.map]                                       | Mean Arterial Pressure: DBP + (SBP-DBP)/3.                           | `.map("MAP", systolic="SYSBP", diastolic="DIABP")`                      |
| [`.qtc()`][fleet.adam.AdamNamespace.qtc]                                       | Corrected QT (Fridericia / Bazett); QT in ms, RR in ms by default.   | `.qtc("QTCF", qt="QT", rr="RR", rr_unit="ms")`                         |
| [`.nrind()`][fleet.adam.AdamNamespace.nrind]                                   | Normal range indicator: LOW / NORMAL / HIGH.                         | `.nrind("ANRIND", value="AVAL", low="LO", high="HI")`                   |
| [`.on_treatment()`][fleet.adam.AdamNamespace.on_treatment]                     | On-treatment flag within `[TRTSDT, TRTEDT]`.                         | `.on_treatment("ONTRTFL", adt="ADT", trtsdt="TRTSDT", trtedt="TRTEDT")` |
| [`.shift()`][fleet.adam.AdamNamespace.shift]                                   | Categorical shift string (`"NORMAL to HIGH"`).                       | `.shift("SHIFT1", baseline_cat="BNRIND", post_cat="ANRIND")`            |
| [`.merge()`][fleet.core._verb_mixin.SharedVerbsMixin.merge]                    | Left-join an external dataset on key columns.                        | `.merge(other_df, on="USUBJID")`                                        |
| [`.transform()`][fleet.adam.AdamNamespace.transform]                           | Apply an arbitrary frame-level transformation.                       | `.transform(lambda df: df.sort("USUBJID"))`                             |
| [`.derive_summary_records()`][fleet.adam.AdamNamespace.derive_summary_records] | Aggregate by group and append summary rows.                          | `.derive_summary_records(by=["USUBJID"], ...)`                          |
| [`.derive_locf_records()`][fleet.adam.AdamNamespace.derive_locf_records]       | LOCF forward-fill within patient groups.                             | `.derive_locf_records(by=["USUBJID","PARAMCD"])`                        |
| [`.derive_param()`][fleet.adam.AdamNamespace.derive_param]                     | Derive a new parameter and append rows (own frame or `from_dataset=`). | `.derive_param(by=["USUBJID"], parameter_filter={...}, from_dataset=adlb, ...)` |
| [`.from_spec()`][fleet.adam.AdamNamespace.from_spec]                           | Build the entire pipeline from a `define.yaml` spec.                 | `df.adam.from_spec("define.yaml", dataset="ADVS")`                      |
| [`.validate()`][fleet.core._verb_mixin.SharedVerbsMixin.validate]                             | Run CDISC Rules Engine on the resulting frame.                       | `.validate("ADVS")`                                                     |

## ADSL namespace (`df.adam.adsl`)

| Verb                                                           | Description                                                                 | Example                                                       |
| -------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------- |
| [`.first_date()`][fleet.adam.SharedADaMVerbsMixin.first_date] | Earliest date per subject from a second dataset.                     | `.first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")`  |
| [`.last_date()`][fleet.adam.SharedADaMVerbsMixin.last_date]   | Latest date per subject from a second dataset.                       | `.last_date("TRTEDT", from_dataset=ex, date_col="EXENDTC")`   |
| [`.duration()`][fleet.core._verb_mixin.SharedVerbsMixin.duration]             | Number of elapsed days (start to end).                                      | `.duration("TRTDURD", start="TRTSDT", end="TRTEDT")`          |
| [`.flag()`][fleet.adam.FlagCriterionMixin.flag]                | Generalised `"Y"` flag (first/last/max/min/exists/before/after/expression). | `.flag("SAFFL", criteria='pl.col("TRTSDT").is_not_null()', false_value="N")` |
| [`.count_events()`][fleet.adam.SharedADaMVerbsMixin.count_events] | Tally events for each subject.                                   | `.count_events("NUMAE", from_dataset=ae)`                     |
| [`.age_years()`][fleet.adam.ADSLNamespace.age_years]           | Unit-aware age conversion (YEARS, MONTHS, WEEKS, DAYS).                     | `.age_years("AAGE", age_col="AGE", age_unit_col="AGEU")`      |
| [`.age_from_dates()`][fleet.adam.ADSLNamespace.age_from_dates] | Age in completed years between two dates (`unit="decimal"` for days / 365.25). | `.age_from_dates("AAGE", birth_date="BRTHDT", reference_date="TRTSDT")` |
| [`.derive_period()`][fleet.adam.ADSLNamespace.derive_period]   | Create APxxSDT / APxxEDT / TRTxxP subperiod variables.                      | `.derive_period(periods=[{"number": 1, ...}])`                |

## OCCDS namespace (`df.adam.occds`)

| Verb                                                                    | Description                                      | Example                                                                                  |
| ----------------------------------------------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| [`.treatment_emergent()`][fleet.adam.OCCDSNamespace.treatment_emergent] | TRTEMFL flag (admiral `derive_var_trtemfl` rules). | `.treatment_emergent("TRTEMFL", start_date="ASTDT", end_date="AENDT", trtsdt="TRTSDT", trtedt="TRTEDT", end_window=30)` |
| [`.onset_recovery()`][fleet.adam.OCCDSNamespace.onset_recovery]         | Onset and recovery interval flags.               | `.onset_recovery(...)`                                                                   |

## PK namespace (`df.adam.pk`)

| Verb                                                                        | Description                                                         | Example                                                          |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------- |
| [`.blq_flag()`][fleet.adam.pk_namespace.PKNamespace.blq_flag]               | Flag BLQ: `conc < LLOQ`, or no number and a BLQ text in `PCSTRESC`. | `.blq_flag("BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ")`     |
| [`.blq_impute()`][fleet.adam.pk_namespace.PKNamespace.blq_impute]           | Impute BLQ concentrations (`half_lloq`, `zero`, `lloq`, `missing`). | `.blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ")`    |
| [`.blqfn()`][fleet.adam.pk_namespace.PKNamespace.blqfn]                     | Numeric BLQ flag: `1` when BLQ, `0` otherwise.                      | `.blqfn("BLQFN", conc_col="PCSTRESN", lloq_col="PCLLOQ")`        |
| [`.nominal_time()`][fleet.adam.pk_namespace.PKNamespace.nominal_time]       | Nominal elapsed time with unit conversion.                          | `.nominal_time("NTIME", from_col="PCTPTNUM")`                    |
| [`.duration()`][fleet.core._verb_mixin.SharedVerbsMixin.duration]               | Actual elapsed time between datetime columns.                       | `.duration("ATIME", start="EXSTDTC", end="PCDTC", unit="hours")` |
| [`.predose_flag()`][fleet.adam.pk_namespace.PKNamespace.predose_flag]       | Flag pre-dose samples within a window.                              | `.predose_flag("PREDFL", time_col="ATIME")`                      |
| [`.dose_normalized()`][fleet.adam.pk_namespace.PKNamespace.dose_normalized] | Dose-normalise concentration: `conc / dose`.                        | `.dose_normalized("AVALDNM", conc_col="AVAL", dose_col="DOSE")`  |
| [`.evid()`][fleet.adam.pk_namespace.PKNamespace.evid]                       | Derive `EVID` for NONMEM-style datasets.                            | `.evid("EVID")`                                                  |
| [`.mrrlt()`][fleet.adam.pk_namespace.PKNamespace.mrrlt]                     | Clip negative ARRLT to 0 for MRRLT.                                 | `.mrrlt("MRRLT", arrlt_col="ARRLT")`                             |
| [`.log_conc()`][fleet.adam.pk_namespace.PKNamespace.log_conc]               | Log-transform concentration.                                        | `.log_conc("DVL", conc_col="DV")`                                |
| [`.mdv()`][fleet.adam.pk_namespace.PKNamespace.mdv]                         | Derive `MDV` for PopPK datasets.                                    | `.mdv("MDV", conc_col="DV", evid_col="EVID")`                    |
| [`.amt()`][fleet.adam.pk_namespace.PKNamespace.amt]                         | Derive `AMT`: dose amount on dosing records.                        | `.amt("AMT", dose_col="EXDOSE", evid_col="EVID")`                |
| [`.cmt()`][fleet.adam.pk_namespace.PKNamespace.cmt]                         | Derive `CMT` compartment number (NONMEM).                           | `.cmt("CMT", evid_col="EVID", dose_cmt=1, conc_cmt=2)`           |
| [`.avalcat()`][fleet.adam.pk_namespace.PKNamespace.avalcat]                 | Listing-ready categorised analysis value.                           | `.avalcat("AVALCAT1", conc_col="PCSTRESN", lloq_col="PCLLOQ")`   |
| [`.anl_flag()`][fleet.adam.pk_namespace.PKNamespace.anl_flag]               | Analysis flag (`ANL01FL` / `ANL02FL`).                              | `.anl_flag("ANL01FL")`                                           |

## Time-to-event (`df.adam.tte`)

Typed `EventSource` / `CensorSource` objects describe the candidates; the
prebuilt library (`DEATH_EVENT`, `AE_EVENT`, ...) is browsable via
`prebuilt_sources_frame()`. Source frames attach by nickname with `.pin()`.

| Verb                                                             | Description                                                        | Example                                                              |
| ---------------------------------------------------------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------- |
| [`.param()`][fleet.adam.TTENamespace.param]                      | Derive one TTE parameter: earliest event wins, else latest censor. | `.param("OS", "Overall Survival", start_date="TRTSDT", events=[...])` |
| [`.aval()`][fleet.adam.TTENamespace.aval]                        | AVAL (+AVALU) from STARTDT/ADT with CDISC unit conventions.        | `.aval(unit="months")`                                                |
| [`.km_data()`][fleet.adam.TTENamespace.km_data]                  | `(duration, event)` frame for lifelines / scikit-survival.         | `.km_data("OS", by=["TRT01P"])`                                       |

## Trial Design (`df.sdtm` verbs + `fleet.StudyDesign`)

TDD verbs live directly on `df.sdtm` (there is no `.tdd` sub-namespace).
`fleet.StudyDesign` is the define-once aggregate that derives every TDD
domain — see the [Trial Design concepts page](../concepts/tdd.md).

| Verb                                                                                            | Description                                            | Example                                               |
| ------------------------------------------------------------------------------------------------ | ------------------------------------------------------ | ----------------------------------------------------- |
| [`.fetch_structure()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.fetch_structure]                   | Load domain IG structure (packaged offline for 3.4).   | `df.sdtm.fetch_structure("TA")`                       |
| [`.study_header()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.study_header]                         | Hardcode STUDYID and DOMAIN.                           | `.study_header("STUDY01", "TA")`                      |
| [`.add_elements()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.add_elements]                         | Load a `TrialElements` collection (TE).                | `.add_elements(te_rows)`                              |
| [`.add_arms()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.add_arms]                                 | Load a `TrialArms` collection (TA), FK vs TE.          | `.add_arms(ta_rows, te=te_rows)`                      |
| [`.add_visits()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.add_visits]                             | Load a `TrialVisits` collection (TV), FK vs TA.        | `.add_visits(tv_rows, ta=ta_rows)`                    |
| [`.add_parameters()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.add_parameters]                     | Load a `TrialParameters` collection (TS).              | `.add_parameters(ts_rows)`                            |
| [`.add_criteria()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.add_criteria]                         | Load a `TrialCriteria` collection (TI).                | `.add_criteria(ti_rows)`                              |
| [`.add_disease_assessments()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.add_disease_assessments]   | Load a `TrialDiseaseAssessments` collection (TD).      | `.add_disease_assessments(td_rows)`                   |
| [`.add_milestones()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.add_milestones]                     | Load a `TrialMilestones` collection (TM).              | `.add_milestones(tm_rows)`                            |
| [`.element_boundaries()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.element_boundaries]             | Compute element start/end (SE).                        | `.element_boundaries("SESTDTC", "SEENDTC", ...)`      |
| [`.epoch_assign()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.epoch_assign]                         | Assign EPOCH from date ranges or per-subject SE.       | `.epoch_assign("EPOCH", date_col="AESTDTC", se=se)`   |
| [`.visit_map()`][fleet.sdtm._tdd_mixin.TrialDesignMixin.visit_map]                               | Map planned ↔ actual visits (SV).                      | `.visit_map("VISITNUM", "VISIT", ...)`                |
| [`.duration()`][fleet.core._verb_mixin.SharedVerbsMixin.duration]                                 | Derive study day from reference.                       | `.duration("SVSTDY", start="RFSTDTC", end="SVSTDTC")` |

---

## How linking works

Click any verb name in the tables above. Your browser navigates to the corresponding namespace API page and scrolls to the auto-generated heading anchor for that method — a heading rendered live from the Python docstring.

This means:

1. **Parameter accuracy** — the cheat sheet links never describe a parameter that doesn't exist in code.
2. **Examples stay current** — code samples in docstrings are the same ones the test suite exercises.
3. **Discoverability** — IDE hover, docs site, and `help()` in a REPL all read from the same docstring.

If you find a verb missing from this cheat sheet, file an issue or add a row — the link target itself is generated automatically once the method exists in source.
