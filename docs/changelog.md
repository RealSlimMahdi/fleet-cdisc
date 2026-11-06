# Changelog

All notable changes to Fleet are documented here.

## [Unreleased]

### Study run

#### Added

- `examples/minipilot`: a small study with raw CSV files and two define
  files that `fleet run` and `build_dag` run end to end, DM, AE, VS and EX to
  ADSL, ADVS, ADAE and ADEX (c1-347). ADVS takes AVAL from VSSTRESN, and ABLFL
  flags the last record with a non-missing AVAL on or before TRTSDT, and CHG
  and PCHG are only on post-baseline records. The page *Study run end to end
  (MINIPILOT)* says why the study exists and how to use it.
- `chg(post_baseline=)` and `pchg(post_baseline=)`: a condition that marks the
  post-baseline records; the other records get null (ADaMIG 1.3, section
  3.3.4). The default (`None`) keeps a value on every record. A define takes
  it as `post_baseline:`.
- `optional: true` on a define variable with no derivation: `fleet run` may
  write the dataset without it (ADR 0053).

#### Changed

- `fleet run` and `run_study` stop when a declared variable with no
  derivation is in no input; before, the dataset was written without it and
  the run exited 0. `--no-strict` (`strict=False`) turns the stop into a
  warning (ADR 0053).
- The CDISCPILOT01 ADaM define derives SAFFL and ITTFL (`algorithm: flag`),
  and the spec-driven example no longer derives them inline. The SDTM define
  marks RFXSTDTC and RFXENDTC `optional: true`.

### Alpha audit: medium and low findings

The medium and low findings of the alpha audit (`ML-REMAINING.md`, rechecked on 5 November 2026), fixed where no clinical decision was needed. Engineering choices follow the recommendation of each finding. ADR-0047 to ADR-0052 record the changed defaults.

#### Added

- `fleet.ct.terms.terms_for(ct, validator=, study_classes=, define_items=)`: one lookup of the terms of a codelist, in a fixed order (loaded validator, codelist class, study `codelists.py` classes, define items). The MCP tool `fleet_ct_terms` uses it, so it answers in a study with `codelists.py` and no loaded CT file. The source-path CT warnings of `assign` name `fleet init ct` (c1-35, part: the `assign` paths move to it with c1-33).
- `ComparisonFailed`, a subclass of `ComparisonError`: `.compare(..., on_fail="raise")` raises it when the datasets differ, so `except ComparisonFailed` catches the QC finding only and not a comparison that could not run (c1-50).
- c1-64: a namespace prints as "SDTM pipeline, not materialised. Call .to_frame() to see the data." (or ADaM); the `verbs()` example prints every row with `pl.Config(tbl_rows=-1, fmt_str_lengths=200)`.
- c1-749: the `fleet` command line writes every WARNING of the `fleet` logger to stderr (`fleet.core.log.enable_cli_warnings`); `fleet init define` stops with exit 1 when no requested domain is in the IG, and a skipped domain (or one with no codelists in `fleet init ct`) is a `UserWarning` for library users.
- c1-543: `fleet check` gives a FAIL row when `study_config.yaml` and a define disagree on the standard, the IG version (3-4 and 3.4 are equal) or the study id.
- c1-550: `fleet new` (`StudyContext.init`) writes a `.gitignore` with `.env` when the study has none.
- c1-751: `CDISCClient.get(path)` is public; tests cover `RulesScaffolder` (domain files, the `_ALL` file, no overwrite without `force`).
- `derive_param(constant_by=, constant_parameters=)`: a parameter measured once per subject (height at screening) joins each visit, as admiral `constant_by_vars` (c1-320, ADR-0047).
- `derive_summary_records(set_values_to=)` evaluates a `pl.Expr` value per group, for example `ADT=pl.col("ADT").min()` (c1-326).
- `.adam` on every ADaM sub-namespace goes back to the BDS namespace with the pins, lineage and domain of the chain: `adae.adam.occds.treatment_emergent(...).adam.on_treatment(...)` (c1-337).
- `tte.param()` carries the ADSL flag of the start date: `<start>DTF` as STARTDTF and, with `create_datetime=True`, `<start>TMF` as STARTTMF, as admiral `derive_param_tte` (c1-358).
- c2-lead-1: `adam.pk.predose_flag(include_zero=True)` also flags time 0, for a nominal time column (NFRLT).
- c1-395: `adam.pk.avalcat(digits=)` rounds the number text to significant digits (default `None`, no rounding).
- c1-414: `src/fleet/THIRD_PARTY_NOTICES` ships in the package. It names admiral (the grading criteria data, ADR-0014) and admiralophtha with the Apache License 2.0 text. The ophtha module docstring says "inspired by ... (not ports)", and the test comment calls admiral Apache-2.0, not MIT.
- c1-439: `Row.order_by` orders the levels of a row field by a numeric column. Without it, the engine takes `<field>N` when the dataset has it, so AVISIT sorts by AVISITN (Baseline, Week 2, Week 4, Week 12) and AGEGR1 by AGEGR1N (ADR-0049).
- c2-965: `DMSummarySpec(continuous_vars={"AGE": "Age (yr)", "HEIGHTBL": "Height (cm)"})` and the builder verb `.continuous({...})` put several continuous blocks in one demographics table. `age_var` is removed (no alias).
- c1-502: `LBListingSpec.prefilter` holds the abnormal-record rule of the lab listing; it applies after `dataset_filter`, and `prefilter=None` lists every record.
- c1-817: the builder `to_html`, `to_rtf`, `to_pdf` and `to_pptx` take `rows_per_page`. Every physical PDF page shows "Page X of Y" from the PDF page counter.
- c1-810: `df.tlg.verbs()` and `df.tlg.<domain>.verbs()` list the TLG verbs, as on `df.sdtm` and `df.adam`.
- c1-793: `fleet.tlg.get`, `fleet.tlg.by_class` and `fleet.tlg.by_namespace` are exported.
- c1-814: `fleet.tlg.render.html.html_document()` wraps an HTML fragment in a UTF-8 document.
- c1-251: `tdd_audit.audit()` takes `td=` and `tm=` and reports each Req variable of the SDTMIG 3.4 structure that is absent, null or blank (`FLEETTD08`). `StudyDesign.audit()` reports an empty elements or arms section as an error and an empty visits or criteria section as a warning (`FLEETTD09`).
- c1-786: `tdd_audit.audit(dm=)` warns when a DM (ARMCD, ARM) pair is not a TA pair (`FLEETTD07`, CORE-000047).
- c1-224: `visit_map` with no `tolerance=` warns with the count of mapped rows and the largest distance in study days.
- c1-110: `export_supp` checks the SUPPQUAL limits: a QNAM that is not 1 to 8 upper-case letters, digits or underscores with no digit first, or a QLABEL that is not 1 to 40 characters, raises; a QVAL over 200 characters warns.
- c1-114: `ae_aerel` warns once with the values that have no mapping.
- c1-784: `StudyDesign.from_usdm` writes the encounter transition rules to TVSTRL and TVENRL and warns with the count of visits with no start rule.
- `fleet run --overwrite` lets a spec derivation replace a column the input already has; default off, so a QC run keeps the guard. A spec error from `fleet run` names `--overwrite` and `--no-strict`, not the Python arguments. (c1-245)
- A validation finding keeps the record the engine names: `ValidationIssue.usubjid`, `.seq` and `.values`. The full report, the HTML page and the MCP `fleet_validate` issues show them. (c1-831)
- The MCP tool `fleet_validate` returns the study-level findings as `study_issues`. (c1-267)
- `scripts/refresh_rule_schema.py` rebuilds the bundled rule schema from the installed CORE engine and prints the added and removed rule types and operators. (c1-837)
- `fleet.validation.check_ig_version` and `fleet.validation.missing_engine_reason` are public. (c1-838, c1-523)
- `fleet.core.define_spec.read_define_yaml` and `validate_define_data`: one reader for `DefineSpecGenerator` and `DatasetChecker`. Bad YAML, an empty file, a list file or a file with no `datasets:` gives one `SpecSchemaError` line, also from `fleet define-xml`; an old algorithm name says "Run: fleet migrate --spec <file>" (c1-564).
- define.yaml `subclass:` (written as `def:SubClass`) and `domain:` (the SDTM `Domain` of a split dataset, QSPH: QS) on a dataset (c1-567).
- define.yaml value-level `where:` takes a list of conditions, ANDed into one WhereClauseDef, each with an optional `comparator:` (`EQ`, `NE`, `LT`, `LE`, `GT`, `GE`, `IN`, `NOTIN`) (c1-570).
- `define2-1.xsl` ships in the package. `DefineSpecGenerator.generate()` copies it next to the XML when no file of that name is there (also with `--no-preview`), and never replaces one (c1-569).
- `DatasetChecker(check_values=True)`: `check()` reports a text value longer than the define `length`, a null or blank value in a `mandatory` variable, and two records with the same `keys` (a null key value counts as one value, as in PROC SORT NODUPKEY). The pilot ADVS keys are now STUDYID, USUBJID, PARAMCD, ADT (c1-772).
- `try_load_dotenv(start=)`: the CLI reads the `.env` next to the `--config` file first, then walks up from the working directory (c1-762).
- `fleet.introspect` (additive): `check_derivation`, `DerivationProblem`, `renamed_algorithm` and `standard_of`; `fleet.core.define_spec.standard_of`. (c1-608 c1-614 c1-615)
- `fleet.tlg.resolve_population(meta, data, adsl)`. (c1-601)
- `ComparisonReport.values.within_tolerance` and the JSON key `values.within_tolerance` count the values equal under a tolerance or `ignore_trailing_whitespace` but not exactly equal. The text and HTML reports say "All compared values are within the rule in effect; 3 of them are not exactly equal." (c1-727)
- `fleet run --check`: stop before the write when a variable's values do not match its define type. Without it, `fleet run` prints the type mismatch as a warning on stderr (c1-316).
- An offline test runs `fleet new`, `fleet check`, `fleet add-rule` and `fleet check-rule` with a recorded CDISC Library, and one runs `fleet init rules` (c1-313).
- `--config` on `fleet tlg run`, `fleet tlg explore`, `fleet tlg export` and `fleet add-ct`, as the CLI docstring promises. `StudyContext.define_path` is left for #161 (c1-306).
- `fleet.introspect.algorithm_doc(name, standard=None)`: with `standard="adam"`, `seq` and `date` name the ADaM verb that runs, not the SDTM verb. The language server passes the standard of the file. (c1-780)
- `import fleet` now exports `FleetError`, `DerivationError`, `SpecError`, `ValidationError`, `ComparisonError`, `PinError`, `PKNamespace` and `TTENamespace`. (c1-699)
- `.github/dependabot.yml`: monthly grouped updates for `uv` and GitHub Actions. The release steps in CONTRIBUTING.md now refresh `uv.lock` first. (c2-871)
- Tests with exact values replace presence and range checks, and new tests cover: `fleet lsp` and `fleet mcp` over stdio, `fleet new` to `define-xml`, `fleet add-ct` and the CDISC client over a mock transport, `DatasetChecker` per check, every docs page (compile, imports, YAML), SAS-written pilot XPT files and the CDISC Dataset-JSON ADSL, TD/TM and the IG column order, CTCAE and DAIDS cut-off edges, ties in `nodup` and `seq`. A `docs:no-run` marker now states its reason. Strict xfails record open defects: ADTM `value=` with hh:mm, the 24-month anniversary in `age_months`, VISITNUM 3.5 in `TrialVisit`, and egt01 with ATPT/DTYPE records. (c1-841, c1-843, c1-844, c1-846, c1-847, c1-848, c1-849, c1-851, c1-852, c1-853, c1-854, c1-855, c1-856, c1-857, c1-858, c2-972, c2-974, c2-975)
- `docs/concepts/coming-from-sas.md`: the SAS rule and the Fleet rule for missing values, sort order, rounding, merge and dates, each with a tested sample (c1-688).
- `SECURITY.md` and a "Trust" section in `define-yaml.md`: a study folder is code; the expression allow-list is not a security boundary (c1-642).
- Cheat sheet: a TLG table with the one-line spec, the EX reference dates, the partial-date rule, BNRIND and the `--DTC` type (c1-639, c1-594).
- `full_pipeline.md`: an EX step, RFXSTDTC/RFXENDTC from EX, TRTSDT from EX with `impute=`, BNRIND with `baseline()`; the page runs in a test (c1-594).
- Docs CI fails when a mkdocstrings `options:` block prints as text (c1-636).
- `PinMixin` on the core API page; `load_spec_yaml` and `Standard` on the introspect page (c1-636, c1-641).
- `validation-strategy.md`: a dependency statement with a dated advisory scan, the `uv export` SBOM route and a dated licence summary (c2-875).
- c1-192: `docs/getting-started/from-sas.md` maps SAS statements (PROC SORT NODUPKEY, FIRST./LAST., MERGE, IF/ELSE) to Fleet verbs and shows where a null in a condition gives a result other than a SAS missing value. README and Quickstart link to it.
- c1-186: the pilot study ships small synthetic raw CSVs under `examples/cdiscpilot01/raw/`; the SDTM define names them as `raw/<name>.csv`, so `fleet run --dataset DM` runs on a copy of the folder. A test runs it.
- c1-632: CONTRIBUTING.md section "Add a verb" lists the five edits of a spec-executable verb and the test that checks each.
- c1-355: `df.adam.tte.param(keep_reason=[...])` names censor keys whose frame keeps its own CNSR and EVNTDESC before a stop (admiral `consider_end_dates = FALSE`), for example no baseline assessment.
- c1-355: the TTE decision trace (`explain=True`, `select_tte()`) has a `cnsr_from` column that names the rule that gave the CNSR: `event`, `keep_reason`, `stop_at <column>`, `censors key` or `retain`.

