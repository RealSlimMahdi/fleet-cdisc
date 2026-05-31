"""Fleet CLI — study bootstrapping, controlled terminology, and Define-XML.

Entry point: ``fleet`` (registered as a console script).

Bootstrapping pipeline (run in order):

- ``fleet init cfg``    — create ``study_config.yaml`` and directory structure.
- ``fleet init define`` — generate ``define.yaml`` from the CDISC Library IG.
- ``fleet init ct``     — generate ``codelists.py`` from the ``define.yaml``.

Standalone commands:

- ``fleet init-ct``    — bootstrap ``codelists.py`` directly from the SDTM IG.
- ``fleet add-ct``     — add domains to an existing ``codelists.py``.
- ``fleet define-xml`` — generate Define-XML 2.1 from a ``define.yaml``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fleet",
        description="Fleet — CDISC SDTM/ADaM derivation toolkit CLI.",
    )
    sub = parser.add_subparsers(dest="command")

    # ── init (parent) ── cfg / define / ct ──────────────────────────── #
    init_parser = sub.add_parser(
        "init",
        help="Bootstrapping pipeline: cfg → define → ct.",
    )
    init_sub = init_parser.add_subparsers(dest="init_command")

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

    # -- init define ---------------------------------------------------- #
    define = init_sub.add_parser(
        "define",
        help="Generate define.yaml from the CDISC Library IG.",
    )
    define.add_argument(
        "--config",
        "-c",
        default="study_config.yaml",
        help="Path to study_config.yaml (default: study_config.yaml).",
    )
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

    # -- init ct -------------------------------------------------------- #
    ct = init_sub.add_parser(
        "ct",
        help="Generate codelists.py from the define.yaml specifications.",
    )
    ct.add_argument(
        "--config",
        "-c",
        default="study_config.yaml",
        help="Path to study_config.yaml (default: study_config.yaml).",
    )
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

    # -- init rules ----------------------------------------------------- #
    rules = init_sub.add_parser(
        "rules",
        help="Cache CDISC conformance rules as YAML from the CDISC Library.",
    )
    rules.add_argument(
        "--config",
        "-c",
        default="study_config.yaml",
        help="Path to study_config.yaml (default: study_config.yaml).",
    )
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

    # -- init-ct (standalone, legacy) ----------------------------------- #
    init_ct = sub.add_parser(
        "init-ct",
        help="Bootstrap a codelists.py from the SDTM IG for given domains.",
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

    # -- add-ct --------------------------------------------------------- #
    add = sub.add_parser(
        "add-ct",
        help="Add domains to an existing codelists.py (preserves existing).",
    )

    # -- add-rule ------------------------------------------------------- #
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

    # -- check-rule ----------------------------------------------------- #
    check_rule_parser = sub.add_parser(
        "check-rule",
        help="Validate a custom rule YAML (syntax, structure, schema).",
    )
    check_rule_parser.add_argument(
        "rule_file",
        help="Path to the custom rule YAML file to validate.",
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

    # -- define-xml ----------------------------------------------------- #
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

    # -- install-engine ------------------------------------------------- #
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

    # -- uninstall-engine ----------------------------------------------- #
    sub.add_parser(
        "uninstall-engine",
        help="Remove the managed CDISC Rules Engine binary.",
    )

    # -- doctor --------------------------------------------------------- #
    sub.add_parser(
        "doctor",
        help="Check Fleet setup: engine, dependencies, environment.",
    )

    # -- tlg export ----------------------------------------------------- #
    tlg = sub.add_parser(
        "tlg",
        help="TLG rendering: ARD → HTML / PDF / slides.",
    )
    tlg_sub = tlg.add_subparsers(dest="tlg_command")
    tlg_export = tlg_sub.add_parser(
        "export",
        help="Render an AE or VS summary to HTML, PDF, or slides.",
    )
    tlg_export.add_argument(
        "--domain",
        required=True,
        choices=["ae", "vs"],
        help="TLG domain (ae or vs).",
    )
    tlg_export.add_argument(
        "--format",
        dest="fmt",
        default="html",
        choices=["html", "pdf", "pptx"],
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
        default=None,
        help="Output file path.  Defaults to <domain>_summary.<format>.",
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
        "--wrap",
        default=None,
        help="Path to an HTML wrapper template with {table} placeholder.",
    )

    # -- derivation ----------------------------------------------------- #
    drv_parser = sub.add_parser(
        "derivation",
        help="Scaffold and manage study-specific derivations.",
    )
    drv_sub = drv_parser.add_subparsers(dest="derivation_command")

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
    drv_add.add_argument(
        "--config",
        "-c",
        default="study_config.yaml",
        help="Path to study_config.yaml (default: study_config.yaml).",
    )

    return parser


def _parse_domains(raw: str) -> list[str]:
    return [d.strip().upper() for d in raw.split(",") if d.strip()]


# ── Bootstrapping pipeline ──────────────────────────────────────────── #


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
    print(f"Created study workspace → {ctx.study_root}")
    print(f"Config  → {ctx.study_root / 'study_config.yaml'}")
    print()
    print("Next step: fleet init define")


def _run_init_define(args: argparse.Namespace) -> None:
    from fleet.core.scaffolder import DefineScaffolder
    from fleet.core.study_context import load_study_context
    from fleet.ct.api import CDISCClient

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"Error: config not found: {config_path}")
        print("Run `fleet init cfg` first.")
        sys.exit(1)

    ctx = load_study_context(config_path)
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
        print("Nothing to generate. Configure domains/datasets in study_config.yaml.")
        sys.exit(1)

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

    print()
    print("Next step: fleet init ct")


def _run_init_rules(args: argparse.Namespace) -> None:
    from fleet.core.rules_scaffolder import RulesScaffolder
    from fleet.core.study_context import load_study_context
    from fleet.ct.api import CDISCClient

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"Error: config not found: {config_path}")
        print("Run `fleet init cfg` first.")
        sys.exit(1)

    ctx = load_study_context(config_path)
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
    from fleet.core.study_context import load_study_context
    from fleet.ct.api import CDISCClient
    from fleet.ct.generator import CodelistGenerator, extract_concept_ids

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"Error: config not found: {config_path}")
        print("Run `fleet init cfg` first.")
        sys.exit(1)

    ctx = load_study_context(config_path)
    cfg = ctx.config

    # Collect concept IDs from all define.yaml files
    all_ids: set[str] = set()
    define_paths: list[Path] = []

    sdtm_define = ctx.metadata_sdtm_dir / "define.yaml"
    adam_define = ctx.metadata_adam_dir / "define.yaml"

    for dpath in (sdtm_define, adam_define):
        if dpath.is_file():
            define_paths.append(dpath)
            ids = extract_concept_ids(dpath)
            all_ids |= ids
            print(f"Scanned {dpath.name}: {len(ids)} codelist(s)")

    if not all_ids:
        print("No codelist references found in define.yaml files.")
        print("Run `fleet init define` first.")
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

    print(f"Generated {len(gen._codelists)} codelists → {dest}")

    print()
    print("Bootstrap complete! Next steps:")
    print(
        "  - Spec-driven:  codelists are already referenced in define.yaml — start writing derivations."
    )
    print("  - Inline code:  from fleet.ct import import_codelists; ct = import_codelists()")
    print("                  or: import_codelists(); from codelists import SEX, RACE, ...")
    print("  - When ready:   fleet define-xml --spec <define.yaml>")


# ── Standalone commands ─────────────────────────────────────────────── #


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

    count = len(gen._codelists)
    print(f"Generated {count} codelists → {dest}")


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

    print(f"Updated {dest} — {len(gen._codelists)} codelists")


def _run_add_rule(args: argparse.Namespace) -> None:
    from fleet.validation.rule_scaffolder import scaffold_rule

    # Resolve output directory
    output_dir: Path | None = None
    if args.output:
        output_dir = Path(args.output)
    else:
        # Try loading study_config.yaml from cwd
        config_path = Path.cwd() / "study_config.yaml"
        if config_path.exists():
            from fleet.core.study_context import load_study_context

            ctx = load_study_context(config_path)
            if ctx.custom_rules_dir is not None:
                output_dir = ctx.custom_rules_dir
            else:
                print(
                    "Error: No 'validation.custom_rules' configured in study_config.yaml.\n"
                    "Either add it to your config or pass --output <dir>."
                )
                sys.exit(1)
        else:
            print(
                "Error: No study_config.yaml found in current directory.\n"
                "Either run from a study root or pass --output <dir>."
            )
            sys.exit(1)

    # Resolve organization from study_config if available
    organization: str | None = None
    config_path = Path.cwd() / "study_config.yaml"
    if config_path.exists():
        from fleet.core.study_context import load_study_context

        ctx = load_study_context(config_path)
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
        print(f"Error: {exc}")
        sys.exit(1)

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
        print(f"Error: File not found: {rule_path}")
        sys.exit(1)

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
        print()
        for err in errors:
            print(f"  ✗ {err}")
        print()
        print(f"  {len(errors)} error(s) found.")
        sys.exit(1)


def _run_install_engine(args: argparse.Namespace) -> None:
    from fleet.validation.engine import install_engine

    try:
        install_engine(version=args.version, force=args.force)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        sys.exit(1)


def _run_uninstall_engine() -> None:
    from fleet.validation.engine import uninstall_engine

    uninstall_engine()


def _run_doctor() -> None:
    from fleet.validation.engine import doctor

    checks = doctor()
    print("Fleet Doctor")
    print("=" * 40)
    for name, status in checks.items():
        print(f"  {name:.<20s} {status}")
    print()


def _run_define_xml(args: argparse.Namespace) -> None:
    from fleet.define_xml.spec_generator import DefineSpecGenerator

    spec = Path(args.spec)
    output = Path(args.output)

    if not spec.is_file():
        print(f"Error: spec file not found: {spec}")
        sys.exit(1)

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


# ── TLG rendering ───────────────────────────────────────────────────── #


def _load_dataset(path_str: str) -> pl.DataFrame:  # noqa: F821
    """Load a CSV or Parquet file into a Polars DataFrame."""
    import polars as pl  # noqa: F811

    p = Path(path_str)
    if not p.is_file():
        print(f"Error: file not found: {p}")
        sys.exit(1)
    if p.suffix == ".parquet":
        return pl.read_parquet(p)
    return pl.read_csv(p)


def _run_tlg_export(args: argparse.Namespace) -> None:

    from fleet.tlg import RenderMetadata, ard_to_table_model, render_html
    from fleet.tlg.render.pdf import render_pdf
    from fleet.tlg.render.slides import render_pptx

    domain: str = args.domain
    fmt: str = args.fmt

    # Load datasets
    data_df = _load_dataset(args.data)
    adsl_df = _load_dataset(args.adsl)

    # Default output filename
    output = args.output or f"{domain}_summary.{fmt}"
    output_path = Path(output)

    # Metadata
    meta = RenderMetadata(
        title=args.title or "",
        subtitle=args.subtitle or "",
        footnotes=args.footnote or [],
    )

    # HTML wrapper
    html_wrapper: str | None = None
    if args.wrap:
        wp = Path(args.wrap)
        if not wp.is_file():
            print(f"Error: wrapper template not found: {wp}")
            sys.exit(1)
        html_wrapper = wp.read_text(encoding="utf-8")

    # Compute ARD
    print(f"Domain:   {domain}")
    print(f"Format:   {fmt}")
    print(f"Data:     {args.data} ({data_df.shape[0]} rows)")
    print(f"ADSL:     {args.adsl} ({adsl_df.shape[0]} rows)")
    print(f"Output:   {output_path}")
    print()

    # Auto-detect groupby column
    group_col = "TRTA" if "TRTA" in adsl_df.columns else "TRT01P"

    # Domain → ARD computation dispatch
    _domain_dispatch = {
        "ae": lambda df: df.tlg.ae.t_summary(groupby=group_col, adsl=adsl_df),
        "vs": lambda df: df.tlg.vs.t_summary(groupby=group_col, adsl=adsl_df),
    }
    if domain not in _domain_dispatch:
        print(f"Error: unsupported domain '{domain}'")
        sys.exit(1)
    ard = _domain_dispatch[domain](data_df)

    model = ard_to_table_model(ard, meta)
    print(f"ARD:      {ard.shape[0]} rows × {ard.shape[1]} cols")
    print(f"Model:    {len(model.columns)} columns, {len(model.rows)} display rows")

    # Format → render dispatch
    _format_dispatch = {
        "html": lambda: (
            output_path.parent.mkdir(parents=True, exist_ok=True),
            output_path.write_text(render_html(model, html_wrapper=html_wrapper), encoding="utf-8"),
            print(f"\nHTML written → {output_path}"),
        ),
        "pdf": lambda: (render_pdf(model, output_path), print(f"\nPDF written → {output_path}")),
        "pptx": lambda: (
            render_pptx(model, output_path),
            print(f"\nPPTX written → {output_path}"),
        ),
    }
    if fmt not in _format_dispatch:
        print(f"Error: unsupported format '{fmt}'")
        sys.exit(1)
    _format_dispatch[fmt]()


def _run_derivation_add(args: argparse.Namespace) -> None:
    """Scaffold a new derivation file under specs/<study_id>/adam/derivations/."""
    name: str = args.name.strip()
    dataset: str = args.dataset.strip().upper()
    kind: str = args.kind
    config_path = Path(args.config)

    # Resolve derivations directory.
    if config_path.is_file():
        from fleet.core.study_context import load_study_context

        ctx = load_study_context(config_path)
        derivations_dir = ctx.programs_adam_dir.parent / "derivations"
    else:
        # Fallback: create under specs/<study_id>/adam/derivations relative to CWD.
        derivations_dir = Path(".") / "derivations"

    derivations_dir.mkdir(parents=True, exist_ok=True)
    out_file = derivations_dir / f"{name}.py"

    if out_file.exists():
        print(f"File already exists: {out_file}")
        print("Delete it manually if you want to regenerate.")
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


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "init":
        if args.init_command == "cfg":
            _run_init_cfg(args)
        elif args.init_command == "define":
            _run_init_define(args)
        elif args.init_command == "ct":
            _run_init_ct_pipeline(args)
        elif args.init_command == "rules":
            _run_init_rules(args)
        else:
            # Show init subcommand help
            parser.parse_args(["init", "--help"])
    elif args.command == "init-ct":
        _run_init_ct(args)
    elif args.command == "add-ct":
        _run_add_ct(args)
    elif args.command == "add-rule":
        _run_add_rule(args)
    elif args.command == "check-rule":
        _run_check_rule(args)
    elif args.command == "define-xml":
        _run_define_xml(args)
    elif args.command == "install-engine":
        _run_install_engine(args)
    elif args.command == "uninstall-engine":
        _run_uninstall_engine()
    elif args.command == "doctor":
        _run_doctor()
    elif args.command == "tlg":
        if getattr(args, "tlg_command", None) == "export":
            _run_tlg_export(args)
        else:
            parser.parse_args(["tlg", "--help"])
    elif args.command == "derivation":
        if getattr(args, "derivation_command", None) == "add":
            _run_derivation_add(args)
        else:
            parser.parse_args(["derivation", "--help"])
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
