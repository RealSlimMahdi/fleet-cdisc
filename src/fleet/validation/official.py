"""Official CDISC Rules Engine integration via subprocess."""

import ast
import json
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

import polars as pl

from fleet.validation.engine import discover_engine
from fleet.validation.models import RuleSource, Severity, ValidationIssue, ValidationResult


def _resolve_variable_field(item: dict) -> str | None:
    """Resolve the engine's variables/values pair into a human-readable string.

    The engine returns template parameter names (e.g. ``$dataset_variables``)
    in ``variables`` and actual values in a parallel ``values`` list.
    For missing-variable rules (CORE-000334, CORE-000355) we compute the
    set difference. For everything else, we join the resolved values.
    """
    raw_vars = item.get("variables", item.get("Variables"))
    raw_vals = item.get("values", item.get("Values"))

    # Simple case: variables is a plain string (not a template)
    if isinstance(raw_vars, str):
        return raw_vars or None

    # Not a list or empty → nothing to show
    if not isinstance(raw_vars, list) or not raw_vars:
        return None

    # If all entries are $-prefixed templates, resolve from values
    all_templates = all(isinstance(v, str) and v.startswith("$") for v in raw_vars)
    if not all_templates:
        # Non-template list — just join as-is
        return ", ".join(str(v) for v in raw_vars) or None

    # We have template variables — use values for resolution
    if not isinstance(raw_vals, list) or len(raw_vals) != len(raw_vars):
        # Can't resolve — show template names without $
        return ", ".join(v.lstrip("$") for v in raw_vars)

    # Build a name→value map
    resolved = dict(zip(raw_vars, raw_vals))

    # Special handling for missing-variable rules
    rule_id = item.get("core_id", "")
    if rule_id in ("CORE-000334", "CORE-000355"):
        # Compute which variables are missing
        dataset_vars = _parse_list_string(resolved.get("$dataset_variables", ""))
        expected_key = (
            "$expected_variables" if "$expected_variables" in resolved else "$required_variables"
        )
        expected_vars = _parse_list_string(resolved.get(expected_key, ""))
        missing = sorted(set(expected_vars) - set(dataset_vars))
        if missing:
            return ", ".join(missing)
        # Fallback: show expected vars
        return ", ".join(expected_vars) if expected_vars else None

    # Generic: show the resolved values joined
    parts = []
    for val in raw_vals:
        parsed = _parse_list_string(val)
        if parsed:
            parts.extend(parsed)
        elif val:
            parts.append(str(val))
    return ", ".join(parts) or None


def _parse_list_string(s: str) -> list[str]:
    """Safely parse a string like "['VAR1', 'VAR2']" into a list."""
    if not s:
        return []
    try:
        result = ast.literal_eval(s)
        if isinstance(result, list):
            return [str(x) for x in result]
    except (ValueError, SyntaxError):
        pass
    return [s]


def _build_result(
    dataset_name: str,
    dataset_type: str,
    model_version: str,
    errors: list[ValidationIssue] | None = None,
    warnings: list[ValidationIssue] | None = None,
    infos: list[ValidationIssue] | None = None,
) -> ValidationResult:
    errors = errors or []
    warnings = warnings or []
    infos = infos or []
    return ValidationResult(
        dataset_name=dataset_name,
        dataset_type=dataset_type,
        model_version=model_version,
        total_issues=len(errors) + len(warnings) + len(infos),
        errors=errors,
        warnings=warnings,
        infos=infos,
    )


