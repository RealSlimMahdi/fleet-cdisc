"""Fleet CLI — study bootstrapping, pipeline execution, validation, and TLG rendering.

Entry point: ``fleet`` (registered as a console script).

Bootstrapping pipeline (run in order):

- ``fleet init cfg``    — create ``study_config.yaml`` and directory structure.
- ``fleet init define`` — generate ``define.yaml`` from the CDISC Library IG.
- ``fleet init ct``     — generate ``codelists.py`` from the ``define.yaml``.
- ``fleet init rules``  — cache CDISC conformance rules as YAML.
- ``fleet new``         — run all four steps with a single confirmation.

Execution commands:

- ``fleet run``      — execute define.yaml derivations and write datasets.
- ``fleet validate`` — validate datasets with the CDISC Rules Engine.
- ``fleet check``    — one CI gate: config + define schema + rule YAMLs.
- ``fleet tlg``      — list / run / export TLG templates (``tlg --help``).
- ``fleet migrate``  — rewrite removed pre-alpha verb spellings to canonical ones.
- ``fleet mcp``      — MCP server for AI assistants (``mcp`` extra).
- ``fleet lsp``      — define.yaml language server (``lsp`` extra).

Every command that needs ``study_config.yaml`` discovers it git-style: the
current directory first, then each parent.  Pass ``--config`` to override.

Errors print a single clean message to **stderr** and exit ``1``; missing
or unknown (sub)commands print usage to stderr and exit ``2``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import polars as pl

    from fleet.core.study_context import StudyContext

#: Treatment-arm columns tried (in order) when ``--groupby`` is not given.
_GROUPBY_CANDIDATES: tuple[str, ...] = ("TRTA", "TRT01A", "TRT01P")

#: Optional-dependency probes for ``fleet doctor`` / ``fleet check``:
#: import name → (extra name, what it enables).
_OPTIONAL_EXTRAS: dict[str, tuple[str, str]] = {
    "weasyprint": ("tlg-pdf", "PDF rendering"),
    "pptx": ("tlg-pptx", "PPTX slide rendering"),
    "pyreadstat": ("io", "SAS XPT read/write"),
    "libcst": ("migrate", "fleet migrate codemod"),
    "watchfiles": ("watch", "--watch mode"),
    "pygls": ("lsp", "fleet lsp language server"),
    "mcp": ("mcp", "fleet mcp server"),
}


# ────────────────────────────────────────────────────────────────────── #
# Output helpers                                                          #
# ────────────────────────────────────────────────────────────────────── #


def _err(msg: str) -> None:
    """Print *msg* to stderr."""
    print(msg, file=sys.stderr)


def _fail(msg: str) -> None:
    """Print an error to stderr and exit 1."""
    _err(f"Error: {msg}")
    sys.exit(1)


# ────────────────────────────────────────────────────────────────────── #
# Config discovery                                                        #
# ────────────────────────────────────────────────────────────────────── #


def find_study_config(start: Path | None = None) -> Path | None:
    """Locate ``study_config.yaml`` by walking up parent directories.

    Git-style discovery: the start directory is checked first, then each
    parent up to the filesystem root.  Every CLI command that needs study
    configuration resolves it through this single function.

    Args:
        start: Directory to start from (default: current working directory).

    Returns:
        Path | None: The first ``study_config.yaml`` found, or ``None``.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        cfg = candidate / "study_config.yaml"
        if cfg.is_file():
            return cfg
    return None


def _resolve_config(config_arg: str | None) -> Path:
    """Resolve the config path from ``--config`` or parent-walking discovery.

    Exits 1 with a clear hint when no configuration can be found.
    """
    if config_arg:
        cfg = Path(config_arg)
        if not cfg.is_file():
            _fail(f"config not found: {cfg}")
        return cfg
    cfg = find_study_config()
    if cfg is None:
        _fail(
            "no study_config.yaml found in the current directory or any parent. "
            "Run `fleet init cfg` to create one, or pass --config <path>."
        )
    return cfg  # type: ignore[return-value]  # _fail never returns


def _load_ctx(config_arg: str | None) -> StudyContext:
    """Load the study context from an explicit or discovered config path."""
    from fleet.core.study_context import load_study_context

    return load_study_context(_resolve_config(config_arg))


def _config_flag_hint(config_path: Path) -> str:
    """Return `` --config <path>`` unless the config sits in the cwd."""
    if config_path.resolve().parent == Path.cwd().resolve():
        return ""
    return f" --config {config_path}"


# ────────────────────────────────────────────────────────────────────── #
# Shared helpers                                                          #
# ────────────────────────────────────────────────────────────────────── #


def _parse_domains(raw: str) -> list[str]:
    return [d.strip().upper() for d in raw.split(",") if d.strip()]


def _load_dataset(path_str: str) -> pl.DataFrame:
    """Load a dataset file (CSV / Parquet / XPT / SAS) as a DataFrame."""
    from fleet.io import load_raw_data

    p = Path(path_str)
    if not p.is_file():
        _fail(f"file not found: {p}")
    return load_raw_data(p).collect()


def _detect_groupby(df: pl.DataFrame, explicit: str | None) -> str:
    """Resolve the treatment-arm column against the *analysis data* frame.

    Uses ``--groupby`` when given (validated against the frame), otherwise
    auto-detects TRTA → TRT01A → TRT01P.  On failure, errors out listing
    the candidate columns actually present in the data.
    """
    if explicit:
        if explicit not in df.columns:
            _fail(
                f"--groupby column '{explicit}' not found in the data. "
                f"Available columns: {', '.join(df.columns)}"
            )
        return explicit
    for cand in _GROUPBY_CANDIDATES:
        if cand in df.columns:
            return cand
    _fail(
        "could not auto-detect a treatment-arm column "
        f"(tried {', '.join(_GROUPBY_CANDIDATES)}). Pass --groupby <column>. "
        f"Columns present in the data: {', '.join(df.columns)}"
    )
    raise AssertionError("unreachable")


def _watch_loop(paths: Sequence[Path], run_once: Callable[[], None]) -> None:
    """Re-run *run_once* whenever any of *paths* changes (``--watch``)."""
    try:
        from watchfiles import watch
    except ImportError:
        _fail(
            "watchfiles is required for --watch. Install it with: "
            "uv sync --extra watch  (or: uv pip install 'fleet-cdisc[watch]')"
        )

    from fleet.core.exceptions import FleetError
    from fleet.core.study_context import StudyConfigError

    def _guarded() -> None:
        try:
            run_once()
        except (FleetError, StudyConfigError, ImportError) as exc:
            _err(f"Error: {exc}")

    _guarded()
    print(f"\nWatching for changes ({', '.join(str(p) for p in paths)}) — Ctrl-C to stop.")
    for _changes in watch(*[str(p) for p in paths]):
        print()
        _guarded()


# ────────────────────────────────────────────────────────────────────── #
# Bootstrapping pipeline                                                  #
# ────────────────────────────────────────────────────────────────────── #


def _run_init_cfg(args: argparse.Namespace) -> None:
    from fleet.core.study_context import (
        ADAMConfig,
        CTConfig,
        SDTMConfig,
        StudyContext,
        ValidationConfig,
    )

    study_root = Path(args.root).resolve()
    domains = _parse_domains(args.domains) if args.domains else []
    adam_datasets = _parse_domains(args.adam_datasets) if args.adam_datasets else []

    print(f"Study ID: {args.study_id}")
    print(f"Root:     {study_root}")
    if domains:
        print(f"Domains:  {', '.join(domains)}")
    if adam_datasets:
        print(f"ADaM:     {', '.join(adam_datasets)}")
    print()

    ctx = StudyContext.init(
        study_root=study_root,
        study_id=args.study_id,
        company=args.company,
        sdtm=SDTMConfig(ig_version=args.ig, domains=domains),
        adam=ADAMConfig(ig_version=args.adam_ig, datasets=adam_datasets),
        ct=CTConfig(package=args.package),
        validation=ValidationConfig(custom_rules="metadata/custom_rules"),
    )
    config_path = ctx.study_root / "study_config.yaml"
    hint = _config_flag_hint(config_path)
    print(f"Created study workspace → {ctx.study_root}")
    print(f"Config  → {config_path}")
    print()
    print("Next steps:")
    print(f"  fleet init define{hint}")
    print(f"  fleet init ct{hint}")
    print(f"  fleet init rules{hint}")


