"""Validation provider abstractions."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
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

    def validate_datasets(
        self,
        datasets: Mapping[str, pl.DataFrame],
        standard: str,
        version: str,
        custom_rules: Path | None = None,
    ) -> dict[str, ValidationResult]:
        """Validate several datasets of one standard; one at a time unless overridden."""
        validate = self.validate_adam if standard == "adam" else self.validate_sdtm
        return {
            name: validate(df, name, version, custom_rules=custom_rules)
            for name, df in datasets.items()
        }


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

    def validate_datasets(
        self,
        datasets: Mapping[str, pl.DataFrame],
        standard: str,
        version: str,
        custom_rules: Path | None = None,
    ) -> dict[str, ValidationResult]:
        return self.validator.validate_datasets(
            datasets,
            standard=f"{standard}ig",
            version=version.replace(".", "-"),
            custom_rules=custom_rules,
        )
