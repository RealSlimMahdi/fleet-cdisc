# Changelog

All notable changes to Fleet are documented here.

## [Unreleased]

### Alpha audit: high findings

The high findings of the alpha audit (`HIGH-REMAINING.md`), fixed with the decisions of 4 November 2026. ADR-0021 to ADR-0042 record the changed defaults.

#### Added

- `peds.bmi_percentile_category`: BMI-for-age class by age in months and sex from the CDC 2000 (`bmiagerev.csv`) or WHO 2007 (BMI-for-age 5-19 years) reference. `reference=` has no default. The official tables are package data under `fleet/adam/data/growth/`, with sources and SHA-256 in its README; `scripts/regen_growth_references.py` downloads them again. ADR-0026. (c1-161)
- `metabolic.bmi_category_adult`: the WHO adult BMI classes, moved from `peds.bmi_category`. (c1-161)
- `round_digits=` on `bmi`, `bsa`, `map`, `qtc` and `adsl.age_years`, with the SAS `ROUND` rule (half away from zero): 24.25 gives 24.3. (c1-76)
- `nrind(signif_dig=15)`: the value and the limits are compared at 15 significant digits, as admiral `derive_var_anrind`. (c1-77)
- `age_from_dates(unit=)` and `peds.age_years(unit=)`: `"years"` (default) or `"decimal"`. (c1-138)
- `metabolic.body_fat_pct(sex_female_value=)` and `metabolic.visceral_fat_flag(sex_female_value=)`. (c1-160, c1-706)
- `vaccine.fever_flag(inclusive=)`: `False` flags strictly above the threshold. (c1-417)
- `vaccine.seroconversion_flag(lloq_col=, seronegative_fold=)`: the FDA CBER 2007 two-arm rule for a baseline below the LLOQ. (c1-416)
- c1-323: `derive_summary_records(where=...)` filters the source records of the summary. When `where` is None and the source holds a non-null DTYPE, the verb warns.
- c1-406: `confirmed_response_flag(max_nr_ne=1, max_nr_sd=0)` sets the NE and SD limits between a response and its confirmation (ADR-0030).
- `merge(validate=)` takes `"m:1"`, `"1:m"` or `"1:1"`. The rule is checked at `to_frame()`, and the error names the repeated keys (c1-14).
- c1-216: `fleet.validation.rule_scaffolder.scaffold_population_flag_rule()` writes the custom rule FLEET-ADSL-001: SAFFL, ITTFL, FASFL, PPROTFL, RANDFL, ENRLFL and COMPLFL must be Y or N on every ADSL record. `fleet init cfg` with ADaM datasets writes it into the study's custom rules directory.
- c1-39: a define.yaml dataset can hold `row_steps:`, the record filters in pipeline order (`whereclauses`, `nodup`), each anchored `after:` a variable (ADR-0034). `to_spec_yaml()` writes the row steps of a chain, `from_spec` runs each one right after its anchor, and Define-XML shows them as the dataset comment (`def:CommentDef`). A step that a define.yaml cannot hold (a `pl.Expr` filter, `derive_param`, `derive_summary_records`, `derive_locf_records`, `filter_pd`) is written as `algorithm: TODO` with a warning, and `from_spec` refuses it until it is edited. A column that a verb added with no lineage node (`merge`) gets a TODO stub and the warning.
- `StudyDesign` arm paths take a step, `{"etcd", "epoch", "tabranch", "tatrans"}`, for the TA values of one position, and a `randomized_at=` element for the TABRANCH default; `design.audit()` warns on identical arm paths (FLEETTD04) and on an element repeated in an arm with no per-position epoch (FLEETTD05). ADR 0036. (c1-781, c1-247)
- `fleet run` moves SDTM variables with `role: qualifier` or `algorithm: nsv` to a `SUPP<domain>` dataset (IDVAR `<domain>SEQ`), writes the parent without them, and keeps the full frame for later steps; `BuiltDataset.supp` holds it. `fleet define-xml` does not yet write the SUPP ItemGroupDef (step B open). (c1-105)
- A TSVAL over 200 characters is split at a word boundary into TSVAL, TSVAL1..TSVALn; the audit reports any other trial design Char value over 200 characters (FLEETTD03). (c1-246)
- `TrialParameter.tsgrpid` (TSGRPID) and `TrialVisit.arm` (TV.ARM). (c1-782)
- c1-442: `MissingLevel` and the spec field `missing`: a null or blank category value counts in a "Missing" row, last in its block, with big N as the percent base. Defaults per template (DM: SEX, AGEGR1, RACE, ETHNIC; AET03/AET04/relationship: the ranked level; DST01: EOSSTT; ENT01: SITEID; PDT01: DVDECOD). `label=None` writes the count to the ARD `warning` column instead. Builder verb `.missing()`. ADR-0038.
- c1-432: the spec field `adsl_group_col`, the builder argument `population(adsl, group_col=...)` and the CLI flag `--adsl-groupby` (`fleet tlg run`, `fleet tlg explore`; MCP `fleet_tlg_run(adsl_groupby=...)`) name the ADSL arm (TRT01A) when the analysis arm is TRTA.
- c1-273: `fleet.tlg.resolve_groupby(spec, columns, explicit)`, the one arm rule of `fleet tlg run`, `fleet tlg explore` and the MCP tool.
- c1-452: an event count prints in the count cell as `n (%) E` (`2 (50.0%) 3`), with a footnote that explains the form. ADR-0039.
- c1-820: `render_rtf(..., body_title=True)` and `render_listing_rtf(..., body_title=True)` write the title and footnotes in the body at each page break, as SAS ODS RTF BODYTITLE (ADR-0040).
- c1-302: `fleet tlg export --population FILTER` passes an ADSL filter to the spec's `adsl_filter` and shows it in a footnote. There is no built-in default population.
- `occds.treatment_emergent` is a spec verb (ADR-0008 dotted name): a define.yaml derives TRTEMFL with `algorithm: occds.treatment_emergent`, and the MethodDef names `OCCDSNamespace.treatment_emergent`, the method lineage records (c1-488).
- Codelists: `external:` (ExternalCodeList, e.g. MedDRA), `nci_code:` on a codelist or a term (NCI Alias), `extended: true` on a term (`def:ExtendedValue="Yes"`). A codelist whose oid is an NCI code gets `def:StandardOID="STD.CT"` when `study.ct_version` is set; `standard_oid:` is honoured (c1-559).
- Dataset key `is_reference_data:` (c1-561).
- `fleet check` fails when `study.ct_version` or `study.adam_ct_version` in a define.yaml is not the date of the CT package that `study_config.yaml` pins, and names the field to edit; `fleet init ct` prints the same note (`fleet.ct.study_codelists.ct_version_problems`) (c1-766).
- `semantic_errors` names each OID or leaf reference that resolves to nothing, each ValueListDef that no ItemDef uses, a value-level ItemDef longer than its parent, and a CodeList whose DataType differs from its variable (c1-778).
- `DefineSpecGenerator(..., import_study_code=False)` builds the define without importing the spec's `derivations_module` (c1-565).
- c1-576: `save_dataset_json` takes `columns=` (label, length, keySequence, displayFormat, targetDataType), `study_oid=` and `metadata_version_oid=`. `fleet.io.dataset_json.metadata_from_define()` builds them from a define.yaml. `fleet run --format dataset-json`, `fleet tdd build --format dataset-json` and `to_dataset_json` after `from_spec` fill them. New `fleet.core.oids` holds the OID rules that the Define-XML and Dataset-JSON writers share.
- c1-263: each validation report states, per engine run and source, the rules executed, skipped and could not run (`Rules (engine run, official): 90 executed, 313 skipped, 27 could not run`). `ValidationResult.rule_runs` holds the counts. `fleet validate` and the HTML report list the IDs of the rules that could not run; the verb prints the count line only.
- c1-264: the custom-rules run also counts and names the rules that were not loaded (a YAML file that does not parse, or an ID absent from the engine report) and the rules that could not run, with the engine's reason. Rule problems never change the status or the exit code.
- c1-842: frozen, trimmed real CORE 0.15.0 reports under `tests/fixtures/core` (dirty, clean, custom) test the report parser and the exit code with no engine.
- c1-286: `fleet run` prints one line per input with the file it came from (`input DM -> data/sdtm/dm.parquet`, or `built in this run`). A `.json` (Dataset-JSON) file is found as an input, and `load_raw_data` reads `.json` as Dataset-JSON.
- c1-287: `fleet define-xml` warns when a leaf href names a file that the data folder does not hold. `DefineSpecGenerator.leaf_hrefs()` returns the href of each dataset.
- c1-268: `fleet validate --define PATH` (and `ValidationService.validate_datasets(define_xml=)`) gives a Define-XML to CORE (`-dxp`) through the run setup; the header names it. Opt-in only (ADR 0042).
- c1-268: new define.yaml variable key `sdtm_role:` (SDTM role), written as the Define-XML ItemRef `Role`. `fleet init define` fills it from the CDISC Library (ADR 0042).

#### Changed

