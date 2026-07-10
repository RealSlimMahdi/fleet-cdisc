"""Pipeline DAG — build and query dataset dependency graphs from define.yaml specs.

Usage
-----
    from fleet.core import build_dag

    dag = build_dag(
        "examples/cdiscpilot01/sdtm/define.yaml",
        "examples/cdiscpilot01/adam/define.yaml",
        output_dir="outputs/cdiscpilot01",
    )

    # What needs to run if AE changes?
    dag.impacted_by("ae_raw")        # → ["ae_raw", "AE", "ADAE", ...]

    # Safe execution order for the whole pipeline
    dag.execution_order()            # → ["dm_raw", "DM", "ae_raw", "AE", ...]

    # Export for external orchestrators
    dag.to_snakefile("Snakefile")    # → executable Snakefile (fleet run per rule)
    dag.to_airflow_dag(path="dags/study.py")  # → executable Airflow DAG module
    dag.to_snakemake()               # → {name: {"input": [...], "output": path}}
    dag.to_airflow()                 # → {task_id: [upstream_task_ids]}
    dag.to_dict()                    # → JSON-serializable adjacency dict
"""

from __future__ import annotations

import warnings
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: File extension per supported export format (spec key ``output_format``).
_OUTPUT_FORMAT_EXT: dict[str, str] = {
    "parquet": ".parquet",
    "xpt": ".xpt",
    "dataset-json": ".json",
}

# ─────────────────────────────────────────────────────────── data model ── #


@dataclass
class PinDependency:
    """A cross-domain dependency recorded when a verb consumes a pinned domain.

    Attributes:
        target_col: Output column produced by the verb (e.g. ``"AESTDY"``).
        target_domain: Domain of the pipeline that consumed the pin
            (e.g. ``"AE"``).
        verb: Fleet verb that triggered the pin access
            (e.g. ``"study_day"``).
        source_domain: Pinned domain that was consulted (e.g. ``"DM"``).
        source_cols: Columns read from the pinned frame
            (e.g. ``["RFSTDTC"]``).
        join_key: Join key(s) used to align frames
            (e.g. ``["USUBJID"]``).
        relationship: Semantic tag — ``"derivation"``, ``"fk_check"``,
            or ``"carry_forward"``.
    """

    target_col: str
    target_domain: str | None
    verb: str
    source_domain: str
    source_cols: list[str]
    join_key: list[str]
    relationship: str = "derivation"


@dataclass
class VariableNode:
    """A single derived variable inside a dataset node.

    Captures variable-level lineage so the DAG is navigable down to the
    individual column: each entry records the verb that produced the
    column, the source columns it consumed, and a dotted Python path to
    the verb method (suitable for IDE / MkDocs cross-linking).

    Attributes:
        name: Output column name (e.g. ``"TRTSDT"``).
        verb: Fleet verb that produced the column (e.g. ``"first_date"``).
        sources: Upstream column names consumed by the verb.
        method: Fully-qualified Python path to the verb method
            (e.g. ``"fleet.adam.adsl_namespace.ADSLNamespace.first_date"``).
        domain: Optional CDISC domain code (e.g. ``"DM"``, ``"ADAE"``).
            Set automatically when the producing namespace has domain
            context; ``None`` otherwise.
        pin_sources: Cross-domain dependencies recorded by pin-consuming
            verbs.  Empty for purely intra-frame derivations.
        params: Verb keyword arguments captured at call time (only
            YAML-serialisable, non-default values).  ``None`` when the
            producing verb did not expose its parameters.  Consumed by
            ``to_spec_yaml()`` to reconstruct ``derivation:`` blocks.
        spec: Ready-made define.yaml ``derivation:`` block when the
            variable was produced by ``from_spec()`` (the validated spec
            fields round-trip verbatim).  Takes precedence over *params*.
    """

    name: str
    verb: str
    sources: list[str]
    method: str
    domain: str | None = None
    pin_sources: list[PinDependency] = field(default_factory=list)
    params: dict[str, Any] | None = None
    spec: dict[str, Any] | None = None

    @property
    def cdisc_ref(self) -> str:
        """Full-derivation CDISC notation for this variable.

        Format: ``[DOMAIN].VAR ← verb(src1, src2)`` when *domain* is set,
        or ``VAR ← verb(src1, src2)`` otherwise.
        """
        prefix = f"[{self.domain}].{self.name}" if self.domain else self.name
        args = ", ".join(self.sources) if self.sources else ""
        return f"{prefix} ← {self.verb}({args})"