#### Changed

- The Define-XML `FormalExpression` and `VariableNode.method` name the public namespace class the verb runs on (`fleet.adam.namespace.AdamNamespace.assign(...)`), not a private mixin, so the text of an unchanged study does not change when Fleet moves a verb between its mixins. A dotted verb names its sub-namespace class (c1-177, c1-175).
- `from_spec` loads a spec `ct: file:` into a validator of that spec only, also without `validate: true`; the global `fleet.get_validator()` is unchanged, and an ID the file lacks falls back to it. The CT state of one `from_spec` call no longer reaches the next one (c1-56, c1-37).
- `from_spec()` and `fleet define-xml` print one stderr line when they import the spec's `derivations_module`, because the module is study Python that runs (c1-60).
- The define.yaml `case_when` method text reads each branch as "if <condition> then <value>"; `fleet define-xml` warns for each variable whose method text holds a Polars expression and that has no `comment:`. The pilot ABLFL has a `comment:` (c1-171).

- `flag()` raises `VerbUsageError` for `by=` with an expression criteria or an exists mode, where it had no effect: an expression flags each row on its own. The pilot ABLFL in `examples/cdiscpilot01` and the docs no longer pass it (c1-214).
- `criterion()` has no `prefix=` argument, requires `description=`, and refuses a number below 1, so it cannot write MCRIT1, CRIT0, CRIT-1 or a null CRIT1 (ADaMIG 1.3 CRITy; admiral `derive_vars_crit_flag`) (c1-205).
- `flag_relative` (and `flag(criteria="before"/"after")`) computes the row position and the landmark in one window, so it scales with the number of groups; a condition with its own `.over()` gives the same flags (c1-208).
- `merge_adsl(by=)` and `pick(by=)` accept one column name as a string; `flag(condition=)`, `flag_relative(condition=)`, `criterion(condition=)` and `flag_exists(source_filter=)` accept an expression string, parsed as `where=` is (c1-215).

