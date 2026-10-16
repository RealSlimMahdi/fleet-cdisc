# Fleet

CDISC-compliant clinical data derivation, expressed as Polars namespace extensions. Raw study data goes in; SDTM domains, ADaM datasets, and the Define-XML that describes them come out.

## Language

### Tooling surface

**Introspection surface**:
The narrow, additive-only set of names Fleet publishes for tooling that needs to _describe_ Fleet rather than run a derivation — algorithm catalogues, parameter tables, the define schema. Distinct from the derivation API, which is aimed at analysts.
_Avoid_: public API, tooling API

**Protocol adapter**:
A module that translates an external wire protocol into calls on Fleet's own registries and holds no clinical knowledge of its own. The language server and the MCP server are the two that exist.
_Avoid_: server, integration, backend

### Validation

**Validation**:
The operation that runs the CDISC conformance rules of one Implementation Guide version against one or more datasets of one standard and reports the findings. Distinct from a compare, which pairs two datasets.
_Avoid_: check, conformance run, P21 run

**Run setup**:
The resolved inputs of one validation, fixed before the engine starts: the standard, the IG version, the custom rules, the engine, the study config it came from, and the datasets with their mode (one dataset or a sweep). Each input is taken from the first source that gives it: an explicit argument, then the study config, then the environment, then the built-in default. Every surface that validates works from a run setup and resolves nothing itself.
_Avoid_: engine setup, run settings, validation plan

**Not assessed**:
The outcome of a validation in which no rule executed, so the dataset is neither passed nor failed. Today every ADaM run ends this way, because CDISC has published no executable ADaMIG rules.
_Avoid_: pass, skipped, empty run

**Could not run**:
The outcome of a validation that never reached the rules, because its run setup was refused, for example when the directory and the file name of a dataset point to different standards. Neither passed nor failed, and distinct from not assessed, where the rules were reached and none applied.
_Avoid_: error, fail, skipped

**Custom rule**:
A sponsor rule written in the CORE rule schema and kept in the study's custom rules directory. Custom rules run in their own engine run next to the official CDISC rules, and each finding says which of the two it came from.
_Avoid_: local rule, sponsor check, SOP rule

**Sweep**:
A validation of every dataset in the study's data directories, in one engine run per standard (two with custom rules), so that rules spanning several datasets of that standard can execute. The SDTM and ADaM results are joined into one report with one verdict. The verb validates one dataset and cannot run those rules.
_Avoid_: batch, bulk validation, study run

### Tables, listings and graphs

**Template**:
One named TLG output as the catalogue lists it, for example `aet01`, the overview of adverse events. A template has a stable id, a CDISC class, and exactly one way to produce it.
_Avoid_: shell, mock, report, table type

**Spec**:
The complete description of one TLG output that a template consumes: rows, statistics, columns, filters, formats. It is a data object; a YAML file and the fluent builder are two ways to write one.
_Avoid_: config, settings, options, parameters

**ARD**:
The analysis results dataset: one long table with one row per statistic per cell, which every TLG output is first computed as and every renderer reads from. Compatible with the R `cards` package layout.
_Avoid_: result, output table, summary

**Population filter**:
The spec's filter on ADSL that decides who is in the denominator, for example the safety population. Applied to ADSL only, never to the analysis dataset.
_Avoid_: adsl filter, subset, big-N filter

**Dataset filter**:
The spec's filter on the analysis dataset that decides which records are counted, for example treatment-emergent events only. Applied after the uncoded rule and before the template's prefilter. An analyst sets it per study.
_Avoid_: where clause, subset, record filter

**Prefilter**:
A template's own filter on the analysis dataset, for example "drop the baseline record" on a change-from-baseline table. It is a spec field with a default per template, written as an expression, and applied after the dataset filter. Every column it names is a required column of the template.
_Avoid_: guard, hard-coded filter, built-in filter

**Uncoded**:
The rule that gives a null coding term, for example a missing AEDECOD, a visible level such as "No Coding Available" so the record is counted instead of dropped. A spec field that names the coding columns and the label; switched off by setting it to nothing.
_Avoid_: fill uncoded, no-coding row, missing term handling

### Comparison

**Compare**:
The operation that pairs two datasets observation by observation on their keys and variable by variable on their names, and reports where they differ. Distinct from validation, which checks one dataset against CDISC conformance rules.
_Avoid_: validate, check, diff, reconcile

**Base**:
The dataset a comparison is measured against; the reference the candidate is expected to match.
_Avoid_: left, production, expected

**Candidate**:
The dataset being measured against the base.
_Avoid_: compare (as a noun), right, actual, QC dataset

**Comparison report**:
The outcome of a compare: which variables and observations were common, which were missing from either side, and every value that differed.
_Avoid_: diff, comparison result, compare output

**Verdict**:
The single answer a comparison report gives: EQUAL when the compare found no difference, NOT EQUAL otherwise. Every way of running a compare gives the same verdict for the same two datasets.
_Avoid_: pass/fail, result, status

**Keys**:
The variables that together identify one observation within a dataset. A compare pairs observations on them and refuses to run without them.
_Avoid_: ID variables, join columns, primary key

**BY group**:
The observations sharing one combination of values of the BY variables. A compare given `by` prepends those variables to the keys, labels every difference with its group, and reports the observation and values summaries per group; the verdict stays global.
_Avoid_: stratum, cohort, partition, split, subgroup

**Variable pair**:
A base variable and a candidate variable compared under different names, on top of the variables matched automatically by name.
_Avoid_: VAR/WITH, rename map, column mapping

**Kind**:
The family a variable's dtype belongs to for comparison purposes: numeric, string, temporal, boolean or other. Two variables of one kind but different dtypes are compared after casting; two of different kinds are a type conflict.
_Avoid_: type, class, category

**Tolerance**:
How far two numeric values may drift and still count as equal: absolute (`abs_tol`), or relative to the base value (`rel_tol`). A compare is exact unless a tolerance is given.
_Avoid_: precision, epsilon, fuzz, approximate equality

### Spec

**Spec algorithm**:
The verb a define.yaml names in `algorithm:`. The keys of the block are the keyword arguments of that verb, so one verb is one spec algorithm (ADR-0008). A declaration adds only what the signature cannot say: excluded arguments, exclusive groups, a stricter required key, the target default of `source`, and the Define-XML method text.
_Avoid_: derivation type, spec verb, dialect, alias
