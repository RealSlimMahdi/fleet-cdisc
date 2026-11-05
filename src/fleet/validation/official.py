"""Official CDISC Rules Engine integration via subprocess."""

import ast
import json
import os
import re
import signal
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import yaml

from fleet.validation.engine import discover_engine
from fleet.validation.models import (
    RuleRun,
    RuleSource,
    Severity,
    ValidationIssue,
    ValidationResult,
)

#: ``Rules_Report`` statuses of a rule the engine executed.
_EXECUTED_STATUSES = frozenset({"SUCCESS", "ISSUE_REPORTED"})

#: What CORE says when its rule cache has nothing for the standard and version.
_NO_RULES = "No rules were selected"

_ERROR_LINE = re.compile(r"^[A-Za-z_.]*(Error|Exception)\b.*")


def _error_line(stderr: str) -> str | None:
    """Return the last ``SomethingError: ...`` line of a Python traceback, or ``None``."""
    found = [line.strip() for line in stderr.splitlines() if _ERROR_LINE.match(line.strip())]
    return found[-1] if found else None


@dataclass(frozen=True)
class _CouldNotRun:
    """An engine run that gave no report Fleet can read."""

    reason: str


def _run_command(cmd: list[str], *, cwd: str, timeout: float) -> subprocess.CompletedProcess[str]:
    """Run *cmd* in its own process group, and stop the whole group on timeout.

    CORE starts worker processes; ``subprocess.run`` stops only the parent,
    so the workers kept running after a timeout.

    Raises:
        subprocess.TimeoutExpired: After every process of the group is stopped.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # Windows: no process groups
            proc.kill()
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


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
    (env var → ``~/.fleet/cdisc-rules-engine/core/core`` → legacy
    ``../cdisc-rules-engine/core.py``), or accepts an explicit *rules_engine_path*.
    """

    def __init__(self, rules_engine_path: Path | None = None) -> None:
        if rules_engine_path is not None:
            self._executable = Path(rules_engine_path).resolve()
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
            self._executable = found.resolve()

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
                else {name: _could_not_run_result(name, standard, version, outcome)},
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
        define_xml: Path | None = None,
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
            define_xml: A Define-XML file each engine run checks with the
                datasets (``-dxp``), or ``None``.

        Returns:
            dict[str, ValidationResult]: One result per dataset name.  A
            finding the report attributes to no given dataset gets its own
            result under the name the report uses.

        Examples:
            Validate DM and AE together, then read the AE result::

                validator = OfficialCDISCValidator(
                    Path("~/.fleet/cdisc-rules-engine/core/core").expanduser()
                )
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
            define_args = ["-dxp", str(define_xml)] if define_xml is not None else []
            outcomes = self._run_sources(
                ["-d", str(data_dir), *define_args],
                standard,
                version,
                custom_rules,
                timeout,
                tmpdir_path,
            )
        return _join_sources(
            (
                source,
                _split_validation_result(outcome, names)
                if isinstance(outcome, dict)
                else {
                    name: _could_not_run_result(name, standard, version, outcome) for name in names
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
    ) -> list[tuple[RuleSource, dict | _CouldNotRun]]:
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
    ) -> dict | _CouldNotRun:
        """Run the engine once: its JSON report, or why it could not run.

        The return code is read first: CORE 0.17 writes half a report
        before it fails, and that half must not be read as a clean run.
        """
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
        )

        if custom_rules is not None:
            # The engine runs in its own folder: a relative path is the user's, so resolve it here.
            rules_path = Path(custom_rules).resolve()
            if not rules_path.exists():
                raise FileNotFoundError(f"Custom rules path does not exist: {rules_path}")
            if not rules_path.is_dir():
                raise NotADirectoryError(f"Custom rules path must be a directory: {rules_path}")
            cmd.extend(["-lr", str(rules_path)])

        try:
            result = _run_command(cmd, cwd=self._cwd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return _CouldNotRun(
                f"the engine did not finish within {timeout:g} s. Raise validation.timeout "
                "in study_config.yaml, or pass --timeout to fleet validate."
            )
        except OSError as exc:
            return _CouldNotRun(f"the engine could not start: {exc}")
        if result.returncode != 0:
            error = _error_line(result.stderr)
            if error is not None and _NO_RULES in error:
                # CORE 0.16+ stops when its cache has no rule for the standard.
                return {"Rules_Report": [], "_fleet_note": error}
            tail = error or result.stderr.strip()[-500:]
            return _CouldNotRun(
                f"the engine exited with code {result.returncode}" + (f": {tail}" if tail else ".")
            )
        json_output = output_file.with_suffix(".json")
        if not json_output.exists():
            return _CouldNotRun("the engine exited with code 0 but wrote no report.")
        try:
            data = json.loads(json_output.read_text(encoding="utf-8"))
        except ValueError as exc:
            return _CouldNotRun(f"the engine report is not valid JSON: {exc}")
        if not isinstance(data, dict) or not {"Issue_Details", "Rules_Report"} & data.keys():
            return _CouldNotRun(
                "the engine report has no Issue_Details and no Rules_Report: "
                "Fleet cannot read this CORE report format."
            )
        if custom_rules is not None:
            data["_fleet_not_loaded"] = _not_loaded(rules_path, data.get("Rules_Report") or [])
        return data

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
        """Parse the CDISC Rules Engine JSON report of a single-dataset run.

        The JSON report has these top-level keys:

        * ``Conformance_Details`` — metadata (engine version, standard, …)
        * ``Dataset_Details``     — file / dataset info
        * ``Issue_Summary``       — one row per rule that reported issues
        * ``Issue_Details``       — one row per individual finding
        * ``Rules_Report``        — execution status of every rule

        When validating a single dataset, the engine still evaluates ALL
        rules for the standard.  A rule with status ``EXECUTION_ERROR`` in
        ``Rules_Report`` could not run (often because a dataset it needs
        is absent): its rows are left out of the findings and the rule is
        counted as "could not run".  ``SKIPPED`` rules are only counted.
        The filter reads the rule status, never the message text.

        A study-level finding (dataset ``STUDY``) is kept as information:
        one dataset cannot show whether the study lacks a domain.
        """
        name = domain or "unknown"
        return _parse_report(data, [name], lambda _item: name, study_is_info=True)[name]


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
    data: dict,
    names: list[str],
    dataset_of: Callable[[dict], str],
    *,
    study_is_info: bool = False,
) -> dict[str, ValidationResult]:
    """Parse an engine report into one result per dataset *dataset_of* names.

    CORE gives no severity, so every finding blocks until the study
    accepts it (ADR-0017).
    """
    conformance = data.get("Conformance_Details", {})
    dataset_type = conformance.get("Standard", "unknown").lower()
    model_version = conformance.get("Version", "unknown").lower()
    rules_report = data.get("Rules_Report")
    run = _rule_run(data, rules_report) if isinstance(rules_report, list) else None
    # A row of a rule that could not run is the engine's error, not a data finding.
    failed_rules = set(run.could_not_run) if run is not None else set()

    issues: dict[str, list[ValidationIssue]] = {name: [] for name in names}
    note = data.get("_fleet_note")
    if note:
        for found in issues.values():
            found.append(ValidationIssue(Severity.INFO, "NOT-ASSESSED", f"CORE: {note}"))

    def place(item: dict, issue: ValidationIssue) -> None:
        if study_is_info and str(item.get("dataset", "")).upper() == "STUDY":
            issue.severity = Severity.INFO
            issue.message += " (study-level rule: not assessable in a single-dataset run)"
        issues.setdefault(dataset_of(item), []).append(issue)

    # ── Issue_Details: one entry per individual finding ──────────
    for item in data.get("Issue_Details", []):
        if item.get("core_id") in failed_rules:
            continue
        message = item.get("message", item.get("Message", "No message"))
        place(
            item,
            ValidationIssue(
                severity=Severity.ERROR,
                rule_id=item.get("core_id", item.get("Rule", "UNKNOWN")),
                message=message,
                variable=_resolve_variable_field(item),
                rows_affected=_safe_int(item.get("row", item.get("Rows"))),
            ),
        )

    # ── Issue_Summary: real findings aggregated per rule ─────────
    for item in data.get("Issue_Summary", []):
        rule_id = item.get("core_id", "UNKNOWN")
        message = item.get("message", "")
        if rule_id in failed_rules:
            continue
        # Issue_Summary is a rollup of Issue_Details: add a rule only once.
        if rule_id not in {i.rule_id for i in issues.get(dataset_of(item), [])}:
            place(item, ValidationIssue(severity=Severity.ERROR, rule_id=rule_id, message=message))

    # ── Rules_Report: counted per run, never turned into findings ──
    # A skipped rule is expected (no dataset in scope, or a permissive
    # variable not collected), and a rule that could not run is a rule
    # problem: the CLI and HTML report list them apart from the findings.
    runs = [run] if run is not None else []
    return {
        name: _result_from_issues(name, dataset_type, model_version, found, runs)
        for name, found in issues.items()
    }


