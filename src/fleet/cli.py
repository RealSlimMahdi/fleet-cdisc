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
- ``fleet compare``  — compare a candidate dataset against a base on keys.
- ``fleet check``    — one CI gate: config + define schema + codelists.py + rule YAMLs.
- ``fleet tlg``      — list / run / export TLG templates (``tlg --help``).
- ``fleet migrate``  — rewrite removed pre-alpha verb spellings to canonical ones.
- ``fleet mcp``      — MCP server for AI assistants (``mcp`` extra).
- ``fleet lsp``      — define.yaml language server (``lsp`` extra).

Every command that needs ``study_config.yaml`` discovers it git-style: the
current directory first, then each parent.  Pass ``--config`` to override.

Errors print a single clean message to **stderr** and exit ``1``; missing
or unknown (sub)commands print usage to stderr and exit ``2``.  ``fleet
compare`` is the one command whose exit code is a verdict: ``0`` equal,
``1`` different, ``2`` the comparison could not run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import keyword
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, get_args, get_type_hints

from fleet.core.define_spec import load_spec_yaml
from fleet.core.study_context import find_study_config
from fleet.run import find_dataset_file

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import polars as pl

    from fleet.core.define_spec import DatasetEntry, DefineSpec
    from fleet.core.study_context import StudyContext

#: Optional-dependency probes for ``fleet doctor`` / ``fleet check``:
#: the dotted module a feature imports → (extra name, what it enables).
#: Probing the dotted path, not the distribution, is what catches a
#: distribution that is installed but too old to expose the API.
_OPTIONAL_EXTRAS: dict[str, tuple[str, str]] = {
    "weasyprint": ("tlg-pdf", "PDF rendering"),
    "pptx": ("tlg-pptx", "PPTX slide rendering"),
    "pyreadstat": ("io", "SAS XPT read/write"),
    "libcst": ("migrate", "fleet migrate codemod"),
    "watchfiles": ("watch", "--watch mode"),
    "pygls.lsp.server": ("lsp", "fleet lsp language server"),
    "mcp.server.fastmcp": ("mcp", "fleet mcp server"),
}


# ────────────────────────────────────────────────────────────────────── #
# Output helpers                                                          #
# ────────────────────────────────────────────────────────────────────── #


def _err(msg: str) -> None:
    """Print *msg* to stderr."""
    print(msg, file=sys.stderr)


def _fail(msg: str, *, code: int = 1) -> NoReturn:
    """Print an error to stderr and exit — ``1`` unless *code* says otherwise."""
    _err(f"Error: {msg}")
    sys.exit(code)


# ────────────────────────────────────────────────────────────────────── #
# Config discovery                                                        #
# ────────────────────────────────────────────────────────────────────── #


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


def _try_ctx(config_arg: str | None = None) -> StudyContext | None:
    """Best-effort study context — ``None`` when no config is discoverable.

    For commands that also work standalone on explicit paths: inside a
    study workspace they resolve defaults from the config, outside one
    they fall back to their explicit arguments.
    """
    cfg = Path(config_arg) if config_arg else find_study_config()
    if cfg is None or not cfg.is_file():
        return None
    from fleet.core.study_context import StudyConfigError, load_study_context

    try:
        return load_study_context(cfg)
    except StudyConfigError:
        return None


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


def _default_ig(standard: str) -> str:
    """The built-in IG version for *standard*, in the config's dashed form."""
    from fleet.validation.run_setup import DEFAULT_IG_VERSIONS

    return DEFAULT_IG_VERSIONS[standard].replace(".", "-")


def _load_dataset(path_str: str, encoding: str | None = None) -> pl.DataFrame:
    """Load a dataset file (CSV / Parquet / XPT / SAS) as a DataFrame."""
    from fleet.io import load_raw_data

    p = Path(path_str)
    if not p.is_file():
        _fail(f"file not found: {p}")
    return load_raw_data(p, **_encoding_option(p, encoding)).collect()


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
    from fleet.tlg import GROUPBY_CANDIDATES, detect_groupby

    detected = detect_groupby(df.columns)
    if detected is not None:
        return detected
    _fail(
        "could not auto-detect a treatment-arm column "
        f"(tried {', '.join(GROUPBY_CANDIDATES)}). Pass --groupby <column>. "
        f"Columns present in the data: {', '.join(df.columns)}"
    )
    raise AssertionError("unreachable")


def _spec_groupby(spec: Any, df: pl.DataFrame, explicit: str | None) -> str | None:
    """Resolve a spec run's arm column: --groupby, the spec's columns:, detection."""
    from fleet.tlg import resolve_groupby

    if explicit:
        return _detect_groupby(df, explicit)
    groupby, source = resolve_groupby(spec, df.columns)
    if source == "none":
        return _detect_groupby(df, None)
    return groupby


def _with_adsl_groupby(spec: Any, adsl_groupby: str | None) -> Any:
    """Apply ``--adsl-groupby`` to a summary spec (listings have no big N)."""
    if adsl_groupby and "adsl_group_col" in type(spec).model_fields:
        return spec.model_copy(update={"adsl_group_col": adsl_groupby})
    return spec


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
        DEFAULT_ADAM_CT,
        DEFAULT_SDTM_CT,
        ADAMConfig,
        CTConfig,
        SDTMConfig,
        StudyContext,
        ValidationConfig,
    )

    study_root = Path(args.root).resolve()
    domains = _parse_domains(args.domains) if args.domains else []
    adam_datasets = _parse_domains(args.adam_datasets) if args.adam_datasets else []
    adam_package = args.adam_package
    if adam_datasets and adam_package is None:
        if args.package != DEFAULT_SDTM_CT:
            _fail(
                f"--package {args.package} with ADaM datasets needs --adam-package: CDISC "
                "publishes ADaM CT on its own dates. Give the latest ADaM CT package on or "
                f"before {args.package.split('-', 1)[-1]} (for example --adam-package "
                f"{DEFAULT_ADAM_CT} goes with {DEFAULT_SDTM_CT})."
            )
        adam_package = DEFAULT_ADAM_CT

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
        description=args.description or "",
        sdtm=SDTMConfig(ig_version=args.ig, domains=domains),
        adam=ADAMConfig(ig_version=args.adam_ig, datasets=adam_datasets),
        ct=CTConfig(package=args.package, adam_package=adam_package),
        validation=ValidationConfig(custom_rules="metadata/custom_rules"),
    )
    config_path = ctx.study_root / "study_config.yaml"
    hint = _config_flag_hint(config_path)
    print(f"Created study workspace → {ctx.study_root}")
    print(f"Config  → {config_path}")
    if ctx.custom_rules_dir is not None and adam_datasets:
        from fleet.validation.rule_scaffolder import scaffold_population_flag_rule

        try:
            rule_file = scaffold_population_flag_rule(ctx.custom_rules_dir)
            print(f"Rule    → {rule_file} (ADSL population flags are Y or N)")
        except FileExistsError:
            pass
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
    adam_ct = cfg.ct.adam_package
    adam_ct_version = adam_ct.split("-", 1)[-1] if adam_ct and "-" in adam_ct else None

    with CDISCClient() as client:
        scaffolder = DefineScaffolder(client)

        force = getattr(args, "force", False)
        written: list[Path] = []

        if do_sdtm:
            sdtm_path = ctx.metadata_sdtm_dir / "define.yaml"
            if sdtm_path.exists() and not force:
                print(f"Warning: {sdtm_path} already exists — skipping (use --force to overwrite).")
            else:
                dest = scaffolder.scaffold_sdtm(
                    study_id=cfg.study_id,
                    company=cfg.company or "",
                    description=cfg.description,
                    ig_version=cfg.sdtm.ig_version or _default_ig("sdtm"),
                    ct_version=ct_version,
                    domains=cfg.sdtm.domains,
                    output_path=sdtm_path,
                )
                written.append(dest)
                print(f"SDTM define → {dest}")

        if do_adam:
            adam_path = ctx.metadata_adam_dir / "define.yaml"
            if adam_path.exists() and not force:
                print(f"Warning: {adam_path} already exists — skipping (use --force to overwrite).")
            else:
                dest = scaffolder.scaffold_adam(
                    study_id=cfg.study_id,
                    company=cfg.company or "",
                    description=cfg.description,
                    ig_version=cfg.adam.ig_version or _default_ig("adam"),
                    ct_version=ct_version,
                    adam_ct_version=adam_ct_version,
                    datasets=cfg.adam.datasets,
                    output_path=adam_path,
                )
                written.append(dest)
                print(f"ADaM define → {dest}")

    hint = _config_flag_hint(ctx.study_root / "study_config.yaml")
    print()
    _print_schema_optin(written)
    print(f"Next step: fleet init ct{hint}")