- `nodup(keep=...)` always sorts the rows by `subset`, then `sort_by`, as PROC SORT NODUPKEY, also when no duplicate exists. `descending=True` no longer reverses the key columns (c1-20).
- `seq(order_by=...)` sorts the rows by the `by` groups, then `order_by`, so the rows of one subject stay together (c1-22).
- `merge()` keeps the row order of the pipeline for `how="left"`, `"inner"` and `"full"`, whatever the size of the right frame (c1-16).
- `validate()` takes keyword arguments only after the dataset name: `.validate("DM", version="3-4")` (c1-61).
- The foreign-key check runs once, at the public `to_frame()` and the terminal verbs, on the final frame, with the last `fk_policy` of the chain, in any order of `pin`, `fk_policy` and the verbs. It checks `USUBJID` only: `VISITNUM`, `VISIT`, `EPOCH` and `ETCD` gave false orphans on unscheduled visits. A verb that collects mid-chain does not run it (c1-197, c1-198).
- `pin()` and `repin()` collect a LazyFrame once, at pin time, so `study_day` and `join_adsl` work with a `fleet.load_datasets` frame. `repin()` refuses a value that is not a frame (c1-194).
- The `case_when` docstring teaches closed bands with `else_="Missing"` and states that a null condition takes `else_` (c1-27).
- c1-23 c1-24: `seq`, `merge` (`on=` on both sides, `where=` against the right dataset, key types), `group_by`, `nodup` (`subset=` and `sort_by=`, before the duplicate test) and `whereclauses` raise `DerivationError` at the call, with the verb, the column and a did-you-mean, when a column is not in the frame. `seq` says when the column comes from the default `by=`. A text key against a number key in `merge` is an error, as SAS stops on such a BY variable.
- c1-33: `assign(value=, ct=<class>)` checks the literal against the terms of the class when no CT is loaded, and `validate_values=False` silences the check.
- c1-36: the CT warning lists the values not in the codelist in sorted order, shows at most 20 codelist terms ("and N more"), points at the user line, and names the dataset of a `from_spec` run (`ADSL.SEX`).
- c1-542 c1-543: an unknown key in `study_config.yaml` (`sdtm.ig_versoin`) is a `StudyConfigError` that names it; a `validation.engine_path` that does not exist is reported with its path by `fleet check` (WARN), `fleet doctor` and `fleet validate` (could not run), and never replaced by the managed engine.
- c1-546: `ig_version: 3.4`, `'3.4'` and `'3-4'` all load as `'3-4'`.
- c1-548 c1-747: `StudyConfigError` is a `FleetError` and is exported from `fleet.core` under its own name (the `StudyContextError` alias is gone). `fleet.core.exceptions.IOError` is renamed `FleetIOError` and is also an `OSError`. `CheckResult.raise_on_errors` raises `DefineCheckError` and `load_criteria` an unknown system as `DerivationError`, both still `ValueError`. The `FleetError` docstring says which errors it covers.
- c1-549: `load_study_context` takes a `str` or a `Path` and resolves it, so the study paths do not change after `os.chdir`.
- c1-734: `build_dag` adds an edge for each dataset a step reads through a pin (`from_dataset: EX`), so `impacted_by("EX")` includes ADSL, ADVS and ADAE in the pilot.
- c1-748: `logging.getLogger("fleet").setLevel(logging.WARNING)` before the first diagnostic keeps the level, and a handler added to the `fleet` logger receives INFO lines.
- c1-750: `to_repr` prints floats in full and raises when `pl.from_repr` of the table does not give back an equal frame (columns, text or width cut).
- c1-757: `program_from_spec` keeps the dataset label, writes `.derivation(...)` for a bare `callable:` block, passes a pinned dataset as its frame (`from_dataset=ex`), and refuses a spec with no `study.standard`.
- c1-758: `derivations_from_source` gives one row (empty `name`, status `stub` or `unknown`) for a verb call with no target variable, such as `merge`, `whereclauses` or a list target, so a join or a filter is never lost.
- `.adam.date()`, `.sdtm.date()` and the cheat sheet say that a partial date is imputed to the first day or month by default, and show `highest="n"` for the admiral result (c1-120).
- `derive_period()`: `"treatment"` is always a column; a literal goes in the new `"treatment_value"` key (c1-140).
- `derive_param()` adds no record with a null AVAL by default (`keep_nas=False`, as admiral); `keep_nas=True` keeps it (c1-321, ADR-0047).
- The verbs of `AdamNamespace`, `SDTMNamespace` and `TTENamespace` are typed `-> Self`, so a study subclass keeps its type in the chain; tests/unit/test_api_conventions.py checks it (c1-335).
- `peds.corrected_age()` computes `(age in days - 7 x (term - GA)) / 365.25` and keeps full precision; the new `round_digits=` rounds as SAS `ROUND` (ADR-0025) (c1-166).
- The vaccine module docstring says that a NaN from a user expression passes as a number and must be filled with `fill_nan(None)`; the CSV loader part is c1-713 (ml-adam-b) (c1-423).
- `pick(order=)` (and the event key `"order"`) and `nodup(sort_by=)` (and the `row_steps:` key `sort_by:`) are now `order_by`, as `flag(order_by=)` and `seq(order_by=)`. `fleet migrate --spec <define.yaml> --write` rewrites the define.yaml keys, the event keys of a `pick` block included (c1-136).
- c1-396: the `adam.pk.blq_impute` docstring says that one rule applies to every row, whatever the sample position.
- c1-402: the PK namespace docstring no longer claims ADPP parameter datasets.
- c1-404: new tests pin the LLOQ boundary, the pre-dose window, the minutes constant and log base 2.
- c1-438: a table shows the arms first, then the pools. An Enum arm column keeps its category order, and a category with no subject keeps its column with N=0. A `column_order` entry that is not an arm or a pool raises (ADR-0049).
- c1-804: each continuous block of the demographics table starts with `n`, the count of subjects with a value. The golden `dmt01` gains one `n` row per arm. A DM spec with Q1 or Q3, `rows`, or `value_col` (builder `.value()`) is refused.
- c1-805: the deaths table computes the cause block on the full arm and pool universe, so a pool gets its cause cell and an arm with no death shows 0. A null cause of the last row field gets the "Unknown" row. The golden `dtht01` gains the zero cells of Drug B.
- c1-501: `t_abnormal` requires BNRIND. Add a null BNRIND column to apply no baseline exclusion.
- c1-512: `LBChgSpec` and `EGChgSpec` no longer require CHG; the prefilter requires the `value_col` column, so a PCHG table runs without CHG.
- c1-465: a spec field that the template does not use raises at construction when it differs from its default (a YAML `adsl_filter:` on `ael01`, `rows:` on `dmt01`), as the builder does.
- c1-814: `render_html` and `render_listing_html` return pure ASCII (`&#8805;` for a non-ASCII character), and the files that the CLI and `to_html(path)` write are complete UTF-8 documents. The goldens `vst01.html` and `lbt01.html` show `&#160;` for the non-breaking spaces.
- c2-970: a PDF loads no external resource: WeasyPrint gets a `URLFetcher` with no allowed protocol, and each refused resource gives a `UserWarning`. A `file:` or base64 logo in a `--wrap` template is left out. The `tlg-pdf` extra needs `weasyprint>=70.0`.
- c1-461: PPTX prints a header row as HTML and RTF do (not bold); the theme key `bold_header_rows` is removed (c1-819).
- c1-791: a second `.filter()` on a builder raises; combine the conditions with `&`.
- c1-107: SDTM `baseline_flag` requires `testcd_col=` and `ref_col=`; there is no `RFSTDTC` default (ADR-0051).
- c1-786: `StudyDesign` requires an `arm_names` entry for each arm; TA.ARM is no longer made from the ARMCD (ADR-0052).
- c1-109: `condition_add` keeps the current value of an existing target where the condition is false, as SAS `if ... then`.
- c1-112: `multiple_responses` gives no record for an empty response (`x||y`, `x|`, `|`).
- c2-958, c1-252: `TrialVisit.visitnum` accepts 0 and decimals; `TrialVisits` no longer needs VISITDY to rise with VISITNUM; ETCD and ARMCD have length limits only; TAETORD must be unique per arm, not 1..N.
- c1-248: `TrialVisits` is unique per (ARMCD, VISITNUM), `TrialCriteria` per (IETESTCD, TIVERS); the audit TV duplicate rule is `FLEETTD06` keyed on ARMCD and VISITNUM.
- c2-956, c1-96: the automatic FK rules accept ETCD `UNPLAN`, keep VISITNUM and VISIT orphans as warnings under `fk_policy("error")`, and check EPOCH against a pinned TA.
- c1-785: `StudyDesign.from_usdm` orders epochs and encounters by previousId/nextId, takes the sponsor study identifier, raises on no study design or a dangling armId, epochId or elementId, and warns on more than one design.
- c1-229: `study_header` and the `add_*` verbs must name the domain of `fetch_structure`; `study_id` must be a non-empty string.
- c1-230: `fetch_structure` raises `FileNotFoundError` for a missing `define_path`, raises when the `save_to` cache holds another domain or IG version, and gives the CDISC Library cause in the `CTError` message.
- c1-225: the TDD builder chain puts STUDYID and DOMAIN first.
- c1-257: an ISO 8601 duration needs at least one component (`P`, `PT`, `P1DT`, `P1Y2W` raise).
- c1-259: IETESTCD must not start with a digit in the model; the audit SD0018 also flags lower case, hyphens and spaces.
- `ValidationIssue.rows_affected` is renamed `row`; it holds one row number. (c1-831)
- The HTML validation page writes one row per group of identical findings (rule, message, variable, source), with the row ranges, the count and the first 20 records. 1000 identical EPOCH findings give one row, not 1000. (c1-832)
- A finding that names several variables gets each producing verb with its variables (`assign (AESEQ, USUBJID)`); a list of more than five names gets none. (c1-830)
- The bundled CDISC rule schema follows CORE 0.15.0: `references_correct_codelist`, `conformant_value_length` and four more operators, and the Define rule types, pass `fleet check-rule`. (c1-837)
- `fleet add-rule` writes no machine-specific `yaml-language-server` line; it prints the line as an opt-in. The header names only rule types that `fleet check-rule` accepts, and each description line is a comment. (c1-531)
- `save_dataset_json` names Fleet in `sourceSystem`, writes the creation time with `Z`, and defaults `fileOID` to `<STUDYID>.<domain>.<creation time>`. (c1-583)
- `save_dataset_json` writes the rows in slices of 50,000, so memory does not grow with the dataset. (c1-584)
- Install hints name `uv add 'fleet-cdisc[<extra>]'`, which works in a user project. (c1-244)
- `fleet validate --version` help says that it applies to every dataset of the run. (c1-836)
- A SENDIG define gets `Purpose="Tabulation"` (c1-560).
- The define `FileOID` names the standard (`CDISC.CDISCPILOT01.ADAMIG.1.Define-XML_2.1.0`), so the SDTM and ADaM defines of one study differ. `SourceSystemVersion` defaults to the running Fleet version; `source_system_version:` stays an optional override, and `fleet init define` and the pilot specs no longer write it (c1-572).
- A Submission define whose `def:leaf` names a file other than `.xpt` or `.json` gives one warning. The href is kept (c1-568).
- An ADaM ItemGroupDef has no `Domain`. A dataset with no `class:` warns; a class of the other model (FINDINGS on an ADaM dataset) stops the generation. The pilot ADAE has `def:SubClass` ADVERSE EVENT (c1-567).
- Two value-level conditions that give one WhereClauseDef OID, or one value-level ItemDef OID, stop the generation with a `SpecError` (c1-570).
- `predecessor:` takes an optional condition (`DS.DSDECOD where DS.DSCAT='DISPOSITION EVENT'`). The semantic lint no longer flags a MethodOID on a variable that is not Derived, because the CDISC Define-XML 2.1 examples use it (c1-779).
- A blank line inside a define text stays. A control character gives a `SpecError` that names the element and its OID, not a raw XML parser error (c1-573).
- `DatasetChecker.check()` accepts whole Float32/Float64 values (an XPT numeric code) for an `integer` variable and compares `54.0` as the code `54`; 1.5 still fails (c1-770).
- `validate_define_xml()` and `semantic_errors()` read a file given as a `Path` or as a string that does not start with `<`; `DatasetChecker.check()` collects a LazyFrame (c1-773).
- The generated `codelists.py` has one attribute per term: a term that starts with a digit gets `T_` (`FREQ.T_2_TIMES_PER_WEEK`), a term with no letter or digit is `T_<term NCI code>`, and two terms with one name each end with their NCI code (c1-552).
- `fleet check-rule` names a missing key ("Authorities.0: 'Category' is a required property"), not the whole anyOf block. All 67 shipped sdtmchecks rules and the docs sample rule have a `Category` block and pass `check_rule` (c1-687).
- The descriptions of SDTMCHK-AE-002, 003, 004, 005, 015, 016 and 017 and their tracker rows say that they need a sponsor AEDTHDTC (not in SDTMIG 3.4 AE) and name CORE-000253, CORE-000254 and CORE-000841 for standard data (c2-881).
- `fleet.compare` with `by`: the HTML report draws the summary statistics once per variable, above the group sections, with the caption "over all groups". (c1-722)
- The text and HTML compare reports print statistics and differences with 12 significant digits, as a SAS BEST format does. (c1-730)
- The text and HTML value listings quote an ambiguous value: `"M "` against `M`, `"null"` against `null`, `""` against `null`. JSON and parquet keep the raw values. (c1-729)
- `_normalise_tolerance` and `_normalise_flag` moved from `comparison/report.py` to `comparison/engine.py`. No behaviour change. (c1-725)
- `fleet migrate` renames `lookup` only with `dataset=`, and `assigned` and `dataset_level` only with `value=`; a leading positional argument of `merge`/`lookup` becomes `keep=` only with `dataset=`. So `codecs.lookup(...)` and `heapq.merge(...)` stay as they are, and a second run changes nothing. A folder walk skips hidden folders, `__pycache__`, `site-packages` and virtual environments. The `--write` help says that no backup is kept (c1-827).
- `fleet migrate --spec` no longer stamps `fleet_spec_version: 2` while a block is left in the old vocabulary. It names each such block ("left as is, rewrite by hand: DM.DOMAIN") and exits 1. A quoted version (`"1"`) is bumped (c1-823).
- `fleet tdd ctgov --write` writes nothing when no parameter is new (c1-271).
- `fleet add-acrf` and `fleet tdd ctgov --write` edit the YAML file as text, so all comments stay. A layout that the text edit does not handle (a flow-style block) is written through YAML, with a warning that counts the lost comment lines (c1-271, c1-272).
- `fleet doctor` exits 1 when the study config or the rules engine has a cross; an invalid config is a cross, and a define.yaml with a YAML error is a cross on the codelists line, not a traceback (c1-282).
- One dataset extension constant (`fleet.io.DATASET_EXTENSIONS`) and one writer (`fleet.io.write_dataset`) serve `fleet run`, `fleet tdd build` and the validation sweep; the CLI no longer reads `args` with `getattr` (c1-305).
- `fleet new STUDY01` creates the study in `./STUDY01`, as the docs and issue #52 expect; `--root .` keeps the current folder. A second `fleet init cfg` in one folder names `fleet init define`, `ct` or `rules` (with `--force`) in its message, not only a Python function (c1-309).
- `fleet new --help` and `fleet init --help` say when to use each command (c1-310).
- `DEFAULT_SDTM_CT` is the one source of the default SDTM CT package (CLI defaults and help, `CDISCClient.get_codelist`, `CodelistGenerator`); `fleet new` prints the CT package ("CT package: sdtmct-2023-12-15 (default)"). The default stays the one of ADR-0019 (c1-284).
- `fleet validate` says in each engine run that the variable labels and the dataset label that CORE checks come from Fleet, not from the file; docs/concepts/validation-core.md states the limit. Passing the XPT labels to CORE is left for later (c1-280).
- `scripts/regen_tlg_goldens.py` prints each changed cell (template, row keys, column, old, new) and each added or removed row before it writes a Parquet golden, so the review step of its docstring can be done. The `TestANL01FLAdmiralParity` docstring says "same rule as admiral", not "byte-for-byte parity": no admiral output is read (c1-698).
- The `io` extra now needs `pyreadstat>=1.3.7`, and `uv.lock` holds 1.3.7. A SAS file with `E8601DA10.` or `E8601DT19.` formats now loads as Date and Datetime, not as a raw SAS number. A SAS7BDAT record that SAS marks as deleted is no longer read. (c1-151, c2-923)
- Dependency floors now allow only releases that build and pass the tests: `polars>=1.41.1`, `pydantic>=2.11`, `pyyaml>=6.0.1`, `jsonschema>=4.20`, `weasyprint>=63`, `mcp>=1.26`. (c1-152)
- Fleet now needs `certifi>=2026.10.19`, and the `tlg-pdf` extra needs `brotli>=1.2.1`. The older releases have critical advisories. (c2-976)
- The sdist no longer holds `tests/`. Run the tests from the git tag. (c1-155)
- A push to `main` deploys the docs as `dev`. Only a release tag writes `latest`, so the first tag no longer fails in mike. The devel docs step is gone. (c1-625)
- The docs workflow has a read-only token at workflow level; only the deploy job can write. The pull request build checks out with no stored credentials. CI has a read-only token too. (c2-872)
- The docs workflow takes no manual `version` input any more; a manual run redeploys `main`. (c2-873)
- The publish job uploads `dist/` right after `uv build --build-constraints build-constraints.txt`, then checks the uploaded copy with a pinned twine. Its actions are pinned to commit SHAs, with an explicit uv version. (c2-874)
- The publish workflow runs only on a tag of the form `vX.Y.Z...`. (c1-626)
- The blacken-docs CI step fails on every non-zero exit code, so a code block with a syntax error now fails CI. (c1-622)
- `assign(value=, ct=<codelist class>)` checks the literal against the class terms, with no CT loaded, as `source=` already did (c1-640).
- `fleet tlg run <template id>` says that the argument is a template id and gives the one-line spec (c1-639).
- `fleet add-ct`, `fleet tlg run`, `fleet tlg explore` and `fleet tlg export` take `--config`; the CLI reads `.env` from the folder of `--config` (c1-662).
- `fleet lsp` publishes diagnostics only for files named `define*.yaml` / `define*.yml` (c1-665).
- `output_format` (spec level and dataset level) accepts only `parquet`, `xpt` and `dataset-json`; `json` raises `SpecError` instead of a silent parquet path (c1-647).
- `fleet migrate --spec` reports a flow-style derivation block with old names and does not raise `fleet_spec_version` while one remains (c1-647).
- The verb summary keeps "e.g." and "i.e." inside the first sentence (c1-653).
- mkdocs-material floor raised to 9.7.7 (GHSA-xvg9-69gf-fjrf); the lock file changes only this package (c2-877).
- c1-180: the README namespace catalog is built from `.verbs()` of the live namespaces: one shared ADaM list, the specific verbs of each namespace, no counts. A test compares it with `.verbs()`.
- c1-689: the golden define files moved to `tests/fixtures/goldens/define/` with a fixed CreationDateTime; `outputs/` is ignored and holds no tracked file; `define2-1.xsl` moved to `examples/cdiscpilot01/`, and `cdiscpilot01_spec_driven.py` passes it as `xsl_path=`.
- c1-682: `full_pipeline_example.py` writes to `outputs/full_pipeline`, not to the pilot folder.
- c1-589: `Epoch` holds the 13 terms of C99079; the codelist code is set after the class, so it is no longer a 14th member. The docs say seven Trial Design domains plus SV and SE.
- c1-631: the root plan files have true status lines; `tmp_lineage_probe.py` is removed.
- c1-349: `to_spec_yaml()` takes `dataset=` and `path=` as keywords only. A positional call raises `TypeError`. A dataset name that is not a valid dataset name (for example a file path) raises `VerbUsageError`. Before, the path became the dataset name and no file was written.
- c1-499: `examples/r2r_ae_example.py` and `benchmark/fleet_adae_benchmark.py` derive ADY with `study_day(date_col=, ref_col=)`, the verb for a study day. The benchmark ADAE is equal on every row (114,688 rows).
- c2-891: the weekly CORE workflow has a job that installs the pinned engine (v0.15) and runs `tests/unit/test_sdtmchecks_rules.py`. The test still skips locally without an engine.
- c1-355: `df.adam.tte.param(stop_at=...)` is now a dict, ADSL date column -> `(CNSR, EVNTDESC)`. A censored subject takes the date (ADT, CNSDTDSC) from the last censor record before the stop, and CNSR and EVNTDESC from the stop: the earliest stop date, the first column in dict order on a tie. A subject without a stop date keeps the censor key. A list `stop_at` raises and shows the dict form. Stop codes must be distinct and differ from the `censors=` keys (FDA 2018 oncology endpoints guidance, EMA PFS appendix, ADaM BDS-TTE, admiral `end_dates`; ADR-0043).
- **MCP `fleet_validate` lists a study-level finding once.** The finding is in `issues` with `dataset` `"STUDY"`. The `study_issues` key is removed: it repeated the same findings (ml2-misc task 1, follow-up to c1-267).
- **Dependencies:** the lock file takes anyio 4.16.0, idna 3.20 and lxml 6.1.3 (typing-extensions 4.16.0 comes with anyio 4.16). The lxml floor is 6.1.0 (PYSEC-2026-87). `pip-audit` over `uv export --frozen --no-dev` finds no known advisory (ml2-misc task 3).

