"""Validation provider abstractions."""

from abc import ABC, abstractmethod
from pathlib import Path

import polars as pl

from fleet.validation.models import ValidationResult
from fleet.validation.official import OfficialCDISCValidator


class ValidationProvider(ABC):
    """Abstract interface for dataset validation providers."""

    @abstractmethod
    def validate_sdtm(
        self,
        df: pl.DataFrame,
        domain: str,
        version: str,
        custom_rules: Path | None = None,
    ) -> ValidationResult:
        pass

    @abstractmethod
    def validate_adam(
        self,
        df: pl.DataFrame,
        dataset: str,
        version: str,
        custom_rules: Path | None = None,
    ) -> ValidationResult:
        pass


class OfficialRulesEngineProvider(ValidationProvider):
    """Validation backed by the official CDISC Rules Engine."""

    def __init__(self, rules_engine_path: Path | None = None) -> None:
        self.validator = OfficialCDISCValidator(rules_engine_path=rules_engine_path)

    def validate_sdtm(
        self,
        df: pl.DataFrame,
        domain: str,
        version: str,
        custom_rules: Path | None = None,
    ) -> ValidationResult:
        return self.validator.validate_dataset(
            data=df,
            standard="sdtmig",
            version=version.replace(".", "-"),
            dataset_name=domain.upper(),
            domain=domain,
            custom_rules=custom_rules,
        )

    def validate_adam(
        self,
        df: pl.DataFrame,
        dataset: str,
        version: str,
        custom_rules: Path | None = None,
    ) -> ValidationResult:
        return self.validator.validate_dataset(
            data=df,
            standard="adamig",
            version=version.replace(".", "-"),
            dataset_name=dataset.upper(),
            domain=dataset,
            custom_rules=custom_rules,
        )