def _print_schema_optin(specs: list[Path]) -> None:
    """Offer the `$schema` directive to editors without the Fleet extension.

    Scaffolded specs no longer carry it (#71): `fleet lsp` reads the schema
    from the installed package, so a second validator double-reports.
    """
    if not specs:
        return
    from fleet.core.scaffolder import schema_directive

    print("`fleet lsp` validates these against the installed schema already.")
    print("Without the Fleet extension, paste this at the top of each spec:")
    for spec in specs:
        print(f"  {spec}:\n    {schema_directive(spec)}")
    print()


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
    from fleet.core.exceptions import CTError
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
        try:
            gen = CodelistGenerator.from_concept_ids(
                client,
                all_ids,
                package=cfg.ct.package,
                adam_package=cfg.ct.adam_package,
                include_docs=not args.no_docs,
            )
        except CTError as exc:
            _fail(str(exc))
        dest = gen.write(output)

    print(f"Generated {gen.codelist_count} codelists ({', '.join(cfg.ct.pins)}) → {dest}")
    from fleet.ct.study_codelists import ct_version_problems

    for problem in ct_version_problems(ctx):
        print(f"Note: {problem}")
    terms = gen.define_terms()
    for dpath in (sdtm_define, adam_define):
        if dpath.is_file():
            filled = _write_define_terms(dpath, terms, force=force)
            if filled:
                print(f"Wrote the terms of {filled} codelist(s) into {dpath}")

    print()
    print("Bootstrap complete! Next steps:")
    print(
        "  - Spec-driven:  codelists are already referenced in define.yaml — start writing derivations."
    )
    print("  - Inline code:  from fleet.ct import import_codelists; ct = import_codelists()")
    print("                  or: import_codelists(); from codelists import SEX, RACE, ...")
    print("  - When ready:   fleet run   (or: fleet define-xml --spec <define.yaml>)")


def _write_define_terms(path: Path, terms: dict[str, dict], *, force: bool) -> int:
    """Write downloaded terms into the ``codelists:`` entries of a define.yaml; return the count.

    An entry that already has terms is kept unless *force*.  The file is
    rewritten through YAML, so only its header comment survives.
    """
    from itertools import takewhile

    import yaml

    text = path.read_text(encoding="utf-8")
    spec = yaml.safe_load(text) or {}
    filled = 0
    for entry in spec.get("codelists") or []:
        found = terms.get(str(entry.get("oid")))
        if found is None or (entry.get("items") and not force):
            continue
        entry["name"] = found["name"]
        entry["items"] = found["items"]
        filled += 1
    if filled:
        lines = text.splitlines(keepends=True)
        header = list(takewhile(lambda line: line.startswith("#") or not line.strip(), lines))
        if any(line.lstrip().startswith("#") for line in lines[len(header) :]):
            print(f"Note: {path} is rewritten; comments after its header are not kept.")
        body = yaml.dump(
            spec, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120
        )
        path.write_text("".join(header) + body, encoding="utf-8")
    return filled


# ────────────────────────────────────────────────────────────────────── #
# Standalone CT commands                                                  #
# ────────────────────────────────────────────────────────────────────── #


def _run_add_ct(args: argparse.Namespace) -> None:
    from fleet.ct.api import CDISCClient
    from fleet.ct.generator import (
        CodelistGenerator,
        existing_concept_ids,
        extract_ig_concept_ids,
    )

    domains = _parse_domains(args.domains)
    ctx = _try_ctx()
    output = (
        Path(args.output) if args.output else (ctx.codelists_file if ctx else Path("codelists.py"))
    )
    # Version resolution mirrors every other command: explicit flag, then the
    # discovered study config, then the hard default. Regenerating existing
    # codelists against a different CT package than the study pins would
    # silently change already-reviewed terms.
    ig = args.ig or (ctx.config.sdtm.ig_version if ctx else None) or _default_ig("sdtm")
    package = args.package or (ctx.config.ct.package if ctx else "sdtmct-2023-12-15")
    if args.package and output.is_file():
        from fleet.ct.study_codelists import load_codelists

        current = load_codelists(output)[0]
        if current and args.package not in current:
            _fail(
                f"{output} was generated from {', '.join(current)}, not {args.package}; "
                "fleet add-ct does not change the CT package of existing codelists. "
                "Set ct.package in study_config.yaml, then run: fleet init ct --force, "
                "and set study.ct_version in each define.yaml to the package date"
            )
    existing = existing_concept_ids(output)

    print(f"Adding domains: {', '.join(domains)}")
    print(f"Existing file:  {output} ({len(existing)} codelists)")
    print(f"IG / package:   {ig} / {package}")
    print()

    with CDISCClient() as client:
        new_ids = extract_ig_concept_ids(client, ig, domains)
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
            package=package,
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

        with open(rule_path, encoding="utf-8") as f:
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
    results: list[tuple[str, bool, str]] = []
    for module, (extra, purpose) in _OPTIONAL_EXTRAS.items():
        installed = _module_available(module)
        hint = f"{purpose} — install with: uv sync --extra {extra}"
        results.append((module.split(".")[0], installed, hint))
    return results


def _print_codelists_status(config_path: Path) -> None:
    """The doctor line of the study's codelists.py: its CT package, or each problem."""
    from fleet.core.exceptions import SpecError
    from fleet.core.study_context import StudyConfigError, load_study_context
    from fleet.ct.study_codelists import check_codelists, load_codelists

    try:
        ctx = load_study_context(config_path)
    except StudyConfigError:
        return  # fleet check reports the invalid config
    try:
        problems = check_codelists(ctx)
        packages = load_codelists(ctx.codelists_file)[0] if ctx.codelists_file.is_file() else ()
    except SpecError as exc:
        print(f"  ✗ codelists.py ....... {exc}")
        return
    for problem in problems:
        print(f"  ✗ codelists.py ....... {problem}")
    if problems or not ctx.codelists_file.is_file():
        return
    if not packages:
        print(f"  ✓ codelists.py ....... {ctx.codelists_file} (no CT package recorded)")
    else:
        print(f"  ✓ codelists.py ....... {', '.join(packages)} (matches study_config)")


def _run_doctor(args: argparse.Namespace) -> None:
    from fleet.core.exceptions import ValidationSetupError
    from fleet.validation import build_run_setup
    from fleet.validation.engine import discover_engine, doctor

    config_path = Path(args.config) if getattr(args, "config", None) else find_study_config()

    print("Fleet Doctor")
    print("=" * 52)

    if config_path and config_path.is_file():
        print(f"  ✓ study config ....... {config_path}")
        _print_codelists_status(config_path)
    else:
        print("  ✗ study config ....... not found (run `fleet init cfg`)")

    # A run setup with no datasets: the standard only fills the record.
    try:
        setup = build_run_setup(standard="sdtm", config=config_path)
        engine, where = setup.engine.value, f" ({setup.engine.source})"
    except ValidationSetupError as exc:
        print(f"  ✗ run setup .......... {exc}")
        study_root = config_path.parent if config_path and config_path.is_file() else None
        engine, where = discover_engine(study_root), ""

    if engine is None:
        print("  ✗ rules engine ....... NOT FOUND — run `fleet install-engine`")
    else:
        checks = doctor(engine=engine)
        print(f"  ✓ rules engine ....... {engine}{where}")
        print(f"      version: {checks['version']}")
        print(f"      type: {checks['type']}")
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

    gen = DefineSpecGenerator(str(spec), strict=getattr(args, "strict", False))
    gen.generate(str(output), html_preview=not args.no_preview)
    print(f"Generated Define-XML → {output}")
    ctx = _try_ctx(getattr(args, "config", None))
    if ctx is not None and getattr(args, "standard", None) in ("sdtm", "adam"):
        data_dir = ctx.data_dir(args.standard)
        absent = [href for href in gen.leaf_hrefs().values() if not (data_dir / href).is_file()]
        if absent:
            _err(
                f"warning: no file in {data_dir} for leaf href(s) {', '.join(absent)}. "
                "Run fleet run, or check output_format: and output: in define.yaml."
            )
    if not args.no_preview:
        # The generator skips the preview (with its own message) when the
        # XSL stylesheet is unavailable — only report a file that exists.
        preview = output.with_name(output.stem + "_preview.html")
        if preview.is_file():
            print(f"HTML preview → {preview}")


def _run_add_acrf(args: argparse.Namespace) -> None:
    import yaml

    ctx = _load_ctx(args.config)
    standards = ["sdtm", "adam"] if args.standard == "both" else [args.standard]
    touched = 0
    for std in standards:
        meta_dir = ctx.metadata_adam_dir if std == "adam" else ctx.metadata_sdtm_dir
        spec_path = meta_dir / "define.yaml"
        if not spec_path.is_file():
            print(f"  {std}: no define.yaml at {spec_path} — skipped")
            continue
        text = spec_path.read_text(encoding="utf-8")
        # Preserve the leading comment header (e.g. the yaml-language-server
        # schema hint) — yaml round-trips drop comments.
        header: list[str] = []
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                header.append(line)
            else:
                break
        data = load_spec_yaml(text) or {}
        acrf = (
            data.setdefault("study", {}).setdefault("documents", {}).setdefault("annotated_crf", {})
        )
        acrf["href"] = args.href
        if args.title:
            acrf["title"] = args.title
        acrf.setdefault("title", "Annotated Case Report Form")
        if args.page_map:
            acrf["page_map"] = args.page_map
        body = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
        prefix = "\n".join(header) + "\n" if header else ""
        spec_path.write_text(prefix + body, encoding="utf-8")
        print(f"  {std}: annotated_crf ({args.href}) → {spec_path}")
        touched += 1
    if not touched:
        _fail("no define.yaml found to update. Run `fleet init define` first.")


