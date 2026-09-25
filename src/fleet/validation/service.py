"""Unified validation service."""

from collections.abc import Mapping
from pathlib import Path

import polars as pl

from fleet.validation.models import ValidationResult
from fleet.validation.providers import OfficialRulesEngineProvider, ValidationProvider


class ValidationService:
    """Single entrypoint for SDTM/ADaM dataset validation."""

    def __init__(
        self,
        provider: ValidationProvider | None = None,
        rules_engine_path: Path | None = None,
    ) -> None:
        if provider is not None:
            self.provider = provider
        else:
            self.provider = OfficialRulesEngineProvider(rules_engine_path=rules_engine_path)

    def validate_sdtm(
        self,
        df: pl.DataFrame | pl.LazyFrame,
        domain: str,
        version: str,
        custom_rules: Path | str | None = None,
    ) -> ValidationResult:
        if isinstance(df, pl.LazyFrame):
            df = df.collect()
        resolved = Path(custom_rules) if custom_rules is not None else None
        return self.provider.validate_sdtm(
            df=df, domain=domain, version=version, custom_rules=resolved
        )

    def validate_adam(
        self,
        df: pl.DataFrame | pl.LazyFrame,
        dataset: str,
        version: str,
        custom_rules: Path | str | None = None,
    ) -> ValidationResult:
        if isinstance(df, pl.LazyFrame):
            df = df.collect()
        resolved = Path(custom_rules) if custom_rules is not None else None
        return self.provider.validate_adam(
            df=df, dataset=dataset, version=version, custom_rules=resolved
        )

    def validate_datasets(
        self,
        datasets: Mapping[str, pl.DataFrame],
        standard: str,
        version: str,
        custom_rules: Path | str | None = None,
    ) -> dict[str, ValidationResult]:
        """Validate several datasets of one standard together, in one engine run.

        Args:
            datasets: Dataset name (``"AE"``) to its frame.
            standard: ``"sdtm"`` or ``"adam"``.
            version: IG version, ``"3.4"`` or ``"3-4"``.
            custom_rules: Directory of custom CORE rules.

        Returns:
            dict[str, ValidationResult]: One result per dataset name.

        Examples:
            The engine sees DM and AE together::

                results = ValidationService().validate_datasets(
                    {"DM": dm, "AE": ae}, standard="sdtm", version="3.4"
                )
                results["AE"].print_report()
        """
        resolved = Path(custom_rules) if custom_rules is not None else None
        return self.provider.validate_datasets(
            datasets, standard=standard, version=version, custom_rules=resolved
        )