- **`.date(highest=)` follows admiral `highest_imputation`** (c1-67, c1-74; ADR-0021). `"n"` imputes nothing, `"D"` the day, `"M"` the month and the day: `highest="M"` now imputes `2021` to 2021-01-01 (flag M), `highest="D"` imputes `2021-03` to 2021-03-01. `"Y"` and the time levels `"h"`, `"m"`, `"s"` raise on a `*DT` target, and any `highest=` raises on a `*DTM` target, in both namespaces.
- **A `*DTF` or `*TMF` flag is null where its date is null** (c1-74, c1-69; ADR-0021), also with `highest=` and `impute="none"`.
- **`on_treatment` compares the start with the time when `adt` and `trtsdt` are both date-times** (c1-78; ADR-0022), as admiral `derive_var_ontrtfl`: a pre-dose record on the first dose day is no longer on treatment. The end comparison stays at date level.
- **`duration(out="iso8601")` keeps the sign and writes the clock in parts** (c1-7, Mahdi option A; ADR-0022): `-PT15M`, `PT1H30M`, `PT2H`. It adds one only when `add_one=True` is given (`P9D` from 1 to 10 January; `P10D` with `add_one=True`). Months and years raise; weeks that are not whole give null with a warning.
- **A date verb refuses a numeric date column** (c1-141, c1-117; ADR-0022). `.date()`, `duration`, `study_day`, `on_treatment`, `treatment_emergent`, `onset_recovery`, `age_from_dates`, the `peds` ages and `tte.aval()` raise `DerivationError` with the column and the SAS conversion `pl.date(1960, 1, 1) + pl.duration(days=pl.col(...))`, in place of a date counted from 1970. New public helper `fleet.core.dtc.refuse_number`; `to_day()` takes an optional `verb=`.
- c1-125: `pick` raises `DerivationError` when an event has no order and a group has more than one matching record. Give `"order"` in the event or at top level (ADR-0024).
- c1-207: `pick(mode="last")` takes the last input record of a tie on the order, as SAS `LAST.`, and warns when tied records set different values (ADR-0024).
- c1-18: `nodup(descending=True)` sorts a missing value last, so `keep="first"` keeps the highest value, as SAS PROC SORT BY DESCENDING (ADR-0023). The docstring example "keep latest record" now uses `keep="first"`.
- c1-209: `flag_relative(when="after")` follows `flag_no_ref_groups`: with the default `True`, a group with no landmark gets the flag on every record, as admiral. Pass `flag_no_ref_groups=False` for a post-event flag.
- c1-213: `flag(criteria="exists_after"/"exists_before")` raises `VerbUsageError` for more than one `order_by` column. Build one ordered key column (ADTM).
- `bmi`, `bsa`, `map`, `qtc` and `adsl.age_years` store full precision; they no longer round to 1, 4, 2, 2 and 1 decimals. ADR-0025. (c1-76)
- `adsl.age_from_dates` and `peds.age_years` return Int64 completed years by default, as admiral `derive_vars_aage` and SAS `FLOOR(YRDIF(..., 'AGE'))`. `unit="decimal"` gives days / 365.25 with no default rounding; `round_digits` with completed years raises `VerbUsageError`. ADR-0025. (c1-138)
- `peds.bmi_category` is removed (no rename entry); use `metabolic.bmi_category_adult` for adults or `peds.bmi_percentile_category` for children. (c1-161)
- `count_events` returns Int64 instead of UInt32; `chg` and `pchg` compute in Float64. (c1-137)
- `vaccine.fever_flag` flags at or above the threshold by default (38.0 C gets the flag). ADR-0027. (c1-417)
- `vaccine.seroconversion_flag` needs `lloq_col=`: a column name for the LLOQ rule, or `None` for the plain ratio. ADR-0027. (c1-416)
- `vaccine.event_flag`: `by` is required, `severity_col` defaults to `"AVALC"` (`None` opts out), the default severity values add `"Y"`, `[]` means no value, and a record with missing AVAL and AVALC in a group with no event gets null, as admiralvaccine. ADR-0027. (c1-418)
- `atoxgr`: `unit_var` is a required keyword, as admiral. A row whose unit has no criteria gets null with a warning per term. The docstring states that `ctcae_*` and `daids` hold SI cut-offs and `*_uscv` hold US units. ADR-0028. (c1-329)
- `combine_grades`: `low_desc_var="ATOXDSCL"` and `high_desc_var="ATOXDSCH"` are the defaults and the columns are required; '0' only when the other side is '0' or its description is null, as admiral `derive_var_atoxgr`. ADR-0028. (c1-386)
- c1-317, c1-318: `derive_locf_records` ports admiral. It needs `dataset_ref=` (the expected visits) and `order_by=`, adds a record for each missed visit and for each null value, and sets DTYPE "LOCF" on each imputed record. `imputation="add"` (default), `"update"` or `"update_add"`; `keep_vars=` carries other columns. The first `order_by` column must be in `dataset_ref`, and a null `order_by` value raises (ADR-0029).
- c1-406: `confirmed_response_flag` follows the admiralonco `crsp_y_cr` and `crsp_y_pr` rules, stops at the first PD, and flags only the confirmed record. It warns on null responses, on two assessments on one date, and on a CR followed by a PR or SD. A `responses` value other than CR or PR raises.
- c1-407: `best_overall_response` requires `date_col=`, `reference_date=` and `min_sd_days=`. An SD or NON-CR/NON-PD before the minimum, or with a null date, counts as NE. `min_sd_days=0` switches the rule off (ADR-0031).
- c1-354: `join_adsl()` raises for a requested column that is already on the frame, instead of adding `<col>_right`.
- `merge(keep=)` limits the right dataset only, as SAS `merge ae dm(keep=USUBJID AGE)`: every pipeline column stays. A `keep` name not in the right dataset raises with a did-you-mean. A spec `merge` block raises when its variable is not in the frame after the block (c1-17, ADR-0032).
- A non-key column on both sides of a join raises and is named, in `merge`, `merge_adsl`, `join_adsl`, `first_date`, `last_date` and `count_events`. Before, Fleet added an `X_right` column and kept the left value (c1-12, c1-131, ADR-0032).
- A repeated subject in ADSL (or DM) raises in `merge_adsl`, `join_adsl`, `study_day` and `baseline_flag` with a reference frame, and in the carry-through join of `fleet run`. Identical rows count as one. `merge` warns at `to_frame()` on a many-to-many join (c1-14, ADR-0032).
- `fleet.compare(..., ignore_trailing_whitespace=True)` strips string keys too, before the duplicate-key check, so a SAS-padded USUBJID pairs (c1-63).
- c1-204: `criterion()` gives a null CRITyFL and CRITyFN when the condition is null (for example a missing AVAL), as admiral `derive_vars_crit_flag()`. Write "missing is not met" as `condition=(...).fill_null(False)` (ADR-0033).
- c1-746: a column `@derivation` without `.alias()` writes the column named as the function (AGEC), not its source column (AGE) or a column named `literal`. An explicit alias still wins. The `fleet derivation add --kind column` template ends with `.alias("<name>")`, and the scaffold refuses a name that is not a Python identifier. `from_spec` raises SpecError when a `callable:` writes a column other than its variable.
- `visit_map` numbers a dated record outside every window as an unscheduled visit (last planned VISITNUM + .1, .2, ...; VISIT `UNSCHEDULED 5.1`), warns on null and unscheduled counts and on repeated SV keys, and refuses a number that would reach the next whole number or repeat a planned VISITNUM. ADR 0035. (c2-950)
- `visit_map` window distance is the difference of study-day numbers, now stated in the docstring; `TrialVisits.from_schedule` TVSTRL says "study days, no Day 0". (c1-222)
- `TrialParameter.tsparm` holds 40 characters at most. (c1-246)
- `from_ctgov` writes ACTUAL enrollment as ACTSUB, ESTIMATED as PLANSUB, and neither with no type. (c1-249)
- `StudyDesign`, its row models and `trial_design.yaml` refuse an unknown key, a repeated YAML key (also in `fleet tdd ctgov --write`) and an `arm_names` key that is not an arm. (c1-782)
- `to_mermaid` labels a single arm, escapes quotes, and warns when `from_mermaid` cannot read the design back; the docs name YAML as the lossless round trip. `from_mermaid` accepts `arm_names=`. (c1-660)
- `export_supp` raises on a missing or absent `idvar` (except DM), an absent qualifier, a spec dataset typo, no metadata source, and an unknown RDOMAIN. (c1-102, c1-103)
- c1-428: `apply_fmt_fn` and `format_ard` round a printed tie half away from zero, as SAS `ROUND` and the {cards} default: 5/16 = 31.25 % prints `31.3`, not `31.2`; `-0.04` prints `0.0`. ADR-0037.
- c1-430: a population subject with a null arm is left out of every N with one `UserWarning` that names the arm column and the count, instead of a raw `TypeError`. ADR-0038.
- c1-451: the SOC row of a SOC/PT table prints its subject count (`NERV 2 (50.0%)`); a PARAMCD stub of continuous rows stays blank. A page never ends on a group or section row. ADR-0039.
- c1-453: an LBT04 cell prints `n/N (%)`, and `n/N` when n or N is 0. ADR-0039.
- c1-798, c1-800: AET03, AET04 and the relationship table reduce to the worst value in the engine, after the pools and at the last row level only. A subject on two arms counts once in Total; SOC event counts and header rows count every record; the reduced level has no `n_events`. The ranked column and the reduction key follow `rows` (the last row field, e.g. ASEV); the required columns follow `rows`; empty `rows` are refused.
- c1-436: a row field that the data does not hold stops the table with a `SchemaError` (it was skipped without a message). DM still leaves out a default variable that ADSL lacks, but an explicit `categorical_vars` or `age_var` must exist. A listing column that the user set must exist.
- c1-273: `fleet tlg run`, `fleet tlg explore` and the MCP tool `fleet_tlg_run` group by the spec's `columns:` when it declares one; `--groupby` still wins, and detection is the last step.
- c1-803: the CM docstrings say that every ADCM record counts, prior medications included, unless a filter is set; the `t_summary` example shows the `ATIREL` = `CONCOMITANT` filter.
- c1-820: RTF tables and listings put the title in the Word page header and the footnotes in the page footer by default, as the SAS ODS RTF default. The footer holds `Page X of Y` as Word PAGE and NUMPAGES fields, so every physical page has a correct number. The page budget is measured in points (title, header lines, footnotes, wrapped rows); `rows_per_page` (default 40) stays as a cap (ADR-0040).
- c1-456: a page that starts inside a block repeats its parent rows (parameter, visit, SOC) with " (continued)" and empty cells. The statistic rows of one level stay on one page when they fit. `render_pdf` now uses 40 rows per page by default, as `render_rtf` (ADR-0040).
- c1-470: a spec whose `interactive:` axis default differs from the field that batch reads (`columns[0]`, `adsl_filter`, `dataset_filter`, `statistics`) no longer loads; the error names the axis. Each variant from `enumerate_variants` marks its own choices as `default: true`, so a variant YAML copied from the explorer loads and is its own batch output.
- c1-447: docstrings and CONTEXT.md no longer call the Fleet ARD "{cards}-compatible". The ARD uses the {cards} long layout, but the names differ (`fmt_fn`, `pct` on 0 to 100, big-N rows): convert it before R tools read it.
- Each dataset variable has its own ItemDef `IT.<DATASET>.<VARIABLE>`: STUDYID, USUBJID, AGE, SEX and the other common variables no longer share one ItemDef, so each keeps its own type, length, origin and codelist (c1-558).
- A codelist with no decode on any term is written as EnumeratedItem; a codelist that mixes decoded and bare terms raises `SpecError` that names the list and the term (c1-559).
- With no key, DM, ADSL and TA, TE, TV, TI, TS, TD, TM are `Repeating="No"`, and the trial design datasets (and class TRIAL DESIGN) are `IsReferenceData="Yes"`; `fleet init define` writes the same rule (ADR-0041) (c1-561).
- SDTMIG 3.4 or earlier: a `role: qualifier` (or `algorithm: nsv`) variable in its parent domain stops Define-XML generation with a `SpecError` that names it and its SUPP-- dataset; a SUPPxx dataset gets `Domain` = its parent domain (ADR-0041) (c1-562).
- The study-day `duration` method text: a `*DY` target in days reads "Study day of ASTDT relative to TRTSDT." in place of "Duration from ... in days." (c1-482).
- `fleet check` imports no study code: the spec's `derivations_module` is imported only by `fleet define-xml` (and the API) with method enrichment on, and `DefineSpecGenerator(spec, enrich_methods=False)` imports nothing. The `fleet define-xml` help says that it imports study code (c1-565).
- The pilot ADaM define states the methods the pilot runs: TRTSDT and TRTEDT use `first_date` and `last_date` on the pinned EX, TRTEMFL uses `occds.treatment_emergent`, the ADSL variables carried into ADVS, ADAE and ADEX and the ADAE and ADVS USUBJID are `Predecessor`; the SDTM USUBJID comment names its real source; `cdiscpilot01_spec_driven.py` runs these from the spec (c1-680, c1-488, c1-558).
- c1-576: a Dataset-JSON `itemOID` is now the ItemDef OID of the Define-XML (`IT.STUDYID`, `IT.DM.BRTHDTC`), not always `IT.<dataset>.<variable>`. A string column with no value gets no `length` (it was 200).
- c1-577: a `pl.Date`, `pl.Datetime` or `pl.Time` column goes to Dataset-JSON with `targetDataType: integer` and DATE9., DATETIME20. or TIME8.; `read_dataset_json` reads it back strictly as a date. A column with no `targetDataType` stays ISO text.
- c1-579: `read_dataset_json` reads `float` as `pl.Float64` (it was Float32) and `decimal` as `pl.Float64`; an empty decimal is null, a value that is not a number raises.
- c1-263: findings are dropped by the `Rules_Report` status of their rule (`EXECUTION_ERROR`, spelled with an underscore or a space), not by their message text. A NOT ASSESSED report ends with "No rule executed, so nothing was assessed.", not "No issues found."
- c1-262: docs/validation-strategy.md says ADaM conformance gives NOT ASSESSED until CORE ships ADaM rules, so it is not a qualification activity today.
- c1-286: `fleet run` honours `type:` in `inputs:`. A `type: raw` input, or one named as the dataset being built, comes from the raw directory only. A `type: dataset` input never comes from the raw directory: it comes from the data directory of the standard a define declares it in, else ADaM then SDTM (ADaM step) or SDTM then ADaM (SDTM step). Two files for one dataset in one directory (`dm.parquet` and `dm.csv`) stop the run and name both; this also applies to `fleet tlg`. `--out` is write-only.
- c1-286: before it writes, `fleet run` checks each built dataset against its define (columns, mandatory variables; no type or CT check). A build with no column or a define error stops the run, and the old file is kept.
- c1-287: `fleet run` writes each dataset in `--format`, else its `output_format:`, else the define's `output_format:`, else parquet: the rule of the Define-XML leaf href. `--format` has no default now. A flag that differs from the define warns. `output:` names the Define-XML leaf only; `fleet run` warns when it writes another file name. The docs list `dataset-json`, not `json`.
- c1-291: `fleet run` orders the plan so that a dataset runs after the planned datasets it reads as `type: dataset` inputs; file order breaks ties. ADVS listed before ADSL now reads the ADSL of the same run. Two datasets that read each other stop the plan with both names.
- c1-481: `import_codelists()` with no path now finds `study_config.yaml` in the working folder or a parent folder, as the CLI does. A program in `programs/sdtm` loads the codelists of its study. The CWD fallback stays. The CT API page documents `python.analysis.extraPaths` for editor auto-completion.
- c1-474: `fleet init rules` now prints "Rules cached for reference. CORE runs its own rules; pin the engine with fleet install-engine --version." GUIDE and the validation strategy call the rule snapshot a reference copy and say that the engine version fixes the rules.
- The sponsor rules in `metadata/custom_rules` follow the condition of their sdtmchecks R function (decision A). Each file says "Based on: sdtmchecks::<function>" and its `Description` states any difference that the engine cannot express. Partial-date rules (CE-001, CM-002, LB-005, MH-001, PR-001) flag only `yyyy---dd`, so CMSTDTC = 2020-03 no longer fires. After-death rules read DM.DTHDTC; rules that R limits to investigator records, valid doses or results now do so; AE-015, AE-021, EX-010, EX-011, QS-004, RS-003, TR-004 and TU-004 no longer test the inverse condition; PR-001 and SS-001 to SS-004 have the right class and now run. (c2-918)
- `SDTMCHECKS_TRACKER.md`: a Fidelity column (Same as R / Differs / Removed), no typed Summary totals, CORE-000718 for `check_ae_aestdtc_after_aeendtc`, CORE-000007 and CORE-000705 for DTHFL/DTHDTC, CORE-000186 and CORE-000351 for USUBJID, CORE-000119 and CORE-000213 marked partial, `check_dd_ae_aeout_aedthdtc` in the custom group. (c2-919)
- benchmark: Fleet and R use one ANL01FL tie rule (last record by AESEVN, then AESEQ) and number ASEQ by AESEQ. `run_benchmark.py` compares every row of the smallest scale on 17 variables and exits 1 on a difference; `--max-rows` caps the scale. (c1-484)
- benchmark/REPORT.md: synthetic 64-row source (not CDISC Pilot 01), subject and thread counts, both pipelines near-linear, rpy2 about 36% at 1M and 2M rows, line counts by a stated rule (55 and 89). (c1-483, c1-487)
- docs/validation-strategy.md: 39 parity tests of selected admiral formulas, the BSA method "DuBois", and a table of known differences from admiral (pchg sign, rounding, LOCF record structure). (c1-341)
- docs/index.md, docs/api/ta.md and the TA module docstrings say the TA verbs are inspired by the admiral TA packages, not ports. (c1-343)
- docs/concepts/validation-core.md: a section says that CORE checks only a few CT values, with the 7-value example; `spec_codelists` no longer calls CORE the authority. (c1-344)
- `examples/adnca_example.py` prints a verb map with no check marks and no `actual_time()`; the PK module docstring and the README ADPC line match the code. (c1-342)

