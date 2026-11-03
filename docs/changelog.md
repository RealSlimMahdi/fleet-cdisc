# Changelog

All notable changes to Fleet are documented here.

## [Unreleased]

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

### Changed

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