@dataclass
class PipelineNode:
    """A single node in the pipeline DAG.

    Attributes
    ----------
    name:
        Logical node name — dataset name (e.g. ``"DM"``, ``"ADSL"``) or
        raw source identifier (e.g. ``"dm_raw"``).
    node_type:
        One of ``"raw"``, ``"sdtm"``, ``"adam"``, ``"send"``, ``"unknown"``.
    path:
        For **raw** nodes: the source file path (csv, xpt, sas7bdat, parquet…).
        For **dataset** nodes: the derived output path (resolved from *output_dir*).
        ``None`` if neither the spec nor a convention can determine it.
    inputs:
        Ordered list of upstream node names this node depends on.
    variables:
        Optional variable-level lineage captured at runtime by the
        SDTM/ADaM namespaces; empty for nodes built from spec only.
    """

    name: str
    node_type: str
    path: str | None
    inputs: list[str]
    variables: dict[str, VariableNode] = field(default_factory=dict)


@dataclass
class PipelineDAG:
    """Directed Acyclic Graph of pipeline dataset dependencies.

    Build with :func:`build_dag` rather than constructing directly.
    """

    nodes: dict[str, PipelineNode] = field(default_factory=dict)

    # ── queries ─────────────────────────────────────────────────────────── #

    def execution_order(self) -> list[str]:
        """Return all node names in a safe topological execution order.

        Uses Kahn's algorithm (BFS on in-degree).

        Raises
        ------
        ValueError
            If the graph contains a cycle (should have been caught by
            :func:`build_dag`, but re-checked here for safety).
        """
        in_degree: dict[str, int] = {n: 0 for n in self.nodes}
        for node in self.nodes.values():
            for upstream in node.inputs:
                if upstream in in_degree:
                    in_degree[node.name] += 1

        queue: deque[str] = deque(n for n, deg in in_degree.items() if deg == 0)
        order: list[str] = []

        while queue:
            n = queue.popleft()
            order.append(n)
            for downstream in self._downstream(n):
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)

        if len(order) != len(self.nodes):
            raise ValueError("DAG contains a cycle — cannot produce a linear execution order.")

        return order

    def impacted_by(self, name: str) -> list[str]:
        """Return all nodes that must be rerun when *name* changes.

        Performs a BFS downstream from *name*, then returns the results
        in topological execution order so callers get a ready-made run
        schedule.

        Parameters
        ----------
        name:
            Logical node name (dataset or raw source) that changed.

        Returns
        -------
        list[str]
            Topologically-ordered list of node names to rerun, inclusive
            of *name* itself.

        Raises
        ------
        KeyError
            If *name* is not a node in this DAG.
        """
        if name not in self.nodes:
            raise KeyError(f"Node '{name}' not found in DAG. Available nodes: {sorted(self.nodes)}")

        visited: set[str] = set()
        queue: deque[str] = deque([name])
        while queue:
            n = queue.popleft()
            if n in visited:
                continue
            visited.add(n)
            queue.extend(self._downstream(n))

        return [n for n in self.execution_order() if n in visited]

    def _downstream(self, name: str) -> list[str]:
        """Direct downstream dependents of *name* (nodes that list it in inputs)."""
        return [n.name for n in self.nodes.values() if name in n.inputs]

    # ── lineage injection ───────────────────────────────────────────────── #

    def inject_lineage(self, namespace: Any, dataset_name: str) -> None:
        """Merge variable-level and pin lineage from *namespace* into the DAG.

        Populates ``variables`` on the node named *dataset_name* (when a
        variable was derived more than once, the last derivation wins —
        matching what the materialised frame actually contains) and, for
        each ``PinDependency``, adds the pinned source domain to the
        node's ``inputs`` if it is not already present (creating the
        cross-domain edge in the DAG).

        Declared ``inputs:`` are reconciled against the runtime pin
        evidence in both directions:

        * a dataset-type input declared in the spec but never consulted
          at runtime emits a ``UserWarning`` (stale declaration);
        * a runtime pin source missing from the declaration emits a
          ``UserWarning`` *and* the edge is added (the DAG follows the
          evidence).

        Raw inputs carry no pin evidence and are exempt from the
        declared-but-unused check.

        Args:
            namespace: A namespace instance with ``_lineage`` and
                optionally ``_pin_lineage`` attributes.
            dataset_name: The logical node name to attach lineage to.
        """
        node = self.nodes.get(dataset_name)
        if node is None:
            return

        from fleet.core.lineage import lineage_of, pin_lineage_of

        declared = list(node.inputs)

        # Merge intra-frame variable lineage (last write wins per target)
        for vnode in lineage_of(namespace):
            node.variables[vnode.name] = vnode

        # Merge pin lineage → enrich variable nodes + add DAG edges
        runtime_domains: set[str] = set()
        for pdep in pin_lineage_of(namespace):
            runtime_domains.add(pdep.source_domain)
            if pdep.target_col in node.variables:
                vnode = node.variables[pdep.target_col]
                vnode.pin_sources.append(pdep)
            # Ensure the source domain is an input edge
            if pdep.source_domain in self.nodes and pdep.source_domain not in node.inputs:
                warnings.warn(
                    f"inject_lineage('{dataset_name}'): runtime evidence shows a "
                    f"dependency on '{pdep.source_domain}' (via {pdep.verb}) that is "
                    f"not declared in the spec's inputs: {declared}. "
                    f"Adding the edge; declare it in the define.yaml to silence this.",
                    stacklevel=2,
                )
                node.inputs.append(pdep.source_domain)

        # Reverse direction: declared dataset inputs with no runtime evidence.
        for name in declared:
            upstream = self.nodes.get(name)
            if upstream is not None and upstream.node_type == "raw":
                continue  # raw sources are consumed as columns, not pins
            if name not in runtime_domains:
                warnings.warn(
                    f"inject_lineage('{dataset_name}'): input '{name}' is declared "
                    f"in the spec but no runtime pin/lineage evidence consumed it. "
                    f"Remove the declaration or check the pipeline wiring.",
                    stacklevel=2,
                )

    def trace(self, dataset: str, variable: str) -> list[dict[str, Any]]:
        """Return the full recursive provenance chain for a single variable.

        Walks the variable's ``sources`` transitively — including
        cross-domain pin sources into other DAG nodes — collecting every
        upstream *derived* variable exactly once (cycle-safe, deduped).
        Raw/leaf columns appear inside each entry's ``sources`` but do
        not get entries of their own.

        Args:
            dataset: Logical node name (e.g. ``"AE"``).
            variable: Column name (e.g. ``"AESTDY"``).

        Returns:
            list[dict]: Depth-first provenance entries from the output
                variable back to its sources, each with ``dataset``,
                ``name``, ``verb``, ``sources``, ``domain``, and
                ``pin_sources``.
        """
        chain: list[dict[str, Any]] = []
        visited: set[tuple[str, str]] = set()
        self._trace_into(dataset, variable, chain, visited)
        return chain

    def _trace_into(
        self,
        dataset: str,
        variable: str,
        chain: list[dict[str, Any]],
        visited: set[tuple[str, str]],
    ) -> None:
        """DFS helper for :meth:`trace` — appends entries in pre-order."""
        key = (dataset, variable)
        if key in visited:
            return
        visited.add(key)

        node = self.nodes.get(dataset)
        if node is None:
            return
        vnode = node.variables.get(variable)
        if vnode is None:
            return  # leaf: raw column or variable without lineage

        chain.append(
            {
                "dataset": dataset,
                "name": vnode.name,
                "verb": vnode.verb,
                "sources": vnode.sources,
                "domain": vnode.domain,
                "pin_sources": [
                    {
                        "source_domain": p.source_domain,
                        "source_cols": p.source_cols,
                        "join_key": p.join_key,
                        "relationship": p.relationship,
                    }
                    for p in vnode.pin_sources
                ],
            }
        )

        # Columns attributed to a pinned domain recurse into that domain,
        # not into the local frame (the local copy is a join artefact).
        pinned_cols: set[str] = set()
        for pdep in vnode.pin_sources:
            for col in pdep.source_cols:
                pinned_cols.add(col)
                self._trace_into(pdep.source_domain, col, chain, visited)

        for src in vnode.sources:
            if src not in pinned_cols:
                self._trace_into(dataset, src, chain, visited)

    # ── export ──────────────────────────────────────────────────────────── #

    def to_dict(self) -> dict:
        """Return a JSON-serializable adjacency representation.

        Shape::

            {
              "dm_raw": {"node_type": "raw",  "path": "datasets/.../dm_raw.csv", "inputs": []},
              "DM":     {"node_type": "sdtm", "path": "outputs/.../dm.parquet",  "inputs": ["dm_raw"]},
              "ADSL":   {"node_type": "adam", "path": "outputs/.../adsl.parquet","inputs": ["DM"]},
              ...
            }
        """
        return {
            name: {
                "node_type": node.node_type,
                "path": node.path,
                "inputs": node.inputs,
                **(
                    {
                        "variables": {
                            v.name: {
                                "verb": v.verb,
                                "sources": v.sources,
                                "method": v.method,
                                "cdisc_ref": v.cdisc_ref,
                                **(
                                    {
                                        "pin_sources": [
                                            {
                                                "source_domain": p.source_domain,
                                                "source_cols": p.source_cols,
                                                "join_key": p.join_key,
                                                "relationship": p.relationship,
                                            }
                                            for p in v.pin_sources
                                        ]
                                    }
                                    if v.pin_sources
                                    else {}
                                ),
                            }
                            for v in node.variables.values()
                        }
                    }
                    if node.variables
                    else {}
                ),
            }
            for name, node in self.nodes.items()
        }

    def to_snakemake(self) -> dict:
        """Return a Snakemake-compatible rule dict.

        Each entry maps a logical name to ``{"input": [...paths...], "output": path}``.
        Drop this into a Snakefile generator to produce concrete rules::

            for name, rule in dag.to_snakemake().items():
                # rule["input"]  → list of input file paths
                # rule["output"] → output file path

        Raw nodes are included with an empty ``input`` list and the source
        file as ``output``, so Snakemake can model them as source checkpoints.
        """
        rules: dict[str, dict] = {}
        for name, node in self.nodes.items():
            input_paths: list[str] = []
            for upstream_name in node.inputs:
                upstream = self.nodes.get(upstream_name)
                if upstream and upstream.path:
                    input_paths.append(upstream.path)
                else:
                    input_paths.append(upstream_name)
            rules[name] = {
                "input": input_paths,
                "output": node.path,
                "node_type": node.node_type,
            }
        return rules

    def to_airflow(self) -> dict:
        """Return an Airflow-compatible task dependency dict.

        Shape::

            {
              "DM":   [],           # no upstream tasks
              "ADSL": ["DM"],
              "ADVS": ["VS", "ADSL"],
            }

        Wire operators in a DAG file with::

            for task_id, upstreams in dag.to_airflow().items():
                for u in upstreams:
                    tasks[u] >> tasks[task_id]
        """
        return {name: list(node.inputs) for name, node in self.nodes.items()}

    @staticmethod
    def _task_id(name: str) -> str:
        """Dataset name → safe Python/Snakemake identifier."""
        import re

        return re.sub(r"\W", "_", name.lower())

    def to_snakefile(self, path: str | Path | None = None) -> str:
        """Render an executable ``Snakefile`` — one rule per derived dataset.

        Each rule declares its upstream files as ``input:``, the dataset file
        as ``output:``, and shells out to ``fleet run --dataset <NAME>`` — so
        Snakemake provides incremental re-execution while Fleet does the
        derivation (study_config.yaml discovery applies as usual).

        Parameters
        ----------
        path:
            Optional destination; when given the Snakefile is also written
            there.

        Example
        -------
        ::

            dag = build_dag("metadata/sdtm/define.yaml", "metadata/adam/define.yaml",
                            output_dir="data")
            dag.to_snakefile("Snakefile")
            # then:  snakemake -j1
        """
        derived = {n: node for n, node in self.nodes.items() if node.node_type != "raw"}
        outputs = [node.path or f"{self._task_id(n)}.parquet" for n, node in derived.items()]
        lines = [
            "# Snakefile generated by Fleet (PipelineDAG.to_snakefile) — do not hand-edit.",
            "# Each rule shells out to `fleet run`; run from the study root so",
            "# study_config.yaml discovery resolves the configured paths.",
            "",
            "rule all:",
            "    input:",
            *[f"        {p!r}," for p in outputs],
            "",
        ]
        for name, node in derived.items():
            inputs = [(self.nodes[u].path or u) if u in self.nodes else u for u in node.inputs]
            lines += [
                f"rule {self._task_id(name)}:",
                "    input:",
                *[f"        {p!r}," for p in inputs],
                "    output:",
                f"        {(node.path or f'{self._task_id(name)}.parquet')!r},",
                "    shell:",
                f'        "fleet run --dataset {name}"',
                "",
            ]
        text = "\n".join(lines)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def to_airflow_dag(self, dag_id: str = "fleet_pipeline", path: str | Path | None = None) -> str:
        """Render an executable Airflow DAG module — one BashOperator per dataset.

        The generated module imports Airflow, declares one ``BashOperator``
        running ``fleet run --dataset <NAME>`` per derived dataset, and wires
        the ``>>`` dependencies from the define.yaml ``inputs:`` blocks. Drop
        the file into your Airflow ``dags/`` folder.

        Parameters
        ----------
        dag_id:
            The Airflow DAG id (default ``"fleet_pipeline"``).
        path:
            Optional destination; when given the module is also written there.

        Example
        -------
        ::

            dag = build_dag("metadata/sdtm/define.yaml", "metadata/adam/define.yaml")
            dag.to_airflow_dag(dag_id="mystudy", path="dags/mystudy.py")
        """
        derived = {n: node for n, node in self.nodes.items() if node.node_type != "raw"}
        lines = [
            '"""Airflow DAG generated by Fleet (PipelineDAG.to_airflow_dag) — do not hand-edit."""',
            "",
            "from datetime import datetime",
            "",
            "from airflow import DAG",
            "from airflow.operators.bash import BashOperator",
            "",
            f"with DAG(dag_id={dag_id!r}, start_date=datetime(2024, 1, 1),",
            "         schedule=None, catchup=False) as dag:",
        ]
        for name in derived:
            lines.append(
                f"    {self._task_id(name)} = BashOperator("
                f"task_id={name!r}, bash_command='fleet run --dataset {name}')"
            )
        lines.append("")
        for name, node in derived.items():
            for upstream in node.inputs:
                if upstream in derived:
                    lines.append(f"    {self._task_id(upstream)} >> {self._task_id(name)}")
        text = "\n".join(lines) + "\n"
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def generate(self, output_path: str | Path) -> None:
        """Write the DAG to *output_path* as a JSON file.

        The file contains the full adjacency representation produced by
        :meth:`to_dict` plus the topological execution order, so it is
        self-contained and can be consumed by external tools without needing
        to re-parse the define YAMLs.

        Parameters
        ----------
        output_path:
            Destination path for the ``.json`` file (e.g.
            ``outputs/cdiscpilot01/pipeline_dag.json``).

        Example
        -------
        ::

            dag = build_dag(
                "examples/cdiscpilot01/sdtm/define.yaml",
                "examples/cdiscpilot01/adam/define.yaml",
                output_dir="outputs/cdiscpilot01",
            )
            dag.generate("outputs/cdiscpilot01/pipeline_dag.json")
        """
        import json

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "execution_order": self.execution_order(),
            "nodes": self.to_dict(),
            "snakemake": self.to_snakemake(),
            "airflow": self.to_airflow(),
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Pipeline DAG generated: {out}")