#### Fixed

- **`.date()` reads the form of a partial date, not its length** (c1-69; ADR-0021). `2021---15` gives 2021-01-01 (flag M) and `2021-03--T08:30` gives 2021-03-01 (flag D), as admiral `impute_dtc_dt`. `202103` and `foo` give null with a null flag.
- **`.adam.date()` honours `time=` on a `*DTM` target** (c1-119), with the same code as `.sdtm.date()`; before, the time was dropped with no message.
- **`.date("ASTDTM", value="2024-01-15")` gives 2024-01-15T00:00:00** (c1-74), not null.
- **`.date()` to a `*DT` or `*DTM` target reads a `pl.Date` or `pl.Datetime` source** (c1-117) in both namespaces, in place of a raw Polars error.
- **`on_treatment`, `onset_recovery`, `age_from_dates` and the `peds` ages read `--DTC` text by its date portion** (c1-143; ADR-0011), in place of a raw Polars error on timed, partial or blank text. The cheat sheet row of `age_from_dates` now uses `birth_date=` and `reference_date=`, and `examples/cdiscpilot01_spec_driven.py` passes `ASTDT` and `AENDT` to `treatment_emergent`.
- **`tte.aval()` reads each row from its own date or date-time columns** (c1-371): one chain that mixes date and date-time parameters no longer gives a null AVAL for the date parameters.
- **`duration()` reads a `pl.Expr` input by its type** (c1-4): `start=pl.col("TRTSDTM")` now gives the calendar study day (2, -1, -2, 3), as a column name does.
- **`duration()` in hours, minutes or seconds warns on text with no time** (c1-5): the warning gives the column, the count and a hint to `.date()`.
- c1-21: `seq`, `nodup`, `derive_locf_records` and the AE and LB listings keep input order on ties of the sort keys, as PROC SORT EQUALS.
- c1-325: `derive_summary_records`, `sdtm.group_by` and `tte.param` give the same row order at each run (groups in order of their first record).
- c1-210: `flag_exists` and `flag(criteria="exists")` with two or more keys add only the flag column, chain a second time, stay lazy and record lineage.
- `bmi`, `metabolic.waist_hip_ratio` and `metabolic.waist_height_ratio` give null for a zero denominator, not inf or NaN; `derive_param` sets a non-finite new AVAL to null and warns with the count; `nrind` gives null for a NaN value. (c1-84)
- `nrind` no longer gives HIGH or LOW for a value equal to a limit with float noise (1.3 x 88.4 against 114.92). (c1-77)
- `metabolic.bmi_category_adult` (formerly `peds.bmi_category`) gives null for a null, NaN or infinite BMI, and for a value not below the last custom bound. (c1-158)
- `peds.corrected_age` gives null for a null or NaN gestational age. (c1-159, c1-160)
- `metabolic.body_fat_pct` and `metabolic.visceral_fat_flag` give null for a sex that is neither male nor female (U, UNDIFFERENTIATED, null). (c1-160, c1-706)
- `vaccine.aval_adis` raises `DerivationError` for a `lloq_rule` other than `"half"` or `"lloq"`; `atoxgr` raises for a `direction` other than `"L"` or `"H"`. (c1-420)
- c1-324: `derive_summary_records(stat="sum")` gives null, not 0, for a group whose values are all null, as SAS.
- c1-354: ADTTE rows from `tte.param()` carry STUDYID from ADSL as the first column. A subject key with two STUDYID values raises.
- c1-408: the onco docstrings and the ADTTE-style module example run `filter_pd` on a copy before `best_overall_response`, so a response after the first PD does not set BOR.
- `merge(how="full")` gives one key column; a subject on the right only keeps its USUBJID (c1-15).
- `join_adsl` raises on a column that is not in ADSL, with a did-you-mean, before lineage is recorded (c1-131).
- `select(columns=)` raises on an absent name with a did-you-mean, and a single string is one column name (c1-30).
- `assign(ct_map=)` on a numeric source column maps the text form of each value (`{"1": "M"}` or `{1: "M"}`) and gives text; before, it crashed at `to_frame()` (c1-32).
- Under `fk_policy("error")` every `to_frame()`, `write_parquet` and `to_dataset_json` raises on an orphan USUBJID and writes no file; before, only the first call raised and `to_dataset_json` never checked (c1-38, c1-195).
- c1-741: the define.yaml reader keeps a bare `010`, `12:30` or `2024-01-15` as text (no YAML 1.1 octal, sexagesimal or date resolvers), and refuses a duplicate key with its line.
- c1-743: a variable entry with an unknown key (`derivaton:`, `codelst:`) raises SpecError that names the dataset, the variable and the closest known key. `VariableEntry` declares every key of the JSON schema and refuses others.
- c1-732: the Define-XML method text from a docstring ends at a period followed by a space or the end of the text (18.5 and v2.1 stay whole), and asterisks inside a formula are no longer stripped. The generator and the semantic lint share one emphasis pattern.
- c1-538: `fleet init define` writes the SDTMIG `datasetStructure` as `structure:` and the parent class (for example `EVENTS`, `SPECIAL PURPOSE`) as `class:`. ADaM: ADSL gets `SUBJECT LEVEL ANALYSIS DATASET`; a dataset cloned from the BDS template gets no class and a message to set it.
- c1-536: `DatasetChecker(check_ct=True)` warns when a codelist has no items, in place of a silent skip. A failed `fleet define-xml` no longer tells the user to pass `validate_xml=False`, an option the CLI does not have. `fleet init ct` keeps all package terms (decision A).
- c1-169, c1-651: in a define.yaml `pick` block, an event `source: AE` is read as the pinned dataset AE (a missing pin raises PinError), in place of an AttributeError. `algorithm:`, `events:` and `targets:` beside `name:` raise SpecError. docs/concepts/pick.md shows the block under `derivation:` with date columns and no longer claims full round-tripping or semantic equivalence with admiral.
- c1-62: in a string expression of `flag`, `case_when` or `derivation`, `TRTEDT - TRTSDT` of two date columns outside `.dt` raises DerivationError that names `(TRTEDT - TRTSDT).dt.total_days()`. Before, `> 10` compared with 10 microseconds and the flag was wrong with no warning. `parse_expression()` takes an optional `schema=`.
- c1-168, c1-185: `to_spec_yaml()` writes each `.source()` column as `algorithm: assign` (with `source:` only when the input name differs), so the frozen define.yaml reruns. `study_day` stays a TODO stub (a `duration` block would give a day 0). The stub warning now says that `from_spec` fails on a TODO stub until it is replaced. README and docs/index.md no longer call the two forms round-trippable: verbs listed in `fleet.spec_coverage()` round-trip, other verbs emit a TODO stub.
- c1-695: `seq`, `first_date`, `last_date` and `count_events` record a lineage node. `to_spec_yaml()` now writes `algorithm: seq` for AESEQ, and `from_spec` gives AESEQ back. A date or count verb with an inline `from_dataset=` frame writes a TODO stub with a warning, in place of a silent loss.
- c1-40: `to_spec_yaml(predecessor=...)` writes Predecessor only for a column present at the start of the chain (the start plan is kept on the namespace and passed to sub-namespaces). A new column with no lineage node (TRTSDT from `merge`) gets no Predecessor, a TODO stub and the warning. The header note on joins is removed.
- An expression with `is None`, `is not None`, `== None` or `!= None` raises and names `is_null()` / `is_not_null()`. (c1-93)
- `export_supp` writes a float AESEQ as IDVARVAL `1`, a float QVAL with no float noise, a Date as ISO 8601, and drops a blank QVAL; `pk.avalcat` writes `5.0` as `5`. (c1-101, c1-104)
- `visit_map` reads `ref_date` from the DM pin, names a missing `ref_date`, `date_col` or VISITDY column, replaces an existing target column, and takes only visits of the subject's arm. (c1-220, c1-221, c1-223)
- `epoch_assign(se=)` replaces an existing EPOCH column. (c1-221)
- `element_boundaries` takes the next element by start date for any row order. (c1-226)
- `parse_trial_design` reads every line or raises, keeps a sponsor epoch, and raises on an unlabelled fork, a cycle, an orphan node, more than one start node, a code collision and an empty diagram. (c1-250)
- `from_usdm` reads v4 criterion items and v3 population criteria, resolves `usdm:tag`, strips XHTML, prefixes a numeric IETESTCD with IN or EX, raises on a missing category or a code collision, warns on text cut at 200, and gives each study cell its own epoch. (c1-783, c1-247)
- c1-431: a `"*"` pool leaves out records with a null arm, in the counts and in the big N, so Total equals the sum of the arms.
- c1-432: the error for an arm column that ADSL does not hold names `--adsl-groupby` and the ADSL arm columns found.
- c1-435: continuous statistics on a non-numeric value column (a text AVAL, a text AGE) stop with a `SchemaError` that names the column, its type and the cast.
- c1-463: the builder `.by("TRT01A")` runs on a conformant ADSL without TRTA, as the direct call does.
- c2-962: a header row whose filter column is null or blank on every record (AEACN in aet01) gives one `UserWarning`, the same text in the ARD `warning` column of that row, and a line from `check()`.
- c2-968: `t_abnormal` (LBT04) stops when ANRIND holds abnormal codes (H, L) and none of them is in `low_values` or `high_values`; the message says how to set them.
- c1-464: `to_yaml` keeps an explicit `uncoded: null` (as `prefilter: null`), so a reloaded AE spec does not switch the uncoded rule on again.
- c1-813: a wide listing in PDF wraps long cell text, and every column stays on the page.
- aCRF page references: an integer page in a page map is kept as a page string; a missing or non-mapping page map file raises `SpecError`; page map keys that match no variable give one warning; `crf_pages` with no annotated CRF warns; value-level `crf_pages` are read under `DATASET.VARIABLE.<where values>` (c1-563).
- Dangling references: a `crf_pages` `doc:` that matches no annotated CRF or supplemental document href, a key that is not a dataset variable, and a value-level or where-clause variable that its dataset does not declare raise `SpecError` that names DATASET.VARIABLE (c1-778).
- c1-242: `load_raw_data` refuses a transport file with more than one member. The error names the member count and the members, so DM and AE from one PROC COPY no longer read as one table of garbage rows.
- c1-578: NaN and infinity go to Dataset-JSON as null with one warning that names the columns and counts, so the file is valid JSON. A duration column stops the write. `.adam.bmi` gives null for a height of 0.
- c2-943: `read_dataset_json` reads `63.0` in an integer column as 63; `2.5` raises `FleetIOError` with file, column, row and value.
- c1-514: `fleet.compare` with a tolerance: infinity differs from a finite number and from the other infinity, and `inf` equals `inf`, in every mode (R `all.equal`).
- c1-314: the CLI no longer stops with UnicodeEncodeError on a cp1252 stdout (a Windows pipe or redirect). A glyph the code page lacks prints as `\u2713` or `\u2717`. Fleet reads and writes its YAML, JSON and cache files as UTF-8 on every platform.
- c1-526: `fleet add-rule` writes `Scope: Classes: Include: [ALL]`, so a rule for DM, VS or ADSL fires on its domain. `Domains` still sets the scope.
- c1-264: a custom finding whose message holds a phrase such as "operation failed" is no longer deleted.
- c1-269: a relative custom rules path (`--custom-rules metadata/custom_rules`, `custom_rules="metadata/custom_rules"` on the verb or `ValidationService`) and a relative engine path (`FLEET_RULES_ENGINE`, `rules_engine_path=`) are resolved against the working directory before CORE starts in its own folder, so the custom rules run.
- c1-290: a carry-through column from an extra input with two records for one USUBJID stops the run (`join(validate="m:1")`): "ADSL: input EX has 2 records for USUBJID S1 ... List the many-row input first." ADSL no longer gains repeated records silently.
- c1-292: a variable that reads a dataset not declared under `inputs:` stops with "dataset ADSL, variable TRTSDT reads EX: add EX to the inputs: block of ADSL", not with advice to call `.pin()`.
- c1-181, c1-193: the README, quickstart, installation and full pipeline pages run as printed in an empty folder: `uv init` before `uv add`, `uv run` before `fleet` and `python`, and `cd` into the folder that `fleet init cfg --root` makes.
- c1-184, c1-684: the README Quick Demo DM ends with `.keep(...)` in IG order and is no longer called submission-ready (README, docs/index.md card, full pipeline page). The R2R AE chain and the inline pilot DM chain keep only SDTM variables, so `ae.json` and `dm.json` hold no raw columns.
- c1-187: the README, why-fleet, CONTRIBUTING, pipeline and pick pages no longer say that nothing runs before `.to_frame()`. They name the verbs that read data first (`baseline`, `date` to DTC, `whereclauses`, `pick`, `derive_*`, `nodup`). "Zero overhead", "No intermediate DataFrames" and "millions of records in milliseconds" are removed. The GUIDE laziness table lists `date` to DTC as a check.
- c1-591: docs/concepts/pipeline.md imports `SDTMConfig` and `ADAMConfig` from `fleet.core.study_context`. A test resolves every `from fleet... import` in the docs.
- c1-592: installation.md names `.sdtm`, `.adam` and `.tlg` as the DataFrame namespaces, with ADSL and OCCDS under `.adam`.
- c1-674: the ADNCA example writes ADPPK sorted by USUBJID, AFRLT, EVID, CMT: the dose follows the pre-dose sample (ASEQ 2) and the file is the same on each run.
- c1-678: the documented ADAE chain (GUIDE Part 9, cdiscpilot01_inline, r2r_ae_example, tlg_ae_example, llms.txt) imputes as the admiral template: a partial start gets the first day but not before TRTSDT (`min_date="TRTSDT"`), a partial end gets the last day (`impute="last"`).
- c1-476: GUIDE no longer says that old spec names keep working and no longer teaches `algorithm: callable`; three code comments and the schema description use `algorithm: derivation`. A test checks every `algorithm:` in the tracked Markdown against the spec registry.

