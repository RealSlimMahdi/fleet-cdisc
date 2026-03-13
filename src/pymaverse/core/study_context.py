"""Study-level configuration and path resolution utilities.

Adapted from pharmaversepy study/config.py.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class StudyPathConfig(BaseModel):
    """Relative path definitions for a study workspace."""

    raw_data: str = Field(default="data/raw")
    sdtm_data: str = Field(default="data/sdtm")
    adam_data: str = Field(default="data/adam")
    metadata_sdtm: str = Field(default="metadata/sdtm")
    metadata_adam: str = Field(default="metadata/adam")
    define_xml: str = Field(default="metadata")
    outputs: str = Field(default="outputs")


class StudyConfig(BaseModel):
    """Top-level study configuration model."""

    study_id: str
    company: str | None = None
    paths: StudyPathConfig = Field(default_factory=StudyPathConfig)


class StudyConfigError(Exception):
    """Raised when study configuration cannot be loaded or validated."""


class StudyContext:
    """Runtime context that resolves configured study paths."""

    def __init__(self, study_root: Path, config: StudyConfig) -> None:
        self.study_root = study_root
        self.config = config

    @property
    def study_id(self) -> str:
        return self.config.study_id

    def resolve(self, relative_path: str) -> Path:
        """Resolve a configured relative path under study root."""
        return (self.study_root / relative_path).resolve()

    @property
    def raw_data_dir(self) -> Path:
        return self.resolve(self.config.paths.raw_data)

    @property
    def sdtm_data_dir(self) -> Path:
        return self.resolve(self.config.paths.sdtm_data)

    @property
    def adam_data_dir(self) -> Path:
        return self.resolve(self.config.paths.adam_data)

    @property
    def metadata_sdtm_dir(self) -> Path:
        return self.resolve(self.config.paths.metadata_sdtm)

    @property
    def metadata_adam_dir(self) -> Path:
        return self.resolve(self.config.paths.metadata_adam)

    @property
    def define_xml_dir(self) -> Path:
        return self.resolve(self.config.paths.define_xml)

    @property
    def outputs_dir(self) -> Path:
        return self.resolve(self.config.paths.outputs)

    def raw_file(self, file_name: str) -> Path:
        return self.raw_data_dir / file_name

    def sdtm_file(self, file_name: str) -> Path:
        return self.sdtm_data_dir / file_name

    def adam_file(self, file_name: str) -> Path:
        return self.adam_data_dir / file_name

    def sdtm_spec(self, file_name: str) -> Path:
        return self.metadata_sdtm_dir / file_name

    def adam_spec(self, file_name: str) -> Path:
        return self.metadata_adam_dir / file_name

    def define_yaml(self, file_name: str = "define.yaml") -> Path:
        return self.define_xml_dir / file_name

    def define_schema(self, file_name: str = "define_xml_2_1_schema.json") -> Path:
        return self.define_xml_dir / file_name


def load_study_context(config_path: Path) -> StudyContext:
    """Load study configuration and return a resolved context.

    Args:
        config_path: Path to study_config.yaml

    Returns:
        StudyContext with resolved paths

    Raises:
        StudyConfigError: If the config file is missing or invalid
    """
    if not config_path.exists():
        raise StudyConfigError(f"Study configuration file not found: {config_path}")

    try:
        with open(config_path) as f:
            config_data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise StudyConfigError(f"Invalid YAML in study configuration: {e}") from e

    try:
        config = StudyConfig(**config_data)
    except Exception as e:
        raise StudyConfigError(f"Invalid study configuration schema: {e}") from e

    return StudyContext(study_root=config_path.parent, config=config)
