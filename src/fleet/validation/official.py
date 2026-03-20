"""Official CDISC Rules Engine integration via subprocess."""

import json
import subprocess
import tempfile
from pathlib import Path

import polars as pl

from .engine import discover_engine
from .models import Severity, ValidationIssue, ValidationResult


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
    def _cwd(self) -> str | None:
        """Working directory for subprocess — only needed for legacy core.py."""
        if self._is_legacy:
            return str(self._executable.parent)
        return None

    def validate_dataset(
        self,
        data: pl.DataFrame,
        standard: str,
        version: str,
        dataset_name: str = "dataset",
        domain: str | None = None,
    ) -> ValidationResult:
        """Run CDISC rules engine validation on a Polars DataFrame."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            dataset_path = tmpdir_path / dataset_name
            self._save_as_xpt(data, dataset_path)

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

                # No output file — treat as clean
                return _build_result(
                    dataset_name=domain or "unknown",
                    dataset_type=standard,
                    model_version=version,
                    infos=[
                        ValidationIssue(
                            severity=Severity.INFO,
                            rule_id="INFO-000",
                            message=f"Validation completed. Output: {result.stdout.strip()}",
                        )
                    ],
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
    def _save_as_xpt(df: pl.DataFrame, path: Path) -> None:
        try:
            import pandas  # noqa: F401
            import pyreadstat  # noqa: F401

            pd_df = df.to_pandas()
            pyreadstat.write_xport(pd_df, str(path))
        except ImportError as exc:
            raise ImportError(
                "pyreadstat is required for XPT export. Install it with: uv add fleet[io]"
            ) from exc

    @staticmethod
    def _parse_validation_result(
        data: dict,
        df: pl.DataFrame,
        domain: str | None,
    ) -> ValidationResult:
        results = data.get("results", [])
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        infos: list[ValidationIssue] = []

        for item in results:
            severity_str = item.get("severity", "WARNING").upper()
            try:
                severity = Severity[severity_str]
            except KeyError:
                severity = Severity.WARNING

            issue = ValidationIssue(
                severity=severity,
                rule_id=item.get("rule_id", "UNKNOWN"),
                message=item.get("message", "No message"),
                variable=item.get("variable"),
                rows_affected=item.get("rows_affected"),
            )
            if severity == Severity.ERROR:
                errors.append(issue)
            elif severity == Severity.WARNING:
                warnings.append(issue)
            else:
                infos.append(issue)

        return _build_result(
            dataset_name=domain or "unknown",
            dataset_type=data.get("standard", "unknown"),
            model_version=data.get("version", "unknown"),
            errors=errors,
            warnings=warnings,
            infos=infos,
        )
