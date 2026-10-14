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

### Running a study

**Study run**:
The operation that reads the study's define files, builds every dataset they declare from its inputs, and hands each built dataset forward to the datasets that take it as an input. The CLI, a notebook and a protocol adapter all start the same study run. Distinct from a sweep, which validates datasets already built.
_Avoid_: run (alone), execution, build, pipeline run

**Study plan**:
The ordered list of steps a study run will take, fixed before the first dataset builds: for each step, the define file, the standard and the dataset name. A caller can read the plan without running it.
_Avoid_: queue, schedule, run list

**Step**:
One dataset of a study plan, built from its declared inputs in its turn.
_Avoid_: task, job, stage

**Built dataset**:
What a study run yields for one step: the dataset name, its standard, the define file it came from, the frame, and where each input came from.
_Avoid_: result, output, run result

**Carry-through column**:
A variable a define declares with no derivation. A study run takes it from the dataset's inputs, unchanged. A variable with a derivation never comes from an input, only from its algorithm.
_Avoid_: pass-through, copied column, merged column

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
