# Plan: `extends` Cross-File Reference for define.yaml

## TL;DR

Add an optional `extends: <relative-path>` top-level key to `define.yaml`. When present, Fleet loads the referenced (master) file first, then deep-merges the study-specific file on top using a **study-wins** strategy. Merge is keyed: codelists by `oid`, datasets by `name`, variables by `name`. Recursive chaining is supported with cycle detection.

## Decisions

- Scope: `define.yaml` files only (SDTM + ADaM)
- Codelist merge: whole codelist replaced when OID matches (study wins entirely)
- Variables/datasets: per-name merge, study wins completely
- `study:` block: field-level merge (master fills missing fields, study overrides present ones)
- Recursive: yes — a master can itself extend another file (grandparent); cycle detection required
- Deletions: no — study can only add or override, never remove

---

## Phase 1 — Core Loader (no call-site changes yet)

### Step 1: Create `src/fleet/core/_yaml_loader.py`

New module containing:

- `load_define_spec(path: Path | str) -> dict` — public entry point
  - Resolves path to absolute
  - Calls `_resolve(path, seen=set())`
- `_resolve(path: Path, seen: set[Path]) -> dict`
  - `yaml.safe_load(path.read_text())`
  - If `extends` key present:
    - Resolve extends path relative to `path.parent`
    - Cycle check: if abs(extends_path) in seen → raise `SpecExtendsCycleError`
    - Recursively call `_resolve(extends_path, seen | {path})`
    - Call `_merge(parent_spec, child_spec)` (child = study, parent = master)
  - Return dict
- `_merge(parent: dict, child: dict) -> dict`
  - `study:` — `{**parent.get('study',{}), **child.get('study',{})}`
  - `codelists:` — `_merge_by_key(parent, child, list_key='codelists', id_key='oid')`
  - `datasets:` — `_merge_datasets(parent, child)`
- `_merge_by_key(parent, child, list_key, id_key) -> list`
  - Build ordered dict from parent keyed by id_key; overlay child entries (child wins)
  - New child entries appended at end
- `_merge_datasets(parent: dict, child: dict) -> list`
  - Merge datasets list by `name`
  - For matched datasets: merge `variables` sub-list by `name` + merge `inputs` sub-list by `name`
  - Non-matched: include as-is from whichever file has them
- `SpecExtendsCycleError(SpecError)` — new exception class

Export `load_define_spec` from `src/fleet/core/__init__.py`.

---

## Phase 2 — Replace all call sites

10 call sites replace `yaml.safe_load(Path(spec_path).read_text())` with `load_define_spec(spec_path)`. Only applies where the loaded dict is a _define.yaml_ (has `datasets` key or is intended as one). Non-define YAML files (study_config, CT, TLG specs) stay on `yaml.safe_load`.

| File                                     | Line | Function                        |
| ---------------------------------------- | ---- | ------------------------------- |
| `src/fleet/sdtm/namespace.py`            | 767  | `from_spec()`                   |
| `src/fleet/sdtm/namespace.py`            | 992  | `_spec_dataset_meta()`          |
| `src/fleet/adam/namespace.py`            | 1055 | `from_spec()`                   |
| `src/fleet/adam/namespace.py`            | 1363 | `_spec_dataset_meta()`          |
| `src/fleet/define_xml/generator.py`      | 40   | `DefineXMLGenerator.__init__()` |
| `src/fleet/define_xml/validator.py`      | 53   | `validate()`                    |
| `src/fleet/define_xml/checker.py`        | 198  | `DefineChecker.__init__()`      |
| `src/fleet/define_xml/spec_generator.py` | 75   | `SpecGenerator.__init__()`      |
| `src/fleet/core/dag.py`                  | 318  | `PipelineDAG.from_spec()`       |
| `src/fleet/ct/generator.py`              | 78   | `generate_codelists()`          |

---

## Phase 3 — JSON Schema update

- `src/fleet/define_xml/schemas/define_spec_schema.json` — add `"extends": {"type": "string"}` as an optional property in the top-level object schema. No `additionalProperties: false` conflict expected (check first).

---

## Phase 4 — Tests

### New test file: `tests/unit/test_yaml_extends.py`

- Fixture A: `tests/fixtures/specs/master_define.yaml` — master with 2 codelists, 2 datasets (DM, AE), each with 3 variables
- Fixture B: `tests/fixtures/specs/study_define.yaml` — `extends: master_define.yaml`, overrides 1 codelist, 1 variable in DM, adds 1 new variable to DM, adds new dataset (VS)
- Test cases:
  1. `test_extends_loads_merged_spec` — merged dict has all master + study content
  2. `test_study_codelist_wins` — overridden codelist OID has study's items
  3. `test_master_codelist_preserved` — non-overridden codelist OID retained
  4. `test_study_variable_wins` — overridden variable has study's derivation
  5. `test_new_variable_added` — new study variable present in merged output
  6. `test_new_dataset_added` — VS dataset from study present
  7. `test_master_dataset_preserved` — AE dataset from master (not in study) present
  8. `test_no_extends_unchanged` — file without `extends` behaves identically to `yaml.safe_load`
  9. `test_recursive_extends` — grandparent → master → study chain resolves correctly
  10. `test_cycle_detection` — circular extends raises `SpecExtendsCycleError`

---

## Verification

1. `uv run pytest tests/unit/test_yaml_extends.py` — all 10 new tests pass
2. `uv run pytest` — full suite green
3. `uv run ruff check && uv run ruff format --check`
4. `uv run python examples/cdiscpilot01_spec_driven.py` — existing spec-driven pipeline unaffected
5. Manual smoke test: create a study define.yaml with `extends: master` and call `raw_df.sdtm.from_spec(...)`

## Relevant files

- `src/fleet/core/_yaml_loader.py` — **new** (merge engine)
- `src/fleet/core/__init__.py` — export `load_define_spec`
- `src/fleet/core/exceptions.py` — add `SpecExtendsCycleError`
- `src/fleet/sdtm/namespace.py` L767, L992
- `src/fleet/adam/namespace.py` L1055, L1363
- `src/fleet/define_xml/generator.py` L40
- `src/fleet/define_xml/validator.py` L53
- `src/fleet/define_xml/checker.py` L198
- `src/fleet/define_xml/spec_generator.py` L75
- `src/fleet/core/dag.py` L318
- `src/fleet/ct/generator.py` L78
- `src/fleet/define_xml/schemas/define_spec_schema.json`
- `tests/unit/test_yaml_extends.py` — **new**
- `tests/fixtures/specs/master_define.yaml` — **new**
- `tests/fixtures/specs/study_define.yaml` — **new**
