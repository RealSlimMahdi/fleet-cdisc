"""Pipeline DAG — build and query dataset dependency graphs from define.yaml specs.

Usage
-----
    from pymaverse.core import build_dag

    dag = build_dag(
        "specs/cdiscpilot01/sdtm/define.yaml",
        "specs/cdiscpilot01/adam/define.yaml",
        output_dir="outputs/cdiscpilot01",
    )

    # What needs to run if AE changes?
    dag.impacted_by("ae_raw")        # → ["ae_raw", "AE", "ADAE", ...]

    # Safe execution order for the whole pipeline
    dag.execution_order()            # → ["dm_raw", "DM", "ae_raw", "AE", ...]

    # Export for external orchestrators
    dag.to_snakemake()               # → {name: {"input": [...], "output": path}}
    dag.to_airflow()                 # → {task_id: [upstream_task_ids]}
    dag.to_dict()                    # → JSON-serializable adjacency dict
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ─────────────────────────────────────────────────────────── data model ── #


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
    """

    name: str
    node_type: str
    path: str | None
    inputs: list[str]


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
            raise KeyError(
                f"Node '{name}' not found in DAG. "
                f"Available nodes: {sorted(self.nodes)}"
            )

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
        Directory where derived dataset outputs land (used to resolve the
        ``path`` of non-raw nodes via the convention
        ``{output_dir}/{name.lower()}.parquet``).
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
    ...     "specs/cdiscpilot01/sdtm/define.yaml",
    ...     "specs/cdiscpilot01/adam/define.yaml",
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

            output_path = str(out_dir / f"{ds_name.lower()}.parquet")
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