class OfficialCDISCValidator:
    """Wrapper for the official CDISC Rules Engine CLI.

    Discovers the engine automatically via ``discover_engine()``
    (env var → ``~/.fleet/bin/core`` → legacy ``../cdisc-rules-engine/core.py``),
    or accepts an explicit *rules_engine_path*.
    """

    def __init__(self, rules_engine_path: Path | None = None) -> None:
        if rules_engine_path is not None:
            self._executable = Path(rules_engine_path)
            if not self._executable.is_file():
                raise FileNotFoundError(f"CDISC Rules Engine not found at {self._executable}.")
        else:
            found = discover_engine()
            if found is None:
                raise FileNotFoundError(
                    "CDISC Rules Engine not found.\n\n"
                    "Install it with:\n"
                    "  fleet install-engine\n\n"
                    "Or set FLEET_RULES_ENGINE to the path of an existing binary/script."
                )
            self._executable = found

        self._is_legacy = self._executable.suffix == ".py"

    def _build_cmd(self, *args: str) -> list[str]:
        """Build the subprocess command list."""
        if self._is_legacy:
            return ["python", str(self._executable), *args]
        return [str(self._executable), *args]

    @property
    def _cwd(self) -> str:
        """Working directory for subprocess.

        The CDISC Rules Engine binary resolves ``resources/templates/``
        relative to its working directory, so we always ``cd`` into the
        directory that contains the executable.
        """
        return str(self._executable.parent)

    def validate_dataset(
        self,
        data: pl.DataFrame,
        standard: str,
        version: str,
        dataset_name: str = "dataset",
        domain: str | None = None,
        custom_rules: Path | None = None,
        timeout: float = 300,
    ) -> ValidationResult:
        """Run CDISC rules engine validation on a Polars DataFrame.

        With *custom_rules*, the official and the custom rules run in two
        engine runs, because CORE runs only the ``-lr`` rules when given.
        """
        name = domain or "unknown"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            dataset_path = tmpdir_path / f"{dataset_name}.json"
            self._write_dataset_json(data, dataset_path, domain=domain or dataset_name)
            outcomes = self._run_sources(
                ["-dp", str(dataset_path)], standard, version, custom_rules, timeout, tmpdir_path
            )
        return _join_sources(
            (
                source,
                {name: self._parse_validation_result(outcome, data, domain)}
                if isinstance(outcome, dict)
                else {name: _result_from_issues(name, standard, version, outcome)},
            )
            for source, outcome in outcomes
        )[name]

    def validate_datasets(
        self,
        datasets: Mapping[str, pl.DataFrame],
        standard: str,
        version: str,
        custom_rules: Path | None = None,
        timeout: float = 300,
    ) -> dict[str, ValidationResult]:
        """Validate several datasets of one standard in one engine run.

        All datasets are written to one directory, so rules that span
        several datasets can execute.  The one engine report is split into
        one result per dataset.  With *custom_rules*, a second engine run
        executes the custom rules, and its findings join the same results.

        Args:
            datasets: Dataset name (``"AE"``) to its frame.
            standard: Engine standard, ``"sdtmig"`` or ``"adamig"``.
            version: Engine IG version, dashed (``"3-4"``).
            custom_rules: Directory of custom CORE rules.
            timeout: Seconds before the engine run is stopped.

        Returns:
            dict[str, ValidationResult]: One result per dataset name.  A
            finding the report attributes to no given dataset gets its own
            result under the name the report uses.

        Examples:
            Validate DM and AE together, then read the AE result::

                validator = OfficialCDISCValidator(Path("~/.fleet/core"))
                results = validator.validate_datasets(
                    {"DM": dm, "AE": ae}, standard="sdtmig", version="3-4"
                )
                results["AE"].is_valid
        """
        names = list(datasets)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            data_dir = tmpdir_path / "data"
            data_dir.mkdir()
            for name, df in datasets.items():
                self._write_dataset_json(df, data_dir / f"{name}.json", domain=name)
            outcomes = self._run_sources(
                ["-d", str(data_dir)], standard, version, custom_rules, timeout, tmpdir_path
            )
        return _join_sources(
            (
                source,
                _split_validation_result(outcome, names)
                if isinstance(outcome, dict)
                else {
                    name: _result_from_issues(name, standard, version, outcome) for name in names
                },
            )
            for source, outcome in outcomes
        )

    def _run_sources(
        self,
        data_args: list[str],
        standard: str,
        version: str,
        custom_rules: Path | None,
        timeout: float,
        workdir: Path,
    ) -> list[tuple[RuleSource, dict | list[ValidationIssue]]]:
        """Run the official rules, then the custom rules when given: one engine run each."""
        runs: list[tuple[RuleSource, Path | None]] = [("official", None)]
        if custom_rules is not None:
            runs.append(("custom", custom_rules))
        return [
            (
                source,
                self._run_engine(data_args, standard, version, rules, timeout, workdir, source),
            )
            for source, rules in runs
        ]

    def _run_engine(
        self,
        data_args: list[str],
        standard: str,
        version: str,
        custom_rules: Path | None,
        timeout: float,
        workdir: Path,
        source: RuleSource = "official",
    ) -> dict | list[ValidationIssue]:
        """Run the engine once: the raw JSON report, or the issues that replace it."""
        output_file = workdir / f"validation_result_{source}"
        cmd = self._build_cmd(
            "validate",
            "-s",
            standard,
            "-v",
            version,
            *data_args,
            "-o",
            str(output_file),
            "-of",
            "JSON",
            "-rr",
        )

        if custom_rules is not None:
            rules_path = Path(custom_rules)
            if not rules_path.exists():
                raise FileNotFoundError(f"Custom rules path does not exist: {rules_path}")
            if not rules_path.is_dir():
                raise NotADirectoryError(f"Custom rules path must be a directory: {rules_path}")
            cmd.extend(["-lr", str(rules_path)])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self._cwd,
                timeout=timeout,
            )
            json_output = output_file.with_suffix(".json")
            if json_output.exists():
                return json.loads(json_output.read_text())

            if result.returncode == 0:
                return [
                    ValidationIssue(
                        severity=Severity.INFO,
                        rule_id="INFO-000",
                        message=f"Validation completed with no issues. {result.stdout.strip()}",
                    )
                ]
            # No output file — engine may have crashed.
            stderr_snippet = result.stderr.strip()[:500]
            msg = f"Engine exited (rc={result.returncode}) but produced no report."
            if stderr_snippet:
                msg += f" stderr: {stderr_snippet}"
            return [ValidationIssue(severity=Severity.ERROR, rule_id="ENGINE-001", message=msg)]

        except subprocess.TimeoutExpired:
            return [
                ValidationIssue(
                    severity=Severity.ERROR,
                    rule_id="TIMEOUT-001",
                    message=f"Validation timed out after {timeout:.0f}s.",
                    suggested_fix="Try a smaller dataset or increase the timeout.",
                )
            ]
        except Exception as exc:
            return [
                ValidationIssue(
                    severity=Severity.ERROR,
                    rule_id="ERROR-001",
                    message=f"Validation error: {exc}",
                )
            ]

    @staticmethod
    def _write_dataset_json(df: pl.DataFrame, path: Path, *, domain: str) -> None:
        from fleet.io.dataset_json import save_dataset_json

        save_dataset_json(df, path, domain=domain)

    @staticmethod
    def _parse_validation_result(
        data: dict,
        df: pl.DataFrame,
        domain: str | None,
    ) -> ValidationResult:
        """Parse the CDISC Rules Engine raw JSON report.

        The engine ``-rr`` (raw report) JSON has these top-level keys:

        * ``Conformance_Details`` — metadata (engine version, standard, …)
        * ``Dataset_Details``     — file / dataset info
        * ``Issue_Summary``       — one row per rule that reported issues
        * ``Issue_Details``       — one row per individual finding
        * ``Rules_Report``        — execution status of every rule
        * ``results_data``        — raw results (legacy / internal)

        When validating a single dataset, the engine still evaluates ALL
        rules for the standard. This parser filters out:

        - Engine-internal crashes and build failures (always noise).
        - Rule evaluation/execution errors (rule couldn't run — expected
          when other datasets aren't present).
        - SKIPPED rules from ``Rules_Report`` (rules for other domains
          that couldn't fire — expected in single-dataset validation).
        """
        name = domain or "unknown"
        return _parse_report(data, [name], lambda _item: name)[name]


