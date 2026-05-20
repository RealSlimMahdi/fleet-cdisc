# Plan: Polymorphic `.derivation()` Verb + `Derivation` Protocol

## Context

Fleet's `.derivation()` verb currently accepts only `str` (sandbox) or `pl.Expr` (direct).
This plan extends it to be the **single unified entry point** for all custom derivation logic —
no new verb name, zero migration cost, full backward compatibility.

## Git branch: `feature/polymorphic-derivation-verb`, don't commit or push code, branch from main and bring uncommitted changes from main to this branch before starting work.

### The four-case API

```python
# Case 1 — existing, YAML-compatible string through AST sandbox
.derivation("AVAL", expression="pl.col('VSSTRESN').cast(pl.Float64)")

# Case 2 — existing, direct pl.Expr
.derivation("AVAL", expression=pl.col("VSSTRESN").cast(pl.Float64))

# Case 3 — NEW: lambda returning pl.Expr (inline, full IDE support, no sandbox)
.derivation("AGEGR1", expression=lambda: (
    pl.when(pl.col("AGE") < 65).then(pl.lit("<65 yrs"))
    .otherwise(pl.lit(">=65 yrs"))
))

# Case 4 — NEW: Derivation object (file-based, full lineage, Define-XML ready)
.derivation(AGEGR1)    # target read from Derivation.targets[0]
.derivation(BMI)       # frame/param shape routed by Derivation.kind
```

CLI scaffold:

```bash
fleet derivation add AGEGR1 --dataset ADSL
```

---

## Phase 1 — Core: `Derivation` protocol

### `src/fleet/core/derivation.py` — NEW FILE

```python
@dataclass
class Derivation:
    fn:            Callable
    name:          str
    kind:          Literal["column", "frame", "param"]
    targets:       list[str]
    sources:       list[str]
    by_vars:       list[str] | None
    set_values_to: dict[str, Any] | None
    dotted_path:   str         # "examples.cdiscpilot01.adam.derivations.AGEGR1"

    def __call__(self, df: pl.DataFrame | None = None) -> pl.Expr | pl.DataFrame:
        if self.kind == "column":
            return self.fn()   # fn() → pl.Expr, no df arg
        return self.fn(df)     # fn(df) → pl.DataFrame
```

#### `@derivation` decorator — kind inference rules

| Function signature                                              | Return hint    | Inferred `kind` |
| --------------------------------------------------------------- | -------------- | --------------- |
| `def AGEGR1() -> pl.Expr:`                                      | `pl.Expr`      | `"column"`      |
| `def add_flags(df) -> pl.DataFrame:`                            | `pl.DataFrame` | `"frame"`       |
| `@derivation(by=["USUBJID"], set_values_to={"PARAMCD": "BMI"})` | any            | `"param"`       |

Auto-population at decoration time:

- `kind == "column"`: calls `fn()`, runs `expr.meta.output_name()` → `targets`, `expr.meta.root_names()` → `sources`
- `kind == "frame"`: `targets` must be declared via `targets=` kwarg on decorator; `sources` optional
- `dotted_path = f"{fn.__module__}.{fn.__qualname__}"`
- Automatically calls `register_transform(fn.__name__, drv)` so the registry is populated on import

Decorator supports both bare and parameterised forms:

```python
@derivation                          # bare form — kind="column" inferred
def AGEGR1() -> pl.Expr: ...

@derivation(targets=["SAFFL", "ITTFL"])   # parameterised — kind="frame"
def add_pop_flags(df: pl.DataFrame) -> pl.DataFrame: ...

@derivation(by=["USUBJID", "ADT"],
            set_values_to={"PARAMCD": "BMI", "PARAM": "Body Mass Index"})
def BMI(df: pl.DataFrame) -> pl.DataFrame: ...  # kind="param"
```

Study derivations live in:

```
specs/<study>/adam/derivations/
    __init__.py        # auto-updated by `fleet derivation add`
    AGEGR1.py
    BMI.py
```

---

### `src/fleet/core/lineage.py` — ADD `_append_lineage_nodes()`

Add after `pin_lineage_of()`:

```python
def _append_lineage_nodes(ns: Any, drv: "Derivation") -> Any:
    """Inject VariableNodes for frame-level / param-level Derivations.

    Called from _apply_derivation() after _materialise_then(), because
    those code paths bypass _chain() and therefore miss record_lineage().
    """
    from fleet.core.dag import VariableNode

    lineage: list[VariableNode] = list(getattr(ns, "_lineage", []))
    domain: str | None = getattr(ns, "_domain", None)
    for t in drv.targets:
        lineage.append(VariableNode(
            name=t,
            verb="derivation",
            sources=drv.sources,
            method=drv.dotted_path,
            domain=domain,
        ))
    ns._lineage = lineage
    return ns
```

