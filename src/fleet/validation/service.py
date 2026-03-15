"""Unified validation service."""

from pathlib import Path
from typing import Optional

import polars as pl

from .models import ValidationResult
from .providers import ValidationProvider, ValidationProviderRegistry


class ValidationService:
    """Single entrypoint for SDTM/ADaM dataset validation."""

    def __init__(
        self,
        provider: Optional[ValidationProvider] = None,
        provider_name: str = "official",
        rules_engine_path: Optional[Path] = None,
    ) -> None:
        if provider is not None:
            self.provider = provider
        else:
            self.provider = ValidationProviderRegistry.create(
                provider_name=provider_name,
                rules_engine_path=rules_engine_path,
            )

    def validate_sdtm(
        self,
        df: pl.DataFrame | pl.LazyFrame,
        domain: str,
        version: str = "3.4",
    ) -> ValidationResult:
        if isinstance(df, pl.LazyFrame):
            df = df.collect()
        return self.provider.validate_sdtm(df=df, domain=domain, version=version)

    def validate_adam(
        self,
        df: pl.DataFrame | pl.LazyFrame,
        dataset: str,
        version: str = "1.3",
    ) -> ValidationResult:
        if isinstance(df, pl.LazyFrame):
            df = df.collect()
        return self.provider.validate_adam(df=df, dataset=dataset, version=version)