def _status(row: dict) -> str:
    """A Rules_Report status, one spelling: CORE 0.16 writes ``EXECUTION ERROR``."""
    return str(row.get("status", "")).upper().replace(" ", "_")


def _rule_run(data: dict, rules_report: list[dict]) -> RuleRun:
    """Count the rules of one engine run by status, and name those that could not run."""
    statuses = {row.get("core_id", "UNKNOWN"): _status(row) for row in rules_report}
    failed = [rid for rid, status in statuses.items() if status == "EXECUTION_ERROR"]
    reasons: dict[str, str] = {}
    for item in data.get("Issue_Details", []):
        rid, values = item.get("core_id"), item.get("values")
        if rid in failed and rid not in reasons:
            reasons[rid] = values if isinstance(values, str) and values else item.get("message")
    return RuleRun(
        executed=sum(status in _EXECUTED_STATUSES for status in statuses.values()),
        skipped=sum(status == "SKIPPED" for status in statuses.values()),
        could_not_run={rid: reasons.get(rid) or "no reason given" for rid in failed},
        not_loaded=list(data.get("_fleet_not_loaded", [])),
    )


def _not_loaded(rules_dir: Path, rules_report: list[dict]) -> list[str]:
    """The custom rules the engine did not load: an ID absent from its report, or a bad file."""
    reported = {row.get("core_id") for row in rules_report}
    missing = []
    for path in sorted([*rules_dir.glob("*.yaml"), *rules_dir.glob("*.yml")]):
        try:
            rule_id = yaml.safe_load(path.read_text(encoding="utf-8"))["Core"]["Id"]
        except (yaml.YAMLError, TypeError, KeyError, OSError):
            missing.append(path.name)
            continue
        if rule_id not in reported:
            missing.append(str(rule_id))
    return missing