---

### `src/fleet/adam/transforms.py` — ACCEPT `Derivation` OBJECTS

Change the registry type annotation:

```python
# Before
_TRANSFORMS: dict[str, Callable[[pl.DataFrame], pl.DataFrame]] = {}

# After
_TRANSFORMS: dict[str, Callable | "Derivation"] = {}
```

No functional change to `get_transform()` or `register_transform()`. Update docstring only.

---

## Phase 2 — Extend `.derivation()` on both namespaces

### `src/fleet/adam/_mixins.py` — REPLACE `.derivation()` (line 978)

New signature:

```python
def derivation(
    self,
    target: str | "Derivation" | None = None,
    *,
    expression: str | pl.Expr | Callable[[], pl.Expr] | None = None,
) -> Self:
```

Dispatch logic:

```python
# Case 4: Derivation object passed as first positional arg
if target is not None and not isinstance(target, str):
    return self._apply_derivation(target)

# Cases 1–3 require a string target
if target is None:
    raise ValueError("target is required when expression= is provided.")
if expression is None:
    raise ValueError("expression is required when target is a string.")

# Case 2: direct pl.Expr
if isinstance(expression, pl.Expr):
    return self._chain(expression.alias(target))

# Case 3: lambda / zero-arg callable
if callable(expression):
    expr = expression()
    if not isinstance(expr, pl.Expr):
        raise TypeError(
            f"expression callable must return pl.Expr, got {type(expr).__name__}"
        )
    return self._chain(expr.alias(target))

# Case 1: string through AST sandbox
from fleet.sdtm.utils import parse_expression
return self._chain(parse_expression(str(expression)).alias(target))
```

Add `_apply_derivation()` private method immediately after `.derivation()`:

```python
def _apply_derivation(self, drv: "Derivation") -> Self:
    from fleet.core.lineage import _append_lineage_nodes

    if drv.kind == "column":
        # Pure expression builder — stays fully lazy, lineage via _chain
        expr = drv()
        return self._chain(expr.alias(drv.targets[0]))

    elif drv.kind in ("frame", "param"):
        df = self.to_frame()
        result = drv(df)
        if not isinstance(result, pl.DataFrame):
            raise TypeError(
                f"Derivation '{drv.name}' is kind={drv.kind!r} but fn() returned "
                f"{type(result).__name__!r} — expected pl.DataFrame."
            )
        ns = self._materialise_then(result)
        return _append_lineage_nodes(ns, drv)
```

Update the docstring: document all four cases under `expression:` arg; add lambda and
`Derivation` object examples.

---

### `src/fleet/sdtm/namespace.py` — REPLACE `.derivation()` (line 116)

Exact same four-case dispatch + `_apply_derivation()` as in `_mixins.py`.
Return type annotation is `SDTMNamespace` instead of `Self`.

---

## Phase 3 — Models + `from_spec()` dispatch

### `src/fleet/adam/models.py`

```python
# ADAMAlgorithm — add after DURATION:
CALLABLE = "callable"

# ADAMVariableSpec — add one field before depends_on:
callable_ref: str | None = Field(None, alias="callable")
```

The `Field(..., alias="callable")` maps YAML `callable: foo` without conflicting with
the Python builtin.

Update `_extract_define_variables()` in `namespace.py`: when a derivation block has
`callable:` but no `algorithm:`, inject `algorithm: "callable"` before Pydantic model
construction (backward compat for existing YAML).

---

### `src/fleet/sdtm/models.py`

Same two additions:

```python
CALLABLE = "callable"          # SDTMAlgorithm enum
callable_ref: str | None = Field(None, alias="callable")  # SDTMVariableSpec field
```

---

### `src/fleet/adam/namespace.py` — `_resolve_callable()` + dispatch

Add module-level function:

```python
def _resolve_callable(ref: str) -> "Derivation | Callable":
    from fleet.adam.transforms import get_transform
    try:
        return get_transform(ref)
    except KeyError:
        pass
    if "." in ref:
        module_path, _, attr = ref.rpartition(".")
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise ValueError(
        f"Callable '{ref}' is not registered and is not a dotted import path. "
        f"Register it with @derivation or import the derivations module before from_spec()."
    )
```

