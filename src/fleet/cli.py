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

    return parser


def _parse_domains(raw: str) -> list[str]:
    return [d.strip().upper() for d in raw.split(",") if d.strip()]


# ── Bootstrapping pipeline ──────────────────────────────────────────── #


def _run_init_cfg(args: argparse.Namespace) -> None:
    from .core.study_context import (
        ADAMConfig,
        CTConfig,
        SDTMConfig,
        StudyContext,
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
    )
    print(f"Created study workspace → {ctx.study_root}")
    print(f"Config  → {ctx.study_root / 'study_config.yaml'}")
    print()
    print("Next step: fleet init define")


def _run_init_define(args: argparse.Namespace) -> None:
    from .core.scaffolder import DefineScaffolder
    from .core.study_context import load_study_context
    from .ct.api import CDISCClient

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

        if do_sdtm:
            sdtm_path = ctx.metadata_sdtm_dir / "define.yaml"
            if sdtm_path.exists():
                print(f"Warning: {sdtm_path} already exists — skipping.")
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
            if adam_path.exists():
                print(f"Warning: {adam_path} already exists — skipping.")
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


def _run_init_ct_pipeline(args: argparse.Namespace) -> None:
    from .core.study_context import load_study_context
    from .ct.api import CDISCClient
    from .ct.generator import CodelistGenerator, extract_concept_ids

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
    with CDISCClient() as client:
        gen = CodelistGenerator.from_concept_ids(
            client,
            all_ids,
            package=cfg.ct.package,
            include_docs=not args.no_docs,
        )
        dest = gen.write(output)

    print(f"Generated {len(gen._codelists)} codelists → {dest}")


# ── Standalone commands ─────────────────────────────────────────────── #


def _run_init_ct(args: argparse.Namespace) -> None:
    from .ct.api import CDISCClient
    from .ct.generator import CodelistGenerator

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
    from .ct.api import CDISCClient
    from .ct.generator import (
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


def _run_install_engine(args: argparse.Namespace) -> None:
    from .validation.engine import install_engine

    try:
        install_engine(version=args.version, force=args.force)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        sys.exit(1)


def _run_uninstall_engine() -> None:
    from .validation.engine import uninstall_engine

    uninstall_engine()


def _run_doctor() -> None:
    from .validation.engine import doctor

    checks = doctor()
    print("Fleet Doctor")
    print("=" * 40)
    for name, status in checks.items():
        print(f"  {name:.<20s} {status}")
    print()


def _run_define_xml(args: argparse.Namespace) -> None:
    from .define_xml.spec_generator import DefineSpecGenerator

    spec = Path(args.spec)
    output = Path(args.output)

    if not spec.is_file():
        print(f"Error: spec file not found: {spec}")
        sys.exit(1)

    print(f"Spec:     {spec}")
    print(f"Output:   {output}")
    print()

    gen = DefineSpecGenerator(str(spec))
    gen.generate(str(output), html_preview=not args.no_preview)
    print(f"Generated Define-XML → {output}")
    if not args.no_preview:
        preview = output.with_name(output.stem + "_preview.html")
        print(f"HTML preview → {preview}")


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
        else:
            # Show init subcommand help
            parser.parse_args(["init", "--help"])
    elif args.command == "init-ct":
        _run_init_ct(args)
    elif args.command == "add-ct":
        _run_add_ct(args)
    elif args.command == "define-xml":
        _run_define_xml(args)
    elif args.command == "install-engine":
        _run_install_engine(args)
    elif args.command == "uninstall-engine":
        _run_uninstall_engine()
    elif args.command == "doctor":
        _run_doctor()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