#### Removed

- The private `_check_fk` helper; the queued FK check of `to_frame()` is the one path (c1-195).
- c1-736: `PipelineDAG.to_snakefile()` and `PipelineDAG.to_airflow_dag()` are removed for the alpha. The Snakefile paths differed from where `fleet run` writes, and an Airflow file for the domain IS did not compile. `to_airflow()`, `to_snakemake()`, `execution_order()` and `generate()` stay. full_pipeline.md section 8 now shows the graph as data.
- c1-44: `@derivation(by=..., set_values_to=...)` (kind "param") and `fleet derivation add --kind param` are removed. The decorator raises VerbUsageError that names `.adam.derive_param()`: kind "param" appended no row and overwrote AVAL.
- c1-264: the shipped custom rule SDTMCHK-VS-001 (DBP > SBP). It compares two records and could never run in CORE (`$SYSBP_VALUE` is never defined).
- 14 sponsor rules that the engine cannot express with the R condition: the visit-order rules EG-001, EX-009, LB-004, QS-002, RS-002, TR-002, TU-003 (the engine sorts unscheduled records too), DS-005, AE-018, AE-019, AE-020, DM-003, DS-006 (an operation filter takes exact values only) and VS-001 (needs a SYSBP/DIABP merge). (c2-918)

### Security

