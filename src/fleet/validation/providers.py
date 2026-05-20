"""Validation provider abstractions and registry."""

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
        version: str = "3.4",
        custom_rules: Path | None = None,
    ) -> ValidationResult:
        pass

    @abstractmethod
    def validate_adam(
        self,
        df: pl.DataFrame,
        dataset: str,
        version: str = "1.3",
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
        version: str = "3.4",
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
        version: str = "1.3",
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


class ValidationProviderRegistry:
    """Registry for selecting validation providers by name."""

    _providers: dict[str, type[ValidationProvider]] = {
        "official": OfficialRulesEngineProvider,
    }

    @classmethod
    def create(cls, provider_name: str = "official", **kwargs) -> ValidationProvider:
        provider_cls = cls._providers.get(provider_name)
        if provider_cls is None:
            available = ", ".join(sorted(cls._providers.keys()))
            raise ValueError(
                f"Unknown validation provider '{provider_name}'. Available: {available}"
            )
        return provider_cls(**kwargs)
