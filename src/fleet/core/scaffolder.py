"""Define-spec scaffolder — generates ``define.yaml`` from the CDISC Library IG.

Queries the CDISC Library for the requested SDTM or ADaM IG version,
extracts variable-level metadata (name, label, type, core, codelist),
and renders a ready-to-edit ``define.yaml`` pre-populated with standard
variables.

Usage::

    from fleet.ct.api import CDISCClient
    from fleet.core.scaffolder import DefineScaffolder

    with CDISCClient() as client:
        scaffolder = DefineScaffolder(client)
        scaffolder.scaffold_sdtm(
            study_id="STUDY01",
            company="Pharma Inc",
            ig_version="3-4",
            ct_version="2023-12-15",
            domains=["DM", "AE", "VS"],
            output_path="metadata/sdtm/define.yaml",
        )
"""

from __future__ import annotations

import importlib.resources
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from fleet.core.define_spec import default_repeating

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from fleet.ct.api import CDISCClient

# CDISC simpleDatatype → Fleet define.yaml type
#: A variable name as define_spec_schema.json accepts it.
_VARIABLE_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,7}$")

_TYPE_MAP: dict[str, str] = {
    "Char": "text",
    "Num": "float",
    "Integer": "integer",
    "Float": "float",
    "Date": "date",
    "Datetime": "datetime",
    "datetime": "datetime",
    "date": "date",
    "text": "text",
    "integer": "integer",
    "float": "float",
}

# CDISC core → mandatory flag
_CORE_MAP: dict[str, bool] = {
    "Req": True,
    "Exp": False,
    "Perm": False,
    "Cond": False,
    "Required": True,
    "Expected": False,
    "Permissible": False,
    "Conditionally Required": False,
}

#: Define-XML 2.1 def:Class of the ADaM IG structures Fleet scaffolds as they are.
_ADAM_CLASSES: dict[str, str] = {
    "ADSL": "SUBJECT LEVEL ANALYSIS DATASET",
    "BDS": "BASIC DATA STRUCTURE",
}


def _ig_version_dotted(ver: str) -> str:
    """Convert ``"3-4"`` → ``"3.4"``."""
    return ver.replace("-", ".")


def schema_directive(spec_path: Path) -> str:
    """The ``yaml-language-server`` line pointing *spec_path* at the define schema.

    Scaffolded specs deliberately no longer carry this. Fleet's own
    language server reads the schema from the installed package, so a
    second validator pointed at the same schema reports every violation
    twice -- and the path it needs rots the moment Fleet is reinstalled
    somewhere else.

    Offered for editors without the Fleet extension, where a generic YAML
    language server is the only schema-driven completion available. The
    path is absolute because the schema lives in the Fleet install, never
    inside the study, so a relative one only gets longer.

    Args:
        spec_path: The define.yaml the directive would be pasted into.

    Returns:
        str: A complete comment line, resolved against this Fleet install.
    """
    schema_ref = (
        importlib.resources.files("fleet") / "define_xml" / "schemas" / "define_spec_schema.json"
    )
    with importlib.resources.as_file(schema_ref) as schema_abs:
        return f"# yaml-language-server: $schema={schema_abs}"


# ------------------------------------------------------------------ #
# Module-level IG parsers (re-usable outside DefineScaffolder)         #
# ------------------------------------------------------------------ #