- **A received study package runs no code on read-only commands** (alpha audit 5.2):
  - Expression strings (`derivation(expression=)`, `where=`, `case_when`, `define.yaml` and TLG filters) may use only Polars expression constructors, data types and expression methods. `pl.os.system(...)`, `pl.read_csv(...)`, `pl.DataFrame(...).write_csv(...)`, `.meta`, `.pipe` and `map_*` are refused before evaluation (`c1-88`).
  - `fleet check`, `fleet doctor` and `from_spec` read `codelists.py` as data and no longer run it. A statement that a generated file does not hold stops with its line number; `fleet doctor` prints its other lines (`c1-768`).
  - `fleet check` starts no engine: the run setup asks for the engine version only when a run needs it. The MCP tool `fleet_validate` refuses an engine named by `validation.engine_path` unless the server runs with the new `fleet mcp --trust-study-engine` (`c1-835`).
  - A `.env` file gives Fleet only `CDISC_API_KEY`, and only when the shell has none. `CDISC_BASE_URL`, proxies, `FLEET_RULES_ENGINE` and `FLEET_DEFINE_XSD` now come from the shell only: move them out of `.env` (`c1-763`).
  - The working directory is appended to `sys.path` after the `.env` read, so a file in the study folder never replaces an installed package (`c1-298`).
  - A `define.yaml` dataset name must match `^[A-Z][A-Z0-9]{1,7}$` and an input name `^[A-Za-z][A-Za-z0-9_]*$`, so a name cannot leave the data folder or reach a Snakefile line (`c1-744`).
  - The Define-XML HTML preview runs `define2-1.xsl` with no file or network access; a stylesheet that cannot run skips the preview (`c1-575`).

### Fixed

- **Toxicity grades equal admiral** (ADR-0014, alpha audit package D). The 8 bundled criteria files are generated from the admiral 1.4.1 metadata by `scripts/regen_grading_criteria.R` and keep the admiral text of each term; a frozen admiral grid of 34,146 rows is the CI test.
  - A null BNRIND takes the ULN criteria: ALT 900 with ULN 40 is grade 4, not 0.
  - The unit matches without case: potassium 7.5 in `mmol/L` is grade 4, not null.
  - Each row is graded with the entry of its own DAIDS subgroup and unit: DAIDS `Hemoglobin, Low` 60 g/L is grade 4 for adults and neonates. A term with criteria for several units needs `unit_var=`. Every row keeps its place.
  - CTCAE v5 and v6 INR take the worse of the absolute and the baseline cut-offs (INR 3.0 is grade 3, also with no BASE), as admiral. v4 `Hemoglobin increased` no longer raises; Fibrinogen, Creatinine clearance and Alkaline phosphatase follow admiral.
  - `atoxgr(signif_dig=)` defaults to 15, as admiral.
  - A custom criteria file needs `schema_version: 2` (ordered `case_when` arms); a file in the old format stops with a message.
- **One reader for `--DTC` text** (ADR-0011, alpha audit package A). Every date verb reads `--DTC` through `fleet.core.dtc`:
  - `study_day`, `duration` in days and `visit_map` use the date portion of a timed value (SDTMIG 3.4 section 4.4.4): `2021-03-20T10:30` against `2021-03-15T08:00` is day 6, not null. A `pl.Datetime` gives its date.
  - `duration` adds one **day** before dividing for weeks, months and years (85 days is 2.79 months, not 3.76), gives the raw difference for hours by default, and adds nothing to a negative span (-1, not 0), as admiral `compute_duration`. `tte.aval` has the same sign rule.
  - `baseline_flag` takes the last record strictly before the reference: a record on the reference date counts only when both times show it is earlier. Date-only records on that date are no longer baseline.
  - `epoch_assign(se=)` reads timed and date-only values, treats a blank `SEENDTC` as open and skips a partial one with a warning. On a transition date the time decides; with no time, new `same_day=` decides (`"by_class"` default: `--DTC` earlier element, `--STDTC` later), with a warning for the SDRG.
  - `.sdtm.date()` never guesses: a slash date or a two-digit year raises until `format=` names the layout; a value that is not ISO 8601 becomes null with one warning (count and values), instead of being copied into `--DTC`; `2021-03-15 10:30` becomes `2021-03-15T10:30`. With `time=`, a blank time keeps the date, a partial date takes hyphens (`2021-03--T08:30`) and a time with no date gives `-----T08:30`.
  - `.adam.date()` to a `*DTM` keeps the collected hour and minute (`T10:30` is 10:30:00, flag S), keeps a fraction, and drops an offset with a warning. `min_date` and `max_date` move only an imputed date whose possible range holds the bound; a complete date never moves, and a `*DTM` target refuses them.
  - `first_date` and `last_date` compare dates and give `pl.Date` (`pl.Datetime` for `*DTM`); a partial value is left out with a warning, and new `impute=` imputes it and writes the `*DTF` flag.
  - `select(spec=)` leaves every SDTM column and every `*DTC` as text; ADaM `*DT` and `*DTM` are read from text with no invented time, and a value that is not complete becomes null with a warning. `DatasetChecker` expects text for `*DTC`.