def _run_init_define(args: argparse.Namespace) -> None:
    from fleet.core.scaffolder import DefineScaffolder
    from fleet.ct.api import CDISCClient

    ctx = _load_ctx(args.config)
    cfg = ctx.config
    do_sdtm = not args.adam_only
    do_adam = not args.sdtm_only

    if do_sdtm and not cfg.sdtm.domains:
        print("Warning: No SDTM domains configured. Skipping SDTM define.")
        do_sdtm = False
    if do_adam and not cfg.adam.datasets:
        print("Warning: No ADaM datasets configured. Skipping ADaM define.")
        do_adam = False

    if not do_sdtm and not do_adam:
        _fail("nothing to generate — configure domains/datasets in study_config.yaml.")

    # Extract CT version date from package string (e.g. "sdtmct-2023-12-15" → "2023-12-15")
    ct_version = cfg.ct.package.split("-", 1)[-1] if "-" in cfg.ct.package else "2023-12-15"

    with CDISCClient() as client:
        scaffolder = DefineScaffolder(client)

        force = getattr(args, "force", False)

        if do_sdtm:
            sdtm_path = ctx.metadata_sdtm_dir / "define.yaml"
            if sdtm_path.exists() and not force:
                print(f"Warning: {sdtm_path} already exists — skipping (use --force to overwrite).")
            else:
                dest = scaffolder.scaffold_sdtm(
                    study_id=cfg.study_id,
                    company=cfg.company or "",
                    ig_version=cfg.sdtm.ig_version,
                    ct_version=ct_version,
                    domains=cfg.sdtm.domains,
                    output_path=sdtm_path,
                )
                print(f"SDTM define → {dest}")

        if do_adam:
            adam_path = ctx.metadata_adam_dir / "define.yaml"
            if adam_path.exists() and not force:
                print(f"Warning: {adam_path} already exists — skipping (use --force to overwrite).")
            else:
                dest = scaffolder.scaffold_adam(
                    study_id=cfg.study_id,
                    company=cfg.company or "",
                    ig_version=cfg.adam.ig_version,
                    ct_version=ct_version,
                    datasets=cfg.adam.datasets,
                    output_path=adam_path,
                )
                print(f"ADaM define → {dest}")

    hint = _config_flag_hint(ctx.study_root / "study_config.yaml")
    print()
    print(f"Next step: fleet init ct{hint}")


def _run_init_rules(args: argparse.Namespace) -> None:
    from fleet.core.rules_scaffolder import RulesScaffolder
    from fleet.ct.api import CDISCClient

    ctx = _load_ctx(args.config)
    do_sdtm = not args.adam_only
    do_adam = not args.sdtm_only

    with CDISCClient() as client:
        scaffolder = RulesScaffolder(client)

        if do_sdtm:
            try:
                scaffolder.scaffold_sdtm(ctx, force=args.force)
            except FileNotFoundError as exc:
                print(f"Warning: {exc}")

        if do_adam:
            try:
                scaffolder.scaffold_adam(ctx, force=args.force)
            except FileNotFoundError as exc:
                print(f"Warning: {exc}")

    print()
    print("Rules cached. Commit to VCS for a permanent audit trail.")


def _run_init_ct_pipeline(args: argparse.Namespace) -> None:
    from fleet.ct.api import CDISCClient
    from fleet.ct.generator import CodelistGenerator, extract_concept_ids

    ctx = _load_ctx(args.config)
    cfg = ctx.config

    # Collect concept IDs from all define.yaml files
    all_ids: set[str] = set()

    sdtm_define = ctx.metadata_sdtm_dir / "define.yaml"
    adam_define = ctx.metadata_adam_dir / "define.yaml"

    for dpath in (sdtm_define, adam_define):
        if dpath.is_file():
            ids = extract_concept_ids(dpath)
            all_ids |= ids
            print(f"Scanned {dpath.name}: {len(ids)} codelist(s)")

    hint = _config_flag_hint(ctx.study_root / "study_config.yaml")
    if not all_ids:
        _err("Error: no codelist references found in define.yaml files.")
        _err(f"Run `fleet init define{hint}` first.")
        sys.exit(1)

    print(f"\nTotal unique codelists: {len(all_ids)}")
    print()

    output = ctx.metadata_sdtm_dir / "codelists.py"
    force = getattr(args, "force", False)
    if output.exists() and not force:
        print(f"Warning: {output} already exists — skipping (use --force to overwrite).")
        return

    with CDISCClient() as client:
        gen = CodelistGenerator.from_concept_ids(
            client,
            all_ids,
            package=cfg.ct.package,
            include_docs=not args.no_docs,
        )
        dest = gen.write(output)

    print(f"Generated {gen.codelist_count} codelists → {dest}")

    print()
    print("Bootstrap complete! Next steps:")
    print(
        "  - Spec-driven:  codelists are already referenced in define.yaml — start writing derivations."
    )
    print("  - Inline code:  from fleet.ct import import_codelists; ct = import_codelists()")
    print("                  or: import_codelists(); from codelists import SEX, RACE, ...")
    print("  - When ready:   fleet run   (or: fleet define-xml --spec <define.yaml>)")


# ────────────────────────────────────────────────────────────────────── #
# Standalone CT commands                                                  #
# ────────────────────────────────────────────────────────────────────── #


def _run_init_ct(args: argparse.Namespace) -> None:
    from fleet.ct.api import CDISCClient
    from fleet.ct.generator import CodelistGenerator

    domains = _parse_domains(args.domains)
    output = Path(args.output)

    print(f"Domains:  {', '.join(domains)}")
    print(f"IG:       sdtmig/{args.ig}")
    print(f"Package:  {args.package}")
    print(f"Output:   {output}")
    print()

    with CDISCClient() as client:
        gen = CodelistGenerator.from_sdtm_ig(
            client,
            domains=domains,
            ig_version=args.ig,
            package=args.package,
            include_docs=not args.no_docs,
        )
        dest = gen.write(output)

    print(f"Generated {gen.codelist_count} codelists → {dest}")


def _run_add_ct(args: argparse.Namespace) -> None:
    from fleet.ct.api import CDISCClient
    from fleet.ct.generator import (
        CodelistGenerator,
        existing_concept_ids,
        extract_ig_concept_ids,
    )

    domains = _parse_domains(args.domains)
    output = Path(args.output)
    existing = existing_concept_ids(output)

    print(f"Adding domains: {', '.join(domains)}")
    print(f"Existing file:  {output} ({len(existing)} codelists)")
    print()

    with CDISCClient() as client:
        new_ids = extract_ig_concept_ids(client, args.ig, domains)
        to_add = new_ids - existing
        all_ids = existing | new_ids

        if not to_add:
            print("All codelists for these domains are already present. Nothing to add.")
            return

        print(f"New codelists to add: {len(to_add)}")
        print(f"Total after merge:    {len(all_ids)}")
        print()

        gen = CodelistGenerator.from_concept_ids(
            client,
            all_ids,
            package=args.package,
            include_docs=not args.no_docs,
        )
        dest = gen.write(output)

    print(f"Updated {dest} — {gen.codelist_count} codelists")


# ────────────────────────────────────────────────────────────────────── #
# Custom validation rules                                                 #
# ────────────────────────────────────────────────────────────────────── #


def _run_add_rule(args: argparse.Namespace) -> None:
    from fleet.validation.rule_scaffolder import scaffold_rule

    # Resolve config (optional here — only needed when --output is absent
    # or to pick up the organization name).
    config_path = Path(args.config) if args.config else find_study_config()
    if args.config and not config_path.is_file():  # type: ignore[union-attr]
        _fail(f"config not found: {config_path}")

    ctx = None
    if config_path is not None and config_path.is_file():
        from fleet.core.study_context import load_study_context

        ctx = load_study_context(config_path)

    # Resolve output directory: --output wins, then validation.custom_rules.
    output_dir: Path | None = Path(args.output) if args.output else None
    if output_dir is None:
        if ctx is None:
            _fail(
                "no study_config.yaml found in the current directory or any parent. "
                "Pass --output <dir>, --config <path>, or run from a study root."
            )
        output_dir = ctx.custom_rules_dir  # type: ignore[union-attr]
        if output_dir is None:
            _fail(
                "no 'validation.custom_rules' configured in study_config.yaml. "
                "Either add it to your config or pass --output <dir>."
            )

    # Resolve organization from the study config if available.
    organization: str | None = None
    if ctx is not None:
        company = ctx.config.company
        # "CDISC" and "FDA" are reserved by the schema — use prefix instead
        if company and company.upper() not in ("CDISC", "FDA"):
            organization = company

    try:
        out_file = scaffold_rule(
            domain=args.domain,
            description=args.description,
            output_dir=output_dir,
            prefix=args.prefix,
            rule_id=args.rule_id,
            organization=organization,
        )
    except FileExistsError as exc:
        _fail(str(exc))
        return

    print(f"Created custom rule: {out_file}")
    print(f"  Rule ID: {out_file.stem}")
    print(f"  Domain:  {args.domain.upper()}")
    print()
    print("Next steps:")
    print(f"  1. Edit the Check block in {out_file.name}")
    print(f"  2. Validate:  uv run fleet check-rule {out_file}")
    print('  3. Run in pipeline: .validate(..., custom_rules="<dir>")')


def _run_check_rule(args: argparse.Namespace) -> None:
    from fleet.validation.rule_scaffolder import check_rule

    rule_path = Path(args.rule_file)
    if not rule_path.exists():
        _fail(f"file not found: {rule_path}")

    print(f"Checking rule: {rule_path}")
    print(f"{'─' * 60}")

    errors = check_rule(rule_path)

    if not errors:
        # Also print a summary of what was found
        import yaml as _yaml

        with open(rule_path) as f:
            rule = _yaml.safe_load(f)
        core_id = rule.get("Core", {}).get("Id", "?")
        rule_type = rule.get("Rule Type", "?")
        domains = rule.get("Scope", {}).get("Domains", {}).get("Include", [])
        print(f"  Rule ID:   {core_id}")
        print(f"  Type:      {rule_type}")
        print(f"  Domains:   {', '.join(domains)}")
        print()
        print("  ✓ YAML syntax OK")
        print("  ✓ Structure OK")
        print("  ✓ Schema validation PASSED")
    else:
        _err("")
        for err in errors:
            _err(f"  ✗ {err}")
        _err("")
        _err(f"  {len(errors)} error(s) found.")
        sys.exit(1)


# ────────────────────────────────────────────────────────────────────── #
# Rules engine + doctor                                                   #
# ────────────────────────────────────────────────────────────────────── #