def parse_ig_variable(var: dict[str, Any]) -> dict[str, Any]:
    """Parse an IG variable response into define.yaml variable format.

    This is the module-level equivalent of
    ``DefineScaffolder._parse_ig_variable``.  The Library ``role`` of an
    SDTMIG variable becomes ``sdtm_role:``, the Define-XML ItemRef Role.

    References:
        ADR 0042; Define-XML 2.1 (ItemRef Role); CORE rule CG0010.
    """
    name = var.get("name", "")
    label = var.get("label", "")
    simple_type = var.get("simpleDatatype", "Char")
    fleet_type = _TYPE_MAP.get(simple_type, "text")
    core = var.get("core", "Perm")
    mandatory = _CORE_MAP.get(core, False)

    result: dict[str, Any] = {
        "name": name,
        "label": label[:40] if label else name,
        "type": fleet_type,
    }

    if fleet_type == "text":
        result["length"] = 200

    result["mandatory"] = mandatory
    result["core"] = core
    if var.get("role"):
        # Define-XML ItemRef Role; CORE CG0010 reports a define without it (ADR 0042).
        result["sdtm_role"] = var["role"]

    if name in ("STUDYID", "DOMAIN"):
        result["origin"] = "Assigned"
    elif core in ("Req", "Required"):
        result["origin"] = "Collected"
    else:
        result["origin"] = "Derived"

    for cl in var.get("_links", {}).get("codelist", []):
        m = re.search(r"codelists/(C\d+)", cl.get("href", ""))
        if m:
            result["codelist"] = m.group(1)
            break

    return result


def parse_ig_dataset(detail: dict[str, Any]) -> dict[str, Any]:
    """Parse an IG dataset response into define.yaml format.

    This is the module-level equivalent of
    ``DefineScaffolder._parse_ig_dataset``.
    """
    name = detail.get("name", "")
    label = detail.get("label", "")
    description = detail.get("description", "")
    # Define-XML 2.1 def:Class: the Library sends the SDTM class as _links.parentClass.title
    # ("Special-Purpose", "Events"); the Define-XML value is upper case with a space.
    parent_class = detail.get("_links", {}).get("parentClass", {}).get("title", "")
    ds_class = detail.get("datasetClass", detail.get("class", "")) or parent_class
    if ds_class:
        ds_class = ds_class.upper().replace("-", " ")

    structure = (
        detail.get("datasetStructure")
        or detail.get("structure")
        or description
        or f"One record per {name}"
    )
    repeating = default_repeating(name)

    variables = []
    keys: list[str] = []
    for var in sorted(
        detail.get("datasetVariables", []),
        key=lambda v: int(v.get("ordinal", 999)),
    ):
        var_dict = parse_ig_variable(var)
        variables.append(var_dict)
        role = var.get("role", "")
        if role == "Identifier" and var.get("core", "") in ("Req", "Required"):
            keys.append(var_dict["name"])

    if not keys:
        candidate_keys = [v["name"] for v in variables if v["name"] in ("STUDYID", "USUBJID")]
        keys = candidate_keys or [variables[0]["name"]] if variables else ["STUDYID"]

    ds: dict[str, Any] = {
        "name": name,
        "label": label[:40] if label else name,
        "structure": structure,
        "repeating": repeating,
        "keys": keys,
        "variables": variables,
    }
    if ds_class:
        ds["class"] = ds_class
    return ds