- **Every CORE finding blocks until the study accepts it** (ADR-0017, alpha audit package H, part 1):
  - `fleet validate`, `.validate()` and the MCP tool no longer read an invented `Severity` key: every CORE finding blocks. A DM without COUNTRY now gives `Status: FAIL` and exit 1, not PASS. New `validation.accepted` in `study_config.yaml` lists rule, dataset and reason for a finding the study explains, as in the SDRG; an accepted finding gives `Status: FINDINGS (n)` and shows its reason.
  - New status `NOT ASSESSED` when the engine executed no rule (exit 0). Study-level findings get their own `STUDY` block in a sweep and are information only in a single-dataset run. The last line of `fleet validate` counts each status and the findings.
  - An engine crash, a missing or unreadable report, or a timeout gives `COULD NOT RUN` (exit 2; `ValidationSetupError` on the verb) instead of `FAIL` with `ENGINE-001`, `ERROR-001` or `TIMEOUT-001`. The return code is read before the report. On timeout Fleet stops the engine and all its workers. New `--timeout` on `fleet validate` and `validation.timeout` in the study config (default 300 s).
  - Fleet no longer passes `-rr` to CORE. New `fleet.validation.engine.TESTED_ENGINE_VERSIONS` (0.15.0 and 1.0.0); the report header and `fleet doctor` name an untested CORE version. `fleet install-engine` still installs v0.15 by default; `--version v1.0.0` installs CORE 1.0. CORE 1.0 has no ADaM rules yet: its "No rules were selected" stop reads as `NOT ASSESSED`. New weekly workflow `core-canary.yml` runs Fleet on the newest CORE release.
  - `assign(ct=, ct_map=)` checks the mapped values by default: raw `Unknown` outside the map warns with SEX, C66731 and the value, and the value stays (as SAS PUT with no OTHER=). Null and blank values are never findings; `validate_values=False` or `ct: {validate: false}` in a spec switch the check off. Generated codelist classes list every term in `_terms`, so a term that starts with a digit (`10^9/L`) or shares an attribute name is no longer reported.
- **BLQ comes from the SDTM text, and confirmed response uses every by column** (ADR-0015, alpha audit package E):
  - `blq_flag`, `blqfn`, `blq_impute` and `avalcat` share one BLQ rule: a number below the LLOQ, or no number and a BLQ text in `PCSTRESC` (`<0.1`, `BLQ`, `BQL`, `BLOQ`, `LLOQ`; new `blq_text=`). A record with PCSTRESC `BLQ` and a null PCSTRESN is now BLQFL Y and imputed; before it was skipped with no message. `ALQ`, `>1000` and a missed sample are not BLQ. New `text_col="PCSTRESC"` (a frame without it stops; `text_col=None` for numeric results only) and `numeric_below_lloq=True` (`False` lets only the text decide, as admiral).
  - `avalcat` gives a record with no number that is not BLQ its PCSTRESC text (`>1000`), or null for a missed sample, not `BLQ`.
  - `confirmed_response_flag` checks the confirmation within every `by=` column, not only the first: `by=["STUDYID", "USUBJID"]` no longer flags a subject with one PR. A null by value is a group.
- **SAS files follow SAS rules** (ADR-0010, alpha audit package F):
  - XPT and SAS7BDAT read and write with the `io` extra alone, through the Polars route of pyreadstat; pandas and pyarrow are no longer needed. The `io` extra requires `pyreadstat>=1.3.3`.
  - `save_xpt` writes SAS transport version 5 with the member named as the file (FDA TCG 3.1.1). A `pl.Date` is stored as SAS days with DATE9 (2024-01-15 is 23390), not DATETIME seconds. NaN and infinity become SAS missing. A name over 8 characters, a label over 40 or a value over 200 bytes stops the write instead of being cut. A value that is not ASCII is written as UTF-8 with a warning. New `label=` and `column_labels=` arguments; `fleet run --format xpt`, `fleet tdd build --format xpt` and `DatasetChecker.write_xpt` write the define and IG labels.
  - A blank character value in an XPT or SAS7BDAT file reads as null, the SAS missing value. A variable with no value keeps its SAS type, and TIME formats read as `pl.Time`.
  - Every verb join on user keys matches a missing key to a missing key, as SAS MERGE BY does: `derive_param` keeps the group with a missing ATPT, and `merge`, `pick`, `first_date`, `count_events` and `flag(criteria="exists")` no longer lose such records. `worst_case` never keeps a null over a value.
  - A CSV column with a leading zero (SITEID `001`) reads as text with a warning, types are inferred from every row, and `fleet run` reads define type `text` variables as text, so LBORRES `1.10` stays `1.10`.
  - `fleet compare` types CSV sides across both files: SITEID `001` against `1` differs, AVAL `1.10` against `1.1` is equal, and `--text` keeps a column text. New `blank_is_missing` / `--blank-is-missing` reads `""` as missing on both sides; the default stays exact.
  - `load_raw_data(..., encoding=)` reaches the SAS reader, and `--encoding` is on `fleet compare` and `fleet validate`, so a file from a WLATIN1 SAS session can be read. A keyword the reader does not take raises.
- **The bootstrap pins two CT packages and invents no text** (ADR-0019, alpha audit package H, part 3):
  - `study_config.yaml` gets `ct.adam_package` (ADaM CT). `fleet init cfg` and `fleet new` with ADaM datasets pin `adamct-2023-06-30`, the latest ADaM package on or before the default SDTM package; with another `--package`, new `--adam-package` is required.
  - `fleet init ct` takes each codelist from the first pinned package that holds it, so DTYPE (C81224) comes from ADaM CT. Before, ADaM-only codelists were dropped with no message. A codelist that no pinned package holds stops the command with its ID, and no file is written; a 401 or a network error stops it too.
  - `fleet init ct` writes the terms and decodes into the `codelists:` entries of the `define.yaml` files, so `fleet define-xml` gives a valid `CodeList`. A codelist with no terms is named with the fix.
  - A `codelists.py` from both pins has the marker `__ct_packages__`; `load_codelists` returns a tuple of packages. Two SDTM CT dates still fail `fleet check`.
  - The ADaM `define.yaml` gets `adam_ct_version`, and its Define-XML lists SDTM CT and ADaM CT. `ct_version` now has the publishing set SDTM (SEND for SENDIG) in every define.
  - The scaffold keeps `study.description` and `study.originator` empty when none is given; one message names the empty fields, with no traceback. New `--description` on `fleet init cfg` and `fleet new`. IG template names (TRxxSDT, ANLzzFL) are skipped by the schema name rule.
  - The README python blocks run as written in an empty folder, with inline data, and a test runs them. The schema says that a raw input `path:` is relative to the study root.
- **Define-XML gaps are named, and `--strict` refuses** (ADR-0018, alpha audit package H):
  - `fleet define-xml` emits a `<MethodDef>` per Derived variable by default. A Derived variable with no method text, a `text`, `integer` or `float` item with no `length:` and a `float` item with no `significant_digits:` are listed in one warning, as `DM.SAFFL: no method text (add a comment: or a derivation: block)`. Before, the MethodOID was left out with no message.
  - New `--strict` (`DefineSpecGenerator(spec, strict=True)`) refuses: `SpecError`, exit code 1, no file.
  - New spec key `significant_digits:` on a variable and on a value-level entry, emitted as `SignificantDigits`. The schema refuses it on a type other than `float`, and refuses `length:` on `date` and `datetime`. A schema error is a `SpecSchemaError` that names the path.
  - `fleet check` runs the real generator in strict mode. Before, it ran `DefineValidator`, which read a retired dialect.
  - `DefineXMLGenerator`, `DefineValidator`, `StudyContext.define_schema()` and `define_xml_2_1_schema.json` are removed; use `DefineSpecGenerator(spec).generate(out)` and `fleet check`.
  - The CDISC pilot specs carry `length:`, `significant_digits:`, method text for the inline derivations and `origin: Predecessor` for the ADSL copies; four variables the pipeline does not make are removed from the ADaM spec.
- **TLG numbers count only what the spec states** (ADR-0016, alpha audit package G):
  - `adsl_filter` now selects the subjects of n as well as N: an ADAE record of a subject with SAFFL N is not counted (before, a percentage could pass 100). A subject in ADSL but outside the filter is left out with an INFO note on the `fleet` logger; a subject not in ADSL is left out with a warning. An `adsl_filter` with no `adsl` stops. The deaths table and `lb.t_abnormal` follow the same rule.
  - On a table with continuous statistics, n is the count of non-missing values in the cell, as PROC MEANS N: a null value never counts, and two records of one subject count twice. Q1 and Q3 follow SAS QNTLDEF=5 (1, 2, 3, 4 gives 1.5 and 3.5).
  - `worst_case` stops when a value is not in the order: AEREL `POSSIBLY RELATED` with the default `relationship_order ['N', 'Y']` raises and names the field to set, instead of losing to N. A null or blank value still ranks lowest; ties keep the record order. `sdtm.ae_aerel` says that its default map is Fleet's, not CDISC terminology.
  - `lb.t_shift` and `lb.t_abnormal` take the post-baseline rule from the spec prefilter, default `ONTRTFL = 'Y'` and not the `ABLFL` record. Data without these columns stops with a proposal (`prefilter='pl.col("ADY") > 1'`) instead of counting screening records. An explicit `prefilter: null` survives `to_yaml()`.
  - `eg.t_qtcat` gives one block per parameter and visit, with an n row; the percentage base is that n (new `percent_base="adsl"` selects the big N). A null or blank AVALCAT1 is not counted; two records of one subject in one block stop the table. Visits follow AVISITN and categories AVALCAT1N when present.
  - `VSSummarySpec` rows default to PARAMCD and AVISIT (AVISIT is required), so vst01 no longer pools every visit.
- **ADSL and OCCDS verbs follow the admiral rules they name** (ADR-0012, alpha audit package B):
  - `treatment_emergent` follows admiral `derive_var_trtemfl`: an AE with no start date is Y unless it ended before TRTSDT, an AE that ended before TRTSDT is null, and a start after TRTEDT is Y only within `end_window` days. New required keyword `end_date=` (pass `None` when there is none) and new `end_window=` (required with `trtedt=`). Dates are read with the `--DTC` reader of ADR-0011.
  - `pick` with a top-level `order` keeps the extreme value over all events, as admiral `derive_vars_extreme_event`: `order=["LSTALVDT"], mode="last"` gives the latest date, not the first listed event's date. A tie goes to the first listed event; with no top-level `order` the first listed event with a record still wins. The result no longer depends on the sort engine's order.
  - `recode` types the output from the map: `{"MILD": 1, "MODERATE": 2, "SEVERE": 3}` gives an integer ASEVN, not text. A map that mixes text and numbers raises `DerivationError`.
  - The SAFFL recipes in the README, GUIDE, quickstart, installation, define-yaml and both pilot examples keep placebo subjects (EXDOSE = 0 with PLACEBO in EXTRT, the admiral template rule) and give N to non-members, as ADaMIG 1.3 requires. Both pilot examples now have SAFFL = Y for 5 of 5.