def _run_define_xml(args: argparse.Namespace) -> None:
    # Explicit --spec/--output win; otherwise resolve via study_config.yaml.
    if args.spec is None or args.output is None:
        ctx = _load_ctx(args.config)
        if args.spec is None:
            meta_dir = ctx.metadata_adam_dir if args.standard == "adam" else ctx.metadata_sdtm_dir
            args.spec = str(meta_dir / "define.yaml")
        if args.output is None:
            args.output = str(ctx.define_xml_dir / f"define_{args.standard}.xml")

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


#: SDTMIG 3.4 SUPPQUAL variable labels, for a SUPP dataset that no define declares.
_SUPP_LABELS = {
    "STUDYID": "Study Identifier",
    "RDOMAIN": "Related Domain Abbreviation",
    "USUBJID": "Unique Subject Identifier",
    "IDVAR": "Identifying Variable",
    "IDVARVAL": "Identifying Variable Value",
    "QNAM": "Qualifier Variable Name",
    "QLABEL": "Qualifier Variable Label",
    "QVAL": "Data Value",
    "QORIG": "Origin",
    "QEVAL": "Evaluator",
}


def _run_run(args: argparse.Namespace) -> None:
    """``fleet run``: print the study plan, build it, write each dataset.

    The study run itself lives in :mod:`fleet.run`; this command only
    chooses the writer, prints progress and sets the exit code.  A
    :class:`~fleet.core.exceptions.StudyRunError` is turned into exit 1
    by :func:`main`.
    """
    from fleet.core.define_spec import load_define_spec
    from fleet.io import save_dataset_json, save_parquet, save_xpt
    from fleet.io.dataset_json import metadata_from_define
    from fleet.run import plan_study, run_study

    ctx = _load_ctx(args.config)
    plan = plan_study(ctx, datasets=args.dataset)
    specs = {
        e.name.upper(): spec
        for spec in map(load_define_spec, {s.define for s in plan.steps})
        for e in spec.datasets or []
    }
    entries = {name: spec.select(name) for name, spec in specs.items()}

    writers: dict[str, Callable[[pl.DataFrame, Path, str], Path]] = {
        "parquet": lambda df, d, n: save_parquet(df, d / f"{n.lower()}.parquet"),
        "xpt": lambda df, d, n: save_xpt(
            df,
            d / f"{n.lower()}.xpt",
            label=entries[n].label if n in entries else f"Supplemental Qualifiers for {n[4:]}",
            column_labels=(
                {v.name: v.label for v in entries[n].variables} if n in entries else _SUPP_LABELS
            ),
        ),
        "dataset-json": lambda df, d, n: save_dataset_json(
            df, d / f"{n.lower()}.json", domain=n, **metadata_from_define(specs[n], n)
        ),
    }
    formats = {
        s.dataset: _run_format(args.format, specs[s.dataset], entries[s.dataset])
        for s in plan.steps
    }
    out_override = Path(args.out) if args.out else None
    total = len(plan.steps)

    print(f"Config:  {ctx.study_root / 'study_config.yaml'}")
    print(f"Format:  {', '.join(f'{name} {fmt}' for name, fmt in formats.items())}")
    print(f"Plan:    {total} dataset(s)")
    for i, step in enumerate(plan.steps, start=1):
        print(f"  [{i}/{total}] {step.dataset} ({step.standard}, {step.define.name})")
    print()

    for i, built in enumerate(run_study(plan, strict=args.strict), start=1):
        step = built.step
        _check_built(built.frame, step.define, step.dataset, strict=args.strict)
        out_dir = out_override or ctx.data_dir(step.standard)
        out_path = writers[formats[step.dataset]](built.frame, out_dir, step.dataset)
        rows, cols = built.frame.shape
        print(f"[{i}/{total}] {step.dataset}: {rows} rows × {cols} cols → {out_path}")
        if built.supp is not None:
            supp_path = writers[formats[step.dataset]](built.supp, out_dir, f"SUPP{step.dataset}")
            print(f"        SUPP{step.dataset}: {built.supp.height} rows → {supp_path}")
        for name, source in built.inputs.items():
            where = source.path or ("built in this run" if source.source == "built" else "seed")
            print(f"    input {name} -> {where}")
        declared = entries[step.dataset].output
        if declared and Path(declared).name != out_path.name:
            _err(
                f"warning: {step.dataset}: define.yaml output: {declared} is the Define-XML "
                f"leaf; fleet run wrote {out_path.name}."
            )

    print()
    print(f"Done — {total} dataset(s) written.")


def _check_built(frame: pl.DataFrame, define: Path, dataset: str, *, strict: bool) -> None:
    """Stop before the write when the built dataset does not match its define; the old file stays."""
    from fleet.core.exceptions import StudyRunError
    from fleet.define_xml import DatasetChecker

    if frame.width == 0:
        raise StudyRunError(f"dataset {dataset}: the build has no column. The old file is kept.")
    checker = DatasetChecker(define, check_types=False, check_ct=False, validate_schema=False)
    errors = checker.check(frame, dataset, strict=strict).errors
    if errors:
        raise StudyRunError(
            f"dataset {dataset} does not match {define.name}: {'; '.join(errors)}. "
            "The old file is kept."
        )


def _run_format(flag: str | None, spec: DefineSpec, entry: DatasetEntry) -> str:
    """The format of one dataset: --format, then its output_format, then the spec's, then parquet.

    This is the rule of the Define-XML leaf href, so the leaf names the file
    fleet run writes.  A flag that differs from the define warns.
    """
    spec_level = spec.output_format if "output_format" in spec.model_fields_set else None
    declared = entry.output_format or spec_level
    if flag and declared and flag != declared:
        _err(
            f"warning: {entry.name}: --format {flag} overrides output_format: {declared} "
            "of define.yaml, so the Define-XML leaf names another file."
        )
    return flag or declared or "parquet"


# ────────────────────────────────────────────────────────────────────── #
# fleet validate — CDISC Rules Engine wrapper                             #
# ────────────────────────────────────────────────────────────────────── #

#: ``fleet validate`` exit codes: 0 nothing blocks, 1 a finding blocks, 2 a dataset could not run.
_VALIDATE_ERRORS = 1
_VALIDATE_COULD_NOT_RUN = 2


def _run_validate(args: argparse.Namespace) -> None:
    from fleet.core.exceptions import ValidationSetupError
    from fleet.validation import ValidationService, build_sweep
    from fleet.validation.models import write_html_report

    try:
        sweep = build_sweep(
            args.paths,
            standard=args.standard,
            version=args.standard_version,
            custom_rules=args.custom_rules,
            timeout=args.timeout,
            config=Path(args.config) if args.config else None,
            define_xml=args.define,
        )
    except ValidationSetupError as exc:
        _fail(str(exc), code=_VALIDATE_COULD_NOT_RUN)

    results = []
    for standard, datasets in sweep.runs().items():
        setup = datasets[0].setup
        assert setup is not None  # runs() holds only datasets with a setup
        print(f"Validating {len(datasets)} {standard} dataset(s) in one engine run:")
        for d in datasets:
            print(f"  {d.name} — {d.path}")
        by_name = ValidationService(rules_engine_path=setup.engine.value).validate_datasets(
            {d.name: _load_dataset(str(d.path), args.encoding) for d in datasets},
            standard=standard,
            version=setup.ig_version.value,
            custom_rules=setup.custom_rules.value,
            timeout=setup.timeout.value,
            define_xml=setup.define_xml.value,
        )
        setups = {d.name: d.setup for d in datasets}
        for name, result in by_name.items():
            result.apply_setup(setups.get(name) or setup)
            result.print_report()
            results.append(result)
        runs = {id(run): run for r in by_name.values() for run in r.rule_runs}.values()
        problems = [line for run in runs for line in run.problem_lines()]
        if problems:
            print(
                f"Rule problems in the {standard} engine run (not data findings; exit code kept):"
            )
            for line in problems:
                print(f"  {line}")

    could_not_run = sweep.could_not_run
    for d in could_not_run:
        _err(f"{d.name} ({d.path}): {d.reason}")

    if args.report:
        report_path = Path(args.report)
        write_html_report(results, report_path, could_not_run=could_not_run)
        print(f"HTML report → {report_path}")

    engine_failed = sum(1 for r in results if r.could_not_run is not None)
    failed = sum(1 for r in results if r.could_not_run is None and r.errors)
    not_assessed = sum(1 for r in results if r.status == "NOT ASSESSED")
    accepted_only = sum(1 for r in results if r.status.startswith("FINDINGS"))
    passed = sum(1 for r in results if r.status == "PASS")
    accepted = sum(len(r.warnings) for r in results)
    findings = sum(len(r.errors) for r in results) + accepted
    datasets = sum(1 for r in results if r.dataset_name != "STUDY")
    study = " and the study-level rules" if datasets < len(results) else ""
    print()
    print(
        f"Validated {datasets} dataset(s){study}: {passed} passed, "
        f"{accepted_only} with accepted findings, {not_assessed} not assessed, "
        f"{failed} failed, {len(could_not_run) + engine_failed} could not run. "
        f"Findings: {findings} ({accepted} accepted)."
    )
    if could_not_run or engine_failed:
        sys.exit(_VALIDATE_COULD_NOT_RUN)
    if failed:
        sys.exit(_VALIDATE_ERRORS)