class DefineScaffolder:
    """Generates ``define.yaml`` files by querying the CDISC Library IG API.

    Args:
        client: An authenticated ``CDISCClient`` instance.
    """

    def __init__(self, client: CDISCClient) -> None:
        self._client = client

    # -- public --------------------------------------------------------- #

    def scaffold_sdtm(
        self,
        study_id: str,
        *,
        company: str = "",
        description: str = "",
        ig_version: str = "3-4",
        ct_version: str = "2023-12-15",
        domains: list[str],
        output_path: str | Path,
    ) -> Path:
        """Generate an SDTM ``define.yaml`` from the CDISC Library SDTM IG.

        Args:
            study_id: Study identifier.
            company: Originator / company name; empty when not known.
            description: Study description; empty when not known.
            ig_version: SDTM IG version (e.g. ``"3-4"``).
            ct_version: CT version date (e.g. ``"2023-12-15"``).
            domains: List of SDTM domain abbreviations.
            output_path: Where to write the YAML file.

        Returns:
            Resolved path of the written file.
        """
        datasets = self._fetch_sdtm_datasets(ig_version, domains)
        return self._write_define(
            study_id=study_id,
            company=company,
            description=description,
            standard="SDTMIG",
            standard_version=_ig_version_dotted(ig_version),
            ct_version=ct_version,
            datasets=datasets,
            output_path=Path(output_path),
        )

    def scaffold_adam(
        self,
        study_id: str,
        *,
        company: str = "",
        description: str = "",
        ig_version: str = "1-3",
        ct_version: str = "2023-12-15",
        adam_ct_version: str | None = None,
        datasets: list[str],
        output_path: str | Path,
    ) -> Path:
        """Generate an ADaM ``define.yaml`` from the CDISC Library ADaM IG.

        Args:
            study_id: Study identifier.
            company: Originator / company name; empty when not known.
            description: Study description; empty when not known.
            ig_version: ADaM IG version (e.g. ``"1-1"``).
            ct_version: SDTM CT version date (e.g. ``"2023-12-15"``).
            adam_ct_version: ADaM CT version date (e.g. ``"2023-06-30"``).
            datasets: List of ADaM dataset names (e.g. ``["ADSL", "ADVS"]``).
            output_path: Where to write the YAML file.

        Returns:
            Resolved path of the written file.
        """
        ds_list = self._fetch_adam_datasets(ig_version, datasets)
        return self._write_define(
            study_id=study_id,
            company=company,
            description=description,
            standard="ADAMIG",
            standard_version=_ig_version_dotted(ig_version),
            ct_version=ct_version,
            adam_ct_version=adam_ct_version,
            datasets=ds_list,
            output_path=Path(output_path),
        )

    # -- IG fetchers ---------------------------------------------------- #

    def _fetch_sdtm_datasets(
        self,
        ig_version: str,
        domains: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch dataset + variable metadata from the SDTM IG."""
        ig = self._client._get(f"/mdr/sdtmig/{ig_version}/datasets")
        ds_links = ig.get("_links", {}).get("datasets", [])
        domains_upper = {d.upper() for d in domains}

        # Track which requested domains were found in the IG
        found: set[str] = set()
        result: list[dict[str, Any]] = []
        for ds in ds_links:
            domain = ds["href"].split("/")[-1]
            if domain not in domains_upper:
                continue
            found.add(domain)
            detail = self._client._get(ds["href"])
            result.append(self._parse_ig_dataset(detail))

        # Warn about non-standard domains that were not found in the IG
        missing = domains_upper - found
        for d in sorted(missing):
            logger.warning(
                "Domain '%s' not found in SDTM IG %s — skipped. "
                "If this is a company-specific domain, define it manually in define.yaml.",
                d,
                ig_version,
            )
        return result

    def _fetch_adam_datasets(
        self,
        ig_version: str,
        dataset_names: list[str],
    ) -> list[dict[str, Any]]:
        """Fetch dataset + variable metadata from the ADaM IG.

        The ADaM IG defines *data structures* (ADSL, BDS) rather than
        individual datasets.  ADSL maps directly; all other requested
        datasets (ADVS, ADAE, ADEX, …) are scaffolded from the BDS template.
        """
        ig_path = f"/mdr/adam/adamig-{ig_version}"
        ig = self._client._get(ig_path)
        structures = ig.get("dataStructures", [])

        # Build lookup: structure name → parsed detail
        struct_map: dict[str, dict[str, Any]] = {}
        for ds in structures:
            name = ds.get("name", "")
            struct_map[name] = self._parse_adam_structure(ds)

        names_upper = [d.upper() for d in dataset_names]
        result: list[dict[str, Any]] = []

        for ds_name in names_upper:
            if ds_name == "ADSL" and "ADSL" in struct_map:
                result.append(struct_map["ADSL"])
            elif "BDS" in struct_map:
                # Clone the BDS template for each non-ADSL dataset
                bds = struct_map["BDS"]
                clone = {
                    **bds,
                    "name": ds_name,
                    "label": f"{ds_name} Analysis Dataset",
                    "structure": "One record per subject per parameter per analysis visit",
                    "repeating": True,
                }
                # The clone may be OCCDS or TTE: a BDS class would be false.
                clone.pop("class", None)
                logger.warning(
                    "%s is scaffolded from the BDS template and has no class: in define.yaml. "
                    "Set class: by hand (for example BASIC DATA STRUCTURE or OCCURRENCE "
                    "DATA STRUCTURE).",
                    ds_name,
                )
                # Deep-copy variables so edits don't leak
                clone["variables"] = [dict(v) for v in bds["variables"]]
                result.append(clone)

        return result

    def _parse_adam_structure(self, ds: dict[str, Any]) -> dict[str, Any]:
        """Parse an ADaM IG data structure into define.yaml format."""
        name = ds.get("name", "")
        label = ds.get("label", "")
        description = ds.get("description", "")

        variables = []
        keys: list[str] = []
        ordinal = 0

        for var_set in ds.get("analysisVariableSets", []):
            for var in var_set.get("analysisVariables", []):
                ordinal += 1
                var["ordinal"] = ordinal
                var_dict = self._parse_ig_variable(var)
                # Skip IG template names (TRxxSDT, ANLzzFL, PARCATy): not variable names.
                if not _VARIABLE_NAME.match(var_dict["name"]):
                    continue
                variables.append(var_dict)

        # Key variables for ADSL vs BDS
        if name == "ADSL":
            keys = ["STUDYID", "USUBJID"]
        else:
            keys = ["STUDYID", "USUBJID", "PARAMCD", "AVISIT"]

        result: dict[str, Any] = {
            "name": name,
            "label": label[:40] if label else name,
            "structure": description or f"One record per {name}",
            "repeating": name != "ADSL",
            "keys": keys,
            "variables": variables,
        }
        ds_class = ds.get("className") or ds.get("class") or _ADAM_CLASSES.get(name)
        if ds_class:
            result["class"] = str(ds_class).upper()
        return result

    def _parse_ig_dataset(self, detail: dict[str, Any]) -> dict[str, Any]:
        """Parse an IG dataset response into define.yaml format."""
        return parse_ig_dataset(detail)

    def _parse_ig_variable(self, var: dict[str, Any]) -> dict[str, Any]:
        """Parse an IG variable response into define.yaml variable format."""
        return parse_ig_variable(var)

    # -- YAML writer ---------------------------------------------------- #

    def _write_define(
        self,
        study_id: str,
        company: str,
        standard: str,
        standard_version: str,
        ct_version: str,
        datasets: list[dict[str, Any]],
        output_path: Path,
        description: str = "",
        adam_ct_version: str | None = None,
    ) -> Path:
        """Write the assembled define spec to a YAML file.

        An empty *company* or *description* stays empty: the schema then
        names the field, so no placeholder reaches a Define-XML.
        """
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Collect all unique codelist OIDs from variables
        codelists: list[dict[str, Any]] = []
        seen_oids: set[str] = set()
        for ds in datasets:
            for var in ds.get("variables", []):
                oid = var.get("codelist")
                if oid and oid not in seen_oids:
                    seen_oids.add(oid)
                    codelists.append(
                        {
                            "oid": oid,
                            "name": oid,  # placeholder — fleet init ct will provide real names
                            "type": "text",
                        }
                    )

        spec: dict[str, Any] = {
            "study": {
                "id": study_id,
                "name": study_id,
                "description": description,
                "protocol_name": study_id,
                "originator": company or "",
                "source_system": "Fleet",
                "standard": standard,
                "standard_version": standard_version,
                "ct_version": ct_version,
                **({"adam_ct_version": adam_ct_version} if adam_ct_version else {}),
            },
            "codelists": codelists,
            "datasets": datasets,
        }

        header = (
            f"# {standard} Define Specification — {study_id}\n"
            "# Auto-generated by `fleet init define`. Edit freely.\n"
            "# Variables without a derivation block are carry-through columns.\n"
            "# Add derivation blocks (algorithm + params) to drive the pipeline.\n"
            "\n"
        )

        yaml_body = yaml.dump(
            spec,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )

        output_path.write_text(header + yaml_body, encoding="utf-8")
        return output_path