In `from_spec()` dispatch loop, add:

```python
elif alg == "callable":
    fn = _resolve_callable(var.callable_ref or "")
    ns = ns.derivation(fn) if hasattr(fn, "kind") else ns._materialise_then(
        fn(ns.to_frame())
    )
    continue
```

---

### `src/fleet/sdtm/namespace.py` — same additions

Same `_resolve_callable()` module-level function.
Add `elif alg == "callable":` at the end of the `from_spec()` dispatch loop (before
`return ns`, currently around line 1491).

---

### `src/fleet/define_xml/spec_generator.py` — PREFER `Derivation.dotted_path`

In `_register_method()` (around line 486), after reading `callable_path`:

```python
callable_path = derivation.get("callable")
if callable_path:
    try:
        from fleet.adam.transforms import get_transform
        obj = get_transform(callable_path)
        if hasattr(obj, "dotted_path"):           # Derivation object
            summary = (obj.fn.__doc__ or "").splitlines()[0].strip()
            dotted = obj.dotted_path
        else:
            summary, dotted = resolve_callable_docstring(str(callable_path))
    except (KeyError, Exception):
        summary, dotted = resolve_callable_docstring(str(callable_path))
```

---

## Phase 4 — CLI scaffold

### `src/fleet/cli.py` — ADD `fleet derivation add`

```bash
fleet derivation add AGEGR1 --dataset ADSL --kind column
```

Arguments:

| Arg                 | Description                                                |
| ------------------- | ---------------------------------------------------------- |
| `name` (positional) | Variable name (e.g. `AGEGR1`)                              |
| `--dataset`         | Target dataset name (default: `ADSL`)                      |
| `--kind`            | `column` / `frame` / `param` (default: `column`)           |
| `--config`          | Path to `study_config.yaml` (default: `study_config.yaml`) |

Generated file: `specs/<study_id>/adam/derivations/<NAME>.py`

Template for `kind=column`:

```python
"""<NAME> — <dataset> custom derivation."""
from fleet.core.derivation import derivation
import polars as pl


@derivation
def <NAME>() -> pl.Expr:
    """One-sentence summary of <NAME> derivation.

    Args:
        (none — column-kind derivations take no arguments)

    Returns:
        pl.Expr: Expression that produces the <NAME> column.

    Examples:
        Use in an inline pipeline::

            adsl = (
                dm.adam.adsl
                .derivation(<NAME>)
                .to_frame()
            )
    """
    return pl.col("REPLACE_ME").cast(pl.String)  # TODO: replace with real logic
```

Also updates `specs/<study>/adam/derivations/__init__.py`:

```python
from .<NAME> import <NAME>
```

`fleet init cfg` is updated to create an empty `derivations/__init__.py` when
scaffolding a new study.

---

## Phase 5 — Tests

| File                                        | Action     | What it tests                                                                                                                                                          |
| ------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/unit/test_derivation_protocol.py`    | **NEW**    | `@derivation` auto-sources, `kind` inference from return hint, `dotted_path`, auto-registration in `_TRANSFORMS`                                                       |
| `tests/unit/test_derivation_polymorphic.py` | **NEW**    | All four `.derivation()` cases on both namespaces; lambda return-type error; `Derivation` object routing for column/frame/param; lineage nodes produced for frame kind |
| `tests/unit/test_from_spec_callable.py`     | **NEW**    | `callable:` key in `from_spec()` dispatches to registered Derivation; dotted import fallback; backward compat (no `algorithm:` in YAML)                                |
| `tests/unit/test_transform.py`              | **EXTEND** | Registry accepts `Derivation` objects; `get_transform()` returns them; `list_transforms()` includes `@derivation`-decorated names                                      |

---

## Phase 6 — Documentation

### `docs/concepts/advanced.md` — THREE CHANGES

1. Fix stale `_add_expr` subclass example (replace with `_chain()`).
2. Add `@derivation` as the primary escape-hatch pattern (before the "drop to raw Polars" pattern).
3. Add concrete examples for all three `Derivation.kind` values.

### `docs/concepts/define-yaml.md` — ONE CORRECTION + ONE EXPANSION

1. Correct `callable:` description: remove "takes the upstream DataFrame as its first argument"
   (wrong for `kind="column"`). Replace with actual runtime semantics.
2. Add `derivations/` folder convention section:
   ```
   specs/<study>/adam/derivations/
       __init__.py
       AGEGR1.py
       BMI.py
   ```
   And YAML wiring:
   ```yaml
   - name: AGEGR1
     derivation:
       callable: examples.cdiscpilot01.adam.derivations.AGEGR1
   ```

### `docs/api/core.md` — ADD entries

Add after `PipelineDAG`:

```markdown
## Derivation

