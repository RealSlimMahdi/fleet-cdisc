# Extending Fleet — Company Extension Mechanism Plan

> Status: **approved design, not yet implemented.**
> Model chosen: hybrid *discover via entry points, activate via config* (the MkDocs
> model), with company verbs living at `df.adam.<code>.*` via a new dynamic
> sub-namespace registry.

## 1. Context

Companies adopting Fleet (e.g. Novartis) will need company-specific derivations, TLG
templates, validation rules, and namespace verbs. The core library cannot host
per-company code, so Fleet needs an official, documented extension story that is good
for stat-programmer UX and low-friction for support teams.

Fleet already has the **registration seams** — they just lack an activation story,
support visibility, and a namespace surface:

| Seam | Location | Used for |
|---|---|---|
| `register_transform` / `@derivation` | `src/fleet/adam/transforms.py:71`, `src/fleet/core/derivation.py:239` | custom derivations, YAML `callable:` refs |
| `spec_algorithm(...)` | `src/fleet/core/spec_registry.py:222` | new YAML-executable algorithms |
| `register_template(meta, fn)` | `src/fleet/tlg/_registry.py:406` | sponsor TLG templates |
| Polars namespace subclassing | `docs/concepts/advanced.md` | company accessors |
| `ValidationProvider` ABC | `src/fleet/validation/providers.py:12` | pluggable conformance engine |
| Custom rules YAML / grading JSON | `metadata/custom_rules/`, `grading/_registry.py:54` | sponsor SOP rules |
| `resolve_callable` + `derivations_module:` | `core/_resolve_callable.py:8`, `core/_verb_mixin.py:83` | YAML refs to user modules |

Gaps this plan closes:

1. **No activation mechanism** — everything relies on "import the module somewhere
   and side effects register it": fragile, undocumented, import-order-dependent.
2. **No support surface** — no way to see which package registered what; collision
   warnings don't name the owner.
3. **Sub-namespaces are hardcoded** — `df.adam.tte` etc. are fixed `@property`s on
   `AdamNamespace` (`namespace.py:1023+`); a company can't get `df.adam.nvs.*`.
4. **No "Extending Fleet" docs guide.**

## 2. Options considered (and the ecosystem survey)

| Model | Precedents | Verdict |
|---|---|---|
| Auto-load on install (entry points, executed at `import fleet`) | pytest, flake8, hypothesis | Best notebook UX, but behavior becomes a property of the *environment* — pytest itself grew `PYTEST_DISABLE_PLUGIN_AUTOLOAD` because this bites reproducibility. Rejected for the GxP risk: a dev build of a company package silently active in a production run, with zero trace in any reviewed artifact. |
| Explicit config activation | Django `INSTALLED_APPS`, Sphinx `extensions`, ESLint | Maximum auditability; loses tooling discoverability. |
| **Hybrid: discover via entry points, activate via config** | **MkDocs plugins** | **Chosen.** Tooling can enumerate what's installed; nothing runs unless named in the version-controlled `study_config.yaml`. |
| Declared + pinned + hash-verified | Terraform providers + lockfile | Gold standard for integrity; version-constraint checking kept as a flagged follow-up. |
| Explicit `library()` per program | pharmaverse/admiral company extension packages (R) | The direct pharma precedent — confirms explicit activation is the industry-culture fit. |

