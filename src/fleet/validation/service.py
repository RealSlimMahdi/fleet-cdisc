"""Unified validation service."""

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