::: fleet.core.derivation.Derivation
options:
show*root_heading: true
heading_level: 3
filters: ["!^*"]

## derivation (decorator)

::: fleet.core.derivation.derivation
options:
show_root_heading: true
heading_level: 3
```

---

## Phase 7 — Build artifacts

### `scripts/build_llms.py` — TWO CHANGES

1. Update the `derivation` row in the cheat-sheet table: change description from
   "Last resort — use a Fleet verb first" to
   "Polymorphic: `str`, `pl.Expr`, lambda `() -> pl.Expr`, or `@derivation` object".
2. Add a `callable` row to the derivation algorithms table in the define-yaml section.

Regenerate after changes:

```bash
uv run python scripts/build_llms.py
uv run python scripts/build_llms.py --check
```

### `STRUCTURE.md`

Add `src/fleet/core/derivation.py` to the core module listing:

> `derivation.py` — `Derivation` protocol dataclass and `@derivation` decorator.

### `GUIDE.md`

Add a "Study-Specific Derivations" section covering:

- When to use `@derivation` vs inline `.derivation(expression=...)`
- The `derivations/` folder convention
- How `callable:` in define.yaml links to runtime execution
- How Define-XML MethodDef is enriched from the function docstring

---

## File change summary

| File                                        | Action                                                  | Phase |
| ------------------------------------------- | ------------------------------------------------------- | ----- |
| `src/fleet/core/derivation.py`              | **NEW**                                                 | 1     |
| `src/fleet/core/lineage.py`                 | Add `_append_lineage_nodes()`                           | 1     |
| `src/fleet/adam/transforms.py`              | Type hint + docstring update                            | 1     |
| `src/fleet/adam/_mixins.py`                 | Replace `.derivation()` + add `_apply_derivation()`     | 2     |
| `src/fleet/sdtm/namespace.py`               | Replace `.derivation()` + add `_apply_derivation()`     | 2     |
| `src/fleet/adam/models.py`                  | Add `CALLABLE` enum + `callable_ref` field              | 3     |
| `src/fleet/sdtm/models.py`                  | Add `CALLABLE` enum + `callable_ref` field              | 3     |
| `src/fleet/adam/namespace.py`               | `_resolve_callable()` + `from_spec()` callable dispatch | 3     |
| `src/fleet/sdtm/namespace.py`               | `_resolve_callable()` + `from_spec()` callable dispatch | 3     |
| `src/fleet/define_xml/spec_generator.py`    | Prefer `Derivation.dotted_path` in MethodDef            | 3     |
| `src/fleet/cli.py`                          | `fleet derivation add` + `fleet init cfg` scaffold      | 4     |
| `tests/unit/test_derivation_protocol.py`    | **NEW**                                                 | 5     |
| `tests/unit/test_derivation_polymorphic.py` | **NEW**                                                 | 5     |
| `tests/unit/test_from_spec_callable.py`     | **NEW**                                                 | 5     |
| `tests/unit/test_transform.py`              | Extend                                                  | 5     |
| `docs/concepts/advanced.md`                 | Fix `_add_expr`, add `@derivation` pattern              | 6     |
| `docs/concepts/define-yaml.md`              | Correct `callable:`, add `derivations/` convention      | 6     |
| `docs/api/core.md`                          | Add `Derivation` + `derivation` decorator entries       | 6     |
| `scripts/build_llms.py`                     | Update table + prose                                    | 7     |
| `STRUCTURE.md`                              | Add `derivation.py`                                     | 7     |
| `GUIDE.md`                                  | Add study-specific derivations section                  | 7     |
| `README.md` / `llms.txt`                    | Regenerated by `build_llms.py`                          | 7     |

---

## Verification order

```bash
uv run ruff check && uv run ruff format --check
uv run pytest
uv run python examples/full_pipeline_example.py
uv run python examples/cdiscpilot01_inline.py
uv run python examples/cdiscpilot01_spec_driven.py
uv run python examples/adnca_example.py
uv run python examples/tdd_example.py
uv run python scripts/build_llms.py
uv run python scripts/build_llms.py --check
uv run --extra docs mkdocs build --clean
```