def _split_validation_result(data: dict, names: list[str]) -> dict[str, ValidationResult]:
    """Split one multi-dataset engine report into one result per dataset.

    The engine names the dataset of each finding in its ``dataset`` field,
    as the file name (``ae.json``) or the dataset name (``AE``).
    """
    known = {name.upper(): name for name in names}

    def dataset_of(item: dict) -> str:
        raw = item.get("dataset", item.get("Dataset"))
        stem = Path(str(raw)).stem.upper() if raw else "UNKNOWN"
        return known.get(stem, stem)

    return _parse_report(data, names, dataset_of)


def _parse_report(
    data: dict, names: list[str], dataset_of: Callable[[dict], str]
) -> dict[str, ValidationResult]:
    """Parse a raw engine report into one result per dataset *dataset_of* names."""
    conformance = data.get("Conformance_Details", {})
    dataset_type = conformance.get("Standard", "unknown").lower()
    model_version = conformance.get("Version", "unknown").lower()

    issues: dict[str, list[ValidationIssue]] = {name: [] for name in names}

    # ── Issue_Details: one entry per individual finding ──────────
    for item in data.get("Issue_Details", []):
        message = item.get("message", item.get("Message", "No message"))
        if _is_engine_noise(message):
            continue

        severity_str = item.get("Severity", item.get("severity", "WARNING")).upper()
        try:
            severity = Severity[severity_str]
        except KeyError:
            severity = Severity.WARNING

        issues.setdefault(dataset_of(item), []).append(
            ValidationIssue(
                severity=severity,
                rule_id=item.get("core_id", item.get("Rule", "UNKNOWN")),
                message=message,
                variable=_resolve_variable_field(item),
                rows_affected=_safe_int(item.get("row", item.get("Rows"))),
            )
        )

    # ── Issue_Summary: real findings aggregated per rule ─────────
    for item in data.get("Issue_Summary", []):
        rule_id = item.get("core_id", "UNKNOWN")
        message = item.get("message", "")
        if _is_engine_noise(message):
            continue
        # Issue_Summary is a rollup of Issue_Details: add a rule only once.
        found = issues.setdefault(dataset_of(item), [])
        if rule_id not in {i.rule_id for i in found if i.severity != Severity.INFO}:
            found.append(
                ValidationIssue(severity=Severity.WARNING, rule_id=rule_id, message=message)
            )

    # ── Rules_Report: intentionally NOT surfacing SKIPPED rules ──
    # When validating a single dataset, hundreds of rules for other
    # domains are skipped. Surfacing them would flood the report with
    # irrelevant noise.  Structural issues (missing required variables)
    # are already captured via Issue_Details (CORE-000334, CORE-000355).

    return {
        name: _result_from_issues(name, dataset_type, model_version, found)
        for name, found in issues.items()
    }