def _run_install_engine(args: argparse.Namespace) -> None:
    from fleet.validation.engine import install_engine

    try:
        install_engine(version=args.version, force=args.force)
    except RuntimeError as exc:
        _fail(str(exc))


def _run_uninstall_engine(args: argparse.Namespace) -> None:
    from fleet.validation.engine import uninstall_engine

    uninstall_engine()


def _check_extras() -> list[tuple[str, bool, str]]:
    """Probe optional dependencies: (display name, installed?, install hint)."""
    import importlib.util

    results: list[tuple[str, bool, str]] = []
    for module, (extra, purpose) in _OPTIONAL_EXTRAS.items():
        installed = importlib.util.find_spec(module) is not None
        hint = f"{purpose} — install with: uv sync --extra {extra}"
        results.append((module, installed, hint))
    return results


def _run_doctor(args: argparse.Namespace) -> None:
    from fleet.validation.engine import doctor

    # Honour validation.engine_path from the discovered study config.
    config_path = Path(args.config) if getattr(args, "config", None) else find_study_config()
    study_root = config_path.parent if config_path and config_path.is_file() else None

    checks = doctor(study_root=study_root)

    print("Fleet Doctor")
    print("=" * 52)

    if config_path and config_path.is_file():
        print(f"  ✓ study config ....... {config_path}")
    else:
        print("  ✗ study config ....... not found (run `fleet init cfg`)")

    engine = checks.get("engine", "")
    engine_ok = not engine.startswith("NOT FOUND")
    mark = "✓" if engine_ok else "✗"
    print(f"  {mark} rules engine ....... {engine}")
    if engine_ok:
        if "type" in checks:
            print(f"      type: {checks['type']}")
        if "status" in checks:
            status_mark = "✓" if checks["status"].startswith("OK") else "✗"
            print(f"  {status_mark} engine status ...... {checks['status']}")

    api_key_set = bool(os.environ.get("CDISC_API_KEY"))
    if api_key_set:
        print("  ✓ CDISC_API_KEY ...... set")
    else:
        print(
            "  ✗ CDISC_API_KEY ...... not set — needed by `fleet init define/ct/rules` "
            "(set it in the environment or a .env file)"
        )

    print()
    print("Optional extras")
    print("-" * 52)
    for name, installed, hint in _check_extras():
        if installed:
            print(f"  ✓ {name:.<20s} installed")
        else:
            print(f"  ✗ {name:.<20s} {hint}")
    print()


# ────────────────────────────────────────────────────────────────────── #
# Define-XML                                                              #
# ────────────────────────────────────────────────────────────────────── #


def _generate_define_xml(args: argparse.Namespace) -> None:
    """One Define-XML generation pass (also the --watch worker)."""
    from fleet.define_xml.spec_generator import DefineSpecGenerator

    spec = Path(args.spec)
    output = Path(args.output)

    print(f"Spec:     {spec}")
    print(f"Output:   {output}")
    print()

    gen = DefineSpecGenerator(
        str(spec),
        enrich_methods=getattr(args, "enrich_methods", False),
    )
    gen.generate(str(output), html_preview=not args.no_preview)
    print(f"Generated Define-XML → {output}")
    if not args.no_preview:
        preview = output.with_name(output.stem + "_preview.html")
        print(f"HTML preview → {preview}")


def _run_define_xml(args: argparse.Namespace) -> None:
    spec = Path(args.spec)
    if not spec.is_file():
        _fail(f"spec file not found: {spec}")

    if args.watch:
        _watch_loop([spec], lambda: _generate_define_xml(args))
        return
    _generate_define_xml(args)


# ────────────────────────────────────────────────────────────────────── #
# fleet run — execute define.yaml pipelines                               #
# ────────────────────────────────────────────────────────────────────── #


