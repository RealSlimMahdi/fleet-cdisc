"""Study-level configuration and path resolution utilities.

Adapted from pharmaversepy study/config.py.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fleet.core.exceptions import FleetError


class _ConfigModel(BaseModel):
    """A study_config.yaml block: an unknown key (a typo) is an error."""

    model_config = ConfigDict(extra="forbid")


def _dash_version(value: object) -> object:
    """Read an IG version as the CDISC Library form: 3.4, '3.4' and '3-4' give '3-4'."""
    if value is None:
        return None
    return str(value).replace(".", "-")


class StudyPathConfig(_ConfigModel):
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


class SDTMConfig(_ConfigModel):
    """SDTM Implementation Guide configuration.

    ``ig_version`` is ``None`` when the study does not declare it; the
    validation run setup then applies the built-in default.  ``3.4``,
    ``'3.4'`` and ``'3-4'`` are all read as ``'3-4'``.
    """

    ig_version: str | None = Field(default=None)
    domains: list[str] = Field(default_factory=list)

    _dash_ig_version = field_validator("ig_version", mode="before")(_dash_version)


class ADAMConfig(_ConfigModel):
    """ADaM Implementation Guide configuration.

    ``ig_version`` is ``None`` when the study does not declare it; the
    validation run setup then applies the built-in default.  ``1.3``,
    ``'1.3'`` and ``'1-3'`` are all read as ``'1-3'``.
    """

    ig_version: str | None = Field(default=None)
    datasets: list[str] = Field(default_factory=list)

    _dash_ig_version = field_validator("ig_version", mode="before")(_dash_version)


#: The default SDTM CT package of a new study.
DEFAULT_SDTM_CT = "sdtmct-2023-12-15"
#: The latest ADaM CT package on or before ``DEFAULT_SDTM_CT``.
DEFAULT_ADAM_CT = "adamct-2023-06-30"


class CTConfig(_ConfigModel):
    """Controlled Terminology package configuration.

    CDISC publishes ADaM CT on its own dates, so a study with ADaM
    datasets pins a second package for the ADaM-only codelists (DTYPE).
    """

    package: str = Field(default=DEFAULT_SDTM_CT)
    adam_package: str | None = Field(
        default=None,
        description="ADaM CT package, e.g. ``adamct-2023-06-30``; ``None`` without ADaM datasets.",
    )

    @property
    def pins(self) -> tuple[str, ...]:
        """The pinned packages, SDTM first: ``fleet init ct`` asks them in this order."""
        return (self.package, self.adam_package) if self.adam_package else (self.package,)


class AcceptedFinding(_ConfigModel):
    """A CORE finding the study accepts, as an SDRG explanation does (ADR-0017).

    Every CORE finding blocks the job unless an entry lists its rule and
    dataset with a reason.
    """

    rule: str = Field(min_length=1, description="CORE rule ID, e.g. ``CORE-000767``.")
    dataset: str = Field(min_length=1, description="Dataset name, e.g. ``AE`` or ``STUDY``.")
    reason: str = Field(min_length=1, description="Why the finding is accepted (SDRG text).")


class ValidationConfig(_ConfigModel):
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
    timeout: float | None = Field(
        default=None,
        gt=0,
        description="Seconds before an engine run is stopped (default 300).",
    )
    accepted: list[AcceptedFinding] = Field(
        default_factory=list,
        description="Findings that do not block: rule, dataset and reason for each.",
    )


class StudyConfig(_ConfigModel):
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


class StudyConfigError(FleetError):
    """Raised when study configuration cannot be loaded or validated."""


def find_study_config(start: Path | None = None) -> Path | None:
    """Locate ``study_config.yaml`` by walking up parent directories.

    Git-style discovery: the start directory is checked first, then each
    parent up to the filesystem root.

    Args:
        start: Directory to start from (default: current working directory).

    Returns:
        Path | None: The first ``study_config.yaml`` found, or ``None``.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        cfg = candidate / "study_config.yaml"
        if cfg.is_file():
            return cfg
    return None


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

    def data_dir(self, standard: str) -> Path:
        """The configured data directory of one standard (``"sdtm"`` or ``"adam"``)."""
        if standard == "sdtm":
            return self.sdtm_data_dir
        if standard == "adam":
            return self.adam_data_dir
        raise ValueError(f"unknown standard {standard!r}: expected 'sdtm' or 'adam'")

    def metadata_dir(self, standard: str) -> Path:
        """The configured metadata directory of one standard (``"sdtm"`` or ``"adam"``)."""
        if standard == "sdtm":
            return self.metadata_sdtm_dir
        if standard == "adam":
            return self.metadata_adam_dir
        raise ValueError(f"unknown standard {standard!r}: expected 'sdtm' or 'adam'")

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

    @property
    def engine_file(self) -> Path | None:
        """Resolve ``validation.engine_path``, or None if not configured."""
        if self.config.validation.engine_path is None:
            return None
        return self.resolve(self.config.validation.engine_path)

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
        ``study_config.yaml``.  When the root has no ``.gitignore``, one is
        written that lists ``.env``, the file that holds the CDISC API key.
        Define specs and codelists are created by
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
            *([ctx.custom_rules_dir] if ctx.custom_rules_dir is not None else []),
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

        gitignore = study_root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(".env\n", encoding="utf-8")

        return ctx


def load_study_context(config_path: str | Path) -> StudyContext:
    """Load study configuration and return a resolved context.

    Args:
        config_path: Path to study_config.yaml.  It is resolved to an
            absolute path, so the study paths do not change after
            ``os.chdir``.

    Returns:
        StudyContext with resolved paths

    Raises:
        StudyConfigError: If the config file is missing, is not UTF-8
            text, is not valid YAML, or does not match the schema (an
            unknown key included).
    """
    config_path = Path(config_path).resolve()
    if not config_path.exists():
        raise StudyConfigError(f"Study configuration file not found: {config_path}")

    try:
        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    except UnicodeDecodeError as e:
        raise StudyConfigError(
            f"{config_path.name} is not UTF-8 text (byte 0x{e.object[e.start]:02x} "
            f"at position {e.start}). Save the file as UTF-8."
        ) from e
    except (yaml.YAMLError, ValueError) as e:
        raise StudyConfigError(f"Invalid YAML in study configuration: {e}") from e

    try:
        config = StudyConfig(**config_data)
    except Exception as e:
        raise StudyConfigError(f"Invalid study configuration schema: {e}") from e

    return StudyContext(study_root=config_path.parent, config=config)