def _join_sources(
    runs: Iterable[tuple[RuleSource, dict[str, ValidationResult]]],
) -> dict[str, ValidationResult]:
    """Join the results of the official and custom runs, tagging each finding with its run.

    The type and version of a dataset come from its first run, the official one.
    """
    found: dict[str, list[ValidationIssue]] = {}
    meta: dict[str, tuple[str, str]] = {}
    for source, results in runs:
        for name, result in results.items():
            meta.setdefault(name, (result.dataset_type, result.model_version))
            for issue in (*result.errors, *result.warnings, *result.infos):
                issue.source = source
                found.setdefault(name, []).append(issue)
    return {name: _result_from_issues(name, *meta[name], found.get(name, [])) for name in meta}


def _result_from_issues(
    dataset_name: str, dataset_type: str, model_version: str, issues: list[ValidationIssue]
) -> ValidationResult:
    return _build_result(
        dataset_name=dataset_name,
        dataset_type=dataset_type,
        model_version=model_version,
        errors=[i for i in issues if i.severity == Severity.ERROR],
        warnings=[i for i in issues if i.severity == Severity.WARNING],
        infos=[i for i in issues if i.severity == Severity.INFO],
    )


def _safe_int(val: object) -> int | None:
    """Coerce *val* to int, returning ``None`` on failure."""
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# Patterns that indicate engine-internal noise rather than real data issues.
# When validating a single dataset, the engine runs ALL rules for the
# standard.  Rules that reference missing datasets produce these messages.
_ENGINE_NOISE_PATTERNS = (
    "evaluation dataset failed to build",
    "rule evaluation error",
    "rule execution error",
    "operation failed",
    "An unknown exception has occurred",
)


def _is_engine_noise(message: str) -> bool:
    """Return ``True`` if *message* is engine-internal noise.

    These are messages produced when the CDISC Rules Engine cannot
    execute a rule (missing datasets, internal errors).  They are not
    real data-quality findings and should be suppressed.
    """
    msg = message.lower()
    return any(p.lower() in msg for p in _ENGINE_NOISE_PATTERNS)