- **One flagged record per group, and units stated for QTc** (ADR-0013, alpha audit package C):
  - `baseline_flag` takes only a record with a result: not null or blank in `--STRESC` (else `--ORRES`, or new `result_col=`), and `--STAT` not NOT DONE. A NOT DONE record on the last date no longer takes the flag. With no result column the verb stops.
  - `baseline_flag` flags one record on a tie: the last by new `order_by=` (default `--SEQ`), then input order, as SAS `LAST.`, with a warning when `order_by=` is not given. Before, every record on the last date got the flag.
  - `flag(criteria="last", where=)` no longer loses the flag when a record that fails `where` ties on `order_by`; ABLFL, BASE and CHG come back. A tie among candidates goes to the last input record (`first`: the first). `flag_all=True` takes the extreme over the records that pass `where`.
  - `qtc` reads RR in ms by default, as admiral `compute_qtc`: QT 400 and RR 800 give QTcF 430.89, not 43.09. New `rr_unit=` (`ms`, `msec`, `s`, `sec`). The verb stops when a value cannot be in its unit.
- **A missing sort key sorts last, as admiral** (ADR-0020). In `flag(criteria="first"/"last")`, `flag_first` and `flag_last` a missing `order_by` value sorts last in each key, as `derive_var_extreme_flag`: `last` now flags an AE with no AESEVN or ASTDT, and `first` flags a record with a missing key when every record of the group misses it. Before, such records never got the flag. Give `where=` for the last non-missing record.

### Changed