**Why the hybrid wins for clinical work:** the realistic threat is not malware but the
wrong (non-production) code being active. Config activation makes the study's
version-controlled `study_config.yaml` the single auditable source of truth for what
third-party code ran; a declared-but-missing extension fails **hard** (no silent runs
without the company's derivations); the environment lockfile pins versions as a second
independent control. Entry points still give `fleet plugins` full visibility of
installed-but-inactive packages.

**Namespace decision:** company verbs live at **`df.adam.nvs.*`** (dynamic
sub-namespace registry) rather than a top-level `df.nvs` accessor — one canonical
chain for programmers, pins/lineage hand over automatically via the existing
`_sub_namespace()` helper, and Fleet owns collision diagnostics (Polars top-level
accessor names are an unpoliced global namespace). The top-level accessor pattern
stays documented as the escape hatch for teams overriding core verb behavior.

## 3. Design — six components

### 3.1 Owner tracking (`src/fleet/core/owner.py`, NEW — imports nothing from fleet)

- `owner_context(owner: str)` context manager over a `ContextVar`.
- `describe_owner(obj)` — explicit owner if a context is active, else inferred from
  `obj.__module__` via `importlib.metadata.packages_distributions()` (cached) →
  `"novartis-fleet 1.2.0"`; fleet code → `"fleet"`; honest fallback
  `"session:<module>"` (never guess wrong for editable installs).
- Sidecar owner dicts, registry values untouched (call sites keep doing
  `_TRANSFORMS[name](df)`):
  - `_TRANSFORM_OWNERS` in `adam/transforms.py` (set beside both `_TRANSFORMS[name]`
    assignments at ~:121/:129; cleared by `clear_transforms()`; accessor
    `transform_owner(name)`).
  - `TEMPLATE_OWNERS` in `tlg/_registry.py` (recorded by `register_template`,
    popped by `unregister_template`).
  - `_ALGO_OWNERS` keyed `(standard, spelling)` in `core/spec_registry.py`.
- Collision messages name the owner, e.g.:
  `Transform 'aval_change' is already registered by novartis-fleet 1.2.0 (...); overwriting with session:programs.derivations...`
  - transforms `_warn_on_duplicate` (:135): keep warn-and-overwrite semantics.
  - TLG duplicate `SchemaError` (~:450) and `spec_algorithm` duplicate `ValueError`
    (~:285): include owner.

### 3.2 Plugin discovery + activation (`src/fleet/plugins.py`, NEW)

- Entry-point group **`"fleet.plugins"`**. Documented contract: the entry point
  resolves to a callable `register(api: FleetPluginAPI)`; a module target is
  tolerated (imported for side effects) but docs teach only the callable form —
  it guarantees registrations happen under the loader's owner context.
- `FleetPluginAPI(api_version=1, fleet_version=...)` — deliberately thin handshake
  object; the registration surface stays the existing public functions.
- `discover() -> dict[str, PluginRecord]` — scans entry points (via an
  `_iter_entry_points()` seam for tests); builds records
  `(name, dist, version, target, active, error)`. **Executes nothing.** Fail-soft:
  metadata errors land in the record. Cached, `force=True` for tests.
- `activate(name) -> PluginRecord` — loads the entry point and calls
  `register(api)` under `owner_context(f"{dist} {version}")`. **Fail-hard** —
  activation is declared intent. Idempotent per name.
- **No autoload hook in `fleet/__init__.py`** — activation is opt-in, so no
  kill-switch env var is needed.
- Company-side packaging:

  ```toml
  [project]
  name = "novartis-fleet"
  dependencies = ["fleet-cdisc>=0.1,<0.2"]   # pin a compatible core range

  [project.entry-points."fleet.plugins"]
  nvs = "novartis_fleet.plugin:register"
  ```

### 3.3 `extensions:` on StudyConfig (`src/fleet/core/study_context.py`)

- New field `extensions: list[str] = Field(default_factory=list)` on `StudyConfig`
  (:71).
- `_load_extensions(ctx)` called at the tail of `load_study_context()` (:299) — one
  funnel covers the CLI (`_load_ctx`/`_try_ctx`) *and* notebook users calling
  `load_study_context()`:
  - Each entry: if it matches a discovered `fleet.plugins` entry-point name →
    `plugins.activate(name)`; otherwise treat as an importable module path
    (`importlib.import_module` under `owner_context(f"study:{mod}")`) — covers the
    study-local `programs/derivations` package and non-packaged company modules.
  - When `extensions:` is non-empty: prepend study root and `programs/` dir to
    `sys.path` if absent — fixes the latent gap where the scaffolded
    `programs/derivations` is only importable from the right cwd. **Empty/missing
    key → zero behavior change, `sys.path` untouched.**
  - Failures raise `StudyConfigError` naming the entry (chained) — **fail hard**;
    a declared extension that can't load must never silently produce data.
- `StudyContext.init()` scaffold: write a commented `# extensions: [derivations]`
  hint into the generated `study_config.yaml`.

### 3.4 Dynamic sub-namespace (`src/fleet/adam/namespace.py`, ~40 lines)

- Module-level `_SUBNAMESPACES: dict[str, tuple[type, str]]` (class, owner).
- `AdamNamespace.register_subnamespace(name, sub_cls)` classmethod: validate
  identifier; reject clashes with existing class attributes (verbs and the
  `adsl`/`onco`/… properties); duplicate registration with a different class raises
  naming the owner. `unregister_subnamespace` for tests.
- `AdamNamespace.__getattr__(self, name)`:
  - underscore names → immediate plain `AttributeError` (internal
    `getattr(self, "_pinned", {})` probes at :1012-1016 depend on this);
  - else `_SUBNAMESPACES` lookup → delegate to the existing
    `self._sub_namespace(cls)` (:1002) so **pins, pin lineage, variable lineage,
    pending FK checks, and FK policy hand over automatically** — identical to
    `df.adam.onco`;
  - else plain `AttributeError`. Only fires on attribute *miss* → zero cost on
    normal verb access.
- Company classes subclass `SharedADaMVerbsMixin` (same pattern as `OncoNamespace`,
  `onco_namespace.py:59`); export `SharedADaMVerbsMixin` publicly from `fleet.adam`.
  Works on both DataFrame and LazyFrame accessors (same class); `.verbs()`
  introspection works for free.

Company-side sketch:

```python
# novartis_fleet/namespace.py
from fleet.adam import AdamNamespace, SharedADaMVerbsMixin

class NvsNamespace(SharedADaMVerbsMixin):
    def worst_grade_flag(self, target: str, *, by: list[str]) -> "NvsNamespace":
        ...
        return self._chain(expr.alias(target))

def install() -> None:
    AdamNamespace.register_subnamespace("nvs", NvsNamespace)
```

Usage — pins survive the hop:

```python
adtte = (
    adrs.adam
    .pin("ADSL", adsl)
    .nvs.worst_grade_flag("WGRFL", by=["USUBJID"])
    .to_frame()
)
```

### 3.5 CLI surface (`src/fleet/cli.py`)

- New `_add_plugin_parsers(sub)` wired into `_build_parser()` (:2764):
  **`fleet plugins`** (optional `--json`) prints:
  - discovered plugins with dist + version, **active/inactive** status (active =
    named in the discoverable study config via `_try_ctx`, or already activated in
    this process);
  - what each active plugin registered, grouped from the owner sidecars
    (transforms, TLG templates, spec algorithms, sub-namespaces);
  - activation/metadata errors;
  - study-module extensions (`study:<mod>` owners) in their own section.

  ```
  Fleet Plugins
  ====================================================
    ✓ nvs — novartis-fleet 1.2.0 (novartis_fleet.plugin:register) [active]
        transforms:      nvs_agegr1, nvs_aval_change (+3 more)
        tlg templates:   nvst01
        spec algorithms: adam:nvs_worst_grade
        sub-namespaces:  df.adam.nvs
    - acme — acme-fleet 0.3.0 [installed, not active]

  Study extensions (study_config.yaml → extensions:)
    ✓ derivations (4 transforms)
  ```

- One summary line in `_run_doctor` (~:620):
  `✓ plugins ......... 3 installed, 1 active (nvs) — 'fleet plugins' for details`.

### 3.6 Docs — new top-level nav section (mkdocs.yml, after Examples)

```yaml
- Extending Fleet:
    - Overview — Three Tiers: extending/index.md
    - Study-Local Derivations: extending/study-derivations.md
    - Building a Company Package: extending/company-package.md
    - Plugin Discovery & Activation: extending/plugins.md
```

- **`index.md`** — the three tiers:
  1. *Study-local*: `programs/derivations/` + `extensions: [derivations]`;
  2. *Shared internal package*: module path in `extensions:` or explicit import;
  3. *Packaged plugin*: entry point, activated per study via `extensions: [nvs]`.
  Plus a what-can-be-extended table (seam → register function → where usable) and
  naming conventions: underscore prefix `nvs_agegr1` for transforms/algorithms
  (**not** dotted — `resolve_callable` treats dotted registry misses as import
  paths, producing misleading errors), TLG ids like `nvst01`, entry-point name =
  sub-namespace name = company short code; unprefixed lowercase reserved for core.
- **`study-derivations.md`** — moves `@derivation` + derivations-folder content out
  of `concepts/advanced.md`; covers `fleet derivation add`, `extensions:`,
  `derivations_module:`, troubleshooting ("not registered" → `fleet plugins`).
- **`company-package.md`** (centerpiece) — complete minimal package:

  ```
  novartis-fleet/
  ├── pyproject.toml                  # entry point + fleet-cdisc>=0.1,<0.2 pin
  ├── src/novartis_fleet/
  │   ├── plugin.py                   # def register(api): ...
  │   ├── derivations/__init__.py     # @derivation / register_transform, nvs_ prefixed
  │   ├── templates/__init__.py       # tlg.register_template(...)
  │   ├── namespace.py                # NvsNamespace + install()
  │   └── data/rules/, data/grading/  # sponsor rules YAML, grading JSON
  └── tests/
      ├── test_registration.py        # register(api) registers everything; owners correct
      └── test_derivations.py         # golden tests on synthetic frames
  ```

  Versioning/compat guidance (pin core range, check `api.api_version`, test matrix
  before rollout). **GxP boundary**: core validated once per version; the company
  package is a separately versioned, separately validated artifact; the entry-point
  + config seam is the audit boundary; `fleet plugins` output is point-in-time
  evidence; config activation gives per-study reproducibility. Moves advanced.md's
  "Subclassing Namespaces" here as the fallback pattern.
- **`plugins.md`** — mechanics reference: group name, `register(api)` contract,
  discovery-vs-activation semantics, error model (discovery fail-soft, activation
  fail-hard), `fleet plugins` output, FAQ.
- Touch: `why-fleet.md` §4 links here; `cli.md` documents `fleet plugins`;
  `advanced.md` keeps pin/debugging content with pointer stubs where sections moved.

## 4. Tests

- **NEW `tests/unit/test_plugins.py`** — fake `_iter_entry_points` seam
  (FakeEP/FakeDist): `discover()` lists without executing (assert no side effects);
  `activate()` registers with owner `"dummy-fleet 9.9.9"`; broken plugin raises on
  activate; idempotency; `_reset_for_tests()` fixture.
- **`extensions:` tests** (extend the `tests/unit/test_cli.py:81` study-fixture
  pattern): tmp study config with `extensions: [ext_mod_<uuid>]` + module under
  `programs/`; assert imported, owner `study:...`, `sys.path` prepended; entry-point
  name routes to `activate()` (monkeypatched); missing module → `StudyConfigError`
  naming it; **no `extensions:` key → `sys.path` unchanged** (the
  zero-behavior-change guarantee).
- **Owner/collision-message tests** in `test_tlg_yaml_workflow.py` style: register
  under `owner_context("novartis-fleet 1.2.0")`, assert error/warning text contains
  the owner (transforms warning, TLG `SchemaError`, spec_algorithm `ValueError`).
- **NEW `tests/unit/test_subnamespace_registry.py`** — dummy
  `SharedADaMVerbsMixin` subclass: verbs work on DataFrame + LazyFrame; pins survive
  `.pin("ADSL", adsl).nvs`; duplicate/clashing registration raises naming owner;
  unknown attr → clean `AttributeError`; regression: plain `df.adam` chains
  unaffected with empty registry.
- **CLI** capsys test for `fleet plugins` with monkeypatched records.

## 5. Sequencing

1. `core/owner.py` + owner sidecars + collision messages — shippable alone, zero
   behavior change.
2. `plugins.py` discover/activate + tests.
3. `extensions:` field + `_load_extensions` + tests.
4. `register_subnamespace` + `__getattr__` + tests.
5. `fleet plugins` CLI + doctor line + tests.
6. Docs restructure + example package listings.

## 6. Out of scope (flagged follow-ups)

- **Version constraints in `extensions:`** entries verified against the installed
  distribution at load time, Terraform-style (`novartis_fleet: ">=1.2,<2"`) —
  natural v2, completes the "never run non-production code" guarantee.
- Opt-in autoload flag for sandbox/exploratory environments (default off).
- Escalating transform shadowing from warn to error when owners differ (two plugins
  can currently shadow each other's transforms import-order-dependently — owners
  are at least named now).
- Sub-namespace registries for the SDTM/TLG accessors (mechanism generalizes).

## 7. Risks

- `describe_owner` inference can misattribute editable installs — the honest
  `session:<module>` fallback keeps it truthful rather than wrong.
- `resolve_callable` ambiguity: dotted refs that miss the registry fall through to
  import with misleading errors — addressed by the underscore-prefix naming
  convention, stated plainly in docs.
- Entry-point metadata scanning is cheap (~ms) and executes nothing, so `import
  fleet` latency and hermeticity are unaffected.

## 8. Verification

- `pytest tests/unit/test_plugins.py tests/unit/test_subnamespace_registry.py
  tests/unit/test_cli.py tests/unit/test_tlg_yaml_workflow.py`, then the full suite.
- Manual end-to-end: build a throwaway `demo-fleet` wheel with an entry point and a
  `DemoNamespace`; install into the venv; from a study workspace with
  `extensions: [demo]`: `fleet plugins` shows installed → active; notebook-style
  `load_study_context()` then `df.adam.demo.<verb>()` works with pins; remove from
  config → inert but still listed; break `register()` → `StudyConfigError` at
  context load while `import fleet` stays unaffected.
- `mkdocs build` clean; moved `advanced.md` anchors/links updated.