#### Fixed

- `to_spec_yaml()` writes a TODO stub and a warning for a variable whose frozen block cannot give the inline value: a variable changed after another step read it, or a variable whose last step reads itself after an earlier step wrote it (`AVAL` from `LBSTRESN`, then `AVAL.round(2)`). Frame order stays (c1-202, c1-737).
- `df.adam.tte` keeps its dataset name ADTTE at run time, so `to_spec_yaml()` names the dataset; the `fleet.adam` and `PKNamespace` docstrings name the real accessors and the source of `seq` (c1-755).
- A frame derivation or `transform` that changes the number of rows logs a NOTE with both counts (`derivation drop_rows: 2 -> 1 rows`); a declared target that the returned frame does not hold warns, and lineage records the columns the frame holds (the new columns when no target is declared) (c1-43).
- `fleet init define`, `fleet add-ct` and `fetch_structure` accept an IG version written `3.4` as well as `3-4`: every CDISC Library path builder normalises it (c1-547).
- The method text of `atoxgr` names the grading criteria (default `ctcae_v5`), and `combine_grades` states its sign rule (c1-172).
- A variable block with `algorithm: whereclauses` or `group_by` warns in `from_spec` and `fleet define-xml`: a record filter goes to `row_steps:` (ADR-0034) (c1-173).
- An unknown dotted or sub-namespace algorithm (`onco.best_overall_response`) gives a `SpecError` that says sub-namespace verbs are inline only in this release and points to `algorithm: derivation` with `callable:`; the docs state the limit (c1-174).
- A dotted verb (`occds.treatment_emergent`) round-trips through `to_spec_yaml`, keeps `.occds` in `program_from_spec`, resolves in the define method resolver, and the `fleet lsp` algorithm pattern accepts the dot (c1-175).
- The spec path is never looser than the verb: `nsv` with no label, `nsv` with both `source` and `value`, and an explicit `null` on an optional key (`assign` with `value: null`) give a `SpecError` (c1-176).
- `fleet check` warns when a derivation `ct:` and the variable `codelist:` are two different NCI codelists (c1-37).

- `study_day` takes the reference date from the pinned domain before a frame column of the same name, as its docstring says, so an explicit `ref_pin=` is never ignored (c1-8).
- `study_day(ref_df=...)` records no pinned domain in lineage; `dm=` records DM and `adsl=` ADSL on both namespaces, and `ref_pin=` names the domain of a `ref_df=` frame (c1-11).
- `trail()` reads the pin sources of each lineage node: a literal after a pinned derivation shows `(literal)`, and `join_adsl` columns show with their ADSL origin. `baseline_flag` records its arguments in lineage (c1-203).
- Lineage capture no longer compares a Polars expression, frame or series with its default, so no false "Comparisons with None" warning comes from `lineage.py`; the CT invalid-value warning names the user line (c1-199, c1-200).
- A pin read on one branch of a chain no longer appears on the parent and sibling branches: lineage replaces the node instead of changing it in place, also in `PipelineDAG.inject_lineage` (c1-201).
- `PipelineDAG.inject_lineage` raises `KeyError` for an unknown dataset name and no longer tells the user to remove a declared input that has no pin evidence (c1-735).
- The `PipelineDAG.trace` docstring states that a variable derived from itself shows its last step only (c1-737, part).

