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

**Keys**:
The variables that together identify one observation within a dataset. A compare pairs observations on them and refuses to run without them.
_Avoid_: ID variables, join columns, primary key

**Variable pair**:
A base variable and a candidate variable compared under different names, on top of the variables matched automatically by name.
_Avoid_: VAR/WITH, rename map, column mapping

**Kind**:
The family a variable's dtype belongs to for comparison purposes: numeric, string, temporal, boolean or other. Two variables of one kind but different dtypes are compared after casting; two of different kinds are a type conflict.
_Avoid_: type, class, category

**Tolerance**:
How far two numeric values may drift and still count as equal: absolute (`abs_tol`), or relative to the base value (`rel_tol`). A compare is exact unless a tolerance is given.
_Avoid_: precision, epsilon, fuzz, approximate equality