# ───────────────────────────────────────────────────────── build_dag() ── #


def build_dag(
    *spec_paths: str | Path,
    output_dir: str | Path | None = None,
) -> PipelineDAG:
    """Build a :class:`PipelineDAG` from one or more ``define.yaml`` spec files.

    Parameters
    ----------
    *spec_paths:
        Paths to ``define.yaml`` files (SDTM, ADaM, SEND, or any mix).
        Pass multiple files to span an entire study pipeline.
    output_dir:
        Directory where derived dataset outputs land.  A dataset's
        ``path`` is resolved from, in order: the per-dataset ``output:``
        key (relative paths are joined onto *output_dir*), then the
        convention ``{output_dir}/{name.lower()}{ext}`` where *ext*
        follows the per-dataset or spec-level ``output_format:`` key
        (``parquet`` → ``.parquet`` by default, ``xpt`` → ``.xpt``,
        ``dataset-json`` → ``.json``).
        Defaults to the parent directory of the *first* spec file.

    Returns
    -------
    PipelineDAG
        Validated, cycle-free DAG ready for querying.

    Raises
    ------
    ValueError
        If any ``inputs`` entry references an unknown node, or if the
        resulting graph contains a cycle.
    FileNotFoundError
        If a spec path does not exist.

    Examples
    --------
    >>> dag = build_dag(
    ...     "examples/cdiscpilot01/sdtm/define.yaml",
    ...     "examples/cdiscpilot01/adam/define.yaml",
    ...     output_dir="outputs/cdiscpilot01",
    ... )
    >>> dag.impacted_by("ae_raw")
    ['ae_raw', 'AE']
    >>> dag.execution_order()
    ['dm_raw', 'ae_raw', 'vs_raw', 'DM', 'AE', 'VS', 'ADSL', 'ADVS']
    """
    if not spec_paths:
        raise ValueError("At least one spec_path must be provided.")

    resolved = [Path(p) for p in spec_paths]
    for p in resolved:
        if not p.exists():
            raise FileNotFoundError(f"Spec file not found: {p}")

    out_dir = Path(output_dir) if output_dir else resolved[0].parent

    nodes: dict[str, PipelineNode] = {}

    for spec_path in resolved:
        with spec_path.open("r", encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)

        standard = spec.get("study", {}).get("standard", "")
        node_type = _standard_to_node_type(standard)
        spec_format: str = spec.get("output_format", "parquet")

        for dataset in spec.get("datasets", []):
            ds_name: str = dataset["name"]
            ds_inputs: list[str] = []

            for inp in dataset.get("inputs", []):
                inp_name: str = inp["name"]
                inp_type: str = inp.get("type", "dataset")
                inp_path: str | None = inp.get("path")

                # Register raw sources on first encounter only
                if inp_type == "raw" and inp_name not in nodes:
                    nodes[inp_name] = PipelineNode(
                        name=inp_name,
                        node_type="raw",
                        path=inp_path,
                        inputs=[],
                    )

                ds_inputs.append(inp_name)

            declared_output: str | None = dataset.get("output")
            if declared_output:
                declared = Path(declared_output)
                output_path = str(declared if declared.is_absolute() else out_dir / declared)
            else:
                fmt = dataset.get("output_format", spec_format)
                ext = _OUTPUT_FORMAT_EXT.get(fmt, ".parquet")
                output_path = str(out_dir / f"{ds_name.lower()}{ext}")
            nodes[ds_name] = PipelineNode(
                name=ds_name,
                node_type=node_type,
                path=output_path,
                inputs=ds_inputs,
            )

    _validate(nodes)
    return PipelineDAG(nodes=nodes)