def _join_sources(
    runs: Iterable[tuple[RuleSource, dict[str, ValidationResult]]],
) -> dict[str, ValidationResult]:
    """Join the results of the official and custom runs, tagging each finding with its run.

    The type and version of a dataset come from its first run, the official one.
    The rule runs of both sources are kept; a run that could not run makes the
    dataset could not run.
    """
    found: dict[str, list[ValidationIssue]] = {}
    meta: dict[str, tuple[str, str]] = {}
    rule_runs: dict[str, list[RuleRun]] = {}
    failed: dict[str, list[str]] = {}
    for source, results in runs:
        for name, result in results.items():
            meta.setdefault(name, (result.dataset_type, result.model_version))
            for run in result.rule_runs:
                run.source = source
                rule_runs.setdefault(name, []).append(run)
            if result.could_not_run is not None:
                failed.setdefault(name, []).append(f"{source} run: {result.could_not_run}")
            for issue in (*result.errors, *result.warnings, *result.infos):
                issue.source = source
                found.setdefault(name, []).append(issue)
    joined = {
        name: _result_from_issues(name, *meta[name], found.get(name, []), rule_runs.get(name, []))
        for name in meta
    }
    for name, reasons in failed.items():
        joined[name].could_not_run = " ".join(reasons)
    return joined


def _could_not_run_result(
    name: str, standard: str, version: str, outcome: _CouldNotRun
) -> ValidationResult:
    result = _result_from_issues(name, standard, version, [])
    result.could_not_run = outcome.reason
    return result


def _result_from_issues(
    dataset_name: str,
    dataset_type: str,
    model_version: str,
    issues: list[ValidationIssue],
    rule_runs: list[RuleRun] | None = None,
) -> ValidationResult:
    result = _build_result(
        dataset_name=dataset_name,
        dataset_type=dataset_type,
        model_version=model_version,
        errors=[i for i in issues if i.severity == Severity.ERROR],
        warnings=[i for i in issues if i.severity == Severity.WARNING],
        infos=[i for i in issues if i.severity == Severity.INFO],
    )
    result.rule_runs = list(rule_runs or [])
    result.rules_executed = sum(r.executed for r in result.rule_runs) if rule_runs else None
    return result


def _safe_int(val: object) -> int | None:
    """Coerce *val* to int, returning ``None`` on failure."""
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None