# ────────────────────────────────────────────────────────────────────── #
# fleet compare — the exit code is the verdict                           #
# ────────────────────────────────────────────────────────────────────── #

#: ``fleet compare`` exit codes: the job status is the verdict.
_COMPARE_DIFFERENT = 1
_COMPARE_IMPOSSIBLE = 2


def _scan_comparison_side(path_str: str, side: str, encoding: str | None) -> pl.LazyFrame:
    """Open one side through the raw-data loader; an unreadable file is exit 2.

    A CSV side is read as text: :func:`fleet.comparison.csv_types.type_csv_sides`
    types it against the other side.
    """
    from fleet.core.exceptions import FleetError
    from fleet.io import load_raw_data

    path = Path(path_str)
    options: dict[str, object] = _encoding_option(path, encoding)
    if path.suffix.lower() == ".csv":
        options["infer_schema"] = False
    try:
        return load_raw_data(path, **options)
    except (FleetError, ImportError) as exc:
        _fail(
            f"cannot read the {side} {path_str}: {' '.join(str(exc).split())}",
            code=_COMPARE_IMPOSSIBLE,
        )


def _encoding_option(path: Path, encoding: str | None) -> dict[str, object]:
    """``encoding=`` for a file whose reader takes one (CSV and SAS); none for Parquet."""
    if encoding is None or path.suffix.lower() not in (".csv", ".xpt", ".sas7bdat"):
        return {}
    return {"encoding": encoding}


def _parse_variable_pairs(text: str) -> dict[str, str]:
    """``BASE=CANDIDATE,...`` as a mapping; anything else is exit 2."""
    pairs: dict[str, str] = {}
    for item in (i.strip() for i in text.split(",") if i.strip()):
        base, _, candidate = item.partition("=")
        if not base.strip() or not candidate.strip():
            _fail(
                f"--pairs expects BASE=CANDIDATE pairs separated by commas, got {item!r}",
                code=_COMPARE_IMPOSSIBLE,
            )
        pairs[base.strip()] = candidate.strip()
    return pairs


def _run_compare(args: argparse.Namespace) -> None:
    """Compare a candidate file against a base file on keys; exit 0 / 1 / 2."""
    import polars as pl

    from fleet.comparison import DEFAULT_MAX_PRINT, compare
    from fleet.comparison.csv_types import type_csv_sides
    from fleet.core.exceptions import FleetError

    keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    by = [b.strip() for b in args.by.split(",") if b.strip()] if args.by else None
    pairs = _parse_variable_pairs(args.pairs) if args.pairs else None
    variables = (
        [v.strip() for v in args.variables.split(",") if v.strip()] if args.variables else None
    )
    text = [t.strip() for t in args.text.split(",") if t.strip()] if args.text else []
    base = _scan_comparison_side(args.base, "base", args.encoding)
    candidate = _scan_comparison_side(args.candidate, "candidate", args.encoding)
    base_csv, candidate_csv = (
        Path(p).suffix.lower() == ".csv" for p in (args.base, args.candidate)
    )
    csv_types: dict[str, pl.DataType] = {}
    try:
        if base_csv or candidate_csv:
            base, candidate, csv_types = type_csv_sides(
                base, candidate, base_csv=base_csv, candidate_csv=candidate_csv, text=text
            )
        report = compare(
            base,
            candidate,
            keys=keys,
            by=by,
            pairs=pairs,
            variables=variables,
            abs_tol=args.abs_tol,
            rel_tol=args.rel_tol,
            ignore_trailing_whitespace=args.ignore_trailing_whitespace,
            blank_is_missing=args.blank_is_missing,
            allow_duplicates=args.allow_duplicates,
            max_print=None if args.all else DEFAULT_MAX_PRINT,
            base_name=args.base,
            candidate_name=args.candidate,
        )
    except (FleetError, pl.exceptions.PolarsError) as exc:
        # Keys missing, duplicated or incompatible; a tolerance that is not
        # a tolerance; or a file that scanned but could not be read.
        # Differences never raise.
        _fail(" ".join(str(exc).split()), code=_COMPARE_IMPOSSIBLE)

    if args.out:
        _save_comparison_file(args.out, report.save_listing, "value listing")
    if args.report:
        _save_comparison_file(args.report, report.save_html_report, "HTML report")

    if args.format == "json":
        print(report.to_json())  # the whole of stdout is the document
    else:
        if csv_types:
            read_as = ", ".join(
                f"{c} {'numeric' if t.is_numeric() else 'text' if t == pl.String else t}"
                for c, t in csv_types.items()
            )
            print(f"CSV columns read as: {read_as}")
        print(report.to_text())
        if args.out:
            print(f"Value listing → {args.out}")
        if args.report:
            print(f"HTML report → {args.report}")
    if not report.is_equal:
        sys.exit(_COMPARE_DIFFERENT)