- A Polars error at `to_frame()` (arithmetic on text, a comparison of text with a number, a join key type clash) is a `DerivationError` that names the verbs of the chain, not a raw Polars error (c1-26).
- `case_when` refuses a branch key other than `condition` and `value` with the branch number and a did-you-mean (`else` points to `else_`). Inline, a branch `value` and `else_` can be a Polars expression. The define.yaml schema accepts only `condition` and `value` in a branch (c1-28).
- `assign("X", value=None)` names the way to a typed null column (c1-34).
- tests: `test_keep_last_descending` now tests `keep="last"` (c1-19). New tests pin `join_adsl` keeping a subject that is not in ADSL, `exists_before`, `flag_extreme` with `where=`, an expression flag with `where=`, and the inclusive and no-landmark cases of `flag_relative` (c1-217).
- c1-25: `from_spec` resolves the plan schema inside the try block of each variable, so a schema error names file, dataset and variable; the docstring states that a type error the schema does not show appears only at `to_frame()`. `to_spec_yaml` raises `DerivationError` on a plan that does not resolve.
- c1-29: `flag_exists`/`flag(criteria="exists"...)`, `first_date`, `last_date` and `count_events` raise `VerbUsageError` when `from_dataset` is a name, not a frame; `first_date` names an unknown `date_col`; `nodup(subset="USUBJID")` logs the column name, not its letters.
- c1-41 c1-42: `to_spec_yaml` writes `codelist:` on a variable assigned with `ct=` and a `codelists:` entry with its terms (a TODO comment when no term is known), and writes the NSV `evaluator`, so QEVAL survives the round trip.
- c1-45: `derivation()` raises `VerbUsageError` for a target that is not a name or a `Derivation`, and for a frame-kind `Derivation` given as `expression=`.
- c1-46: the nodup, validation and comparison reports survive a switch to `.occds`, `.adsl` and the other ADaM sub-namespaces.
- c1-48: `inspect()` and `explain()` raise the same `DerivationError` as `to_frame()` for a missing column.
- c1-51: `compare()` and `validate()` continue from the frame they checked, so the chain runs once.
- c1-52: `.validate()` raises `ValidationSetupError` in every `on_fail` mode when no rules engine is found.
- c1-53: `from_spec` raises `SpecError` with a did-you-mean for a name in `only=`/`omit=` that is not a spec variable, and for a `dataset=` that a simplified spec does not describe; a define that declares one dataset twice is refused.
- c1-540: `fleet init define` orders ADaM variables by the Library set ordinal, so STUDYID and USUBJID come first.
- c1-59: `seq(check_uniqueness=True)` has tests: a tie on the key warns and names it, a unique key is silent.
- c1-545 c1-742: a study config that is not UTF-8 text, or holds an impossible date, is a `StudyConfigError`; a define value its tag cannot read (`!!float abc`) or a recursive alias is one YAML diagnostic, not a crash.
- c1-55: a spec in the pre-ADR-0008 vocabulary (an old key under an unchanged algorithm name, or `fleet_spec_version: 1`) names `fleet migrate --spec` in the `from_spec`, `fleet define-xml` and `fleet check` errors.
- c1-731: `docstring_summary` does not cut after `e.g.`, `i.e.`, `etc.`, `vs.` or `cf.`.
- c1-738: `build_dag` refuses a dataset declared in two defines, a raw input with two paths or with the name of a dataset, counts a repeated input once, and names the nodes of a cycle.
- c1-57 c1-739 c1-740: docstrings and docs corrected: `SharedVerbsMixin` needs `PinMixin`; the DAG examples show the real output; `pipeline.md` names `from_spec`; `advanced.md` derives TRTEDT before `duration`; the NumPy and `Example::` docstrings of the DAG, define checker, generator, transforms and vaccine verbs use Google sections.
- `pick()` raises a `DerivationError` with a did-you-mean hint when a `set` key is not a target, instead of a silent null (c1-126). The docstring and `docs/concepts/pick.md` say that an existing target column is replaced.
- `pick()` raises when one event sets a target from a date and another from DTC text, instead of a text target; the `pick()` examples use date columns (c1-127).
- `pick()` keeps the source dtype of a target when no event has a record, so a study with no deaths gets a `Date` DTHDT (c1-128).
- `pick()` names `pl.lit()` when a `set` value is a missing column; `date()` raises for an `impute=` value other than first, mid, last or none; `derive_period()` raises with a did-you-mean hint for a missing treatment column (c1-140).
- `derive_param()` warns when a `parameter_filter` PARAMCD has no record, with a did-you-mean hint (c1-322); raises for an expression in `set_values_to` (c1-326); the docstring says that a by group without every source parameter gives no record (c1-320).
- `baseline()`, `seq()`, `derive_param()` and `derive_locf_records()` read a `by=` string as one column, so the duplicate check of `baseline()` runs (c1-327).
- `atoxgr()` raises for a `signif_dig` that is not a positive integer (c1-331) and warns once with the terms that have no criteria in any direction (c1-332); the docstring example uses `term_var="ATOXDSCL"`, not PARAMCD (c1-331, c1-332).
- `combine_grades()` raises a `DerivationError` that names the column for a numeric grade column or a grade other than "0" to "4" or null, instead of `-G3` or a Polars error (c1-391).
- The grading example says "or" for the Creatinine G3 and G4 rules (CTCAE and DAIDS), and llms.txt lists `combine_grades` (c1-334).
- A sub-namespace switch (`.occds`, `.adsl`, ...) keeps `last_comparison`, `last_validation` and `last_nodup_report`, so a gate that reads them after the switch sees the report (c1-336).
- STRUCTURE.md says that `baseline` runs a side check and does not re-wrap a collected frame, and how a sub-namespace switch keeps the state (c1-338).
- `tte.param(by=)`: a censor frame with none of the by columns (for example from ADSL) is crossed with the strata of the event frames, as admiral `derive_param_tte`; a frame with only some of them raises (c1-356). Under `by=`, the drop warning names this cross (c1-356, c1-363).
- The `select_tte()` trace has a row per subject kept by `retain="censor_at_start"` ("censored at STARTDT: no record") and a row per record after the stop date ("after the stop date") (c1-364).
- `select_tte()` and `tte.param()` raise for a `retain=` value other than "drop" or "censor_at_start" (c1-365).
- The TTE tie warning checks the subject keys, ADT and SRCSEQ, also when SRCSEQ ties, and names these columns (c1-367).
- `tte.param()` raises for a subject with two different ADSL rows, and `km_data()` counts a subject once when ADSL repeats a row (c1-369).
- New tests pin the ADTM time part, SRCDOM and SRCVAR of a `retain="censor_at_start"` row, and the SRCSEQ tie-break for an event and a censor (c1-370).
- `neuro.mmse_category()` and `neuro.moca_category()` give null for a score above 30, as for a score below 0 (c1-716).
- `metabolic.bmi_category_adult(labels=)` raises when the bounds do not strictly ascend (c1-162).
- The `pk.cmt()` docstring says that `conc_cmt` applies to all non-dose records, and the ADNCA example says that its plasma-only data reduce the admiral PCSPEC rule to this call (c1-399).
- `DefineSpecGenerator` (`fleet define-xml`) on a `fleet_spec_version: 1` spec names `fleet migrate --spec <define.yaml> --write`, as `from_spec`; one `check_spec_version()` in `fleet.core.define_spec` serves both (c1-142).
- New boundary tests: the `treatment_emergent` end window includes its last day, an event that ends on TRTSDT has not ended before, `offset_days` moves the start later, and `study_day` from a pinned ADSL gives 1 on the reference day (c1-149).
- New tests run the `t_abnormal` on-treatment prefilter, `flag(criteria="exists_after")` and the literal and column imputation of `impute_dtc_to_date` (c1-86).
- c1-373: `adam.tte.param(explain=True)` now prints the decision trace in a plain script; it attaches the default console handler as other diagnostic verbs do.
- c1-377: `adam.tte.aval()` gives a null AVALU where AVAL is null (admiral `derive_vars_duration`).
- c1-378: `adam.tte.param()` with `by=` and no event or censor record left raises a `DerivationError` that names the by columns and the sources. `km_data()` selects the ADSL pin join key (for example SUBJID), not a literal USUBJID. `param()` refuses CNSR, ADT, ADTM, STARTDT and STARTDTM in `set_values_to`.
- c1-372: the PARAMCD collision guard of `adam.tte.param()` compares every PARAMCD value of the new rows, also one from `set_values_to` or a `by=` expression.
- c1-374: `adam.tte.km_data()` raises when `paramcd` is not in the PARAMCD values (or the frame has no PARAMCD), and warns with the count and the first subjects when AVAL is null.
- c1-376: `adam.tte.param()` records one lineage node per new output column (STARTDT, ADT, CNSR, EVNTDESC, PARAMCD, PARAM, ...) with the start and stop_at dates as sources, not a node named after the PARAMCD.
- c1-401: `adam.pk.nominal_time()` computes `x * scale_in / scale_out`, so 23 minutes gives the correctly rounded `23 / 60`.
- c1-397: `adam.pk.amt()` and `cmt()` treat EVID 1 and 4 as doses; `cmt()` gives null on EVID 2 and 3; `mdv(evid_col=)` gives 1 on every EVID other than 0 (and on a null EVID).
- c1-398: `adam.pk.mdv()` reads `evid_col="EVID"` and `conc_col="DV"` by default and raises when a column is missing (no silent MDV 0). A text DV that is not a number (".") counts as missing.
- c1-413: `adam.onco.filter_pd()` and `confirmed_response_flag()` raise a `DerivationError` that names the verb for a missing column and for a text date that is not complete (`2024-01-01T10:30`, `2024-01`). A Null dtype response column gives null in `aval_resp()` and MISSING in `best_overall_response()`.
- c1-409: `adam.onco.best_overall_response()` gives `MISSING` when no row of the group holds a known response (null, ND, UNK). The docstring says the denominator comes from ADSL.
- c1-410: `adam.onco.best_overall_response()`, `confirmed_response_flag()` and `filter_pd()` raise on unknown response values (for example `'CR '` or `'Partial'`) and name them. ND and UNK are accepted as no response; iRECIST codes are not supported.
- c1-411: the onco module and verb examples use a vertical ADRS filtered to PARAMCD OVRLRESP with `source="AVALC"`, and say that the verbs read every row.
- c1-717: `adam.neuro.centiloid()` gives null for a SUVR of zero or below, and raises when only one of `slope` and `intercept` is given.
- c1-714: `adam.neuro.panss_total()` raises when a subscale column is not numeric (a String column was joined as text).
- c1-715: `adam.neuro.cdrsob_total()` raises unless `domain_cols` names the 6 CDR boxes (an empty list gave a raw AttributeError).
- c1-713: `load_raw_data()` reads a float NaN in a CSV or Parquet file as null. `neuro.mmse_category`, `neuro.moca_category`, `metabolic.visceral_fat_flag` and `ophtha.bcva_criterion` treat NaN as missing.
- c1-707: the therapeutic-area verbs round half away from zero (SAS `ROUND`, ADR-0025): `metabolic.waist_hip_ratio`, `waist_height_ratio`, `body_fat_pct`, `ophtha.etdrs_to_logmar`, `logmar_to_etdrs`, `vaccine.aval_adis`, `neuro.centiloid`, `cdrsob_total`, `peds.corrected_age` and the `peds` BMI z-score. The default digits do not change.
- c1-718: the `ophtha.study_eye` docstring says that the input is the SC FOCID records and shows the filter and an `adam.merge(..., validate="m:1")` into ADSL.
- c1-421: the `vaccine.seroresponse_flag` docstring says it is a threshold rule on AVAL only, points to `seroconversion_flag` for a fold rise, and has a `References:` section.
- c1-415: new tests pin the ophtha default digits and the bilateral study eye, the metabolic default digits, the vaccine event cut-off and the `aval_adis` LLOQ/2 rule without ULOQ.
- c1-390: `adam.atoxgr()` reads a NaN in a float column as null, so a NaN AVAL, limit or BASE gives a null grade, as admiral's NA. The input columns keep their values.
- c1-700: a custom grading criteria file with an unknown key (for example `filtr`) raises a pydantic `ValidationError` at load; a file that is not valid JSON raises a `ValueError` that names the file, the line and the column.
- c1-701: a custom grading criteria file is read again on every call, so an edit in the same session takes effect. The bundled files stay cached.
- c1-703: docs/validation-strategy.md names the CTCAE v5 GGT boundary: AVAL = 2 x BASE with a high baseline gives grade 0, as admiral; the CTCAE text gives grade 1.
- c1-80: the `adam.pchg` docstring says that the ADaMIG formula differs in sign from admiral `derive_var_pchg` on a negative baseline; a test pins PCHG -20 for AVAL -2, BASE -2.5.
- c1-82: `adam.bsa(method="DuBois-DuBois")` (admiral's name) gives the DuBois value.
- c1-83: `adam.adsl.age_years()` divides WEEKS by 365.25/7 and HOURS by 8766, as admiral `compute_age_years` (ADR-0048), and warns with the count of rows whose AGEU is not a known unit.
- c1-85: new tests pin the PCHG zero-baseline guard, the age divisors, `derive_summary_records(stat="min"/"median")` and the no-row rule of `derive_param`.
- c1-71: `adam.date(value=...)` and `sdtm.date(value=...)` raise on a literal that is not ISO 8601 (it gave a null column, or wrote the text to a --DTC target). `YYYY-MM-DDThh:mm[:ss]` works on a DT and a DTM target; a partial --DTC literal stays valid.
- c1-73: the `adam.date` docstring and ADR-0045 say that an hh:mm time gives TMF S, where admiral gives NA by default.
- c1-721: the transform registry docs say `algorithm: derivation`, GUIDE.md says `merge` with `on=`, the ADaM module docstring says only `df.adam` is registered, and `fleet migrate` rewrites `algorithm: transform` to `derivation` (the spec error now gives that hint).
- c1-434: a NaN analysis value counts as missing, with one warning that gives the count; an infinite value raises with the column and the count; the renderer no longer stops on a NaN statistic (ADR-0050).
- c1-443: a duplicate USUBJID + arm record in ADSL raises; a subject in two arms gives a warning; DM `check()` reports the duplicate (ADR-0050).
- c1-448: a numeric arm column (TRTAN) stops at once with a message that names TRTA and `column_order`.
- c1-437: a `decimals` key that is not an ARD stat name, or a pattern that is not `xx.x`, raises (on the spec and on `Row`).
- c1-446: `summarize_ard(prefilter=...)` accepts an expression string.
- c1-455: a count cell with `decimals={"pct": "xx.x%"}` shows one percent sign, and a zero count with decimals shows no percentage.
- c1-457: an unknown `page_by` raises with the row variables of the table; `fleet tlg run --page-by` on a listing is a usage error.
- c1-459: `rows_per_page` below 1 raises in `paginate` and `paginate_listing`; `--rows-per-page` must be 1 or more.
- c1-461: an ARD without `group2` renders.
- c1-462: two header rows, or two interactive options, with one label raise.
- c1-467: a listing prints each column through `Column.format` (a Python format string for a number, strftime for a date); a null or NaN prints empty.
- c1-802: a listing sorts before it selects, so a hidden sort key sorts; an unknown sort key raises and `check()` reports it.
- c2-869: a numeric row level or listing value prints as SAS BEST. does (`2`, `13.566`), and `label_col` maps a Float64 code.
- c1-502: the lab listing falls back from PARAM to PARAMCD for its default column and sort key.
- c1-505: `t_shift` raises on a statistic other than n.
- c1-506: `label_col` raises when one code has two labels.
- c1-510: `t_abnormal` keeps an arm emptied by the population filter, with N=0.
- c1-513: `t_abnormal` compares `low_values` and `high_values` in any case.
- c1-809: a prefilter that keeps no record warns with the values of its columns (EX `PARCAT1` = "Overall"); `ex.check()` reads the spec prefilter and reports a missing row field once.
- c1-815: an HTML wrapper with no `{table}` placeholder raises; `fleet tlg export --wrap` with RTF or PPTX is a usage error.
- c1-818: a WeasyPrint install without Pango gives an `ImportError` that names the libraries, and `fleet doctor` reports WeasyPrint as not usable.
- c1-821: RTF writes a character above U+FFFF as a UTF-16 surrogate pair.
- c1-811: a non-default explorer variant prints "Exploratory view, not the batch output" with its selections.
- c1-792: the `register_template` example sets `spec_cls`, so it gives the AE table.
- c1-793, c2-868: docstrings of `Row.label`, `rows()`, DS `t_summary` and the ARD `warning`/`error` columns match the code.
- c1-450, c1-508: tests for the header-row statistics, adjacent worst-case ranks, two lab parameters, the LOW/HIGH rank, LOW LOW and HIGH HIGH, mixed-case and null ANRIND, and the lab listing.
- c1-108: `ae_aerel` matches map keys with upper-case letters; `aerel_map={}` maps nothing.
- c1-114: `ae_aerel` trims an unmapped value before it is upper-cased.
- c1-113: `export_supp` raises when DOMAIN holds more than one value and `domain=` is not given, takes RDOMAIN from the non-null DOMAIN values, and raises when STUDYID or USUBJID is absent.
- c1-116: `epoch_assign(epoch_ranges=)` accepts a Date column.
- c2-953: `epoch_assign(se=)` raises a named DerivationError when SE has no EPOCH.
- c1-253: an empty TDD section gives a 0-row frame with all columns; VISITDY is Int64 when every value is null.
- c1-256, c1-260: `Epoch` has the 13 C99079 terms; `_concept_id` is no longer a member, so `to_spec_yaml` with `ct=Epoch` works. `cdrsob_total(domain_cols=[])` raises a DerivationError.
- c1-790: the TDD audit does not crash on a null or absent TSVAL or a TA with no ELEMENT, and reports an ETCD not in TE with no false SD0067 on a null ELEMENT.
- c1-92: an expression with `and`, `or` or a chained comparison raises a message that shows the `(A) & (B)` form.
- c1-106: `multiple_responses` says it is not for DM RACE; docs/concepts/advanced.md gives the RACE = "MULTIPLE" recipe.
- c1-97: docs/concepts/advanced.md says not to change a frame in place after a namespace call.
- c1-115: the `nsv` docstring no longer names "IG 3.5+"; the inline example exports a sponsor flag, not ARM.
- c1-789: docs/concepts/tdd.md says that TS coded values are not checked.
- c2-953: docs say that `TrialElement.epoch` drives TA, not SE.
- c1-231: vaccine verbs, `derive_param`, `derive_summary_records`, `ex.t_summary` and `mh.check` follow the docstring convention.
- `ValidationService.validate_sdtm`, `validate_adam` and `validate_datasets` refuse an IG version Fleet does not support (`banana`, `3.1.3`) with `ValidationSetupError`, not a valid NOT ASSESSED result. `DatasetChecker.validate_core` uses the run setup: the study's engine, custom rules and timeout. (c1-838)
- A `validation.engine_path` that names no file stops validation with a message that names the path; Fleet no longer falls back to another engine. `fleet check` and `fleet doctor` warn with the pinned path. (c1-523)
- An engine report whose rule says "issue reported" but has no `Issue_Details` rows is "could not run", not a pass. (c1-265)
- A finding on a split pair (`LBCH.JSON, LBHM`) is attached once, to the first given dataset, and names the other in its message; `Issue_Summary` no longer adds findings; `fleet validate` counts only the datasets it was given. (c1-267)
- The Variable field of a finding no longer holds a template name, a value or a metadata column name. (c1-831)
- A `fleet validate` directory sweep takes upper-case suffixes (`AE.XPT`) and Dataset-JSON files, and names each file it skips. (c1-834, c1-241)
- A data folder that both standards share is swept once, and a nested ADaM folder names ADaM. (c1-836)
- `fleet install-engine` checks the download against the GitHub digest, extracts a tar with the `data` filter, keeps the installed engine when the new bundle has no executable, and turns a network or archive error into a clear message. (c1-522, c1-524)
- `fleet install-engine --version 0.15.0` installs tag v0.15; with an engine installed, it says the requested version was not installed. (c1-525)
- `fleet add-rule` never replaces a file: it counts file names and `.yml` files, and refuses an ID, prefix or domain with a path or space character. `fleet check` fails on two rule files with one Core.Id. (c1-527, c1-528, c1-532)
- `fleet check-rule` fails on a scaffold that still holds `VARIABLE_NAME`, and accepts a rule scoped with `Domains: Exclude`. (c1-529, c1-530)
- `fleet init define` with a dotted IG version (`3.4`) asks the CDISC Library for the dashed path. (c1-532)
- The engine path docstrings name `~/.fleet/cdisc-rules-engine/core/core`. (c1-839)
- `read_dataset_json` refuses a file whose `records` is not the number of rows, or a row with too many or too few cells. (c1-580)
- `save_dataset_json` writes a `pl.Decimal` column as `decimal`, and a Float32 value with the digits it shows. (c1-581)
- `save_dataset_json` and `read_dataset_json` refuse an `.ndjson` path. (c1-582)
- `load_raw_data` reads the named file when its name holds glob characters (`adsl[1].parquet`). (c1-240)
- `load_study_context`, `download_raw_data`, `save_parquet` and `save_xpt` take a text path. (c1-243)
- `load_raw_data(file_type="xpt")` uses the XPORT reader for a file with another suffix. (c2-948)
- docs/concepts/comparison.md says that SAS special missing values read as null, so `.A` against `.R` compares equal. (c1-239)
- A codelist definition with triple quotes, a backslash or a final double quote no longer makes `codelists.py` invalid Python (c1-554).
- `program_from_spec` (the MCP `fleet_spec_to_code` tool) writes a TODO comment for a `callable:` that is not a dotted Python name, not an import line with its text (c1-555).
- `import_codelists()` leaves `sys.modules` as it was when the file fails (c1-759).
- The CDISC API key is not in the `CDISCClientConfig` repr. The client does not follow a redirect, so the key never goes to another host; a 3xx or a non-JSON answer (a sign-in page) raises `CTError` that names the host (c1-760, c1-761).
- A CT file keeps every term as exact text (YAML `0` and `Yes`, CSV `01`). An empty file or a codelist that is not a term mapping raises `CTError`, and the validator cache stays as it was (c1-764).
- A CT file from a URL is downloaded into a private temporary folder, not a fixed path in the shared temp folder; a local `http_ct.yaml` is not a URL (c1-765).
- The CORE engine input writes a null text value as "", as a SAS transport file does, so SDTMCHK-DS-001 runs when one DEATH record has a null DSSTDTC (c2-887).
- New tests pin value-level where clauses on AVISIT (`def:ItemOID`, Mandatory, SoftHard), checker types, Dataset-JSON types and ISO text, `dtc_text` seconds and unparsable dates, and SE element ends per subject (c1-574).
- `fleet.compare(..., pairs={"AVAL": "RESULT"})` reports a candidate `AVAL` as a candidate-only variable. A pair target that an unpaired base variable also matches by name is refused; a swap stays legal. (c1-515)
- A difference on a Duration column is listed in ISO 8601 (`P1D` against `P3D`); it no longer stops the compare. (c1-518)
- A BY variable named `matched`, `base_only`, `candidate_only` or `observations_with_differences` no longer stops the compare with a DuplicateError. (c1-519)
- Under `allow_duplicates`, the HTML block header counts the same observations as the chip. (c1-723)
- `save_json`, `save_html_report` and `save_listing` make a missing parent folder. (c1-724)
- `fleet lsp`: an unexpected key is reported on its own line, once per key; a refused `derivation:` block gets the text of `from_spec()` on the line of its key ("sorce: Extra inputs are not permitted"). (c1-608)
- `fleet lsp`: a completion after a bare `algorithm:` inserts `" assign"`, so the YAML stays valid; `:` is no longer a trigger character. (c1-609)
- `fleet lsp`: a key that only `fleet define-xml` needs (a study key, a dataset or variable `label`, `structure`, `keys`, `type`) is a warning "(needed by fleet define-xml)", and the root anyOf text is replaced by "A spec needs datasets: with study:, or variables:". (c1-610)
- `fleet lsp`: parameter completion reads the YAML block by indent: a quoted `algorithm: "duration"` works, keys of a nested `when:` or `ct_map` do not leak, and keys the block already holds are left out. (c1-611)
- `fleet lsp`: U+2028, U+2029 and U+0085 no longer shift line numbers; the server uses full document sync and converts positions with the negotiated encoding. (c1-612)
- `fleet lsp`: closing a file clears its diagnostics. (c1-613)
- The standard of a spec with no `study.standard` comes from the nearest `sdtm` or `adam` folder, the same in `fleet lsp`, `fleet spec-to-code` and `fleet define-xml`. (c1-614)
- `fleet lsp`: `algorithm: CHG` gets "Did you mean 'chg'?"; a pre-ADR-0008 name and `fleet_spec_version: 1` name `fleet migrate --spec`. (c1-615)
- A recursive YAML anchor, an alias bomb or a very deep nesting in a define.yaml gives one error ("the file nests too deep or expands too much"); `from_spec`, `fleet check`, `fleet define-xml` and the language server stay alive. (c1-616)
- `fleet mcp`: an error inside a tool reaches the assistant with its reason on mcp 2.x too (`ToolError`). (c1-599)
- `fleet mcp`: `fleet_tlg_run` refuses a table that uses ADSL when no `adsl_path` is given, as `fleet tlg run` refuses it; the rule is `fleet.tlg.resolve_population`, shared by both. (c1-601)
- `fleet mcp`: `fleet_validate` lists the study-level CORE findings (dataset `STUDY`) as information; each issue carries an additive `dataset` key. (c1-602)
- `fleet mcp`: the handshake gives Fleet's version in `serverInfo`. (c1-603)
- `fleet mcp`: `fleet_ct_terms` with a `ct_path` that does not hold the codelist names the file and its codelists. (c1-604)
- `fleet mcp`: `fleet_lineage` refuses a JSON file with no `nodes` key, so it no longer returns values of any JSON file. (c1-605)
- `fleet mcp`: `fleet_ct_terms` refuses a URL as `ct_path`; the CT loader treats only `http://` and `https://` as a URL; the IDE page has a "Trust model" note. (c1-606)
- `fleet migrate` (Python and `--spec`) reports a file that cannot be read, decoded, parsed or written on one line and goes on with the batch; it exits 1 and no longer prints "Nothing to migrate." after a failure (c1-824).
- `fleet migrate` rewrites `assign_dtc(input_format=)` to `date(format=)` and reports `remove_dup` for a rewrite by hand (c1-826).
- `fleet migrate` keeps the comma and the comment of a moved `keep` list, moves a name (`lookup(cols, dataset=...)`) to `keep=`, and reports an old verb name used as a value (`fn = df.sdtm.assign_no_ct`) (c1-828).
- `fleet migrate --write` keeps CRLF line endings (c1-829).
- `fleet compare` turns an unexpected exception into exit 2, "internal error in fleet compare: ...", not exit 1 ("the datasets differ"); `FLEET_DEBUG=1` keeps the traceback. stderr escapes characters that the console cannot encode, as stdout does (c1-275).
- `fleet compare --pairs` refuses an item with more than one `=` and a base name given twice (exit 2). A corrupt or ragged input file is named with its side and path ("cannot read the candidate b.parquet: ...") (c1-276, c1-277).
- `ComparisonReport.save_json`, `save_html_report` and `save_listing` create a missing parent folder (c1-277).
- `fleet compare` refuses (exit 2) an `--out` or `--report` that names the base or the candidate file, and an `--out` equal to `--report` (c1-278).
- `fleet tdd audit` and `fleet tdd build` print one line for a model error ("invalid TrialVisits: Duplicate VISITNUM values", an ARMCD with a hyphen) and name an empty design file; `fleet tdd ctgov --write` on an empty file no longer ends in a traceback (c1-270).
- `fleet` prints one line, not a traceback, for a YAML error (with its line and column), a pydantic error, an `OSError` (a folder that cannot be written), a `UnicodeDecodeError` and a Polars error; `fleet run` names the dataset of a Polars error. `FLEET_DEBUG=1` keeps the traceback (c1-296, c1-315).
- `DatasetChecker` reads a variable with no `label:` as an empty label, so `fleet run` does not stop with `KeyError: 'label'` (c1-315).
- A `study_config.yaml` that is found but invalid is an error in every command, also in `fleet add-ct` and `fleet tlg`; before, they took it as "no study" (c1-300).
- `fleet run` prints the row count of each input and the start and end time. Keep a log with `fleet run > run.log 2>&1` (docs/getting-started/cli.md). A `--log` option is left for later (c1-294).
- `fleet run` stops with "no dataset to build in metadata/sdtm/define.yaml" when the plan is empty (`datasets: []`, the simplified single-dataset format), not "0 dataset(s) written" with exit 0 (c1-295).
- `fleet check` validates each derivation block with the calls of `from_spec`, so a block that `fleet run` refuses (`assign` with `source:` and `value:`, `ct_map` with no codelist) fails the gate (c1-299).
- `fleet validate <folder>` finds a dataset whose extension is in upper case (`DM.PARQUET`) on a case-sensitive disk (c1-289).
- `sdtm.ig_version: 3.4` and `adam.ig_version: 1.3` are stored as `3-4` and `1-3`, so `fleet new --ig 3.4` works. `fleet init rules` exits 1 when no rule file is cached, and `--sdtm-only` with `--adam-only` is a usage error on `init rules` and `init define` (c1-311).
- `fleet add-ct` reads the CT package of an existing `codelists.py` first: outside a study it uses that package, and it refuses a package (from `--package` or the study pin) that differs from the file (c1-283).
- `fleet validate` reads each file before the engine run: a corrupt, empty or unsupported file is "could not run: cannot read the file" (exit 2) and the other datasets are still validated. An `--report` path that cannot be written gives one line and exit 2. `fleet_validate` of the MCP server returns "could not run" for a file it cannot read (c1-279).
- `fleet tlg run/export --rows-per-page` takes a whole number of at least 1 (usage error otherwise). `--wrap` is refused for RTF and PPTX and for a template with no `{table}`; `render_html` and `render_listing_html` raise `ValueError` for such a wrapper. A `--page-by` that matches no group row gives a warning (c1-312).
- `derivations_module: programs.derivations` imports from any working directory: the import uses the study root (the folder of the first `study_config.yaml` above the spec), appended to `sys.path`. An error raised inside the module is a one-line `SpecError` that names the spec, not a traceback (c1-293).
- Parameter texts in the define schema and in editor hovers no longer end at "(e.g.". A codelist hover with no terms no longer shows an empty "Terms:" line. (c1-780)
- `fleet.spec_algorithms("SDTM")` returns the SDTM list; an unknown standard raises a ValueError that names "sdtm" and "adam", not a raw KeyError. (c1-699)
- The CDISC Library client raises a `CTError` when an answer is not JSON (a proxy or sign-in page), not a raw decoding error. (c1-844)
- A NaN score gets no `bcva_criterion` flag and no `mmse_category` or `moca_category` category. Before, NaN compared above every cut-off and gave "Y" or "Normal". (c1-855)
- `adam.tte.param(..., by=[...])` accepts a censor frame with none of the `by` columns, such as an ADSL frame. It applies to every stratum of the events, as admiral `derive_param_tte` Test 5. Before, it raised "column not found". (c1-861)
- API pages: every mkdocstrings option block and admonition body is indented, so the options apply; ADSL and OCCDS pages list inherited verbs (c1-636, c1-637).
- `pipeline.md`: verb tables name real verbs and keywords (`flag_first`, `flag_exists`, `derive_period(periods=)`, `derive_param(by=)`); the plan drawing shows one LazyFrame (c1-637, c1-652, c1-653, c1-669).
- `ct.md`: one validation rule, the real class form, the real loader and its file format; the example runs in a test (c1-640).
- `troubleshooting.md`: real messages (`UserWarning`, `DerivationError`, `SpecError`) and `.explain()` / `.trail()` instead of a private attribute; the page runs in a test (c1-668, c1-669, c1-670).
- `tdd.md`: the SE and EPOCH examples define their inputs and run in a test (c1-654).
- Removed the broken spec-driven notebook; the quickstart points to `examples/cdiscpilot01_spec_driven.py`; notebook 01 runs in a test (c1-655).
- Real trail and CORE output in `full_pipeline.md`, the real rule id in `custom-rules.md`, the tracker command, and `version=` in the `ValidationService` sample of `llms.txt` (c1-659).
- Compare docs: the verb is on the SDTM and ADaM namespaces; `on_fail="ignore"` still prints the report; the truncation hint names `--all`; the pyreadr install line (c1-643).
- `xsd.py`, `STRUCTURE.md`, `installation.md`: no `fleet install-xsd`; the real `load_datasets` signature; the `io` extra reads SAS files and writes XPT (c1-644, c1-645).
- Introspect docstrings name `spec_verb()` and drop aliases; ADR-0001 notes the later names (c1-641).
- `define-yaml.md`: the schema does not catch every `from_spec` error; the old-key message; the define writes `duration(start=, end=)` (c1-646, c1-647).
- `transforms.py` and `advanced.md`: no `algorithm: transform`; AGEGR1 keeps a missing AGE missing (c1-647, c1-653).
- `examples/full_pipeline_example.py` takes TRTSDT from EX, not from AE (c1-652).
- `exports.md` no longer promises graphs; `Row.label` says that no label gives no heading (c1-649).
- `ide-tooling.md` and `quickstart.md`: loads are wrapped with `fleet.frame`; a plain Polars step needs a re-wrap; `inject_lineage` before `generate` for `fleet_lineage`; the LSP scope (c1-597, c1-664, c1-665, c1-666).
- `validation-strategy.md`, `test-status.md`, `index.md`, `validation-core.md`, `why-fleet.md`: five pillars, eight examples, no static test tree or coverage badge, goals labelled, sourced admiral and CORE statements (c1-672, c1-673).
- c1-587: the GUIDE and full-pipeline baseline recipes flag the last pre-dose record (`criteria="last"`, `where=`), so `baseline` no longer stops on two pre-dose records.
- c1-679, c2-879, c1-683: the inline ADSL recipe gives EOSSTT "ONGOING" to a subject with no disposition record, no EOSDT to a screen failure, ACTARMCD on the ARMCD codes, and ITTFL from a non-null ARMCD; `full_pipeline_example.py` takes TRTSDT from EX and ABLFL from a date rule.
- c1-685: `r2r_ae_example.py` sends the planted AESER "YES" only to the SDTM validation, so the AE table counts the serious AE; `r2r_strategy.md` shows the real report.
- c1-681: the CBOR example follows admiralonco `derive_param_confirmed_bor` and ADR-0030 (stop at first PD, NON-CR/NON-PD, MISSING from ADSL); a grid test holds the admiralonco 1.4.1 results.
- c1-676: the ADNCA example states that its data is synthetic, has PK samples only for active subjects, sets TRTSDT at the first dose, and adds STUDYID, PARAMCD and PARAM.
- c1-686: the VS example header row states `statistics=[N_SUBJECTS]`, so it counts subjects instead of pooling SYSBP and DIABP.
- c1-588, c1-590, c1-840: GUIDE, STRUCTURE, CONTRIBUTING and docs lines match the API (no `.by2`, `check_rule`, `programs/derivations`, the SE block with ETCD runs in a test, the TestPyPI line, extras tables, `spec_verb`, `MultiRowMixin`, the `transform` YAML form, `df.adam.pk`/`tte` in the package docstring).
- c1-188, c1-190: docs-site links carry `/latest/`; the LICENSE link is absolute; the README migrate paragraph is removed.
- c1-630: benchmark/REPORT.md no longer names the wrong date of the earlier report.
- c1-353: the validation log says `(1 occurrence)` for one occurrence, not `(1 occurrences)`.
- c1-498: `.rows(["AEBODSYS", "AEDECOD"])` with plain names takes the row labels of the template's default rows. The ARD is equal to the `t_summary()` shortcut, and the stub header is "System Organ Class / Preferred Term". `Row(field=..., label="")` still asks for no label.
- **Validation text report:** the label of the row numbers is `Row:` for one row and `Rows:` for a list such as `2-4, 7`, not `Rows affected:`. The occurrence count stays (ml2-misc task 2).
- **Tests:** the c1-616 deep-nesting test of `load_spec_yaml` nests 101 levels, not 3,000. At 3,000 levels the parser hit the Python recursion limit, so the test never reached the depth-100 limit. A separate test covers the recursion guard (ml2-misc task 4).

#### Removed

- `source(target, from_col=...)`: rename with `assign(target, source=...)`, the one assignment vocabulary that `fleet migrate` already writes. `source(*names)` still carries columns through (c1-755).
- `depends_on:` in a define.yaml derivation block: it had no effect, because every verb checks its own columns. `fleet migrate --spec` removes it; `from_spec` refuses it (c1-54).
- c1-753: dead code: `fleet.core.seq`, `_DOMAIN_ADD_VERBS`, the `first_sentence` aliases, the `_FLAG_CRITERIA_KEYWORDS` re-export, the empty `MultiRowMixin`, `SDTMDomainSpec`, `ADAMDatasetSpec`, the unread `_sas_labels` attribute and `tmp_lineage_probe.py`.
- c1-548 c1-747: `SDTMError` and `ADAMError`, which nothing raised.
- The `ADAMAlgorithm` and `SDTMAlgorithm` enums, the `ADAMVariableSpec` and `SDTMVariableSpec` factories, the `ADAMDatasetSpec` and `SDTMDomainSpec` classes and the two variable-spec unions, with their exports in `fleet`, `fleet.adam` and `fleet.sdtm` (ADR-0008). `fleet.core.spec_registry.algorithm_names()` names the verbs; `NSVMeta` stays (c1-711).
- c1-87: the dead `fleet.core.seq` module and `fleet.adam.utils.study_day` (no caller, false docstrings). The study-day rule (no day 0) is one helper, `fleet.core.dtc.cdisc_day`, used by `duration`, `study_day` and the SDTM TDD study day.
- c2-965: `DMSummarySpec.age_var` (use `continuous_vars`).
- c1-819: the PPTX theme key `bold_header_rows` and the unused `indent` argument of the slide cell helper.
- `CTValidator.get_decode_map`, `CTValidator.apply_ct_mapping`, `CTValidator.load_codelist` and `fleet.ct.create_ct_lookup`: nothing called them, and `get_decode_map` gave M to M on a flat CT file. Use `get_valid_values` or the define.yaml decodes (c1-769).
- `CDISCClient.get_packages`: it had no caller and ignored its product argument (c1-761).
- The `DatasetChecker` core aliases `Required` and `Expected`: the define schema refuses them (c1-574).
- `fleet.tools.migrate.migrate_file`, `fleet.tools.migrate_spec.migrate_spec_file` and `fleet.tools.migrate_spec.migrate_block`: no caller used them; `migrate_source` and `migrate_spec_text` stay (c1-825).
- The Codecov upload, the `fleet-dev.pth` setup step, the `specs/**` docs path and the scratch file `tmp_lineage_probe.py`. (c1-623)

### Alpha audit: high findings

The high findings of the alpha audit (`HIGH-REMAINING.md`), fixed with the decisions of 4 November 2026. ADR-0021 to ADR-0046 record the changed defaults.

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
- c1-432: `fleet tlg export --adsl-groupby` names the ADSL arm column for the big N (sets `adsl_group_col`), as `fleet tlg run` does.
- c1-432: `adsl.tlg.dm.check(groupby=...)` and `adsl.tlg.ds.check(groupby=...)`; `TLGSpec.check()` takes `group_col=`. Without it the check reads the arm that the table takes.

#### Changed

- **`flag(criteria="first"/"last")` is faster with many small groups** (#207). The verb sorts the frame once in place of an ordered window per group. The flags do not change. On the sparse benchmark input (1M AE rows, about 1 record per USUBJID and AETERM) the verb takes 0.2 s in place of 1.2 s, and the ADAE pipeline 0.9 s in place of 2.1 s. With 40 records per subject it takes about the same time. `flag_all=True` keeps the window.
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
- c1-355: `df.adam.tte.param()` follows admiral 1.5 `derive_param_tte` (`end_dates`, `event_type = "negative"`). New API: `param("PFS", start="TRTSDT", events={"PD": pd_frame}, censors={2: last_assessment, 3: start_frame}, stop_at=["EOSDT", "NACTDT"])`. Each source is a plain frame with `USUBJID` and `ADT`; the `events` key is the EVNTDESC, the `censors` key the CNSR. Event and censor records after the earliest `stop_at` date are dropped, so a subject without an event is censored at the last record before it (subject A: ADT 2024-03-01, AVAL 61, not 2024-04-01, AVAL 92). A subject with no record left drops with a warning that names the USUBJIDs. `EventSource`, `CensorSource`, the prebuilt sources, `sources_frame()`, `start_date=`, `end_dates=` and `event_type=` are removed (ADR-0043).
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
- c1-355: `df.adam.tte.param()` without `param=` (and without PARAM in `set_values_to`) takes PARAM from the study CT: the decode of PARAMCD in the codelist of `ADTTE.PARAMCD` in the ADaM `define.yaml`. If no decode is found, it raises and names PARAMCD, the places searched and the fix (`param=`). Before, the rows had no PARAM (ADR-0043).
- c1-355: a censor frame without an `EVNTDESC` column still gives a null EVNTDESC (admiral), and `param()` now warns and names the CNSR keys and the fix (ADR-0043).
- c1-105 c1-562: `fleet define-xml` and `fleet check` accept an SDTMIG 3.4 (or earlier) define.yaml with `role: qualifier` or `algorithm: nsv` variables in the parent dataset, the form that `fleet run` uses to write `SUPP<domain>`. The Define-XML leaves the qualifier out of the parent ItemGroupDef and adds a generated `SUPP<domain>` ItemGroupDef (STUDYID, RDOMAIN, USUBJID, IDVAR, IDVARVAL, QNAM, QLABEL, QVAL, QORIG, QEVAL; IDVAR `<domain>SEQ`, null for DM) with value-level metadata on QVAL, one where clause `QNAM EQ <name>` per qualifier. The c1-562 refusal stays for a qualifier that cannot move: no STUDYID or USUBJID, no `<domain>SEQ` outside DM, a declared `SUPP<domain>` as well, a QNAM over 8 or a QLABEL over 40 characters, or a qualifier that is a key (ADR-0044; ADR-0041 updated).
- c1-119: `.adam.date()` and `.sdtm.date()` share one `*DTM` path (`impute_dtc_to_datetime`), so one call gives one result in both namespaces. `.sdtm.date()` on a partial date now imputes, as `.adam.date()` does (ADR-0045).
- c1-119: `time=` on a `*DTM` target first joins the date and the time into one `--DTC` value (`2024-03--T08:15` for a partial date), which then takes the imputation and `highest=`. A partial date with `time=` is now imputed, not null. TMF now flags the imputed time parts (`08:30` gives `S`, a null time `H`); an `hh:mm` time with `impute_time="last"` takes seconds 59. A null time takes `impute_time`, else `impute`. A time in another layout gives one warning (ADR-0045).
- c1-119: `highest=` on a `*DTM` target takes the admiral levels `"M"`, `"D"`, `"h"`, `"m"`, `"s"` and `"n"`; `"Y"` still raises, because it needs bounds that a `*DTM` target refuses. Parity with admiral 1.4.1 `derive_vars_dtm` is frozen in `tests/fixtures/goldens/dates/admiral_dtm_grid.csv` (`scripts/regen_admiral_dtm_grid.R`).
- c1-432: the subject-level tables on ADSL (`dmt01`, `dst01`, `dtht01`, `ent01`) group by `TRT01A` by default, else by `TRT01P` when ADSL has no `TRT01A`, not by `TRTA` (ADaMIG 1.3; ADR-0046). A spec or call that names the arm never falls back. The CLI, the MCP tool and `resolve_groupby()` let these specs detect their own arm; `tlg export --domain dm|ds` detects `TRT01A` then `TRT01P`. The golden ARDs of the four tables changed in `group1` only (`TRTA` to `TRT01A`).
- c1-432: the examples (`r2r_ae_example.py`, `tlg_ae_example.py`, `tlg_vs_example.py`) and the docs (`r2r_strategy.md`, `tlg_pipeline.md`, README, GUIDE) use conformant ADaM variables: ADSL with `TRT01A`, ADAE and ADVS with `TRTA`, and `adsl_group_col` / `population(adsl, group_col="TRT01A")` / `--adsl-groupby TRT01A` for the big N. The planned arm is no longer aliased as `TRTA`.
- c1-487: `benchmark/run_benchmark.py` now runs Fleet twice per input (default Polars thread count and `POLARS_MAX_THREADS=1`) and oak + admiral once, on the sparse input and on a new dense-subject input (`inflate_data.py --dense-rows`, about 40 AE records per subject). Each scale runs three times (`--reps`); the report gives the median and the min-max range, and records machine, OS, core counts, thread count and load average.
- c1-484: the record-by-record check of 17 ADAE variables now runs at every scale and on both inputs (Fleet at both thread counts against admiral); `run_benchmark.py` exits 1 on any difference.
- c1-487: `benchmark/rpy2_adae_benchmark.py` uses the same ANL01FL tie order and ASEQ order as `admiral_adae_benchmark.R`.
- c1-483, c1-487: `benchmark/REPORT.md` holds the numbers of the rerun only: date, versions, subject and thread counts next to the table, a dense-subject row, a single-thread row and the row-by-row check result per size.

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
- c1-355: the `param()` docstring and ADR-0043 state that an event or censor date before `start` is set to `start` and keeps its CNSR (admiral ADT = max(ADT, STARTDT)).
- c1-119: a `--DTC` value with a hyphen in the time (`2021-03-15T08:-:45`) now gives 08:00:00 with TMF `M`, as admiral, not 00:00:00 with TMF `H`.
- c1-487: the R benchmark scripts reported the R peak memory from the wrong `gc()` column (a cell count, not MB).
- `fleet run` on the CDISCPILOT01 example stopped at ADSL with "would overwrite the existing column 'STUDYID'". The pilot ADSL now copies STUDYID from DM (Predecessor `DM.STUDYID`) and declares EX as an input for TRTSDT and TRTEDT. The SDTM AESEQ and EXSEQ get `algorithm: seq`. The run builds DM, AE, VS, EX and ADSL from the raw inputs.
- The lineage capture compared a verb argument with a None default by `==`. A frame or expression argument (`flag_exists(from_dataset=...)`) gave the Polars warning "Comparisons with None". It now tests None by identity.
- The TLG docstring examples (`t_summary(groupby="TRTA", adsl=adsl)` and the other `t_*` methods), the render examples, docs/api/tlg.md and GUIDE.md failed on an ADSL that holds the arm as TRT01A. They now set `adsl_group_col="TRT01A"` on the spec, or `population(adsl, group_col="TRT01A")` in the builder.

#### Removed

- The private `_check_fk` helper; the queued FK check of `to_frame()` is the one path (c1-195).
- c1-736: `PipelineDAG.to_snakefile()` and `PipelineDAG.to_airflow_dag()` are removed for the alpha. The Snakefile paths differed from where `fleet run` writes, and an Airflow file for the domain IS did not compile. `to_airflow()`, `to_snakemake()`, `execution_order()` and `generate()` stay. full_pipeline.md section 8 now shows the graph as data.
- c1-44: `@derivation(by=..., set_values_to=...)` (kind "param") and `fleet derivation add --kind param` are removed. The decorator raises VerbUsageError that names `.adam.derive_param()`: kind "param" appended no row and overwrote AVAL.
- c1-264: the shipped custom rule SDTMCHK-VS-001 (DBP > SBP). It compares two records and could never run in CORE (`$SYSBP_VALUE` is never defined).
- 14 sponsor rules that the engine cannot express with the R condition: the visit-order rules EG-001, EX-009, LB-004, QS-002, RS-002, TR-002, TU-003 (the engine sorts unscheduled records too), DS-005, AE-018, AE-019, AE-020, DM-003, DS-006 (an operation filter takes exact values only) and VS-001 (needs a SYSBP/DIABP merge). (c2-918)
- c1-119: `fleet.adam.utils.dtm_with_time` (replaced by `dtm_source_text` and the shared path). `refuse_dtm_bounds` no longer takes `highest=`.


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
