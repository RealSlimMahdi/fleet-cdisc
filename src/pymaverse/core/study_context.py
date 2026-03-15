"""Study-level configuration and path resolution utilities.

Adapted from pharmaversepy study/config.py.
"""

import importlib.resources
import os
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

    @classmethod
    def init(
        cls,
        study_root: str | Path,
        study_id: str,
        company: str | None = None,
        paths: "StudyPathConfig | None" = None,
    ) -> "StudyContext":
        """Scaffold a new study workspace and return a ready-to-use StudyContext.

        Creates the directory layout defined by StudyPathConfig, writes
        study_config.yaml, and scaffolds blank define.yaml files for SDTM and ADaM.

        Directories are created silently if they already exist.  If
        study_config.yaml or either define.yaml already exist the method raises
        StudyConfigError without touching any file, to protect in-progress work.

        Args:
            study_root: Root directory for the study (created if absent).
            study_id:   Study identifier (e.g. "STUDY01").
            company:    Optional originator / company name.
            paths:      Custom path config; defaults to StudyPathConfig defaults.

        Returns:
            Initialized StudyContext pointing at the new workspace.

        Raises:
            StudyConfigError: If study_config.yaml or either define.yaml already exist.
        """
        from .._version import __version__

        study_root = Path(study_root).resolve()
        config = StudyConfig(study_id=study_id, company=company, paths=paths or StudyPathConfig())
        ctx = cls(study_root=study_root, config=config)

        # ── Guard: refuse to overwrite existing files ─────────────────────
        config_file = study_root / "study_config.yaml"
        sdtm_define = ctx.metadata_sdtm_dir / "define.yaml"
        adam_define = ctx.metadata_adam_dir / "define.yaml"

        for path in (config_file, sdtm_define, adam_define):
            if path.exists():
                raise StudyConfigError(
                    f"Study already initialized — '{path}' already exists. "
                    "Use load_study_context() to load an existing study."
                )

        # ── Create directory tree (idempotent) ────────────────────────────
        for dir_path in (
            ctx.raw_data_dir,
            ctx.sdtm_data_dir,
            ctx.adam_data_dir,
            ctx.metadata_sdtm_dir,
            ctx.metadata_adam_dir,
            ctx.define_xml_dir,
            ctx.outputs_dir,
        ):
            dir_path.mkdir(parents=True, exist_ok=True)

        # ── Resolve schema path relative to each define.yaml location ─────
        schema_ref = (
            importlib.resources.files("pymaverse") / "define_xml" / "schemas" / "define_spec_schema.json"
        )
        with importlib.resources.as_file(schema_ref) as schema_abs:
            sdtm_schema_rel = os.path.relpath(schema_abs, sdtm_define.parent)
            adam_schema_rel = os.path.relpath(schema_abs, adam_define.parent)

        # ── Write study_config.yaml ───────────────────────────────────────
        config_data: dict = {"study_id": study_id}
        if company:
            config_data["company"] = company
        config_file.write_text(
            yaml.dump(config_data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        # ── Write define.yaml boilerplates ────────────────────────────────
        sdtm_define.write_text(
            _sdtm_define_template(study_id, company or "", sdtm_schema_rel, __version__),
            encoding="utf-8",
        )
        adam_define.write_text(
            _adam_define_template(study_id, company or "", adam_schema_rel, __version__),
            encoding="utf-8",
        )

        return ctx


def _sdtm_define_template(study_id: str, company: str, schema_rel: str, version: str) -> str:
    return f"""\
# yaml-language-server: $schema={schema_rel}
# SDTM Define Specification — {study_id}
# Single source of truth: describes output structure AND drives derivations.
# Used for: (1) Define-XML 2.1 generation  (2) post-dataset structure checks  (3) pipeline execution.

study:
  id: {study_id}
  name: {study_id}
  description: ""
  protocol_name: {study_id}
  originator: "{company}"
  source_system: Pymaverse
  source_system_version: "{version}"
  standard: SDTMIG
  standard_version: "3.4"
  ct_version: "2024-09-27"

codelists: []
# Example:
#   - oid: C66731
#     name: Sex
#     type: text
#     items:
#       - coded_value: "M"
#         decode: MALE
#       - coded_value: "F"
#         decode: FEMALE

datasets: []
# Example:
#   - name: DM
#     label: Demographics
#     structure: One record per subject
#     repeating: false
#     class: SPECIAL PURPOSE
#     keys: [STUDYID, USUBJID]
#     inputs:
#       - name: dm_raw
#         type: raw
#     variables:
#       - name: STUDYID
#         label: Study Identifier
#         type: text
#         length: 12
#         mandatory: true
#         origin: Assigned
#         derivation:
#           algorithm: assigned
#           value: "{study_id}"
"""


def _adam_define_template(study_id: str, company: str, schema_rel: str, version: str) -> str:
    return f"""\
# yaml-language-server: $schema={schema_rel}
# ADaM Define Specification — {study_id}
# Single source of truth: describes output structure AND drives derivations.
# Used for: (1) Define-XML 2.1 generation  (2) post-dataset structure checks  (3) pipeline execution.

study:
  id: {study_id}
  name: {study_id}
  description: ""
  protocol_name: {study_id}
  originator: "{company}"
  source_system: Pymaverse
  source_system_version: "{version}"
  standard: ADAMIG
  standard_version: "1.1"
  ct_version: "2024-09-27"

codelists: []
# Example:
#   - oid: C66731
#     name: Sex
#     type: text
#     items:
#       - coded_value: "M"
#         decode: MALE
#       - coded_value: "F"
#         decode: FEMALE

datasets: []
# Example:
#   - name: ADSL
#     label: Subject-Level Analysis Dataset
#     structure: One record per subject
#     repeating: false
#     class: SUBJECT LEVEL ANALYSIS DATASET
#     keys: [STUDYID, USUBJID]
#     inputs:
#       - name: DM
#         type: dataset
#     variables:
#       - name: STUDYID
#         label: Study Identifier
#         type: text
#         length: 12
#         mandatory: true
#         origin: Assigned
#         derivation:
#           algorithm: assigned
#           value: "{study_id}"
"""


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