def _save_comparison_file(path_str: str, save: Callable[[Path], None], what: str) -> None:
    """Write one comparison output, creating parent directories; an unwritable path is exit 2."""
    path = Path(path_str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        save(path)
    except OSError as exc:
        _fail(f"cannot write the {what} {path}: {exc}", code=_COMPARE_IMPOSSIBLE)


# ────────────────────────────────────────────────────────────────────── #
# fleet check — one CI gate                                               #
# ────────────────────────────────────────────────────────────────────── #


def _run_check(args: argparse.Namespace) -> None:
    """Run the CI gate: config + Define-XML generation + codelists + run setup + rules + essentials."""
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

    # ── 2. define.yaml: the generator itself, in strict mode ──
    if ctx is not None:
        from fleet.define_xml import DefineSpecGenerator

        found_define = False
        for label, path in (
            ("define (sdtm)", ctx.metadata_sdtm_dir / "define.yaml"),
            ("define (adam)", ctx.metadata_adam_dir / "define.yaml"),
        ):
            if not path.is_file():
                continue
            found_define = True
            try:
                # Read-only: the study's derivations_module is not imported.
                DefineSpecGenerator(path, strict=True, import_study_code=False).to_xml_string()
                rows.append(("PASS", label, f"{path} — generates a valid Define-XML"))
            except Exception as exc:
                rows.append(("FAIL", label, str(exc)))
        if not found_define:
            rows.append(
                ("WARN", "define.yaml", "no define.yaml files found (run `fleet init define`)")
            )

    # ── 2b. codelists.py against the study: package, mixed packages, missing classes or file ──
    if ctx is not None:
        from fleet.ct.study_codelists import check_codelists

        try:
            problems = check_codelists(ctx, references=True)
        except Exception as exc:  # a codelists.py or define.yaml that does not load
            problems = [str(exc)]
        rows.extend(("FAIL", "codelists", problem) for problem in problems)
        if not problems and ctx.codelists_file.is_file():
            rows.append(("PASS", "codelists", str(ctx.codelists_file)))

    # ── 3. Run setup with no datasets: IG versions, custom rules, engine ──
    setups = []
    if ctx is not None:
        from fleet.core.exceptions import ValidationSetupError
        from fleet.validation import build_run_setup

        refusals: dict[str, None] = {}
        for std in ("sdtm", "adam"):
            try:
                setups.append(build_run_setup(standard=std, config=config_path))
            except ValidationSetupError as exc:
                refusals[str(exc)] = None
        # A missing rules directory refuses both standards with the same reason.
        rows.extend(("FAIL", "run setup", reason) for reason in refusals)
        for setup in setups:
            label = "SDTMIG" if setup.standard.value == "sdtm" else "ADaMIG"
            detail = f"{label} {setup.ig_version.value} ({setup.ig_version.source})"
            rows.append(("PASS", "run setup", detail))

    # ── 4. Custom-rule YAML checks ──
    if ctx is not None:
        rules_dir = ctx.custom_rules_dir
        if rules_dir is None:
            rows.append(("WARN", "custom rules", "no validation.custom_rules directory configured"))
        elif rules_dir.is_dir():
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

    # ── 5. Doctor essentials (informational — never fail the gate) ──
    if setups:
        engine, where = setups[0].engine.value, f" ({setups[0].engine.source})"
    else:
        from fleet.validation.engine import discover_engine

        engine, where = discover_engine(ctx.study_root if ctx is not None else None), ""
    if engine is not None:
        rows.append(("PASS", "rules engine", f"{engine}{where}"))
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
            description=args.description,
            domains=args.domains,
            adam_datasets=args.adam_datasets,
            ig=args.ig,
            adam_ig=args.adam_ig,
            package=args.package,
            adam_package=args.adam_package,
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
    if args.spec:
        from fleet.tools.migrate_spec import main as migrate_main
    else:
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
    ctx: StudyContext | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame | None, bool]:
    """Resolve one spec's ``(data_df, population, is_listing)`` from CLI args.

    Shared by ``fleet tlg run`` and ``fleet tlg explore`` so both wire
    data identically: NAME=PATH mapping → plain ``--data`` → (for
    ADSL-only templates) the ``--adsl`` frame → the study's configured
    data directories (when a study_config.yaml is discoverable);
    population defaults to the data frame for ADSL-only templates and
    is required for every other table.
    """
    analysis_domain = meta.domains[-1] if meta.domains else None
    is_listing = meta.output_type.value == "listing"

    data_path = named_data.get(analysis_domain or "")
    if data_path is None and default_data is not None:
        data_path = default_data
    if data_path is None and analysis_domain == "ADSL" and adsl_arg:
        data_path = Path(adsl_arg)
    if data_path is None and ctx is not None and analysis_domain:
        data_path = find_dataset_file(analysis_domain, [ctx.adam_data_dir, ctx.sdtm_data_dir])
    if data_path is None:
        _fail(
            f"{spec_path}: template '{meta.id}' needs the {analysis_domain} dataset. "
            f"Pass --data <path> or --data {analysis_domain}=<path>"
            + (
                f", or place it under {ctx.adam_data_dir}."
                if ctx is not None
                else ", or run inside a study workspace."
            )
        )
    data_df = _load_dataset(str(data_path))

    population = adsl_df
    if population is None and analysis_domain == "ADSL":
        population = data_df
    if population is None and not is_listing and "ADSL" in meta.domains and ctx is not None:
        adsl_path = find_dataset_file("ADSL", [ctx.adam_data_dir])
        if adsl_path is not None:
            population = _load_dataset(str(adsl_path))
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
    ctx = _try_ctx()
    out_dir = Path(args.output) if args.output else (ctx.outputs_dir if ctx else Path("."))
    fmt: str = args.fmt

    adsl_df: pl.DataFrame | None = None
    if args.adsl:
        adsl_df = _load_dataset(args.adsl)

    for spec_path in spec_paths:
        spec = _with_adsl_groupby(load_spec(spec_path), args.adsl_groupby)
        meta = TEMPLATES[spec.template]
        data_df, population, is_listing = _resolve_spec_frames(
            spec_path, meta, named_data, default_data, adsl_df, args.adsl, ctx
        )
        groupby = None if is_listing else _spec_groupby(spec, data_df, args.groupby)

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
    ctx = _try_ctx()

    adsl_df: pl.DataFrame | None = None
    if args.adsl:
        adsl_df = _load_dataset(args.adsl)

    entries = []
    for spec_path in spec_paths:
        spec = _with_adsl_groupby(load_spec(spec_path), args.adsl_groupby)
        meta = TEMPLATES[spec.template]
        data_df, population, is_listing = _resolve_spec_frames(
            spec_path, meta, named_data, default_data, adsl_df, args.adsl, ctx
        )
        # A declared groupby axis supplies the arm column per variant —
        # only resolve one when the spec leaves it fixed.
        has_groupby_axis = spec.interactive is not None and spec.interactive.groupby is not None
        groupby = (
            None if (is_listing or has_groupby_axis) else _spec_groupby(spec, data_df, args.groupby)
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

    out_path = (
        Path(args.output)
        if args.output
        else (ctx.outputs_dir / "explorer.html" if ctx else Path("explorer.html"))
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
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
    from fleet.tlg import NAMESPACE_CLASSES, TEMPLATES, RenderMetadata

    domain: str = args.domain
    fmt: str = args.fmt
    ctx = _try_ctx()

    # Resolve datasets: explicit paths, else the study's configured data dirs.
    # The default dataset comes from the registry: the namespace's t_summary
    # template declares its analysis domain last (ADSL for subject-level
    # summaries like dm and ds, ADxx otherwise).
    dataset_name = next(
        (
            meta.domains[-1]
            for meta in TEMPLATES.values()
            if meta.namespace == domain and meta.method == "t_summary" and meta.domains
        ),
        f"AD{domain.upper()}",
    )
    data_arg = args.data
    if data_arg is None and ctx is not None:
        found = find_dataset_file(dataset_name, [ctx.adam_data_dir, ctx.sdtm_data_dir])
        data_arg = str(found) if found else None
    if data_arg is None:
        _fail(
            f"no dataset for domain '{domain}'. Pass --data <path>"
            + (f" or place {dataset_name} under {ctx.adam_data_dir}." if ctx else ".")
        )
    adsl_arg = args.adsl
    if adsl_arg is None and ctx is not None:
        found = find_dataset_file("ADSL", [ctx.adam_data_dir])
        adsl_arg = str(found) if found else None
    if adsl_arg is None:
        _fail(
            "no ADSL dataset. Pass --adsl <path>"
            + (f" or place ADSL under {ctx.adam_data_dir}." if ctx else ".")
        )
    data_df = _load_dataset(data_arg)
    adsl_df = _load_dataset(adsl_arg)

    # Default output: <outputs dir>/<domain>_summary.<fmt> inside a study.
    filename = f"{domain}_summary.{fmt}"
    output_path = (
        Path(args.output)
        if args.output
        else (ctx.outputs_dir / filename if ctx else Path(filename))
    )

    # Metadata (page_by flows through RenderMetadata into every renderer)
    footnotes = list(args.footnote or [])
    if args.population:
        footnotes.append(f"Population: {args.population}")
    rmeta = RenderMetadata(
        title=args.title or "",
        subtitle=args.subtitle or "",
        footnotes=footnotes,
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
    print(f"Data:     {data_arg} ({data_df.shape[0]} rows)")
    print(f"ADSL:     {adsl_arg} ({adsl_df.shape[0]} rows)")
    print(f"Groupby:  {group_col}")
    if args.population:
        print(f"Population: {args.population}")
    print(f"Output:   {output_path}")
    print()

    # Registry-driven dispatch: every TLG namespace exposes t_summary.
    # --population goes to the default spec's adsl_filter, as in a YAML spec.
    ns_cls = NAMESPACE_CLASSES[domain]
    spec = None
    if args.population:
        spec_hint = get_type_hints(ns_cls.t_summary)["spec"]
        spec_cls = next(a for a in get_args(spec_hint) if a is not type(None))
        try:
            spec = spec_cls(adsl_filter=args.population)
        except ValueError as exc:
            _fail(f"--population is not a valid filter: {exc}")
    ard = ns_cls(data_df).t_summary(groupby=group_col, adsl=adsl_df, spec=spec)
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


def _module_available(module: str) -> bool:
    """Whether *module* (a dotted path) can be imported."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # parent package missing, or not a package
        return False


def _distribution_version(dist: str) -> str | None:
    """Installed version of *dist*, or ``None`` when it has no metadata."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(dist)
    except PackageNotFoundError:
        return None


def _require_extra(module: str, extra: str, command: str) -> None:
    """Exit 1 with an install hint when an optional server dep is unusable.

    *module* is the dotted path the command actually imports, so a
    distribution that is present but too old to expose it fails here
    rather than as a bare ``ModuleNotFoundError`` from inside the server.
    """
    if _module_available(module):
        return

    dist = module.split(".")[0]
    found = _distribution_version(dist) if _module_available(dist) else None
    seen = f" (found {dist} {found})" if found else ""
    _fail(
        f"{dist} is required for `fleet {command}`{seen}. Install it with: "
        f"uv sync --extra {extra}  (or: uv pip install 'fleet-cdisc[{extra}]')"
    )


def _run_mcp(args: argparse.Namespace) -> None:
    _require_extra("mcp.server.fastmcp", "mcp", "mcp")
    from fleet.mcp_server import main as mcp_main

    mcp_main(trust_study_engine=args.trust_study_engine)


def _run_lsp(args: argparse.Namespace) -> None:
    _require_extra("pygls.lsp.server", "lsp", "lsp")
    from fleet.lsp_server import main as lsp_main

    lsp_main()


# ────────────────────────────────────────────────────────────────────── #
# Trial Design — build/audit from trial_design.yaml                       #
# ────────────────────────────────────────────────────────────────────── #


def _resolve_design_path(args: argparse.Namespace) -> Path:
    """Resolve the trial design spec: explicit --design, else via study_config.yaml."""
    if args.design:
        return Path(args.design)
    return _load_ctx(args.config).metadata_sdtm_dir / "trial_design.yaml"


def _run_tdd_ctgov(args: argparse.Namespace) -> None:
    import yaml

    from fleet.sdtm.tdd import TrialParameters

    try:
        ts = TrialParameters.from_ctgov(args.nct_id)
    except Exception as exc:
        _fail(f"could not fetch {args.nct_id} from ClinicalTrials.gov: {exc}")
    params = [p.model_dump(exclude_defaults=True) for p in ts.parameters]

    if not args.write:
        print(
            yaml.dump(
                {"parameters": params},
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        )
        print(
            f"# {len(params)} parameter(s) from {args.nct_id} — paste into "
            "trial_design.yaml, or re-run with --write to merge automatically.",
            file=sys.stderr,
        )
        return

    design_path = _resolve_design_path(args)
    if not design_path.is_file():
        _fail(
            f"trial design spec not found: {design_path}. "
            "Create it first, or run without --write to print the YAML."
        )
    from fleet.sdtm.design import load_strict_yaml

    data = load_strict_yaml(design_path.read_text(encoding="utf-8"))
    root = data.get("trial_design", data)
    existing = {(p.get("tsparmcd"), p.get("tsseq", 1)) for p in root.get("parameters") or []}
    added = [p for p in params if (p["tsparmcd"], p.get("tsseq", 1)) not in existing]
    root.setdefault("parameters", []).extend(added)
    design_path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(
        f"{len(added)} parameter(s) from {args.nct_id} merged into {design_path} "
        f"({len(params) - len(added)} already present)."
    )


def _load_design(design_path: Path):
    from fleet.sdtm.design import StudyDesign

    if not design_path.is_file():
        _fail(
            f"trial design spec not found: {design_path}. Create it there or pass --design <path>."
        )
    try:
        return StudyDesign.from_yaml(design_path)
    except Exception as exc:
        _fail(f"invalid trial design spec {design_path}:\n{exc}")


def _print_findings(findings) -> int:
    """Print audit findings to stderr; return the number of errors."""
    errors = 0
    for row in findings.iter_rows(named=True):
        print(
            f"  [{row['severity']}] {row['rule_id']} {row['domain']}: {row['message']}",
            file=sys.stderr,
        )
        errors += row["severity"] == "error"
    return errors


def _run_tdd_audit(args: argparse.Namespace) -> None:
    design = _load_design(_resolve_design_path(args))
    findings = design.audit()
    if findings.is_empty():
        print("Audit clean — no findings.")
        return
    errors = _print_findings(findings)
    print(f"{findings.height} finding(s), {errors} error(s).")
    if errors:
        raise SystemExit(1)


def _run_tdd_build(args: argparse.Namespace) -> None:
    from fleet.io import save_dataset_json, save_parquet, save_xpt
    from fleet.sdtm._tdd_mixin import packaged_structure

    design = _load_design(_resolve_design_path(args))
    frames = design.domains()
    if not frames:
        _fail("trial design spec has no populated sections (elements, arms, visits, ...)")

    findings = design.audit()
    errors = _print_findings(findings)
    if errors and not args.force:
        _fail(f"{errors} conformance error(s) — fix the design or re-run with --force")

    def xpt(df: pl.DataFrame, d: Path, n: str) -> Path:
        ig = packaged_structure(n) or {}
        return save_xpt(
            df,
            d / f"{n.lower()}.xpt",
            label=ig.get("label"),
            column_labels={v["name"]: v.get("label") for v in ig.get("variables", [])},
        )

    def dataset_json(df: pl.DataFrame, d: Path, n: str) -> Path:
        ig = packaged_structure(n) or {}
        return save_dataset_json(
            df,
            d / f"{n.lower()}.json",
            domain=n,
            label=ig.get("label"),
            columns={v["name"]: {"label": v.get("label")} for v in ig.get("variables", [])},
        )

    writers: dict[str, Callable[[pl.DataFrame, Path, str], Path]] = {
        "parquet": lambda df, d, n: save_parquet(df, d / f"{n.lower()}.parquet"),
        "xpt": xpt,
        "dataset-json": dataset_json,
    }
    writer = writers[args.format]
    out_dir = Path(args.out) if args.out else _load_ctx(args.config).sdtm_data_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, df in frames.items():
        out_path = writer(df, out_dir, name)
        print(f"  {name}: {df.shape[0]} rows × {df.shape[1]} cols → {out_path}")
    print(f"Done — {len(frames)} trial design dataset(s) written.")


# ────────────────────────────────────────────────────────────────────── #
# Derivation scaffolding                                                  #
# ────────────────────────────────────────────────────────────────────── #


def _run_derivation_add(args: argparse.Namespace) -> None:
    """Scaffold a derivation file in the study's derivations/ package.

    The package sits next to the configured programs_adam directory
    (``programs/derivations/`` with default paths), where ``fleet init cfg``
    created its ``__init__.py`` stub.
    """
    name: str = args.name.strip()
    dataset: str = args.dataset.strip().upper()
    kind: str = args.kind
    if not name.isidentifier() or keyword.iskeyword(name):
        _fail(f"derivation name {name!r} is not a Python identifier (for example AGEGR1).")

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
    return pl.col("REPLACE_ME").cast(pl.String).alias("{name}")  # TODO: replace with real logic
'''
    else:  # frame
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
        help="Originator / company name (study.originator in define.yaml).",
    )
    cfg.add_argument(
        "--description",
        default=None,
        help="Study description (study.description in define.yaml).",
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
        default=_default_ig("sdtm"),
        help=f"SDTM IG version (default: {_default_ig('sdtm')}).",
    )
    cfg.add_argument(
        "--adam-ig",
        default=_default_ig("adam"),
        help=f"ADaM IG version (default: {_default_ig('adam')}).",
    )
    cfg.add_argument(
        "--package",
        default="sdtmct-2023-12-15",
        help="SDTM CT package version (default: sdtmct-2023-12-15).",
    )
    cfg.add_argument(
        "--adam-package",
        default=None,
        help=(
            "ADaM CT package, for the codelists only ADaM CT holds (DTYPE). Default with "
            "ADaM datasets: adamct-2023-06-30, the latest on or before the default SDTM "
            "package; required with another --package."
        ),
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
        default=None,
        help=(
            "SDTM IG version. Default: sdtm.ig_version from the discovered "
            "study_config.yaml (3-4 outside a study)."
        ),
    )
    add.add_argument(
        "--package",
        default=None,
        help=(
            "CT package version. Default: ct.package from the discovered "
            "study_config.yaml (sdtmct-2023-12-15 outside a study). Refused when it "
            "differs from the package an existing codelists.py was generated from."
        ),
    )
    add.add_argument(
        "--output",
        "-o",
        default=None,
        help=(
            "Path to the existing codelists.py. Default: "
            "<metadata_sdtm>/codelists.py from the discovered study_config.yaml "
            "(./codelists.py outside a study)."
        ),
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
        help="Explicit rule ID (e.g. ACME-AE-042). Skips auto-increment.",
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
        description=(
            "Generate Define-XML 2.1 from a define.yaml specification. This imports the "
            "spec's derivations_module (study Python code) to describe callable: "
            "derivations: run it only on a study you trust."
        ),
    )
    defxml.add_argument(
        "--spec",
        "-s",
        default=None,
        help=(
            "Path to the define.yaml specification file. Default: "
            "<metadata_sdtm|metadata_adam>/define.yaml from the discovered "
            "study_config.yaml (per --standard)."
        ),
    )
    defxml.add_argument(
        "--output",
        "-o",
        default=None,
        help=(
            "Output path for the Define-XML file. Default: "
            "<define_xml dir>/define_<standard>.xml from the discovered "
            "study_config.yaml."
        ),
    )
    defxml.add_argument(
        "--standard",
        choices=["sdtm", "adam"],
        default="sdtm",
        help="Which define.yaml to use for the config-based defaults (default: sdtm).",
    )
    _add_config_flag(defxml)
    defxml.add_argument(
        "--no-preview",
        action="store_true",
        help="Skip generating the HTML preview alongside the XML.",
    )
    defxml.add_argument(
        "--enrich-methods",
        action="store_true",
        help=(
            "Kept for old scripts: MethodDefs are on by default. Every Derived "
            "variable with a comment: or a derivation: gets a MethodDef. This "
            "imports the spec's derivations_module (study Python code)."
        ),
    )
    defxml.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Refuse to write the file when the define has gaps: a Derived variable "
            "with no method text, a text, integer or float variable with no length, "
            "a float with no significant_digits. Without it the gaps are warnings."
        ),
    )
    defxml.add_argument(
        "--watch",
        action="store_true",
        help="Re-generate whenever the spec file changes (requires the 'watch' extra).",
    )
    defxml.set_defaults(func=_run_define_xml)

    # -- add-acrf --------------------------------------------------------- #
    add_acrf = sub.add_parser(
        "add-acrf",
        help="Declare the annotated CRF document (study.documents block) in define.yaml.",
    )
    add_acrf.add_argument(
        "--href",
        default="blankcrf.pdf",
        help="aCRF file path in the submission package (default: blankcrf.pdf).",
    )
    add_acrf.add_argument(
        "--title",
        default=None,
        help='Display title (default: "Annotated Case Report Form").',
    )
    add_acrf.add_argument(
        "--page-map",
        default=None,
        help="External DOMAIN.VARIABLE → pages YAML file, relative to define.yaml.",
    )
    add_acrf.add_argument(
        "--standard",
        choices=["sdtm", "adam", "both"],
        default="sdtm",
        help="Which define.yaml to update (default: sdtm).",
    )
    _add_config_flag(add_acrf)
    add_acrf.set_defaults(func=_run_add_acrf)


def _add_engine_parsers(sub: argparse._SubParsersAction) -> None:
    from fleet.validation.engine import DEFAULT_ENGINE_TAG

    inst = sub.add_parser(
        "install-engine",
        help="Download the CDISC Rules Engine binary for validation.",
    )
    inst.add_argument(
        "--version",
        default=DEFAULT_ENGINE_TAG,
        help=(
            f"Release tag to download (default: {DEFAULT_ENGINE_TAG}, the CORE release "
            "that Fleet is tested with). 'latest' gets the newest release and warns."
        ),
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
        help="Check Fleet setup: engine, API key, codelists.py, optional extras.",
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
            "data/sdtm and data/adam directories. Fleet only writes here: inputs "
            "are read from the run, a declared path:, the raw directory (type: raw) "
            "or the data directory of the input's standard (type: dataset)."
        ),
    )
    run.add_argument(
        "--format",
        default=None,
        choices=["parquet", "xpt", "dataset-json"],
        help=(
            "Output format of every dataset. Default: the output_format of the dataset, "
            "else of define.yaml, else parquet (the rule of the Define-XML leaf)."
        ),
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
        help=(
            "Validate datasets with the CDISC Rules Engine, one engine run per standard. "
            "Every finding blocks unless validation.accepted lists it "
            "(exit 0 nothing blocks, 1 a finding blocks, 2 a dataset could not run)."
        ),
    )
    validate.add_argument(
        "paths",
        nargs="*",
        help=(
            "Dataset files or directories (parquet / csv / xpt / sas7bdat). "
            "Default: the configured sdtm_data and adam_data directories."
        ),
    )
    _add_config_flag(validate)
    validate.add_argument(
        "--standard",
        choices=["sdtm", "adam"],
        default=None,
        help=(
            "Force the standard. Default: the configured data directory that holds "
            "the dataset, else AD* datasets → adam, others → sdtm."
        ),
    )
    validate.add_argument(
        "--version",
        dest="standard_version",
        default=None,
        help=(
            "IG version. Default: the sdtm/adam ig_version declared in the "
            "discovered study_config.yaml (3.4 / 1.3 outside a study)."
        ),
    )
    validate.add_argument(
        "--define",
        default=None,
        metavar="PATH",
        help=(
            "Define-XML file that CORE checks with the datasets (CORE -dxp). Opt-in: "
            "Fleet never passes a define by default."
        ),
    )
    validate.add_argument(
        "--custom-rules",
        default=None,
        help=(
            "Directory of custom validation rule YAML files, relative to the working "
            "directory. Default: validation.custom_rules from the discovered study_config.yaml."
        ),
    )
    validate.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Seconds before an engine run is stopped. "
            "Default: validation.timeout from the discovered study_config.yaml, else 300."
        ),
    )
    validate.add_argument(
        "--report",
        default=None,
        metavar="PATH",
        help="Write an HTML findings report to PATH.",
    )
    validate.add_argument(
        "--encoding",
        metavar="NAME",
        help=(
            "Text encoding of the CSV and SAS files, e.g. iso-8859-1 for files from a "
            "WLATIN1 SAS session (default: UTF-8)."
        ),
    )
    validate.set_defaults(func=_run_validate)

    # -- check -------------------------------------------------------------- #
    check = sub.add_parser(
        "check",
        help=(
            "CI gate: config parse + define.yaml schema + codelists.py + run setup + "
            "custom-rule YAMLs."
        ),
        description=(
            "CI gate: parse the study config, check each define.yaml against its schema, "
            "check codelists.py against ct.package, ct.adam_package and the define.yaml files, "
            "build the validation run setup for SDTM and ADaM with no datasets, and check "
            "each custom rule YAML. An unsupported sdtm.ig_version or adam.ig_version and a "
            "configured validation.custom_rules directory that does not exist fail the gate. "
            "A missing rules engine and an unset CDISC_API_KEY are warnings only, because CI "
            "installs no engine. Exit 1 on any failure, else 0."
        ),
    )
    _add_config_flag(check)
    check.set_defaults(func=_run_check)

    # -- compare ------------------------------------------------------------ #
    compare_parser = sub.add_parser(
        "compare",
        help=(
            "Compare a candidate dataset against a base on keys "
            "(exit 0 equal, 1 different, 2 could not run)."
        ),
        description=(
            "PROC COMPARE analogue: pair the two datasets on --keys, match variables by "
            "name and print the comparison report. --pairs compares variables named "
            "differently on each side and --variables restricts the comparison to the ones "
            "that matter. Equality is exact unless --abs-tol, "
            "--rel-tol or --ignore-trailing-whitespace widens it. --by sections the report "
            "per group and --allow-duplicates pairs duplicate keys by position. Exit 0 when "
            "the datasets are equal, 1 when they differ, 2 when the comparison could not run "
            "(unreadable file, missing keys, duplicate keys without --allow-duplicates, a "
            "negative tolerance, a --variables list of keys only, --out or --report not "
            "writable)."
        ),
    )
    compare_parser.add_argument(
        "base",
        help="The reference dataset (parquet / csv / xpt / sas7bdat; SAS formats need the io extra).",
    )
    compare_parser.add_argument(
        "candidate",
        help="The dataset measured against the base (same formats).",
    )
    compare_parser.add_argument(
        "--keys",
        required=True,
        metavar="K1,K2",
        help=(
            "Comma-separated variables that identify one observation on each side, "
            "e.g. USUBJID,AESEQ. Required; keys are never looked up."
        ),
    )
    compare_parser.add_argument(
        "--by",
        metavar="B1,B2",
        help=(
            "Comma-separated variables to section the report by, e.g. TRT01P. They are "
            "prepended to --keys automatically, so they need not be repeated there. The "
            "observation and values summaries are also reported per group, and a group "
            "present on one side only is flagged and listed; the verdict stays global."
        ),
    )
    compare_parser.add_argument(
        "--pairs",
        metavar="BASE=CAND,...",
        help=(
            "Comma-separated variable pairs whose sides carry different names, e.g. "
            "WEIGHT=WT. Applied on top of the automatic name matching, so a renamed "
            "column is compared rather than reported missing; the report names it after "
            "the base. A pair whose candidate variable is absent reports the base one as "
            "missing from the candidate."
        ),
    )
    compare_parser.add_argument(
        "--variables",
        metavar="V1,V2",
        help=(
            "Comma-separated variables to restrict the comparison to, in base names, so a "
            "work-in-progress candidate is checked on the columns that are finished. A "
            "variable outside the list is ignored on both sides: neither compared nor "
            "reported as missing."
        ),
    )
    compare_parser.add_argument(
        "--abs-tol",
        type=float,
        default=0.0,
        metavar="TOL",
        help=(
            "Absolute tolerance on the numeric variables (default: 0, exact). A numeric "
            "pair differs when the absolute difference exceeds max(--abs-tol, --rel-tol x "
            "|base|)."
        ),
    )
    compare_parser.add_argument(
        "--rel-tol",
        type=float,
        default=0.0,
        metavar="TOL",
        help=(
            "Relative tolerance on the numeric variables, as a fraction of the base value "
            "(default: 0, exact). It anchors on the base because the base is the reference, "
            "as in SAS: 0.01 is one percent of the base."
        ),
    )
    compare_parser.add_argument(
        "--ignore-trailing-whitespace",
        action="store_true",
        help=(
            "Strip trailing whitespace from both sides of a string before comparing, so a "
            "legacy SAS dataset's padded character values equal Fleet's stripped ones. "
            "Leading whitespace still differs."
        ),
    )
    compare_parser.add_argument(
        "--blank-is-missing",
        action="store_true",
        help=(
            "Read an empty string as missing on both sides, keys included, as SAS does. "
            "Use it when one side comes from a tool that kept blanks as empty strings "
            "(an R data frame without convert_blanks_to_na). A SAS file always reads a "
            "blank as missing."
        ),
    )
    compare_parser.add_argument(
        "--text",
        metavar="V1,V2",
        help=(
            "Comma-separated CSV columns to read as text, the equivalent of a SAS $ "
            "informat, e.g. LBORRES. A CSV file holds no types: a column is text when a "
            "value on either side has a leading zero or is not a number, a number "
            "otherwise, and the other side's type when that side is not a CSV file."
        ),
    )
    compare_parser.add_argument(
        "--encoding",
        metavar="NAME",
        help=(
            "Text encoding of a CSV or SAS file, e.g. iso-8859-1 for a file from a "
            "WLATIN1 SAS session (default: UTF-8)."
        ),
    )
    compare_parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help=(
            "Pair duplicate keys by their position within each key group instead of "
            "refusing to run. The report then counts the duplicates per side, raises the "
            "duplicate_keys flag and warns at the top: order within a key group decides "
            "which observations pair."
        ),
    )
    compare_parser.add_argument(
        "--all",
        action="store_true",
        help="Print every unequal value (default: 50 per variable, 500 overall).",
    )
    compare_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help=(
            "Output format: the text report, or one JSON document (verdict, flags, "
            "summaries, listing within the print limits, settings, Fleet version) and "
            "nothing else on stdout (default: text)."
        ),
    )
    compare_parser.add_argument(
        "--out",
        metavar="PATH",
        help=(
            "Also write the complete value listing (never truncated) to PATH as parquet, "
            "e.g. differences.parquet."
        ),
    )
    compare_parser.add_argument(
        "--report",
        metavar="PATH",
        help=(
            "Also write a self-contained HTML report to PATH for a reviewer without Python: "
            "structural findings as chips, then every mismatched observation with the base "
            "and candidate values side by side, one collapsible block per variable."
        ),
    )
    compare_parser.set_defaults(func=_run_compare)

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
        help="Originator / company name (study.originator in define.yaml).",
    )
    new.add_argument(
        "--description",
        default=None,
        help="Study description (study.description in define.yaml).",
    )
    new.add_argument(
        "--ig",
        default=_default_ig("sdtm"),
        help=f"SDTM IG version (default: {_default_ig('sdtm')}).",
    )
    new.add_argument(
        "--adam-ig",
        default=_default_ig("adam"),
        help=f"ADaM IG version (default: {_default_ig('adam')}).",
    )
    new.add_argument(
        "--package",
        default="sdtmct-2023-12-15",
        help="SDTM CT package version (default: sdtmct-2023-12-15).",
    )
    new.add_argument(
        "--adam-package",
        default=None,
        help=(
            "ADaM CT package, for the codelists only ADaM CT holds (DTYPE). Default with "
            "ADaM datasets: adamct-2023-06-30, the latest on or before the default SDTM "
            "package; required with another --package."
        ),
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
        help=(
            "Rewrite removed pre-alpha spellings: Python verbs and kwargs (libcst), "
            "or, with --spec, define.yaml algorithms and keys (ADR-0008)."
        ),
    )
    migrate.add_argument(
        "files",
        nargs="+",
        help="Python files or directories to migrate (define.yaml files with --spec).",
    )
    migrate.add_argument(
        "--spec",
        action="store_true",
        help="Migrate define.yaml files to the verb vocabulary (fleet_spec_version 2).",
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


def _add_tdd_parsers(sub: argparse._SubParsersAction) -> None:
    tdd = sub.add_parser(
        "tdd",
        help="Trial design workflow: build/audit TDD datasets from trial_design.yaml.",
    )
    tdd_sub = tdd.add_subparsers(dest="tdd_command", required=True)

    # -- tdd build ----------------------------------------------------- #
    tdd_build = tdd_sub.add_parser(
        "build",
        help="Derive the trial design datasets (TE/TA/TV/TS/TI/TD/TM) and write them.",
    )
    tdd_build.add_argument(
        "--design",
        default=None,
        help=(
            "Path to the trial design YAML spec. Default: "
            "<metadata_sdtm>/trial_design.yaml from the discovered study_config.yaml."
        ),
    )
    tdd_build.add_argument(
        "--out",
        "-o",
        default=None,
        help=(
            "Output directory. Default: the sdtm_data directory from the "
            "discovered study_config.yaml."
        ),
    )
    tdd_build.add_argument(
        "--format",
        choices=["parquet", "xpt", "dataset-json"],
        default="parquet",
        help="Output format (default: parquet).",
    )
    tdd_build.add_argument(
        "--force",
        action="store_true",
        help="Write datasets even when the conformance audit reports errors.",
    )
    _add_config_flag(tdd_build)
    tdd_build.set_defaults(func=_run_tdd_build)

    # -- tdd ctgov ------------------------------------------------------ #
    tdd_ctgov = tdd_sub.add_parser(
        "ctgov",
        help="Seed TS parameters from a ClinicalTrials.gov registration.",
    )
    tdd_ctgov.add_argument(
        "nct_id",
        help="ClinicalTrials.gov identifier (e.g. NCT04280705).",
    )
    tdd_ctgov.add_argument(
        "--write",
        action="store_true",
        help=(
            "Merge the parameters into the trial design spec (new TSPARMCD/TSSEQ "
            "rows only) instead of printing YAML to stdout."
        ),
    )
    tdd_ctgov.add_argument(
        "--design",
        default=None,
        help=(
            "Trial design spec to merge into with --write. Default: "
            "<metadata_sdtm>/trial_design.yaml from the discovered study_config.yaml."
        ),
    )
    _add_config_flag(tdd_ctgov)
    tdd_ctgov.set_defaults(func=_run_tdd_ctgov)

    # -- tdd audit ------------------------------------------------------ #
    tdd_audit = tdd_sub.add_parser(
        "audit",
        help="Run the P21-style conformance pre-check on a trial design spec.",
    )
    tdd_audit.add_argument(
        "--design",
        default=None,
        help=(
            "Path to the trial design YAML spec. Default: "
            "<metadata_sdtm>/trial_design.yaml from the discovered study_config.yaml."
        ),
    )
    _add_config_flag(tdd_audit)
    tdd_audit.set_defaults(func=_run_tdd_audit)


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
        default=None,
        help=(
            "Output directory. Default: the configured outputs directory "
            "(current directory outside a study workspace)."
        ),
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
        help=(
            "Treatment-arm column. Default: the spec's columns: field when it "
            "declares one, else auto-detect (TRTA → TRT01A → TRT01P)."
        ),
    )
    tlg_run.add_argument(
        "--adsl-groupby",
        default=None,
        help=(
            "ADSL arm column for the big N when ADSL lacks the analysis arm "
            "(e.g. TRT01A for an ADAE grouped by TRTA). Sets adsl_group_col."
        ),
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
        default=None,
        help=(
            "Output HTML file. Default: explorer.html in the configured "
            "outputs directory (current directory outside a study workspace)."
        ),
    )
    tlg_explore.add_argument(
        "--groupby",
        default=None,
        help=(
            "Treatment-arm column for specs without a groupby axis. "
            "Default: the spec's columns: field when it declares one, else "
            "auto-detect (TRTA → TRT01A → TRT01P)."
        ),
    )
    tlg_explore.add_argument(
        "--adsl-groupby",
        default=None,
        help=(
            "ADSL arm column for the big N when ADSL lacks the analysis arm "
            "(e.g. TRT01A for an ADAE grouped by TRTA). Sets adsl_group_col."
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
        default=None,
        help=(
            "Path to the primary analysis dataset. Default: the analysis dataset "
            "the domain's t_summary template declares (e.g. ADAE for ae, ADSL for "
            "dm/ds), found in the configured data directories."
        ),
    )
    tlg_export.add_argument(
        "--adsl",
        default=None,
        help=(
            "Path to the ADSL dataset. Default: ADSL found in the configured adam_data directory."
        ),
    )
    tlg_export.add_argument(
        "--output",
        "-o",
        default=None,
        help=(
            "Output file path. Default: <domain>_summary.<format> in the "
            "configured outputs directory (current directory outside a study)."
        ),
    )
    tlg_export.add_argument(
        "--groupby",
        default=None,
        help="Treatment-arm column. Default: auto-detect (TRTA → TRT01A → TRT01P).",
    )
    tlg_export.add_argument(
        "--population",
        default=None,
        metavar="FILTER",
        help=(
            "ADSL population filter, passed to the spec's adsl_filter and shown in a "
            'footnote, e.g. \'pl.col("SAFFL") == "Y"\'. Default: none (all ADSL subjects).'
        ),
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
    mcp.add_argument(
        "--trust-study-engine",
        action="store_true",
        help=(
            "Let fleet_validate start the engine that validation.engine_path of a "
            "study config names. Without it, such a run could not run."
        ),
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
        help=(
            "Scaffold a new derivation file in the study's derivations/ package "
            "(next to the configured programs/adam directory)."
        ),
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
        choices=["column", "frame"],
        help=(
            "Derivation kind: column / frame (default: column). "
            "For a new parameter row, use .adam.derive_param()."
        ),
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
    _add_tdd_parsers(sub)
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
    # A cp1252 pipe on Windows cannot encode a check mark; print \u2713 instead of crashing.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Read the CDISC_API_KEY of a study .env (walking up from the cwd) before
    # any handler needs it; commands must work from any study subdirectory.
    from fleet.ct.api import try_load_dotenv

    try_load_dotenv()

    # Make project-local modules (e.g. a spec's `derivations_module:
    # fixtures.derivations`) importable from the bare `fleet` console script.
    # Appended, so a file in the study folder never shadows an installed package.
    if "" not in sys.path and os.getcwd() not in sys.path:
        sys.path.append(os.getcwd())

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
