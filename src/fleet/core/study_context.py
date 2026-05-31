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
    rules_sdtm: str = Field(default="metadata/sdtm/rules")
    rules_adam: str = Field(default="metadata/adam/rules")
    programs_sdtm: str = Field(default="programs/sdtm")
    programs_adam: str = Field(default="programs/adam")
    programs_tlg: str = Field(default="programs/tlg")
    programs_misc: str = Field(default="programs/misc")


class SDTMConfig(BaseModel):
    """SDTM Implementation Guide configuration."""

    ig_version: str = Field(default="3-4")
    domains: list[str] = Field(default_factory=list)


class ADAMConfig(BaseModel):
    """ADaM Implementation Guide configuration."""

    ig_version: str = Field(default="1-1")
    datasets: list[str] = Field(default_factory=list)


class CTConfig(BaseModel):
    """Controlled Terminology package configuration."""

    package: str = Field(default="sdtmct-2023-12-15")


class ValidationConfig(BaseModel):
    """CDISC Rules Engine configuration.

    Optional — when omitted, Fleet auto-discovers the engine via
    ``FLEET_RULES_ENGINE`` env var or the managed install at ``~/.fleet/bin``.
    Set ``engine_path`` to share a team-wide path in version control.
    """

    engine_path: str | None = Field(
        default=None,
        description="Path to the CDISC Rules Engine executable (absolute or relative to study root).",
    )
    custom_rules: str | None = Field(
        default=None,
        description=(
            "Directory containing custom validation rule YAML files. "
            "Passed to the engine via -lr flag. Absolute or relative to study root."
        ),
    )


class StudyConfig(BaseModel):
    """Top-level study configuration model.

    Drives the entire bootstrapping pipeline:
    ``fleet init cfg`` → ``fleet init define`` → ``fleet init ct``.
    """

    study_id: str
    company: str | None = None
    protocol_name: str | None = None
    description: str = ""
    paths: StudyPathConfig = Field(default_factory=StudyPathConfig)
    sdtm: SDTMConfig = Field(default_factory=SDTMConfig)
    adam: ADAMConfig = Field(default_factory=ADAMConfig)
    ct: CTConfig = Field(default_factory=CTConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)


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

    @property
    def programs_sdtm_dir(self) -> Path:
        return self.resolve(self.config.paths.programs_sdtm)

    @property
    def programs_adam_dir(self) -> Path:
        return self.resolve(self.config.paths.programs_adam)

    @property
    def programs_tlg_dir(self) -> Path:
        return self.resolve(self.config.paths.programs_tlg)

    @property
    def rules_sdtm_dir(self) -> Path:
        return self.resolve(self.config.paths.rules_sdtm)

    @property
    def rules_adam_dir(self) -> Path:
        return self.resolve(self.config.paths.rules_adam)

    @property
    def programs_misc_dir(self) -> Path:
        return self.resolve(self.config.paths.programs_misc)

    @property
    def codelists_file(self) -> Path:
        """Resolve the generated codelists.py path (inside SDTM metadata dir)."""
        return self.metadata_sdtm_dir / "codelists.py"

    @property
    def custom_rules_dir(self) -> Path | None:
        """Resolve the custom validation rules directory, or None if not configured."""
        if self.config.validation.custom_rules is None:
            return None
        return self.resolve(self.config.validation.custom_rules)

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
        protocol_name: str | None = None,
        description: str = "",
        paths: "StudyPathConfig | None" = None,
        sdtm: "SDTMConfig | None" = None,
        adam: "ADAMConfig | None" = None,
        ct: "CTConfig | None" = None,
        validation: "ValidationConfig | None" = None,
    ) -> "StudyContext":
        """Scaffold a new study workspace and return a ready-to-use StudyContext.

        Creates the directory layout defined by StudyPathConfig and writes
        ``study_config.yaml``.  Define specs and codelists are created by
        subsequent pipeline steps (``fleet init define``, ``fleet init ct``).

        Directories are created silently if they already exist.  If
        ``study_config.yaml`` already exists the method raises
        ``StudyConfigError`` to protect in-progress work.

        Args:
            study_root: Root directory for the study (created if absent).
            study_id:   Study identifier (e.g. ``"STUDY01"``).
            company:    Optional originator / company name.
            protocol_name: Optional protocol identifier.
            description: Optional study description.
            paths:      Custom path config; defaults to ``StudyPathConfig`` defaults.
            sdtm:       SDTM IG configuration (version, domains).
            adam:        ADaM IG configuration (version, datasets).
            ct:         CT package configuration.
            validation: Validation engine configuration (engine path, custom rules).

        Returns:
            Initialized ``StudyContext`` pointing at the new workspace.

        Raises:
            StudyConfigError: If ``study_config.yaml`` already exists.
        """
        study_root = Path(study_root).resolve()
        config = StudyConfig(
            study_id=study_id,
            company=company,
            protocol_name=protocol_name,
            description=description,
            paths=paths or StudyPathConfig(),
            sdtm=sdtm or SDTMConfig(),
            adam=adam or ADAMConfig(),
            ct=ct or CTConfig(),
            validation=validation or ValidationConfig(),
        )
        ctx = cls(study_root=study_root, config=config)

        # ── Guard: refuse to overwrite existing config ────────────────────
        config_file = study_root / "study_config.yaml"
        if config_file.exists():
            raise StudyConfigError(
                f"Study already initialized — '{config_file}' already exists. "
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
            ctx.rules_sdtm_dir,
            ctx.rules_adam_dir,
            ctx.programs_sdtm_dir,
            ctx.programs_adam_dir,
            ctx.programs_tlg_dir,
            ctx.programs_misc_dir,
        ):
            dir_path.mkdir(parents=True, exist_ok=True)

        # ── Create derivations package stub ──────────────────────────────
        derivations_dir = ctx.programs_adam_dir.parent / "derivations"
        derivations_dir.mkdir(parents=True, exist_ok=True)
        derivations_init = derivations_dir / "__init__.py"
        if not derivations_init.exists():
            derivations_init.write_text(
                "# Auto-generated by fleet init cfg.\n"
                "# Import study-specific derivations here so they are auto-registered.\n",
                encoding="utf-8",
            )

        # ── Write study_config.yaml ───────────────────────────────────────
        config_data = config.model_dump(exclude_none=True)
        # Drop empty defaults to keep the file lean
        if not config_data.get("description"):
            config_data.pop("description", None)
        config_file.write_text(
            yaml.dump(config_data, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        return ctx


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