def _load_run_input(ctx: StudyContext, name: str, built: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Resolve one ``inputs:`` entry: in-memory result first, then files."""
    from fleet.io import load_raw_data

    key = name.upper()
    if key in built:
        return built[key]

    search_dirs = [ctx.raw_data_dir, ctx.sdtm_data_dir, ctx.adam_data_dir]
    extensions = (".parquet", ".csv", ".xpt", ".sas7bdat")
    for directory in search_dirs:
        for stem in (name.lower(), name.upper()):
            for ext in extensions:
                candidate = directory / f"{stem}{ext}"
                if candidate.is_file():
                    return load_raw_data(candidate).collect()

    _fail(
        f"input dataset '{name}' not found. Searched for {name.lower()}/{name.upper()} "
        f"with extensions {', '.join(extensions)} under: "
        f"{', '.join(str(d) for d in search_dirs)}. "
        "Run the upstream dataset first (fleet run --dataset ...) or place the file "
        "in one of those directories."
    )
    raise AssertionError("unreachable")


def _compose_run_frame(
    ctx: StudyContext,
    ds: dict[str, Any],
    built: dict[str, pl.DataFrame],
) -> pl.DataFrame:
    """Build the input frame for one dataset from its ``inputs:`` block.

    The first input is the base frame; every additional input is
    left-joined on ``USUBJID``, restricted to the spec-declared columns
    the base does not already carry (the standard ADSL-into-BDS merge).
    """
    name = ds.get("name", "?")
    inputs = [i["name"] for i in ds.get("inputs", []) if i.get("type", "dataset") == "dataset"]
    if not inputs:
        _fail(
            f"dataset {name}: the define declares no `inputs:` — "
            "fleet run cannot determine the source data. Add an inputs: block."
        )

    base = _load_run_input(ctx, inputs[0], built)
    declared = {v["name"] for v in ds.get("variables", [])}

    for extra_name in inputs[1:]:
        extra = _load_run_input(ctx, extra_name, built)
        if "USUBJID" not in base.columns or "USUBJID" not in extra.columns:
            _fail(
                f"dataset {name}: cannot merge input '{extra_name}' — "
                "both frames must carry USUBJID."
            )
        cols = [
            c for c in extra.columns if c != "USUBJID" and c in declared and c not in base.columns
        ]
        base = base.join(extra.select(["USUBJID", *cols]), on="USUBJID", how="left")

    return base


def _run_run(args: argparse.Namespace) -> None:
    import yaml

    import fleet  # noqa: F401 — registers .sdtm / .adam namespaces
    from fleet.io import save_dataset_json, save_parquet, save_xpt

    ctx = _load_ctx(args.config)

    defines: list[tuple[Path, str]] = []
    for path, standard in (
        (ctx.metadata_sdtm_dir / "define.yaml", "sdtm"),
        (ctx.metadata_adam_dir / "define.yaml", "adam"),
    ):
        if path.is_file():
            defines.append((path, standard))
    if not defines:
        _fail(
            f"no define.yaml found under {ctx.metadata_sdtm_dir} or "
            f"{ctx.metadata_adam_dir}. Run `fleet init define` first."
        )

    plan: list[tuple[Path, str, dict[str, Any]]] = []
    for path, standard in defines:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for ds in data.get("datasets", []):
            plan.append((path, standard, ds))

    if args.dataset:
        wanted = {d.upper() for d in args.dataset}
        known = {ds["name"].upper() for _, _, ds in plan}
        unknown = sorted(wanted - known)
        if unknown:
            _fail(
                f"unknown dataset(s): {', '.join(unknown)}. "
                f"Datasets in the define files: {', '.join(sorted(known))}"
            )
        plan = [entry for entry in plan if entry[2]["name"].upper() in wanted]

    writers: dict[str, Callable[[pl.DataFrame, Path, str], Path]] = {
        "parquet": lambda df, d, n: save_parquet(df, d / f"{n.lower()}.parquet"),
        "xpt": lambda df, d, n: save_xpt(df, d / f"{n.lower()}.xpt"),
        "dataset-json": lambda df, d, n: save_dataset_json(df, d / f"{n.lower()}.json", domain=n),
    }
    writer = writers[args.format]

    built: dict[str, pl.DataFrame] = {}
    out_override = Path(args.out) if args.out else None

    print(f"Config:  {ctx.study_root / 'study_config.yaml'}")
    print(f"Format:  {args.format}")
    print()

    for i, (path, standard, ds) in enumerate(plan, start=1):
        name = ds["name"].upper()
        print(f"[{i}/{len(plan)}] {name} ({standard}, {path.name}) ...")

        frame = _compose_run_frame(ctx, ds, built)
        ns = frame.sdtm if standard == "sdtm" else frame.adam  # type: ignore[attr-defined]
        result = (
            ns.from_spec(path, dataset=name, strict=args.strict)
            .select(spec=path, dataset=name)
            .to_frame()
        )
        built[name] = result

        out_dir = out_override or (ctx.sdtm_data_dir if standard == "sdtm" else ctx.adam_data_dir)
        out_path = writer(result, out_dir, name)
        print(f"        {result.shape[0]} rows × {result.shape[1]} cols → {out_path}")

    print()
    print(f"Done — {len(plan)} dataset(s) written.")


# ────────────────────────────────────────────────────────────────────── #
# fleet validate — CDISC Rules Engine wrapper                             #
# ────────────────────────────────────────────────────────────────────── #

_DATA_EXTENSIONS = (".parquet", ".csv", ".xpt", ".sas7bdat")


def _collect_data_files(paths: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for ext in _DATA_EXTENSIONS:
                files.extend(sorted(p.glob(f"*{ext}")))
        elif p.is_file():
            files.append(p)
        else:
            _fail(f"path not found: {p}")
    return files


def _write_validation_report(path: Path, results: list[Any]) -> None:
    """Write a minimal self-contained HTML report of validation findings."""
    from html import escape

    rows: list[str] = []
    for res in results:
        for issue in (*res.errors, *res.warnings, *res.infos):
            rows.append(
                "<tr>"
                f"<td>{escape(res.dataset_name)}</td>"
                f"<td>{escape(issue.severity.value)}</td>"
                f"<td>{escape(issue.rule_id)}</td>"
                f"<td>{escape(issue.variable or '')}</td>"
                f"<td>{escape(issue.message)}</td>"
                "</tr>"
            )
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Fleet validation report</title>"
        "<style>body{font-family:sans-serif}table{border-collapse:collapse}"
        "td,th{border:1px solid #999;padding:4px 8px;font-size:13px}</style>"
        "</head><body><h1>Fleet validation report</h1>"
        "<table><tr><th>Dataset</th><th>Severity</th><th>Rule</th>"
        "<th>Variable</th><th>Message</th></tr>"
        f"{''.join(rows) or '<tr><td colspan=5>No findings.</td></tr>'}"
        "</table></body></html>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _run_validate(args: argparse.Namespace) -> None:
    from fleet.validation import ValidationService
    from fleet.validation.engine import discover_engine

    files = _collect_data_files(args.paths)
    if not files:
        _fail(
            "no dataset files found. Pass files or a directory containing "
            f"{', '.join(_DATA_EXTENSIONS)} files."
        )

    config_path = find_study_config()
    study_root = config_path.parent if config_path else None
    engine = discover_engine(study_root)
    if engine is None:
        _fail(
            "CDISC Rules Engine not found. Install it with `fleet install-engine` "
            "or set FLEET_RULES_ENGINE / validation.engine_path."
        )

    service = ValidationService(rules_engine_path=engine)
    results = []
    failed = 0

    for f in files:
        df = _load_dataset(str(f))
        name = f.stem.upper()
        standard = args.standard or ("adam" if name.startswith("AD") else "sdtm")
        kwargs: dict[str, Any] = {"custom_rules": args.custom_rules}
        if args.standard_version:
            kwargs["version"] = args.standard_version

        print(f"Validating {name} ({standard}) — {f}")
        if standard == "adam":
            result = service.validate_adam(df, name, **kwargs)
        else:
            result = service.validate_sdtm(df, name, **kwargs)
        results.append(result)
        result.print_report()
        if result.errors:
            failed += 1

    if args.report:
        report_path = Path(args.report)
        _write_validation_report(report_path, results)
        print(f"HTML report → {report_path}")

    print()
    print(f"Validated {len(files)} dataset(s): {len(files) - failed} passed, {failed} failed.")
    if failed:
        sys.exit(1)


# ────────────────────────────────────────────────────────────────────── #
# fleet check — one CI gate                                               #
# ────────────────────────────────────────────────────────────────────── #


def _run_check(args: argparse.Namespace) -> None:
    """Run the CI gate: config + define schema + rule YAMLs + essentials."""
    from fleet.core.study_context import StudyConfigError, load_study_context

    rows: list[tuple[str, str, str]] = []  # (status, name, detail)

    # ── 1. Config parse ──
    config_path = Path(args.config) if args.config else find_study_config()
    ctx = None
    if config_path is None or not config_path.is_file():
        rows.append(("FAIL", "study config", "study_config.yaml not found (run `fleet init cfg`)"))
    else:
        try:
            ctx = load_study_context(config_path)
            rows.append(("PASS", "study config", f"{config_path} ({ctx.study_id})"))
        except StudyConfigError as exc:
            rows.append(("FAIL", "study config", str(exc)))

    # ── 2. define.yaml JSON-schema validation ──
    if ctx is not None:
        from fleet.define_xml import DatasetChecker

        found_define = False
        for label, path in (
            ("define (sdtm)", ctx.metadata_sdtm_dir / "define.yaml"),
            ("define (adam)", ctx.metadata_adam_dir / "define.yaml"),
        ):
            if not path.is_file():
                continue
            found_define = True
            try:
                DatasetChecker(path)  # parses YAML + validates against the JSON schema
                rows.append(("PASS", label, f"{path} — schema OK"))
            except Exception as exc:
                rows.append(("FAIL", label, f"{path}: {exc}"))
        if not found_define:
            rows.append(
                ("WARN", "define.yaml", "no define.yaml files found (run `fleet init define`)")
            )

    # ── 3. Custom-rule YAML checks ──
    if ctx is not None:
        rules_dir = ctx.custom_rules_dir
        if rules_dir is None or not rules_dir.is_dir():
            rows.append(("WARN", "custom rules", "no validation.custom_rules directory configured"))
        else:
            from fleet.validation.rule_scaffolder import check_rule

            rule_files = sorted([*rules_dir.glob("*.yaml"), *rules_dir.glob("*.yml")])
            bad = 0
            for rf in rule_files:
                errors = check_rule(rf)
                if errors:
                    bad += 1
                    rows.append(("FAIL", "custom rule", f"{rf.name}: {errors[0]}"))
            if not bad:
                rows.append(("PASS", "custom rules", f"{len(rule_files)} rule file(s) valid"))

    # ── 4. Doctor essentials (informational — never fail the gate) ──
    from fleet.validation.engine import discover_engine

    study_root = ctx.study_root if ctx is not None else None
    engine = discover_engine(study_root)
    if engine is not None:
        rows.append(("PASS", "rules engine", str(engine)))
    else:
        rows.append(("WARN", "rules engine", "not found (run `fleet install-engine`)"))

    if os.environ.get("CDISC_API_KEY"):
        rows.append(("PASS", "CDISC_API_KEY", "set"))
    else:
        rows.append(("WARN", "CDISC_API_KEY", "not set (needed by `fleet init define/ct/rules`)"))

    # ── Summary table ──
    marks = {"PASS": "✓", "FAIL": "✗", "WARN": "!"}
    print("Fleet Check")
    print("=" * 60)
    for status, name, detail in rows:
        print(f"  {marks[status]} [{status}] {name:.<18s} {detail}")
    print("-" * 60)

    failures = sum(1 for status, _, _ in rows if status == "FAIL")
    warnings_ = sum(1 for status, _, _ in rows if status == "WARN")
    print(f"{failures} failure(s), {warnings_} warning(s)")
    if failures:
        sys.exit(1)


# ────────────────────────────────────────────────────────────────────── #
# fleet new — chained bootstrap                                           #
# ────────────────────────────────────────────────────────────────────── #


def _run_new(args: argparse.Namespace) -> None:
    study_root = Path(args.root).resolve()
    config_path = study_root / "study_config.yaml"
    api_key_set = bool(os.environ.get("CDISC_API_KEY"))
    hint = _config_flag_hint(config_path)

    print(f"About to bootstrap study {args.study_id} in {study_root}:")
    print("  1. fleet init cfg     — study_config.yaml + directory layout")
    if api_key_set:
        print("  2. fleet init define  — define.yaml from the CDISC Library IG")
        print("  3. fleet init ct      — codelists.py from the define.yaml")
        print("  4. fleet init rules   — cache CDISC conformance rules")
    else:
        print("  2. fleet init define  — SKIPPED (CDISC_API_KEY not set)")
        print("  3. fleet init ct      — SKIPPED (CDISC_API_KEY not set)")
        print("  4. fleet init rules   — SKIPPED (CDISC_API_KEY not set)")
    print()

    if not args.yes:
        try:
            answer = input("Proceed? [y/N]: ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            _err("Aborted.")
            sys.exit(1)
        print()

    _run_init_cfg(
        argparse.Namespace(
            study_id=args.study_id,
            company=args.company,
            domains=args.domains,
            adam_datasets=args.adam_datasets,
            ig=args.ig,
            adam_ig=args.adam_ig,
            package=args.package,
            root=str(study_root),
        )
    )

    if not api_key_set:
        print()
        print("Note: CDISC_API_KEY is not set — the CDISC Library steps were skipped.")
        print("Set the key (environment variable or .env file), then resume with:")
        print(f"  fleet init define{hint}")
        print(f"  fleet init ct{hint}")
        print(f"  fleet init rules{hint}")
        return

    print()
    _run_init_define(
        argparse.Namespace(config=str(config_path), sdtm_only=False, adam_only=False, force=False)
    )
    print()
    _run_init_ct_pipeline(argparse.Namespace(config=str(config_path), no_docs=False, force=False))
    print()
    _run_init_rules(
        argparse.Namespace(config=str(config_path), sdtm_only=False, adam_only=False, force=False)
    )


# ────────────────────────────────────────────────────────────────────── #
# fleet migrate — codemod wrapper                                         #
# ────────────────────────────────────────────────────────────────────── #


def _run_migrate(args: argparse.Namespace) -> None:
    from fleet.tools.migrate import main as migrate_main

    argv = [*args.files]
    if args.write:
        argv.append("--write")
    sys.exit(migrate_main(argv))


# ────────────────────────────────────────────────────────────────────── #
# TLG commands                                                            #
# ────────────────────────────────────────────────────────────────────── #


def _run_tlg_list(args: argparse.Namespace) -> None:
    from fleet.tlg import TEMPLATES

    print(f"{'ID':<8} {'TYPE':<8} {'STATUS':<9} {'NS':<4} {'DOMAINS':<14} TITLE")
    print("-" * 84)
    for meta in TEMPLATES.values():
        domains = ",".join(meta.domains)
        print(
            f"{meta.id:<8} {meta.output_type.value:<8} {meta.status.value:<9} "
            f"{meta.namespace:<4} {domains:<14} {meta.title}"
        )
    print("-" * 84)
    print(f"{len(TEMPLATES)} templates. Details: fleet tlg schema <id>")


def _run_tlg_schema(args: argparse.Namespace) -> None:
    from fleet.tlg import spec_schema

    json.dump(spec_schema(args.template_id), sys.stdout, indent=2)
    print()


def _parse_data_args(data_args: Sequence[str] | None) -> tuple[dict[str, Path], Path | None]:
    """Split repeatable ``--data`` values into ``NAME=PATH`` pairs + default."""
    named: dict[str, Path] = {}
    default: Path | None = None
    for item in data_args or []:
        if "=" in item and not Path(item).exists():
            name, _, path = item.partition("=")
            named[name.strip().upper()] = Path(path)
        else:
            default = Path(item)
    return named, default


def _render_output(
    result: pl.DataFrame,
    *,
    is_listing: bool,
    fmt: str,
    out_path: Path,
    rmeta: Any,
    rows_per_page: int | None,
    html_wrapper: str | None = None,
) -> None:
    """Render an ARD/listing to *out_path* in the requested format."""
    from fleet.tlg import (
        ard_to_table_model,
        listing_to_model,
        render_html,
        render_listing_html,
        render_listing_pdf,
        render_listing_pptx,
        render_listing_rtf,
        render_pdf,
        render_pptx,
        render_rtf,
    )

    page_kwargs: dict[str, Any] = {}
    if rows_per_page is not None:
        page_kwargs["rows_per_page"] = rows_per_page

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if is_listing:
        lmodel = listing_to_model(result, rmeta)
        listing_dispatch: dict[str, Callable[[], Any]] = {
            "html": lambda: out_path.write_text(
                render_listing_html(lmodel, **page_kwargs), encoding="utf-8"
            ),
            "rtf": lambda: render_listing_rtf(lmodel, out_path, **page_kwargs),
            "pdf": lambda: render_listing_pdf(lmodel, out_path, **page_kwargs),
            "pptx": lambda: render_listing_pptx(lmodel, out_path, **page_kwargs),
        }
        listing_dispatch[fmt]()
        return

    model = ard_to_table_model(result, rmeta)
    table_dispatch: dict[str, Callable[[], Any]] = {
        "html": lambda: out_path.write_text(
            render_html(model, html_wrapper=html_wrapper, **page_kwargs), encoding="utf-8"
        ),
        "rtf": lambda: render_rtf(model, out_path, **page_kwargs),
        "pdf": lambda: render_pdf(model, out_path, html_wrapper=html_wrapper, **page_kwargs),
        "pptx": lambda: render_pptx(model, out_path, **page_kwargs),
    }
    table_dispatch[fmt]()


def _collect_spec_paths(spec_arg: str) -> list[Path]:
    p = Path(spec_arg)
    if p.is_dir():
        specs = sorted({*p.glob("*.yaml"), *p.glob("*.yml")})
        if not specs:
            _fail(f"no .yaml/.yml spec files found in {p}")
        return specs
    if p.is_file():
        return [p]
    _fail(f"spec path not found: {spec_arg}")
    raise AssertionError("unreachable")


def _resolve_spec_frames(
    spec_path: Path,
    meta: Any,
    named_data: dict[str, Path],
    default_data: Path | None,
    adsl_df: pl.DataFrame | None,
    adsl_arg: str | None,
) -> tuple[pl.DataFrame, pl.DataFrame | None, bool]:
    """Resolve one spec's ``(data_df, population, is_listing)`` from CLI args.

    Shared by ``fleet tlg run`` and ``fleet tlg explore`` so both wire
    data identically: NAME=PATH mapping → plain ``--data`` → (for
    ADSL-only templates) the ``--adsl`` frame; population defaults to
    the data frame for ADSL-only templates and is required for every
    other table.
    """
    analysis_domain = meta.domains[-1] if meta.domains else None
    is_listing = meta.output_type.value == "listing"

    data_path = named_data.get(analysis_domain or "")
    if data_path is None and default_data is not None:
        data_path = default_data
    if data_path is None and analysis_domain == "ADSL" and adsl_arg:
        data_path = Path(adsl_arg)
    if data_path is None:
        _fail(
            f"{spec_path}: template '{meta.id}' needs the {analysis_domain} dataset. "
            f"Pass --data <path> or --data {analysis_domain}=<path>."
        )
    data_df = _load_dataset(str(data_path))

    population = adsl_df
    if population is None and analysis_domain == "ADSL":
        population = data_df
    if population is None and not is_listing and "ADSL" in meta.domains:
        _fail(
            f"{spec_path}: template '{meta.id}' needs ADSL for population "
            "denominators. Pass --adsl <path>."
        )
    return data_df, population, is_listing


def _tlg_run_once(args: argparse.Namespace) -> None:
    """One ``fleet tlg run`` pass over all resolved spec files."""
    from fleet.tlg import TEMPLATES, RenderMetadata, load_spec, run_spec

    spec_paths = _collect_spec_paths(args.spec)
    named_data, default_data = _parse_data_args(args.data)
    out_dir = Path(args.output)
    fmt: str = args.fmt

    adsl_df: pl.DataFrame | None = None
    if args.adsl:
        adsl_df = _load_dataset(args.adsl)

    for spec_path in spec_paths:
        spec = load_spec(spec_path)
        meta = TEMPLATES[spec.template]
        data_df, population, is_listing = _resolve_spec_frames(
            spec_path, meta, named_data, default_data, adsl_df, args.adsl
        )
        groupby = None if is_listing else _detect_groupby(data_df, args.groupby)

        result = run_spec(spec, data_df, adsl=population, groupby=groupby)

        rmeta = RenderMetadata(
            title=args.title or meta.title,
            subtitle=args.subtitle or "",
            footnotes=args.footnote or [],
            page_by=args.page_by,
        )
        out_path = out_dir / f"{spec_path.stem}.{fmt}"
        _render_output(
            result,
            is_listing=is_listing,
            fmt=fmt,
            out_path=out_path,
            rmeta=rmeta,
            rows_per_page=args.rows_per_page,
        )
        kind = "listing" if is_listing else "table"
        print(f"{spec_path.name} → {out_path}  ({meta.id}, {kind}, {result.shape[0]} rows)")


def _run_tlg_run(args: argparse.Namespace) -> None:
    if args.watch:
        watch_paths = _collect_spec_paths(args.spec)
        spec_arg = Path(args.spec)
        targets = [spec_arg] if spec_arg.is_dir() else watch_paths
        _watch_loop(targets, lambda: _tlg_run_once(args))
        return
    _tlg_run_once(args)


def _tlg_explore_once(args: argparse.Namespace) -> None:
    """One ``fleet tlg explore`` pass: specs → one static explorer HTML."""
    from fleet.tlg import TEMPLATES, RenderMetadata, enumerate_variants, load_spec
    from fleet.tlg.render.explorer import ExplorerEntry, render_explorer

    spec_paths = _collect_spec_paths(args.spec)
    named_data, default_data = _parse_data_args(args.data)

    adsl_df: pl.DataFrame | None = None
    if args.adsl:
        adsl_df = _load_dataset(args.adsl)

    entries = []
    for spec_path in spec_paths:
        spec = load_spec(spec_path)
        meta = TEMPLATES[spec.template]
        data_df, population, is_listing = _resolve_spec_frames(
            spec_path, meta, named_data, default_data, adsl_df, args.adsl
        )
        # A declared groupby axis supplies the arm column per variant —
        # only detect one when the spec leaves it fixed.
        has_groupby_axis = spec.interactive is not None and spec.interactive.groupby is not None
        groupby = (
            None if (is_listing or has_groupby_axis) else _detect_groupby(data_df, args.groupby)
        )
        n_variants = len(enumerate_variants(spec))
        print(f"{spec_path.name}: {n_variants} variant(s)")
        entries.append(
            ExplorerEntry(
                name=spec_path.stem,
                spec=spec,
                df=data_df,
                adsl=population,
                groupby=groupby,
                metadata=RenderMetadata(
                    title=args.title or meta.title,
                    subtitle=args.subtitle or "",
                    footnotes=args.footnote or [],
                ),
            )
        )

    out_path = Path(args.output)
    html = render_explorer(entries, path=out_path)
    print(f"Explorer → {out_path}  ({len(entries)} spec(s), {len(html) / 1024:.0f} KiB)")


def _run_tlg_explore(args: argparse.Namespace) -> None:
    if args.watch:
        watch_paths = _collect_spec_paths(args.spec)
        spec_arg = Path(args.spec)
        targets = [spec_arg] if spec_arg.is_dir() else watch_paths
        _watch_loop(targets, lambda: _tlg_explore_once(args))
        return
    _tlg_explore_once(args)


def _run_tlg_export(args: argparse.Namespace) -> None:
    from fleet.tlg import NAMESPACE_CLASSES, RenderMetadata

    domain: str = args.domain
    fmt: str = args.fmt

    # Load datasets
    data_df = _load_dataset(args.data)
    adsl_df = _load_dataset(args.adsl)

    # Default output filename
    output = args.output or f"{domain}_summary.{fmt}"
    output_path = Path(output)

    # Metadata (page_by flows through RenderMetadata into every renderer)
    rmeta = RenderMetadata(
        title=args.title or "",
        subtitle=args.subtitle or "",
        footnotes=args.footnote or [],
        page_by=args.page_by,
    )

    # HTML wrapper
    html_wrapper: str | None = None
    if args.wrap:
        wp = Path(args.wrap)
        if not wp.is_file():
            _fail(f"wrapper template not found: {wp}")
        html_wrapper = wp.read_text(encoding="utf-8")

    # Detect the treatment-arm column against the DATA frame (not ADSL).
    group_col = _detect_groupby(data_df, args.groupby)

    print(f"Domain:   {domain}")
    print(f"Format:   {fmt}")
    print(f"Data:     {args.data} ({data_df.shape[0]} rows)")
    print(f"ADSL:     {args.adsl} ({adsl_df.shape[0]} rows)")
    print(f"Groupby:  {group_col}")
    print(f"Output:   {output_path}")
    print()

    # Registry-driven dispatch: every TLG namespace exposes t_summary.
    ard = NAMESPACE_CLASSES[domain](data_df).t_summary(groupby=group_col, adsl=adsl_df)
    print(f"ARD:      {ard.shape[0]} rows × {ard.shape[1]} cols")

    _render_output(
        ard,
        is_listing=False,
        fmt=fmt,
        out_path=output_path,
        rmeta=rmeta,
        rows_per_page=args.rows_per_page,
        html_wrapper=html_wrapper,
    )
    print(f"{fmt.upper()} written → {output_path}")


# ────────────────────────────────────────────────────────────────────── #
# Editor / assistant servers (lsp + mcp extras)                            #
# ────────────────────────────────────────────────────────────────────── #


def _require_extra(module: str, extra: str, command: str) -> None:
    """Exit 1 with an install hint when an optional server dep is missing."""
    import importlib.util

    if importlib.util.find_spec(module) is None:
        _fail(
            f"{module} is required for `fleet {command}`. Install it with: "
            f"uv sync --extra {extra}  (or: uv pip install 'fleet-cdisc[{extra}]')"
        )


def _run_mcp(args: argparse.Namespace) -> None:
    _require_extra("mcp", "mcp", "mcp")
    from fleet.mcp_server import main as mcp_main

    mcp_main()


def _run_lsp(args: argparse.Namespace) -> None:
    _require_extra("pygls", "lsp", "lsp")
    from fleet.lsp_server import main as lsp_main

    lsp_main()


# ────────────────────────────────────────────────────────────────────── #
# Derivation scaffolding                                                  #
# ────────────────────────────────────────────────────────────────────── #


def _run_derivation_add(args: argparse.Namespace) -> None:
    """Scaffold a new derivation file under specs/<study_id>/adam/derivations/."""
    name: str = args.name.strip()
    dataset: str = args.dataset.strip().upper()
    kind: str = args.kind

    # Resolve derivations directory from the study config — no silent
    # fallback to ./derivations (siblings hard-error too).
    ctx = _load_ctx(args.config)
    derivations_dir = ctx.programs_adam_dir.parent / "derivations"

    derivations_dir.mkdir(parents=True, exist_ok=True)
    out_file = derivations_dir / f"{name}.py"

    if out_file.exists():
        _err(f"Error: file already exists: {out_file}")
        _err("Delete it manually if you want to regenerate.")
        sys.exit(1)

    if kind == "column":
        template = f'''"""{name} — {dataset} custom derivation."""
from fleet.core.derivation import derivation
import polars as pl


@derivation
def {name}() -> pl.Expr:
    """One-sentence summary of {name} derivation.

    Args:
        (none — column-kind derivations take no arguments)

    Returns:
        pl.Expr: Expression that produces the {name} column.

    Examples:
        Use in an inline pipeline::

            adsl = (
                dm.adam.adsl
                .derivation({name})
                .to_frame()
            )
    """
    return pl.col("REPLACE_ME").cast(pl.String)  # TODO: replace with real logic
'''
    elif kind == "frame":
        template = f'''"""{name} — {dataset} custom derivation (frame-level)."""
from fleet.core.derivation import derivation
import polars as pl


@derivation(targets=["{name}"])
def {name}(df: pl.DataFrame) -> pl.DataFrame:
    """One-sentence summary of {name} derivation.

    Args:
        df: Upstream DataFrame.

    Returns:
        pl.DataFrame: Frame with {name} column added.

    Examples:
        Use in an inline pipeline::

            {dataset.lower()} = (
                dm.adam.adsl
                .derivation({name})
                .to_frame()
            )
    """
    return df.with_columns(
        pl.col("REPLACE_ME").cast(pl.String).alias("{name}")  # TODO: replace with real logic
    )
'''
    else:  # param
        template = f'''"""{name} — {dataset} custom derivation (param-level)."""
from fleet.core.derivation import derivation
import polars as pl


@derivation(
    by=["USUBJID"],  # TODO: set correct by-vars
    set_values_to={{"PARAMCD": "{name}", "PARAM": "{name} description"}},
)
def {name}(df: pl.DataFrame) -> pl.DataFrame:
    """One-sentence summary of {name} derivation.

    Args:
        df: Upstream DataFrame.

    Returns:
        pl.DataFrame: Frame with {name} parameter rows added.

    Examples:
        Use in an inline pipeline::

            {dataset.lower()} = (
                dm.adam
                .derivation({name})
                .to_frame()
            )
    """
    return df.with_columns(
        pl.col("REPLACE_ME").cast(pl.Float64).alias("AVAL")  # TODO: replace with real logic
    )
'''

    out_file.write_text(template, encoding="utf-8")
    print(f"Created {out_file}")

    # Update __init__.py.
    init_file = derivations_dir / "__init__.py"
    import_line = f"from .{name} import {name}\n"
    if init_file.exists():
        existing = init_file.read_text(encoding="utf-8")
        if import_line.strip() not in existing:
            init_file.write_text(existing.rstrip("\n") + "\n" + import_line, encoding="utf-8")
    else:
        init_file.write_text(import_line, encoding="utf-8")

    print(f"Updated {init_file}")
    print()
    print(f"Next: open {out_file} and implement the derivation logic.")
    print(f"Then use it in your pipeline:  .derivation({name})")


# ────────────────────────────────────────────────────────────────────── #
# Parser                                                                  #
# ────────────────────────────────────────────────────────────────────── #


def _add_config_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help=(
            "Path to study_config.yaml. Default: discovered by walking up "
            "from the current directory (git-style)."
        ),
    )


def _add_init_parsers(sub: argparse._SubParsersAction) -> None:
    init_parser = sub.add_parser(
        "init",
        help="Bootstrapping pipeline: cfg → define → ct → rules.",
    )
    init_sub = init_parser.add_subparsers(dest="init_command", required=True)

    # -- init cfg ------------------------------------------------------- #
    cfg = init_sub.add_parser(
        "cfg",
        help="Create study_config.yaml and directory structure.",
    )
    cfg.add_argument(
        "--study-id",
        required=True,
        help="Study identifier (e.g. CDISCPILOT01).",
    )
    cfg.add_argument(
        "--company",
        default=None,
        help="Originator / company name.",
    )
    cfg.add_argument(
        "--domains",
        default=None,
        help="Comma-separated SDTM domains (e.g. DM,AE,VS,EX).",
    )
    cfg.add_argument(
        "--adam-datasets",
        default=None,
        help="Comma-separated ADaM datasets (e.g. ADSL,ADVS,ADAE).",
    )
    cfg.add_argument(
        "--ig",
        default="3-4",
        help="SDTM IG version (default: 3-4).",
    )
    cfg.add_argument(
        "--adam-ig",
        default="1-1",
        help="ADaM IG version (default: 1-1).",
    )
    cfg.add_argument(
        "--package",
        default="sdtmct-2023-12-15",
        help="CT package version (default: sdtmct-2023-12-15).",
    )
    cfg.add_argument(
        "--root",
        "-r",
        default=".",
        help="Study root directory (default: current directory).",
    )
    cfg.set_defaults(func=_run_init_cfg)

    # -- init define ---------------------------------------------------- #
    define = init_sub.add_parser(
        "define",
        help="Generate define.yaml from the CDISC Library IG.",
    )
    _add_config_flag(define)
    define.add_argument(
        "--sdtm-only",
        action="store_true",
        help="Generate SDTM define.yaml only (skip ADaM).",
    )
    define.add_argument(
        "--adam-only",
        action="store_true",
        help="Generate ADaM define.yaml only (skip SDTM).",
    )
    define.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing define.yaml files.",
    )
    define.set_defaults(func=_run_init_define)

    # -- init ct -------------------------------------------------------- #
    ct = init_sub.add_parser(
        "ct",
        help="Generate codelists.py from the define.yaml specifications.",
    )
    _add_config_flag(ct)
    ct.add_argument(
        "--no-docs",
        action="store_true",
        help="Omit definitions and preferred terms from generated code.",
    )
    ct.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing codelists.py.",
    )
    ct.set_defaults(func=_run_init_ct_pipeline)

    # -- init rules ----------------------------------------------------- #
    rules = init_sub.add_parser(
        "rules",
        help="Cache CDISC conformance rules as YAML from the CDISC Library.",
    )
    _add_config_flag(rules)
    rules.add_argument(
        "--sdtm-only",
        action="store_true",
        help="Fetch SDTM rules only (skip ADaM).",
    )
    rules.add_argument(
        "--adam-only",
        action="store_true",
        help="Fetch ADaM rules only (skip SDTM).",
    )
    rules.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing rule files.",
    )
    rules.set_defaults(func=_run_init_rules)


def _add_ct_parsers(sub: argparse._SubParsersAction) -> None:
    # -- init-ct (standalone, deprecated) -------------------------------- #
    init_ct = sub.add_parser(
        "init-ct",
        help=(
            "[deprecated] Bootstrap a codelists.py directly from the SDTM IG. "
            "Prefer the pipeline: fleet init cfg → init define → init ct."
        ),
    )
    init_ct.add_argument(
        "--domains",
        required=True,
        help="Comma-separated SDTM domain abbreviations (e.g. DM,AE,VS,EX).",
    )
    init_ct.add_argument(
        "--ig",
        default="3-4",
        help="SDTM IG version (default: 3-4).",
    )
    init_ct.add_argument(
        "--package",
        default="sdtmct-2023-12-15",
        help="CT package version (default: sdtmct-2023-12-15).",
    )
    init_ct.add_argument(
        "--output",
        "-o",
        default="codelists.py",
        help="Output file path (default: codelists.py).",
    )
    init_ct.add_argument(
        "--no-docs",
        action="store_true",
        help="Omit definitions and preferred terms from generated code.",
    )
    init_ct.set_defaults(func=_run_init_ct)

    # -- add-ct ---------------------------------------------------------- #
    add = sub.add_parser(
        "add-ct",
        help="Add domains to an existing codelists.py (preserves existing).",
    )
    add.add_argument(
        "--domains",
        required=True,
        help="Comma-separated SDTM domain abbreviations to add.",
    )
    add.add_argument(
        "--ig",
        default="3-4",
        help="SDTM IG version (default: 3-4).",
    )
    add.add_argument(
        "--package",
        default="sdtmct-2023-12-15",
        help="CT package version (default: sdtmct-2023-12-15).",
    )
    add.add_argument(
        "--output",
        "-o",
        default="codelists.py",
        help="Path to the existing codelists.py (default: codelists.py).",
    )
    add.add_argument(
        "--no-docs",
        action="store_true",
        help="Omit definitions and preferred terms from generated code.",
    )
    add.set_defaults(func=_run_add_ct)


def _add_rule_parsers(sub: argparse._SubParsersAction) -> None:
    # -- add-rule -------------------------------------------------------- #
    add_rule = sub.add_parser(
        "add-rule",
        help="Scaffold a new custom validation rule YAML.",
    )
    add_rule.add_argument(
        "--domain",
        required=True,
        help="SDTM/ADaM domain code (e.g. AE, DM, VS).",
    )
    add_rule.add_argument(
        "--description",
        required=True,
        help="Human-readable description of the rule.",
    )
    add_rule.add_argument(
        "--prefix",
        default="FLEET",
        help="Rule ID prefix (default: FLEET).",
    )
    add_rule.add_argument(
        "--id",
        default=None,
        dest="rule_id",
        help="Explicit rule ID (e.g. ROCHE-AE-042). Skips auto-increment.",
    )
    add_rule.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory for the rule YAML. Defaults to validation.custom_rules from study_config.yaml.",
    )
    _add_config_flag(add_rule)
    add_rule.set_defaults(func=_run_add_rule)

    # -- check-rule ------------------------------------------------------ #
    check_rule_parser = sub.add_parser(
        "check-rule",
        help="Validate a custom rule YAML (syntax, structure, schema).",
    )
    check_rule_parser.add_argument(
        "rule_file",
        help="Path to the custom rule YAML file to validate.",
    )
    check_rule_parser.set_defaults(func=_run_check_rule)


def _add_define_xml_parser(sub: argparse._SubParsersAction) -> None:
    defxml = sub.add_parser(
        "define-xml",
        help="Generate Define-XML 2.1 from a define.yaml specification.",
    )
    defxml.add_argument(
        "--spec",
        "-s",
        required=True,
        help="Path to the define.yaml specification file.",
    )
    defxml.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output path for the Define-XML file (e.g. outputs/define_sdtm.xml).",
    )
    defxml.add_argument(
        "--no-preview",
        action="store_true",
        help="Skip generating the HTML preview alongside the XML.",
    )
    defxml.add_argument(
        "--enrich-methods",
        action="store_true",
        help=(
            "Embed Python verb / callable docstrings into Define-XML "
            "Origin descriptions and emit MethodDef elements with "
            "FormalExpression. Creates a verifiable link between the "
            "regulatory submission and the exact code that produced the data."
        ),
    )
    defxml.add_argument(
        "--watch",
        action="store_true",
        help="Re-generate whenever the spec file changes (requires the 'watch' extra).",
    )
    defxml.set_defaults(func=_run_define_xml)


def _add_engine_parsers(sub: argparse._SubParsersAction) -> None:
    inst = sub.add_parser(
        "install-engine",
        help="Download the CDISC Rules Engine binary for validation.",
    )
    inst.add_argument(
        "--version",
        default="latest",
        help="Release tag to download (default: latest).",
    )
    inst.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already installed.",
    )
    inst.set_defaults(func=_run_install_engine)

    uninst = sub.add_parser(
        "uninstall-engine",
        help="Remove the managed CDISC Rules Engine binary.",
    )
    uninst.set_defaults(func=_run_uninstall_engine)

    doctor = sub.add_parser(
        "doctor",
        help="Check Fleet setup: engine, API key, optional extras.",
    )
    _add_config_flag(doctor)
    doctor.set_defaults(func=_run_doctor)


def _add_exec_parsers(sub: argparse._SubParsersAction) -> None:
    # -- run -------------------------------------------------------------- #
    run = sub.add_parser(
        "run",
        help="Execute define.yaml derivation pipelines and write datasets.",
    )
    run.add_argument(
        "--dataset",
        action="append",
        default=None,
        metavar="NAME",
        help="Dataset to build (repeatable). Default: every dataset in the define files.",
    )
    _add_config_flag(run)
    run.add_argument(
        "--out",
        "--output",
        "-o",
        dest="out",
        default=None,
        help=(
            "Output directory for every dataset. Default: the configured "
            "data/sdtm and data/adam directories."
        ),
    )
    run.add_argument(
        "--format",
        default="parquet",
        choices=["parquet", "xpt", "dataset-json"],
        help="Output format (default: parquet).",
    )
    run.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Raise on unknown spec algorithms (default). --no-strict warns and skips.",
    )
    run.set_defaults(func=_run_run)

    # -- validate ---------------------------------------------------------- #
    validate = sub.add_parser(
        "validate",
        help="Validate datasets with the CDISC Rules Engine (exit 1 on errors).",
    )
    validate.add_argument(
        "paths",
        nargs="+",
        help="Dataset files or directories (parquet / csv / xpt / sas7bdat).",
    )
    validate.add_argument(
        "--standard",
        choices=["sdtm", "adam"],
        default=None,
        help="Force the standard. Default: AD* datasets → adam, others → sdtm.",
    )
    validate.add_argument(
        "--version",
        dest="standard_version",
        default=None,
        help="IG version (default: 3.4 for SDTM, 1.3 for ADaM).",
    )
    validate.add_argument(
        "--custom-rules",
        default=None,
        help="Directory of custom validation rule YAML files.",
    )
    validate.add_argument(
        "--report",
        default=None,
        metavar="PATH",
        help="Write an HTML findings report to PATH.",
    )
    validate.set_defaults(func=_run_validate)

    # -- check -------------------------------------------------------------- #
    check = sub.add_parser(
        "check",
        help="CI gate: config parse + define.yaml schema + custom-rule YAMLs.",
    )
    _add_config_flag(check)
    check.set_defaults(func=_run_check)

    # -- new ---------------------------------------------------------------- #
    new = sub.add_parser(
        "new",
        help="Bootstrap a study: init cfg → define → ct → rules, one confirmation.",
    )
    new.add_argument(
        "study_id",
        help="Study identifier (e.g. STUDY01).",
    )
    new.add_argument(
        "--domains",
        default=None,
        help="Comma-separated SDTM domains (e.g. DM,AE,VS,EX).",
    )
    new.add_argument(
        "--adam-datasets",
        default=None,
        help="Comma-separated ADaM datasets (e.g. ADSL,ADVS,ADAE).",
    )
    new.add_argument(
        "--company",
        default=None,
        help="Originator / company name.",
    )
    new.add_argument(
        "--ig",
        default="3-4",
        help="SDTM IG version (default: 3-4).",
    )
    new.add_argument(
        "--adam-ig",
        default="1-1",
        help="ADaM IG version (default: 1-1).",
    )
    new.add_argument(
        "--package",
        default="sdtmct-2023-12-15",
        help="CT package version (default: sdtmct-2023-12-15).",
    )
    new.add_argument(
        "--root",
        "-r",
        default=".",
        help="Study root directory (default: current directory).",
    )
    new.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    new.set_defaults(func=_run_new)

    # -- migrate ------------------------------------------------------------- #
    migrate = sub.add_parser(
        "migrate",
        help="Rewrite removed pre-alpha verb/kwarg spellings to canonical ones (libcst).",
    )
    migrate.add_argument(
        "files",
        nargs="+",
        help="Python files or directories to migrate.",
    )
    migrate.add_argument(
        "--write",
        action="store_true",
        help="Rewrite files in place (default: print a unified diff).",
    )
    migrate.set_defaults(func=_run_migrate)


def _tlg_domain_choices() -> list[str]:
    """TLG sub-namespaces available for ``tlg export`` (from the registry)."""
    from fleet.tlg import NAMESPACE_CLASSES

    return sorted(NAMESPACE_CLASSES)


def _add_tlg_parsers(sub: argparse._SubParsersAction) -> None:
    tlg = sub.add_parser(
        "tlg",
        help="TLG workflow: list templates, run/explore YAML specs, export summaries.",
    )
    tlg_sub = tlg.add_subparsers(dest="tlg_command", required=True)

    # -- tlg list ---------------------------------------------------------- #
    tlg_list = tlg_sub.add_parser(
        "list",
        help="List every registered TLG template (from fleet.tlg.catalog()).",
    )
    tlg_list.set_defaults(func=_run_tlg_list)

    # -- tlg schema -------------------------------------------------------- #
    tlg_schema = tlg_sub.add_parser(
        "schema",
        help="Print a template's spec JSON Schema to stdout (editor validation).",
    )
    tlg_schema.add_argument(
        "template_id",
        help="Registry template id (e.g. aet01). See `fleet tlg list`.",
    )
    tlg_schema.set_defaults(func=_run_tlg_schema)

    # -- tlg run ------------------------------------------------------------ #
    tlg_run = tlg_sub.add_parser(
        "run",
        help="Execute YAML TLG spec(s) against datasets and render outputs.",
    )
    tlg_run.add_argument(
        "spec",
        help="A spec .yaml file or a directory of spec files.",
    )
    tlg_run.add_argument(
        "--data",
        action="append",
        default=None,
        metavar="[NAME=]PATH",
        help=(
            "Analysis dataset path, repeatable. Plain PATH applies to every "
            "spec; NAME=PATH (e.g. ADAE=adae.parquet) targets the template's "
            "analysis domain."
        ),
    )
    tlg_run.add_argument(
        "--adsl",
        default=None,
        help="ADSL dataset path (population denominators for tables).",
    )
    tlg_run.add_argument(
        "--output",
        "-o",
        default=".",
        help="Output directory (default: current directory).",
    )
    tlg_run.add_argument(
        "--format",
        dest="fmt",
        default="html",
        choices=["html", "rtf", "pdf", "pptx"],
        help="Output format (default: html).",
    )
    tlg_run.add_argument(
        "--groupby",
        default=None,
        help="Treatment-arm column. Default: auto-detect (TRTA → TRT01A → TRT01P).",
    )
    tlg_run.add_argument("--title", default="", help="Output title (default: template title).")
    tlg_run.add_argument("--subtitle", default="", help="Output subtitle.")
    tlg_run.add_argument(
        "--footnote",
        action="append",
        default=None,
        help="Footnote (repeatable).",
    )
    tlg_run.add_argument(
        "--rows-per-page",
        type=int,
        default=None,
        help="Maximum body rows per page (model-layer pagination).",
    )
    tlg_run.add_argument(
        "--page-by",
        default=None,
        help="ARD variable to page-break on (e.g. PARAMCD).",
    )
    tlg_run.add_argument(
        "--watch",
        action="store_true",
        help="Re-run whenever a spec file changes (requires the 'watch' extra).",
    )
    tlg_run.set_defaults(func=_run_tlg_run)

    # -- tlg explore --------------------------------------------------------- #
    tlg_explore = tlg_sub.add_parser(
        "explore",
        help=(
            "Render the interactive variant space of YAML spec(s) into one "
            "self-contained HTML explorer (no server; the default variant is "
            "byte-identical to `tlg run`'s output)."
        ),
    )
    tlg_explore.add_argument(
        "spec",
        help="A spec .yaml file or a directory of spec files.",
    )
    tlg_explore.add_argument(
        "--data",
        action="append",
        default=None,
        metavar="[NAME=]PATH",
        help=(
            "Analysis dataset path, repeatable. Plain PATH applies to every "
            "spec; NAME=PATH (e.g. ADAE=adae.parquet) targets the template's "
            "analysis domain."
        ),
    )
    tlg_explore.add_argument(
        "--adsl",
        default=None,
        help="ADSL dataset path (population denominators for tables).",
    )
    tlg_explore.add_argument(
        "--output",
        "-o",
        default="explorer.html",
        help="Output HTML file (default: explorer.html).",
    )
    tlg_explore.add_argument(
        "--groupby",
        default=None,
        help=(
            "Treatment-arm column for specs without a groupby axis. "
            "Default: auto-detect (TRTA → TRT01A → TRT01P)."
        ),
    )
    tlg_explore.add_argument("--title", default="", help="Output title (default: template title).")
    tlg_explore.add_argument("--subtitle", default="", help="Output subtitle.")
    tlg_explore.add_argument(
        "--footnote",
        action="append",
        default=None,
        help="Footnote (repeatable).",
    )
    tlg_explore.add_argument(
        "--watch",
        action="store_true",
        help="Rebuild whenever a spec file changes (requires the 'watch' extra).",
    )
    tlg_explore.set_defaults(func=_run_tlg_explore)

    # -- tlg export ---------------------------------------------------------- #
    tlg_export = tlg_sub.add_parser(
        "export",
        help="Render a domain summary (t_summary) to HTML, RTF, PDF, or slides.",
    )
    tlg_export.add_argument(
        "--domain",
        required=True,
        choices=_tlg_domain_choices(),
        help="TLG sub-namespace to summarise.",
    )
    tlg_export.add_argument(
        "--format",
        dest="fmt",
        default="html",
        choices=["html", "rtf", "pdf", "pptx"],
        help="Output format (default: html).",
    )
    tlg_export.add_argument(
        "--data",
        required=True,
        help="Path to the primary analysis dataset (CSV or Parquet).",
    )
    tlg_export.add_argument(
        "--adsl",
        required=True,
        help="Path to the ADSL dataset (CSV or Parquet).",
    )
    tlg_export.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file path.  Defaults to <domain>_summary.<format>.",
    )
    tlg_export.add_argument(
        "--groupby",
        default=None,
        help="Treatment-arm column. Default: auto-detect (TRTA → TRT01A → TRT01P).",
    )
    tlg_export.add_argument(
        "--title",
        default="",
        help="Table title.",
    )
    tlg_export.add_argument(
        "--subtitle",
        default="",
        help="Table subtitle.",
    )
    tlg_export.add_argument(
        "--footnote",
        action="append",
        default=None,
        help="Footnote (repeatable).",
    )
    tlg_export.add_argument(
        "--rows-per-page",
        type=int,
        default=None,
        help="Maximum body rows per page (model-layer pagination).",
    )
    tlg_export.add_argument(
        "--page-by",
        default=None,
        help="ARD variable to page-break on (e.g. PARAMCD).",
    )
    tlg_export.add_argument(
        "--wrap",
        default=None,
        help="Path to an HTML wrapper template with {table} placeholder.",
    )
    tlg_export.set_defaults(func=_run_tlg_export)


def _add_server_parsers(sub: argparse._SubParsersAction) -> None:
    mcp = sub.add_parser(
        "mcp",
        help="Serve Fleet tools to MCP-capable assistants (requires the 'mcp' extra).",
    )
    mcp.add_argument(
        "--stdio",
        action="store_true",
        help="Serve over stdio (the only supported transport; accepted for explicitness).",
    )
    mcp.set_defaults(func=_run_mcp)

    lsp = sub.add_parser(
        "lsp",
        help="Language server for define.yaml files (requires the 'lsp' extra).",
    )
    lsp.add_argument(
        "--stdio",
        action="store_true",
        help="Serve over stdio (the only supported transport; accepted for explicitness).",
    )
    lsp.set_defaults(func=_run_lsp)


def _add_derivation_parsers(sub: argparse._SubParsersAction) -> None:
    drv_parser = sub.add_parser(
        "derivation",
        help="Scaffold and manage study-specific derivations.",
    )
    drv_sub = drv_parser.add_subparsers(dest="derivation_command", required=True)

    drv_add = drv_sub.add_parser(
        "add",
        help="Scaffold a new derivation file under specs/<study>/adam/derivations/.",
    )
    drv_add.add_argument(
        "name",
        help="Variable name to create (e.g. AGEGR1).",
    )
    drv_add.add_argument(
        "--dataset",
        default="ADSL",
        help="Target dataset name (default: ADSL).",
    )
    drv_add.add_argument(
        "--kind",
        default="column",
        choices=["column", "frame", "param"],
        help="Derivation kind: column / frame / param (default: column).",
    )
    _add_config_flag(drv_add)
    drv_add.set_defaults(func=_run_derivation_add)


def _build_parser() -> argparse.ArgumentParser:
    from fleet._version import __version__

    parser = argparse.ArgumentParser(
        prog="fleet",
        description="Fleet — CDISC SDTM/ADaM derivation toolkit CLI.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"fleet {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    _add_init_parsers(sub)
    _add_exec_parsers(sub)
    _add_tlg_parsers(sub)
    _add_define_xml_parser(sub)
    _add_ct_parsers(sub)
    _add_rule_parsers(sub)
    _add_engine_parsers(sub)
    _add_derivation_parsers(sub)
    _add_server_parsers(sub)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``); injectable
            for tests.

    Raises:
        SystemExit: ``0`` on success, ``1`` on any Fleet error (single
            clean message on stderr), ``2`` on argparse usage errors.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    from fleet.core.exceptions import FleetError
    from fleet.core.study_context import StudyConfigError

    try:
        args.func(args)
    except KeyboardInterrupt:
        _err("Interrupted.")
        sys.exit(1)
    except (FleetError, StudyConfigError) as exc:
        _fail(str(exc))
    except ImportError as exc:
        # Optional-dependency errors carry their own install hint —
        # surface it as one clean line instead of a traceback.
        _fail(" ".join(str(exc).split()))


if __name__ == "__main__":
    main()