# ─────────────────────────────────────────────────────────── internals ── #


def _standard_to_node_type(standard: str) -> str:
    return {"SDTMIG": "sdtm", "ADAMIG": "adam", "SENDIG": "send"}.get(standard, "unknown")


def _validate(nodes: dict[str, PipelineNode]) -> None:
    """Validate the graph: all references resolve and there are no cycles."""
    # 1. Check all input references exist
    for node in nodes.values():
        for upstream in node.inputs:
            if upstream not in nodes:
                raise ValueError(
                    f"Node '{node.name}' references unknown input '{upstream}'. "
                    "Declare it in one of the spec files under 'inputs' with type: raw, "
                    "or ensure the dataset is defined in a loaded spec."
                )

    # 2. Cycle detection via DFS coloring (white=0, gray=in-progress, black=done)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in nodes}

    # Build downstream adjacency: for each node, who depends on it?
    downstream: dict[str, list[str]] = {n: [] for n in nodes}
    for node in nodes.values():
        for upstream in node.inputs:
            downstream[upstream].append(node.name)

    def _dfs(n: str, path: list[str]) -> None:
        color[n] = GRAY
        path.append(n)
        for child in downstream[n]:
            if color[child] == GRAY:
                cycle_str = " → ".join(path + [child])
                raise ValueError(f"DAG cycle detected: {cycle_str}")
            if color[child] == WHITE:
                _dfs(child, path)
        path.pop()
        color[n] = BLACK

    for n in list(nodes):
        if color[n] == WHITE:
            _dfs(n, [])