- **The verb is the algorithm** (ADR-0008, #146) — a `derivation:` block is the verb call: the `algorithm:` value is the verb name (`assign`, `case_when`, `duration`, `derivation`) and the keys are its keyword arguments (`ct`, `ct_map`, `by`, `else`). The spec registry derives the YAML keys, their types, defaults and required flags from the verb signature; the hand-written `Param` tables, aliases, legacy keys and the spec-only spellings (`assign_ct`, `hardcode_no_ct`, `if_then_else`, `lookup`, `study_day`, `callable`, `ct_codelist`, `else_value`, `groups`, …) are gone. The dialect is `fleet_spec_version: 2`; a version 1 file, or an old name, fails at load with a message that names `fleet migrate --spec`.
  - `ct:` defaults to the variable's `codelist:`, so the id is written once; a `ct_map` with no codelist anywhere is a load-time error.
  - the Define-XML method text keeps the standards vocabulary: one `assign` renders "Direct copy of …", "Value of … mapped to controlled terminology" or "Set to '…' for all records" from the keys given.
  - `fleet.spec_coverage()` rows lose their `aliases` key; `SDTMAlgorithm` / `ADAMAlgorithm` list the verb names; `fleet.core.spec_registry.spec_verb()` replaces `spec_algorithm()`.
  - the `DefineValidator` rules ALG01 to ALG05 are removed: they checked keys the dialect never had.

### Added

- **`fleet migrate --spec <define.yaml> --write`** — rewrites a define.yaml to the verb vocabulary line by line (comments and layout survive) and sets `fleet_spec_version: 2`.
- **Release gates in CI** (alpha audit 5.3):
  - Each CI leg runs the Python in its name; before, the 3.13 and 3.14 legs ran 3.12 (`c1-617`). The define reproducibility test compares canonical XML, so it holds on every Python.
  - The 3.12 leg installs every extra, so the LSP, MCP, migrate and render tests run (`c1-620`), and it runs the eight example scripts (`c1-621`). CI runs on every pull request, also a stacked one (`c1-619`).
  - CI installs from `uv.lock` with `--locked`, and the lock no longer holds the yanked Polars 1.41.0 (now 1.44.2). New `fresh-install.yml` installs the built wheel with no lock, as a user gets it, and runs the tests and examples against it weekly and before each release (`c1-618`).
  - New `scripts/admiral_oracle.py` and weekly `admiral-oracle.yml`: real ADAE shapes through admiral 1.4.1 and Fleet, every cell compared. It found the null-order-key rule of `ANL01FL`, fixed in ADR-0020 (`c1-206`).
  - New tests: real SDTM shapes (time part, partial, blank, tie, missing key) through the date and flag verbs (`c2-972` to `c2-975`); statistics read back from RTF, PPTX and PDF (`c1-860`); every quickstart block runs as written (`c1-848`), which fixed the ADSL block and the `SDTMConfig` import of that page.

### Fixed

- The spec YAML loader reads booleans the YAML 1.2 way (`true`/`false` only), so the `on:` join key of `merge` stays a string (#87).

- **TLG summary specs are the engine contract** (ADR-0005) — one seam, `fleet.tlg.summarize_spec(df, spec, groupby=, adsl=)`, reads every engine argument from the spec; sixteen `df.tlg.<domain>.t_*` methods are now one call on it, and the seven composite tables (AE severity, grade and relationship, deaths, lab shift and abnormal, demographics) share `prepare_frame` before their own logic. Public method signatures are unchanged.
  - two template rules leave method bodies and become spec fields, visible in YAML and settable inline: `uncoded` (an `Uncoded(columns, label)` model, GDSR default `"No Coding Available"` on the AE, CM and MH tables; `null` switches it off) and `prefilter` (an expression string in the same form as `dataset_filter`, applied after it; default per template; `null` switches it off). Builder verbs `.uncoded()` and `.prefilter()` map onto them.
  - every column a prefilter names is a required column: `lb.t_chg` and `eg.t_chg` on a dataset without `ABLFL`, and `ex.t_summary` on a dataset without `PARCAT1`, now raise `SchemaError` instead of counting baseline or per-interval records silently. `check()` reports the missing column.
  - the dataset filter on `lb.t_shift` now bites before the worst-case reduction, as it already did on the AE tables.
  - the AE and VS spec classes moved from `fleet.tlg._specs` to their domain modules; `fleet.tlg.AESummarySpec` and friends are unchanged. `prepare_frame`, `summarize_ard` and `Uncoded` are new public names on `fleet.tlg`.

## [0.2.0a1] — pre-alpha

First pre-alpha on PyPI. It replaces 0.1.0, which is yanked. Install with `pip install --pre fleet-cdisc`.

### Added

- **`verbs()` reports where each verb comes from** — a third column, `origin`, holds the path you type to reach the namespace that defines the verb (`sdtm`, `adam`, `adam.onco`) or `core` for the verbs every namespace shares. A therapeutic-area namespace inherits about 41 verbs; `df.adam.onco.verbs().filter(pl.col("origin") == "adam.onco")` lists the few it adds. Every row stays, so existing readers of the frame are unchanged (#160)
- **Admission bar for clinical verbs** — ADR-0009 writes down when a verb that encodes a clinical rule earns its place: deleting it must let a programmer get a wrong answer, not only type more, and its docstring must cite the rule under `References`. The rule applies to new verbs only; the eight existing verbs that fail it are named in the ADR and kept. The 20 therapeutic-area verbs that pass now carry their references. Glossary terms: verb, chain verb, clinical verb, admission bar (#160)
- **`mmse_category` cut-offs are arguments** — `normal_threshold`, `mild_threshold` and `moderate_threshold` default to the Tombaugh and McIntyre (1992) bands (24 to 30 normal, 19 to 23 mild, 10 to 18 moderate, 9 and below severe) instead of the unsourced 27, 18 and 10. A SAP with other bands passes its own cut-offs (#160)

- **Dataset comparison** — a `PROC COMPARE` analogue in pure Polars (no new dependency), reachable three ways over one engine:
  - `fleet.compare(base, candidate, keys=...)` pairs observations on keys and variables by name, and returns a `ComparisonReport` with the data set, variables, observation and values summaries, the long value listing, named flags (`values_differ`, `base_only_observations`, …) and `is_equal`
  - `.compare(base, keys=..., on_fail="warn")` on every namespace (`sdtm`, `adam`, `adsl`, `occds`, …) — the chain is the candidate, the report stays on `last_comparison`, and `on_fail` speaks the same vocabulary as `.validate()`
  - `fleet compare BASE CANDIDATE --keys K1,K2 [--all]` — exit `0` equal, `1` different, `2` the comparison could not run
  - machine-readable outputs: `report.to_json()` / `save_json(path)` render one JSON document whose keys mirror the report and are additive-only within a major version; `save_listing(path)` writes the complete value listing as parquet; `fleet compare --format json` prints the document and nothing else, `--out differences.parquet` writes the listing
  - tolerances and trailing whitespace: `abs_tol` / `rel_tol` widen equality on the numeric variables (a pair differs when the absolute difference exceeds `max(abs_tol, rel_tol × |base|)`, anchored on the **base** as in SAS), `ignore_trailing_whitespace` makes a legacy SAS dataset's padded character values equal Fleet's stripped ones; exact stays the default, nulls and NaN keep their rule, and the rule in effect shows on the text settings line, the HTML header and the JSON `settings` block. Same three options on every surface: `fleet.compare(...)`, `.compare(...)` and `fleet compare --abs-tol --rel-tol --ignore-trailing-whitespace`
  - HTML report for a reviewer without Python: `report.to_html()` / `save_html_report(path)` render one self-contained page — raised flags as chips, then only the mismatched observations with the base and candidate values side by side, one collapsible block per differing variable, sectioned per group once the listing's `group` column is populated; `fleet compare --report compare.html` writes it
  - duplicate-key override and BY groups: `allow_duplicates` pairs duplicate keys by their position within each key group instead of refusing to run — counting them per side, raising `duplicate_keys` and warning above every report — and `by` prepends the BY variables to the keys, labels every difference with its group, reports the observation and values summaries per group in text, JSON and HTML, and flags the groups found on one side only while the verdict stays global. On every surface: `fleet.compare(...)`, `.compare(...)` and `fleet compare --by TRT01P --allow-duplicates`
  - variable pairs and restriction: `pairs={"WEIGHT": "WT"}` compares two variables named differently on each side, on top of the automatic name matching, and names them after the base throughout the report; `variables=["WEIGHT", "AVISIT"]` narrows the comparison to the variables that matter, ignoring the rest on both sides so a work-in-progress candidate raises no missing-variable flag. On every surface: `fleet.compare(...)`, `.compare(...)` and `fleet compare --pairs WEIGHT=WT --variables WEIGHT,AVISIT`
  - a compare that checks no values keeps the two-value verdict (ADR-0004): sides that share only their keys follow the observations, two empty sides are EQUAL, and the report warns in both cases; `fleet compare` now prints the report and exits `1` for one-sided variables instead of exiting `2`, and a `variables=` list of keys only is refused
  - summary statistics: `report.statistics` gives, per differing numeric variable, the n, mean, std, min and max of the base, the candidate, their difference and its percent, over the matched observations where both sides are finite. A null, NaN or infinite value on either side is left out, so no measure is NaN and the text report, the HTML page and the JSON document show the same numbers (#112)

- **CDISC Library API integration** — native client (`CDISCClient`) for downloading Controlled Terminology directly from the authoritative CDISC Library REST API
  - `CDISCClient.get_packages()` — list available CT versions (SDTM, ADaM)
  - `CDISCClient.get_codelist()` — download a single codelist by NCI concept ID with version pinning
  - Credentials via `.env` file or `CDISC_API_KEY` environment variable
- **CT Code Generator** — `CodelistGenerator` converts CDISC Library JSON into typed Python constants with IDE auto-completion
  - `CodelistGenerator.from_sdtm_ig()` — derive codelists from the SDTM IG (source of truth), scoped to requested domains
  - `CodelistGenerator.from_concept_ids()` — download codelists from an explicit set of NCI concept IDs
  - Generated classes include `_concept_id` attribute, submission value constants, human-readable aliases (e.g. `SEX = C66731`), and `__all__` for clean imports
  - Optional `include_docs` flag to inject CDISC definitions into code comments
- **`fleet` CLI** bootstrapping pipeline and standalone commands:
  - `fleet init cfg` — create `study_config.yaml` with study metadata, IG versions, domains, and directory structure
  - `fleet init define` — generate `define.yaml` pre-populated with standard variables from the CDISC Library IG (SDTM + ADaM)
  - `fleet init ct` — generate `codelists.py` from codelist references in the `define.yaml` files
  - `fleet init-ct` — standalone bootstrap of `codelists.py` from the SDTM IG for given domains
  - `fleet add-ct` — incrementally add domains to an existing `codelists.py` (preserves existing codelists)
  - `fleet define-xml` — generate Define-XML 2.1 from a `define.yaml` specification (with optional HTML preview)
- **Custom Validation Rules** — sponsor-specific CDISC rule authoring and validation workflow:
  - `fleet add-rule` — scaffold a schema-valid rule YAML skeleton (auto-increments ID, uniqueness check across directory)
  - `fleet check-rule` — validate a rule file (YAML syntax + structure + JSON Schema); exits 1 on error for CI gates
  - `custom_rules=` parameter on `.validate()`, `ValidationService.validate_sdtm()`, and `.validate_adam()` — load a directory of rules via the engine's `-lr` flag
  - `validation.custom_rules` in `study_config.yaml` — team-wide default rules directory
  - `fleet init cfg` scaffolds the `custom_rules/` directory and field automatically
  - Header comments in generated rule files include CDISC operator reference link and rule type guide

- **CT assignment now accepts codelist classes** (today: `assign(ct=...)`) — pass a generated class (e.g. `SEX`) instead of a raw NCI string; `ct_map` is optional when raw data already matches CDISC submission values

- **Spec-driven CT checks use the study's `codelists.py`** — inside a study, `from_spec` resolves a `ct_codelist:` ID to the class of that ID in the generated `codelists.py`, so `algorithm: assign_ct` gives the same "values not in codelist" warning as `.assign(..., ct=<class>)`; before, the spec copied values unvalidated unless a CT file was loaded (#131)
  - stale detection: `codelists.py` gets a `__ct_package__` marker; a file from another package than `ct.package`, mixing packages, missing a referenced codelist, or missing warns once in `from_spec`, fails `fleet check` and shows in `fleet doctor`; `fleet add-ct --package` refuses another package

- **Admiral-parity expansion** — new core computations and record-generating verbs:
  - `utils.py`: `bsa()` (Body Surface Area, 4 methods), `mean_arterial_pressure()`, `qtc()` (Fridericia/Bazett), `age_in_years()` (unit-aware), `extreme_flag()` (min/max per group)
  - `df.adam`: `.bsa()`, `.map()`, `.qtc()` — namespace wrappers for the new computations
  - `df.adam`: `.derive_summary_records()` — aggregate by group and append summary rows (mean, sum, min, max, median, count)
  - `df.adam`: `.derive_locf_records()` — forward-fill (LOCF) within patient groups
  - `df.adam`: `.derive_param()` — pivot source parameters, compute a new AVAL, and append as new records (e.g. BMI from HEIGHT+WEIGHT)
  - `df.adam.adsl`: `.age_years()` — unit-aware age conversion (YEARS, MONTHS, WEEKS, DAYS)
  - `df.adam.adsl`: `.derive_period()` — create standard Subperiod/Phase variables (APxxSDT, APxxEDT, TRTxxP)
  - Spec-driven support: `bsa`, `map`, `qtc` are available as `algorithm` values in `define.yaml`
- `StudyContext.init()` — scaffolds a new study workspace (folder tree, `study_config.yaml`) with full IG/CT/domain configuration; raises `StudyConfigError` if already initialised
- `DefineScaffolder` — queries CDISC Library IG to generate `define.yaml` pre-populated with standard variables, types, labels, mandatory flags, and codelist references
- Evolved `StudyConfig` model with `SDTMConfig`, `ADAMConfig`, `CTConfig` sub-models for IG versions, domains, and CT package
- MkDocs documentation site with Material theme
- `mike` versioned deployment to GitHub Pages
- Pre-executed example notebook: ADSL pipeline (CDISCPILOT01)
- `llms.txt` for LLM-friendly documentation

### Changed

- **Polars stays below 2.0**: the requirement is now `polars>=1.41,<2`. Polars 2.0 runs lazy queries on the streaming engine by default, which does not keep the row order of joins, and it removes the cast from a string to a date. Fleet moves to Polars 2.0 after its tests pass on it.
- **Python 3.12 to 3.14, httpx below 1.0**: the requirements are now `requires-python = ">=3.12,<3.15"` and `httpx>=0.27,<1`. On Python 3.15, Polars 1.x Series methods return None, so `import fleet` now stops there with an `ImportError` that gives a working command. httpx 1.0 pre-releases change the `Client` constructor, and a `--pre` install picked them up, so `fleet install-engine` and the CDISC Library commands stopped with a `TypeError`.
- **Spec parameter facts are checked against the verb signature** (ADR-0007, #179 phase 1) — the parity test now compares every `Param` of a spec algorithm with `inspect.signature()` of its verb: the spec may be stricter than the verb, never looser. The ten spec-only defaults are gone, so a define.yaml must state `aval`, `low` and `high` for `nrind`, the three dates for `on_treatment`, `term_var` for `atoxgr`, `on` for `merge` and `lookup`, and `agg` for `group_by`; `ct_codelist` is required on `assign_ct` and `hardcode_ct`, as the define.yaml concept doc already stated. A missing key is a load-time error
- **One validation HTML page**: `fleet validate --report` and `ValidationResult.save_html_report()` write the same page (`fleet.validation.models.write_html_report()`): a status row per dataset, then one row per finding. Every cell is HTML-escaped, so a `<` in a data value or a custom rule message no longer breaks the page or injects markup; `rows_affected=0` is shown (#119)

- **API simplification**: therapeutic-area namespaces (`onco`, `ophtha`, `peds`, `vaccine`, `metabolic`, `neuro`) and ADaM sub-structures (`adsl`, `occds`) are now accessed via `df.adam.<name>` instead of `df.<name>` — reduces registered namespaces from 10 to 2 (`df.sdtm` and `df.adam`)

### Fixed

- **Define-XML `FormalExpression` names the method the run records**: the verb the algorithm dispatches to, by the class that defines it on the define's own namespace, as `VariableNode.method` does (the `fleet lsp` hover names the defining class too). ADaM defines named `SDTMNamespace` and rendered calls that do not exist, such as `study_day('ADY', end=..., start=...)`; ADY now reads `fleet.core._verb_mixin.SharedVerbsMixin.duration('ADY', end='ASTDT', start='TRTSDT')` (#93)

## [0.1.0] — 2025-01-01

### Added

- `df.sdtm` namespace — 14 SDTM derivation verbs
- `df.adam` namespace — 22 ADaM BDS derivation verbs, with `df.adam.adsl` (8 patient-level verbs), `df.adam.occds` (5 occurrence verbs), and 6 TA extensions
- Define-XML 2.1 generation from `define.yaml`
- Define-XML validation against CDISC schema
- Controlled terminology loading and validation
- `StudyContext` and `PipelineDAG` for spec-driven pipelines
- CDISCPILOT01 example dataset and pipeline
- Pytest suite with fixtures
