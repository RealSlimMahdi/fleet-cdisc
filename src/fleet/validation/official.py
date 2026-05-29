"""Official CDISC Rules Engine integration via subprocess."""

import json
import subprocess
import tempfile
from pathlib import Path

import polars as pl

from fleet.validation.engine import discover_engine
from fleet.validation.models import Severity, ValidationIssue, ValidationResult


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
    ) -> ValidationResult:
        """Run CDISC rules engine validation on a Polars DataFrame."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            dataset_path = tmpdir_path / f"{dataset_name}.json"
            self._write_dataset_json(data, dataset_path, domain=domain or dataset_name)

            output_file = tmpdir_path / "validation_result"
            cmd = self._build_cmd(
                "validate",
                "-s",
                standard,
                "-v",
                version,
                "-dp",
                str(dataset_path),
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
                    timeout=300,
                )
                json_output = output_file.with_suffix(".json")
                if json_output.exists():
                    validation_data = json.loads(json_output.read_text())
                    return self._parse_validation_result(validation_data, data, domain)

                # No output file — engine may have crashed.
                stderr_snippet = result.stderr.strip()[:500]
                msg = f"Engine exited (rc={result.returncode}) but produced no report."
                if stderr_snippet:
                    msg += f" stderr: {stderr_snippet}"
                return _build_result(
                    dataset_name=domain or "unknown",
                    dataset_type=standard,
                    model_version=version,
                    errors=[
                        ValidationIssue(
                            severity=Severity.ERROR,
                            rule_id="ENGINE-001",
                            message=msg,
                        )
                    ]
                    if result.returncode != 0
                    else [],
                    infos=[
                        ValidationIssue(
                            severity=Severity.INFO,
                            rule_id="INFO-000",
                            message=f"Validation completed with no issues. {result.stdout.strip()}",
                        )
                    ]
                    if result.returncode == 0
                    else [],
                )

            except subprocess.TimeoutExpired:
                return _build_result(
                    dataset_name=domain or "unknown",
                    dataset_type=standard,
                    model_version=version,
                    errors=[
                        ValidationIssue(
                            severity=Severity.ERROR,
                            rule_id="TIMEOUT-001",
                            message="Validation timed out after 5 minutes.",
                            suggested_fix="Try a smaller dataset or increase the timeout.",
                        )
                    ],
                )
            except Exception as exc:
                return _build_result(
                    dataset_name=domain or "unknown",
                    dataset_type=standard,
                    model_version=version,
                    errors=[
                        ValidationIssue(
                            severity=Severity.ERROR,
                            rule_id="ERROR-001",
                            message=f"Validation error: {exc}",
                        )
                    ],
                )

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
        conformance = data.get("Conformance_Details", {})
        dataset_type = conformance.get("Standard", "unknown").lower()
        model_version = conformance.get("Version", "unknown").lower()

        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        infos: list[ValidationIssue] = []

        # ── Issue_Details: one entry per individual finding ──────────
        for item in data.get("Issue_Details", []):
            rule_id = item.get("core_id", item.get("Rule", "UNKNOWN"))
            message = item.get("message", item.get("Message", "No message"))
            variable = item.get("variables", item.get("Variables")) or None
            rows = _safe_int(item.get("row", item.get("Rows")))

            # Suppress engine-internal noise
            if _is_engine_noise(message):
                infos.append(
                    ValidationIssue(
                        severity=Severity.INFO,
                        rule_id=rule_id,
                        message=message,
                        variable=variable,
                    )
                )
                continue

            severity_str = item.get("Severity", item.get("severity", "WARNING")).upper()
            try:
                severity = Severity[severity_str]
            except KeyError:
                severity = Severity.WARNING

            issue = ValidationIssue(
                severity=severity,
                rule_id=rule_id,
                message=message,
                variable=variable,
                rows_affected=rows,
            )
            if severity == Severity.ERROR:
                errors.append(issue)
            elif severity == Severity.WARNING:
                warnings.append(issue)
            else:
                infos.append(issue)

        # ── Issue_Summary: real findings aggregated per rule ─────────
        for item in data.get("Issue_Summary", []):
            rule_id = item.get("core_id", "UNKNOWN")
            message = item.get("message", "")
            if _is_engine_noise(message):
                continue
            # Deduplicate: Issue_Summary is a rollup of Issue_Details,
            # only add if this rule_id wasn't already seen.
            seen_ids = {i.rule_id for i in errors + warnings}
            if rule_id not in seen_ids:
                issue = ValidationIssue(
                    severity=Severity.WARNING,
                    rule_id=rule_id,
                    message=message,
                )
                warnings.append(issue)

        # ── Rules_Report: intentionally NOT surfacing SKIPPED rules ──
        # When validating a single dataset, hundreds of rules for other
        # domains are skipped. Surfacing them would flood the report with
        # irrelevant noise.  Structural issues (missing required variables)
        # are already captured via Issue_Details (CORE-000334, CORE-000355).

        return _build_result(
            dataset_name=domain or "unknown",
            dataset_type=dataset_type,
            model_version=model_version,
            errors=errors,
            warnings=warnings,
            infos=infos,
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
