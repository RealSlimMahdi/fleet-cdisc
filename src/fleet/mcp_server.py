"""Fleet MCP server — expose existing Fleet public APIs as MCP tools.

Launched with ``fleet mcp --stdio`` (requires the ``mcp`` extra).  Every
tool is a thin, JSON-friendly wrapper over an API that already exists in
Fleet — nothing is duplicated here.  The tool functions are plain module
functions so they can be called (and tested) without a running server;
:func:`create_server` registers them on a ``FastMCP`` instance whose tool
descriptions come straight from the docstrings below.

Examples:
    Serve Fleet to any MCP-capable assistant::

        uv run fleet mcp --stdio

    Call a tool function directly (no server needed)::

        from fleet.mcp_server import fleet_execution_order

        order = fleet_execution_order(
            ["examples/cdiscpilot01/sdtm/define.yaml"]
        )
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    import polars as pl


def _load_frame(path: str) -> pl.DataFrame:
    """Load a dataset file (CSV / Parquet / XPT / SAS) as a DataFrame."""
    from fleet.io import load_raw_data

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"dataset file not found: {p}")
    return load_raw_data(p).collect()


def fleet_execution_order(spec_paths: list[str]) -> list[str]:
    """Return the safe topological execution order for a study pipeline.

    Builds the dataset dependency DAG from one or more ``define.yaml``
    spec files (SDTM, ADaM, or a mix) and returns every node — raw
    sources and derived datasets — in an order that respects ``inputs:``
    dependencies.

    Args:
        spec_paths: Paths to ``define.yaml`` files spanning the pipeline.

    Returns:
        list[str]: Node names in safe execution order
            (e.g. ``["dm_raw", "DM", "ADSL", ...]``).
    """
    from fleet.core.dag import build_dag

    return build_dag(*spec_paths).execution_order()


def fleet_impacted_by(spec_paths: list[str], node: str) -> list[str]:
    """Return every pipeline node that must re-run when *node* changes.

    Args:
        spec_paths: Paths to ``define.yaml`` files spanning the pipeline.
        node: Name of the changed node (raw source like ``dm_raw`` or
            dataset like ``DM``).

    Returns:
        list[str]: The impacted nodes (including *node* itself) in safe
            re-run order.
    """
    from fleet.core.dag import build_dag

    return build_dag(*spec_paths).impacted_by(node)


def fleet_lineage(dag_json_path: str, dataset: str) -> dict[str, Any]:
    """Return one dataset's node record from a ``pipeline_dag.json`` file.

    The file is written by ``build_dag(...).generate(path)`` after a
    pipeline run; dataset records carry ``inputs``, ``path`` and — when
    the pipeline was materialised — per-variable lineage (producing
    verb, source columns, dotted method path).

    Args:
        dag_json_path: Path to a generated ``pipeline_dag.json``.
        dataset: Node name to look up (e.g. ``"ADSL"``).

    Returns:
        dict: The node record (``node_type``, ``path``, ``inputs``, and
            ``variables`` when runtime lineage was captured).
    """
    payload = json.loads(Path(dag_json_path).read_text(encoding="utf-8"))
    nodes: dict[str, Any] = payload.get("nodes", payload)
    node = nodes.get(dataset)
    if node is None:
        raise ValueError(f"dataset {dataset!r} not in {dag_json_path}. Known: {sorted(nodes)}")
    return node


def fleet_validate(
    dataset_path: str,
    standard: str,
    version: str | None = None,
) -> dict[str, Any]:
    """Validate a dataset file with the CDISC Rules Engine.

    Requires the engine binary (``fleet install-engine`` or the
    ``FLEET_RULES_ENGINE`` environment variable).

    Args:
        dataset_path: Dataset file (parquet / csv / xpt / sas7bdat); the
            file stem is used as the domain/dataset name.
        standard: ``"sdtm"`` or ``"adam"``.
        version: IG version override (default: 3.4 for SDTM, 1.3 for ADaM).

    Returns:
        dict: ``{"dataset", "standard", "is_valid", "issues": [{severity,
            rule_id, message, variable}, ...]}``.
    """
    from fleet.validation import ValidationService, discover_engine

    engine = discover_engine()
    if engine is None:
        raise RuntimeError(
            "CDISC Rules Engine not found. Install it with `fleet install-engine` "
            "or set FLEET_RULES_ENGINE."
        )
    df = _load_frame(dataset_path)
    name = Path(dataset_path).stem.upper()
    service = ValidationService(rules_engine_path=engine)
    kwargs: dict[str, Any] = {} if version is None else {"version": version}
    if standard == "adam":
        result = service.validate_adam(df, name, **kwargs)
    else:
        result = service.validate_sdtm(df, name, **kwargs)
    return {
        "dataset": result.dataset_name,
        "standard": standard,
        "is_valid": result.is_valid,
        "issues": [
            {
                "severity": issue.severity.value,
                "rule_id": issue.rule_id,
                "message": issue.message,
                "variable": issue.variable,
            }
            for issue in (*result.errors, *result.warnings, *result.infos)
        ],
    }


def fleet_ct_terms(codelist: str, ct_path: str | None = None) -> list[str]:
    """Return the valid submission values of a controlled-terminology codelist.

    Uses the process-wide ``CTValidator`` cache; pass *ct_path* to load a
    CT file (YAML/CSV) into the cache first.

    Args:
        codelist: Codelist name, alias, or NCI concept ID (e.g. ``C66731``).
        ct_path: Optional CT file to load before the lookup.

    Returns:
        list[str]: Sorted valid coded values.
    """
    from fleet.ct.validator import get_validator

    validator = get_validator()
    if ct_path:
        validator.load_ct_file(ct_path)
    if not validator.has_codelist(codelist):
        raise ValueError(
            f"codelist {codelist!r} is not loaded. Pass ct_path=<CT yaml/csv> to load it."
        )
    return validator.get_valid_values(codelist)


def fleet_tlg_catalog() -> list[dict[str, Any]]:
    """List every registered TLG template (id, type, status, domains, title).

    Returns:
        list[dict]: One row per template from ``fleet.tlg.catalog()``.
    """
    from fleet.tlg import catalog

    return catalog().to_dicts()


def fleet_tlg_run(
    spec_path: str,
    data_path: str,
    adsl_path: str | None = None,
    groupby: str | None = None,
) -> str:
    """Execute a YAML TLG spec against a dataset and return rendered HTML.

    Args:
        spec_path: Path to a ``template:``-carrying TLG spec YAML file.
        data_path: Primary analysis dataset file (e.g. ADAE for ``aet01``).
        adsl_path: ADSL dataset file for population denominators
            (tables only; defaults to *data_path* for ADSL templates).
        groupby: Treatment-arm column (default: auto-detect
            TRTA → TRT01A → TRT01P).

    Returns:
        str: The rendered HTML table or listing.
    """
    from fleet.tlg import (
        GROUPBY_CANDIDATES,
        TEMPLATES,
        OutputType,
        RenderMetadata,
        ard_to_table_model,
        detect_groupby,
        listing_to_model,
        load_spec,
        render_html,
        render_listing_html,
        run_spec,
    )

    spec = load_spec(spec_path)
    meta = TEMPLATES[spec.template]
    is_listing = meta.output_type is OutputType.LISTING
    df = _load_frame(data_path)
    adsl = _load_frame(adsl_path) if adsl_path else None
    if adsl is None and meta.domains and meta.domains[-1] == "ADSL":
        adsl = df
    if not is_listing and groupby is None:
        groupby = detect_groupby(df.columns)
        if groupby is None:
            raise ValueError(
                "could not auto-detect a treatment-arm column "
                f"(tried {', '.join(GROUPBY_CANDIDATES)}). Pass groupby=<column>."
            )
    result = run_spec(spec, df, adsl=adsl, groupby=None if is_listing else groupby)
    rmeta = RenderMetadata(title=meta.title)
    if is_listing:
        return render_listing_html(listing_to_model(result, rmeta))
    return render_html(ard_to_table_model(result, rmeta))


def fleet_dataset_check(data_path: str, define_yaml: str, dataset: str) -> dict[str, Any]:
    """Check a dataset file against its ``define.yaml`` declaration.

    Runs Fleet's ``DatasetChecker`` (column completeness, dtype
    compatibility, inline-codelist CT values).

    Args:
        data_path: Dataset file (parquet / csv / xpt / sas7bdat).
        define_yaml: Path to the ``define.yaml`` declaring *dataset*.
        dataset: Dataset name in the define (e.g. ``"DM"``).

    Returns:
        dict: ``{"dataset", "is_valid", "missing_columns",
            "extra_columns", "type_mismatches", "errors", "warnings",
            "info"}``.
    """
    from fleet.define_xml import DatasetChecker

    df = _load_frame(data_path)
    result = DatasetChecker(define_yaml).check(df, dataset)
    return {
        "dataset": result.dataset,
        "is_valid": result.is_valid,
        "missing_columns": result.missing_columns,
        "extra_columns": result.extra_columns,
        "type_mismatches": [
            {"variable": m.variable, "define_type": m.define_type, "actual_dtype": m.actual_dtype}
            for m in result.type_mismatches
        ],
        "errors": result.errors,
        "warnings": result.warnings,
        "info": result.info,
    }


#: Every function exposed as an MCP tool (docstring = tool description).
TOOLS = (
    fleet_execution_order,
    fleet_impacted_by,
    fleet_lineage,
    fleet_validate,
    fleet_ct_terms,
    fleet_tlg_catalog,
    fleet_tlg_run,
    fleet_dataset_check,
)


def create_server() -> FastMCP:
    """Build the Fleet ``FastMCP`` server with every tool registered.

    Returns:
        FastMCP: Server ready for ``.run(transport="stdio")``.
    """
    server = FastMCP(
        "fleet",
        instructions=(
            "Fleet CDISC toolkit: pipeline DAG queries, dataset validation, "
            "controlled-terminology lookups, and TLG spec execution."
        ),
    )
    for fn in TOOLS:
        server.tool()(fn)
    return server


def main() -> None:
    """Run the Fleet MCP server over stdio (entry point for ``fleet mcp``)."""
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
