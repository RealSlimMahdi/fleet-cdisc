"""Generate Define-XML 2.1 from a simplified Fleet define YAML spec.

Converts the compact ``specs/<study>/<sdtm|adam>/define.yaml`` format into a
fully-compliant CDISC Define-XML 2.1 ODM document.

Simplified YAML format is enforced by:
    ``src/fleet/define_xml/schemas/define_spec_schema.json``

Usage::

    from fleet import DefineSpecGenerator
    from pathlib import Path

    gen = DefineSpecGenerator("examples/cdiscpilot01/sdtm/define.yaml")
    gen.generate("outputs/define_sdtm.xml")
"""

from __future__ import annotations

import json
import re
import warnings
import xml.dom.minidom
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from lxml import etree as lxml_etree

from fleet.core import spec_registry
from fleet.core._verb_mixin import _import_derivations_module
from fleet.core.algorithm_resolver import docstring_summary, resolve_callable_docstring
from fleet.core.define_spec import (
    default_is_reference_data,
    default_repeating,
    load_define_spec,
    load_spec_yaml,
)
from fleet.core.exceptions import SpecError
from fleet.define_xml.semantic_checks import REST_EMPHASIS

_SCHEMA_PATH = Path(__file__).parent / "schemas" / "define_spec_schema.json"

#: An NCI concept code used as a codelist OID (C66731): a CDISC CT list.
_NCI_CODE = re.compile(r"^C\d+$")

# ODM/Define-XML 2.1 namespaces
_NS_ODM = "http://www.cdisc.org/ns/odm/v1.3"
_NS_DEF = "http://www.cdisc.org/ns/def/v2.1"
_NS_XLINK = "http://www.w3.org/1999/xlink"

ET.register_namespace("def", _NS_DEF)
ET.register_namespace("xlink", _NS_XLINK)

# Map simplified type → ODM DataType attribute
_TYPE_TO_ODM: dict[str, str] = {
    "text": "text",
    "integer": "integer",
    "float": "float",
    "date": "date",
    "datetime": "datetime",
}

# Map standard name → standard OID used throughout the document
_STANDARD_OIDS: dict[str, str] = {
    "SDTMIG": "STD.SDTMIG",
    "ADAMIG": "STD.ADAMIG",
    "SENDIG": "STD.SENDIG",
}
_CT_OID = "STD.CT"
_ADAM_CT_OID = "STD.CT.ADAM"

#: Spec ``study.standard`` → the ``def:Standard/@Name`` value Define-XML 2.1
#: enumerates (note the lower-case 'a' in ADaMIG).
_STANDARD_NAMES: dict[str, str] = {
    "SDTMIG": "SDTMIG",
    "ADAMIG": "ADaMIG",
    "SENDIG": "SENDIG",
}

# Map export format (spec key ``output_format``) → def:leaf href extension.
_FORMAT_EXT: dict[str, str] = {
    "parquet": ".parquet",
    "xpt": ".xpt",
    "dataset-json": ".json",
}

#: Spec ``study.standard`` → the algorithm-registry standard (SEND shares
#: the SDTM verb set).
_REGISTRY_STANDARDS: dict[str, str] = {
    "SDTMIG": "sdtm",
    "ADAMIG": "adam",
    "SENDIG": "sdtm",
}


def _is_plain_copy(block: dict) -> bool:
    """An ``assign`` that copies a column: no constant and no codelist (ADR-0008)."""
    return block.get("algorithm") == "assign" and block.get("value") is None and not block.get("ct")


#: reST formatting in study docstrings (````code````, ``ref``, *emphasis*)
#: is noise in a regulatory document — content kept, markup dropped.
_REST_MARKUP = re.compile(r"``([^`]+)``|`([^`]+)`|" + REST_EMPHASIS.pattern)


def _row_steps_text(steps: list[dict[str, Any]]) -> str:
    """Describe a dataset's ``row_steps:`` in pipeline order, for its def:CommentDef."""
    parts: list[str] = []
    for step in steps:
        after = step.get("after")
        where = f"after {after}" if after else "before the first variable"
        if step.get("algorithm") == "whereclauses":
            action = f"keep the records where {step.get('where')}"
        elif step.get("algorithm") == "nodup":
            sort_by = ", ".join(step.get("sort_by") or [])
            action = (
                f"keep the {step.get('keep')} record per {', '.join(step.get('subset') or [])}"
                f" sorted by {sort_by}"
            )
        else:
            action = f"a record step by {step.get('verb')} that the spec does not describe yet"
        parts.append(f"{where}, {action}")
    return "Record selection, in derivation order: " + "; ".join(parts) + "."


def _strip_rest_markup(text: str) -> str:
    return _REST_MARKUP.sub(lambda m: next(g for g in m.groups() if g is not None), text)


class DefineSpecGenerator:
    """Generate Define-XML 2.1 from a simplified Fleet define YAML spec.

    Parameters
    ----------
    define_yaml_path:
        Path to a simplified define YAML file that conforms to
        ``define_spec_schema.json``.
    validate_schema:
        When *True* (default), validates the YAML against the JSON schema
        before generating and raises ``ValueError`` on schema violations.
    validate_xml:
        When *True* (default), validates the generated document against the
        vendored Define-XML 2.1 XSDs and raises
        :class:`~fleet.core.exceptions.SpecError` rather than emitting a
        non-conformant define.xml.  Set to ``False`` to write the file
        anyway (e.g. to inspect what failed).
    enrich_methods:
        When *True* (default), every Derived variable with a ``comment:``
        or a ``derivation:`` gets a MethodDef.  This imports the spec's
        ``derivations_module`` (study Python code); *False* imports nothing.
    import_study_code:
        When *False*, the generator imports no study code even with
        *enrich_methods*: a ``callable:`` derivation is described by its
        ``comment:`` or its dotted path.  ``fleet check`` uses this, so a
        received study runs no code on a read-only command.
    strict:
        When *True*, refuse (``SpecError``) a define with gaps: a Derived
        variable with no method text, a text, integer or float variable
        with no Length, a float with no SignificantDigits.  When *False*
        (default), the gaps are named in one ``UserWarning`` and the file
        is written (ADR-0018).
    """

    def __init__(
        self,
        define_yaml_path: str | Path,
        *,
        validate_schema: bool = True,
        validate_xml: bool = True,
        enrich_methods: bool = True,
        import_study_code: bool = True,
        strict: bool = False,
    ) -> None:
        self._path = Path(define_yaml_path)
        self._data: dict[str, Any] = load_spec_yaml(self._path.read_text(encoding="utf-8"))
        self._check_spec_version()
        self._enrich_methods = enrich_methods
        self._import_study_code = import_study_code
        self._strict = strict
        self._validate_xml = validate_xml
        #: "DATASET.VARIABLE: reason" for each define gap of the last build.
        self._gaps: list[str] = []
        #: (dataset, variable) pairs whose methods live at value level.
        self._vlm_parents: set[tuple[str, str]] = set()
        # Populated via _register_method; rendered into MethodDef elements at
        # the end of MetaDataVersion.
        self._method_defs: dict[str, dict[str, str]] = {}
        # ItemDef OID → ValueListDef OID (populated by _build_value_level;
        # consumed by _build_item_def to emit def:ValueListRef).
        self._value_list_refs: dict[str, str] = {}
        if validate_schema:
            self._validate()
        # Resolve the CRF page map once (merges external page_map with
        # inline crf_pages; inline takes precedence).
        self._page_map: dict[str, dict[str, Any]] = self._load_page_map()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def generate(
        self,
        output_path: str | Path,
        *,
        html_preview: bool = True,
        xsl_path: str | Path | None = None,
    ) -> None:
        """Write a Define-XML 2.1 document to *output_path*.

        Parameters
        ----------
        output_path:
            Destination path for the ``.xml`` file.
        html_preview:
            When ``True`` (default), also write an HTML preview by applying
            the CDISC ``define2-1.xsl`` stylesheet via lxml.  The HTML file
            is written alongside the XML with a ``_preview.html`` suffix
            (e.g. ``define_sdtm.xml`` → ``define_sdtm_preview.html``).
        xsl_path:
            Path to the ``define2-1.xsl`` stylesheet.  Defaults to
            ``define2-1.xsl`` in the same directory as *output_path*, which
            is the standard layout used by Fleet.
        """
        root = self._build_odm()
        xml_str = self._serialise(root)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(xml_str, encoding="utf-8")
        print(f"Define-XML generated: {out}")

        if html_preview:
            self._write_html_preview(out, xsl_path)

    def _write_html_preview(
        self,
        xml_path: Path,
        xsl_path: str | Path | None,
    ) -> None:
        """Apply the define2-1.xsl transform and write an HTML preview file.

        The stylesheet often comes with a received define package, so it
        runs with no file or network access.  A stylesheet that cannot run
        skips the preview; the Define-XML is already written.
        """
        resolved_xsl = Path(xsl_path) if xsl_path else xml_path.parent / "define2-1.xsl"

        if not resolved_xsl.exists():
            print(
                f"HTML preview skipped: XSL stylesheet not found at '{resolved_xsl}'. "
                "Place define2-1.xsl in the same directory as the XML output, "
                "or pass xsl_path= explicitly."
            )
            return

        parser = lxml_etree.XMLParser(resolve_entities=False, no_network=True)
        try:
            xml_doc = lxml_etree.parse(str(xml_path), parser)  # noqa: S320 — entities off
            xsl_doc = lxml_etree.parse(str(resolved_xsl), parser)  # noqa: S320 — entities off
            transform = lxml_etree.XSLT(
                xsl_doc, access_control=lxml_etree.XSLTAccessControl.DENY_ALL
            )
            html_doc = transform(xml_doc)
        except (lxml_etree.XSLTError, lxml_etree.XMLSyntaxError) as exc:
            print(f"HTML preview skipped: {resolved_xsl} cannot run: {exc}")
            return

        html_path = xml_path.with_name(xml_path.stem + "_preview.html")
        html_path.write_bytes(lxml_etree.tostring(html_doc, pretty_print=True, method="html"))
        print(f"HTML preview generated: {html_path}")

    def to_xml_string(self) -> str:
        """Return the Define-XML as a formatted string without writing a file."""
        return self._serialise(self._build_odm())

    def _serialise(self, root: ET.Element) -> str:
        """Format *root* and, unless disabled, validate before returning.

        Two layers, same gate: XSD validation (structure, element order,
        enumerations) and the semantic lint (reviewer-facing conformance
        — see :func:`fleet.define_xml.semantic_checks.semantic_errors`).
        A document that fails either never ships silently.
        """
        xml_str = self._to_pretty_xml(root)
        if not self._validate_xml:
            return xml_str

        from fleet.core.exceptions import SpecError
        from fleet.define_xml.semantic_checks import semantic_errors
        from fleet.define_xml.xsd import validate_define_xml

        errors = [f"schema: {e}" for e in validate_define_xml(xml_str)]
        errors += [f"conformance: {e}" for e in semantic_errors(xml_str)]
        if errors:
            shown = "\n  ".join(errors[:10])
            more = f"\n  ... and {len(errors) - 10} more" if len(errors) > 10 else ""
            raise SpecError(
                f"{self._path}: generated Define-XML failed Define-XML 2.1 "
                f"validation ({len(errors)} error(s)):\n  {shown}{more}\n"
                "Correct define.yaml and generate again. From Python, "
                "DefineSpecGenerator(..., validate_xml=False) writes the file anyway."
            )
        return xml_str

    # ------------------------------------------------------------------ #
    # CRF page map                                                         #
    # ------------------------------------------------------------------ #

    def _load_page_map(self) -> dict[str, dict[str, Any]]:
        """Build a merged CRF page map from external file and inline values.

        Returns a dict keyed by ``"DOMAIN.VARIABLE"`` (value level:
        ``"DOMAIN.VARIABLE.<where values>"``) whose values are page
        references in the dict form; a page string or number becomes
        ``{"pages": "7"}``.  Inline ``crf_pages`` take precedence over
        entries in the external ``page_map`` file.  A declared page that
        cannot reach the Define-XML raises or warns: it is never lost
        silently.
        """
        merged: dict[str, dict[str, Any]] = {}
        known = self._page_map_keys()

        # Layer 3: external page_map YAML
        page_map_path = (self._get_acrf_config() or {}).get("page_map")
        if page_map_path:
            resolved = (self._path.parent / page_map_path).resolve()
            if not resolved.is_file():
                raise SpecError(
                    f"{self._path}: annotated_crf page_map {page_map_path} does not exist "
                    f"(looked for {resolved})."
                )
            raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise SpecError(
                    f"{resolved}: a page map is a mapping of DATASET.VARIABLE to pages, "
                    f"not {type(raw).__name__}."
                )
            for key, value in raw.items():
                merged[str(key)] = self._page_ref_value(value, f"{resolved}: {key}")
            unknown = sorted(k for k in merged if k not in known)
            if unknown:
                shown = ", ".join(unknown[:10]) + (" ..." if len(unknown) > 10 else "")
                warnings.warn(
                    f"{resolved}: {len(unknown)} page map key(s) match no variable of "
                    f"{self._path.name}: {shown}. Their pages are not in the Define-XML.",
                    UserWarning,
                    stacklevel=3,
                )

        # Layer 1 / 2: inline crf_pages (overrides external)
        for key, var in known.items():
            if var.get("crf_pages") is not None:
                merged[key] = self._page_ref_value(var["crf_pages"], key)

        if not self._get_acrf_config():
            lost = [key for key, ref in merged.items() if not ref.get("doc")]
            if lost:
                warnings.warn(
                    f"{self._path}: {', '.join(lost)} declare crf_pages, but "
                    "study.documents has no annotated_crf. Their pages are not in the "
                    "Define-XML. Add study.documents.annotated_crf.",
                    UserWarning,
                    stacklevel=3,
                )
        return merged

    def _page_map_keys(self) -> dict[str, dict[str, Any]]:
        """Map each page map key of the spec to its variable entry."""
        keys: dict[str, dict[str, Any]] = {}
        for ds in self._data.get("datasets", []):
            ds_name = ds["name"]
            for var in ds.get("variables", []):
                keys[f"{ds_name}.{var['name']}"] = var
            for entry in ds.get("value_level") or []:
                vl_key = "_".join(self._normalise_where(ds_name, entry)[2])
                for var in entry.get("variables", []):
                    keys[f"{ds_name}.{var['name']}.{vl_key}"] = var
        return keys

    def _page_ref_value(self, value: Any, where: str) -> dict[str, Any]:
        """Normalise one page reference to the dict form (a YAML ``7`` is page "7")."""
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            return {"pages": str(value)}
        if isinstance(value, dict):
            return {
                k: str(v) if k in ("pages", "first_page", "last_page") else v
                for k, v in value.items()
            }
        raise SpecError(
            f"{where}: a CRF page reference is a page string such as '7 8' or a mapping "
            f"with pages:, not {type(value).__name__}."
        )

    def _get_acrf_config(self) -> dict[str, str] | None:
        """Return the annotated CRF document config, or None if absent."""
        docs = self._data.get("study", {}).get("documents", {})
        return docs.get("annotated_crf")

    def _acrf_leaf_id(self) -> str:
        return "LF.acrf"

    # ------------------------------------------------------------------ #
    # Schema validation                                                    #
    # ------------------------------------------------------------------ #

    def _check_spec_version(self) -> None:
        """Raise ``SpecError`` when the spec declares an unknown future version."""
        from fleet.core._verb_mixin import SUPPORTED_SPEC_VERSION

        version = self._data.get("fleet_spec_version")
        if version is not None and version != SUPPORTED_SPEC_VERSION:
            raise SpecError(
                f"{self._path}: unsupported fleet_spec_version {version!r}. "
                f"This Fleet version supports fleet_spec_version {SUPPORTED_SPEC_VERSION}."
            )

    def _validate(self) -> None:
        from fleet.core.exceptions import SpecSchemaError

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(self._data))
        if not errors:
            return
        empty = [
            e.json_path[2:]
            for e in errors
            if e.json_path in ("$.study.description", "$.study.originator")
            and e.validator == "minLength"
        ]
        lines = [f"  - {e.json_path}: {e.message}" for e in errors if e.json_path[2:] not in empty][
            :5
        ]
        if empty:
            lines.insert(
                0,
                f"  - {' and '.join(empty)} {'is' if len(empty) == 1 else 'are'} empty. "
                "Write the text in this file, or create the study with "
                "`fleet new --description ... --company ...`.",
            )
        msgs = "\n".join(lines)
        raise SpecSchemaError(f"{self._path}: define YAML failed schema validation:\n{msgs}")

    def _validate_codelist_refs(self) -> None:
        """Fail loudly on ``codelist:`` references to undeclared codelists.

        Every ``CodeListRef`` the generated Define-XML would emit must
        point at a ``CodeList`` element declared in this spec's
        ``codelists:`` section — a dangling OID renders a define that
        asserts conformance to nothing.

        Raises:
            SpecError: Naming each offending dataset/variable and listing
                the declared codelist OIDs.
        """
        declared = {cl["oid"] for cl in self._data.get("codelists", [])}
        dangling: list[str] = []
        for ds in self._data.get("datasets", []):
            variables = list(ds.get("variables", []))
            for entry in ds.get("value_level", []) or []:
                variables.extend(entry.get("variables", []))
            for var in variables:
                oid = var.get("codelist")
                if oid and oid not in declared:
                    dangling.append(f"{ds['name']}.{var['name']} → '{oid}'")
        if dangling:
            raise SpecError(
                f"{self._path}: CodeListRef to undeclared codelist(s): "
                f"{'; '.join(dangling)}. Declared codelist OIDs: "
                f"{sorted(declared) or '(none)'}. Add the codelist to the "
                f"spec's `codelists:` section or fix the reference."
            )
        standards = self._declared_standards()
        unknown = [
            f"{cl['oid']} → '{cl['standard_oid']}'"
            for cl in self._data.get("codelists", [])
            if cl.get("standard_oid") and cl["standard_oid"] not in standards
        ]
        if unknown:
            raise SpecError(
                f"{self._path}: codelist standard_oid names no declared standard: "
                f"{'; '.join(unknown)}. Declared standards: {sorted(standards)}. Set "
                "study.ct_version (STD.CT) or study.adam_ct_version (STD.CT.ADAM)."
            )
        empty = [
            cl["oid"]
            for cl in self._data.get("codelists", [])
            if not cl.get("items") and not cl.get("external")
        ]
        if empty:
            raise SpecError(
                f"{self._path}: codelist(s) with no terms: {', '.join(empty)}. A Define-XML "
                "CodeList needs its terms. Run: fleet init ct (it writes the terms of the "
                "pinned CT package into this file), or add items: by hand."
            )

    def _declared_standards(self) -> set[str]:
        """The def:Standard OIDs this define declares."""
        study = self._data["study"]
        declared = {_STANDARD_OIDS.get(study["standard"], f"STD.{study['standard']}")}
        if study.get("ct_version"):
            declared.add(_CT_OID)
        if study.get("adam_ct_version"):
            declared.add(_ADAM_CT_OID)
        return declared

    def _leaf_href(self, ds: dict[str, Any]) -> str:
        """Resolve the ``def:leaf`` href for a dataset.

        Uses the per-dataset ``output:`` path verbatim when given;
        otherwise ``{name.lower()}{ext}`` where the extension follows the
        per-dataset or spec-level ``output_format:`` key (default
        ``parquet`` → ``.parquet``).
        """
        output = ds.get("output")
        if output:
            return str(output)
        fmt = ds.get("output_format") or self._data.get("output_format") or "parquet"
        ext = _FORMAT_EXT.get(fmt, ".parquet")
        return f"{ds['name'].lower()}{ext}"

    # ------------------------------------------------------------------ #
    # ODM root                                                             #
    # ------------------------------------------------------------------ #

    def _warn_predecessor_candidates(self) -> None:
        """Warn on ADaM ``algorithm: source`` variables marked Collected.

        A column copied verbatim from an upstream dataset is a
        ``Predecessor`` in Define-XML 2.1 terms; ``Collected`` claims it
        was captured on the CRF.  Output is not changed (origin stays an
        explicit spec decision) — the warning surfaces the likely miss
        where the author can fix it.
        """
        if self._data.get("study", {}).get("standard") != "ADAMIG":
            return
        hits = [
            f"{ds['name']}.{var['name']}"
            for ds in self._data.get("datasets", [])
            for var in ds.get("variables", [])
            if _is_plain_copy(var.get("derivation") or {}) and var.get("origin") == "Collected"
        ]
        if hits:
            warnings.warn(
                f"{self._path}: {', '.join(hits)} use 'algorithm: assign' (a copy) with "
                "origin 'Collected' — a variable carried from an upstream dataset "
                "should declare origin: Predecessor with "
                "predecessor: '<DATASET>.<VARIABLE>'.",
                stacklevel=2,
            )

    def _validate_variable_refs(self) -> None:
        """Fail loudly on keys and value-level names that are not dataset variables.

        A key, a value-level variable or a where-clause variable that the
        dataset does not declare gives a Define-XML reference to an
        ItemDef that does not exist, or a key that is dropped.

        Raises:
            SpecError: Naming each DATASET.VARIABLE and where it is used.
        """
        problems: list[str] = []
        for ds in self._data.get("datasets", []):
            ds_name = ds["name"]
            names = {var["name"] for var in ds.get("variables", [])}
            for key in ds.get("keys") or []:
                if key not in names:
                    problems.append(f"{ds_name}.{key} (keys)")
            for entry in ds.get("value_level") or []:
                wc_var = self._normalise_where(ds_name, entry)[1]
                if wc_var not in names:
                    problems.append(f"{ds_name}.{wc_var} (value_level where)")
                for var in entry.get("variables", []):
                    if var["name"] not in names:
                        problems.append(f"{ds_name}.{var['name']} (value_level variable)")
        if problems:
            raise SpecError(
                f"{self._path}: not declared in the variables: of their dataset: "
                f"{'; '.join(dict.fromkeys(problems))}. Declare each variable, or remove "
                "the reference."
            )

    def _refuse_parent_qualifiers(self) -> None:
        """Refuse an SDTMIG 3.4 (or earlier) spec with a qualifier in its parent domain.

        Up to SDTMIG 3.4, a non-standard variable goes to SUPP--, not to
        the parent domain.  Fleet does not build SUPP-- metadata itself:
        the spec author moves the variable to a declared SUPP-- dataset.

        References:
            SDTMIG 3.4, section 8.4 (Relating Non-Standard Variable Values
            to a Parent Domain); ADR-0042.

        Raises:
            SpecError: Naming each DATASET.VARIABLE and its SUPP-- dataset.
        """
        study = self._data["study"]
        if study["standard"] != "SDTMIG":
            return
        version = tuple(int(p) for p in str(study["standard_version"]).split(".")[:2])
        if version > (3, 4):
            return
        hits = [
            (ds["name"], var["name"])
            for ds in self._data.get("datasets", [])
            if not ds["name"].startswith("SUPP")
            for var in ds.get("variables", [])
            if var.get("role") == "qualifier"
            or (var.get("derivation") or {}).get("algorithm") == "nsv"
        ]
        if hits:
            names = ", ".join(f"{ds}.{var}" for ds, var in hits)
            supps = ", ".join(dict.fromkeys(f"SUPP{ds}" for ds, _ in hits))
            raise SpecError(
                f"{self._path}: {names} has role qualifier (a non-standard variable). "
                f"SDTMIG {study['standard_version']} puts it in {supps}, not in the parent "
                f"domain. Declare {supps} in this spec, move the variable there, then "
                "generate the Define-XML again."
            )

    def _build_odm(self) -> ET.Element:
        self._validate_codelist_refs()
        self._validate_variable_refs()
        self._refuse_parent_qualifiers()
        self._warn_predecessor_candidates()
        # Import the spec's derivations_module so short-name `callable:`
        # derivations are registered before their MethodDefs are resolved
        # (from_spec does this too).  Study code runs only to write methods.
        if self._enrich_methods and self._import_study_code:
            _import_derivations_module(load_define_spec(self._path), source="define-xml")
        self._gaps = []
        study = self._data["study"]
        std_oid = _STANDARD_OIDS.get(study["standard"], f"STD.{study['standard']}")
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        file_oid = f"CDISC.{study['id']}.1.Define-XML_2.1.0"
        attribs: dict[str, str] = {
            "xmlns": _NS_ODM,
            "xmlns:xlink": _NS_XLINK,
            "xmlns:def": _NS_DEF,
            "ODMVersion": "1.3.2",
            "FileOID": file_oid,
            "FileType": "Snapshot",
            "CreationDateTime": ts,
            "Originator": study["originator"],
            "SourceSystem": study.get("source_system", "Fleet"),
            "SourceSystemVersion": study.get("source_system_version", "0.1.0"),
            "def:Context": "Submission",
        }
        odm = ET.Element("ODM", attrib=attribs)
        odm.append(self._build_study(study, std_oid))
        self._report_gaps()
        return odm

    def _report_gaps(self) -> None:
        """Refuse the define in strict mode, else name its gaps in one warning."""
        if not self._gaps:
            return
        shown = "\n  ".join(self._gaps[:25])
        more = f"\n  ... and {len(self._gaps) - 25} more" if len(self._gaps) > 25 else ""
        text = (
            f"{self._path}: {len(self._gaps)} Define-XML gap(s):\n  {shown}{more}\n"
            "Define-XML 2.1 requires a MethodOID on each Derived ItemRef, Length on "
            "text, integer and float, and SignificantDigits on float."
        )
        if self._strict:
            raise SpecError(text)
        warnings.warn(
            text + " The file is written; fleet define-xml --strict refuses it.",
            UserWarning,
            stacklevel=4,
        )

    # ------------------------------------------------------------------ #
    # Study / MetaDataVersion                                              #
    # ------------------------------------------------------------------ #

    def _build_study(self, study: dict[str, Any], std_oid: str) -> ET.Element:
        elem = ET.Element("Study", {"OID": f"STDY.{study['id']}"})
        gv = ET.SubElement(elem, "GlobalVariables")
        ET.SubElement(gv, "StudyName").text = study["name"]
        ET.SubElement(gv, "StudyDescription").text = study["description"].strip()
        ET.SubElement(gv, "ProtocolName").text = study["protocol_name"]
        elem.append(self._build_metadata_version(study, std_oid))
        return elem

    def _build_metadata_version(self, study: dict[str, Any], std_oid: str) -> ET.Element:
        ig = study["standard"]
        mdv_oid = f"MDV.{study['id']}.1.{ig}.{study['standard_version']}"
        attribs = {
            "OID": mdv_oid,
            "Name": f"{study['id']} {ig} Data Definitions",
            "Description": f"Dataset metadata for {study['id']} {ig} datasets",
            "def:DefineVersion": "2.1.0",
        }
        mdv = ET.Element("MetaDataVersion", attrib=attribs)

        # Standards list — must be wrapped in def:Standards per Define-XML 2.1 spec
        stds_container = ET.SubElement(mdv, "def:Standards")
        stds_container.append(
            self._build_standard(
                std_oid,
                _STANDARD_NAMES.get(study["standard"], study["standard"]),
                "IG",
                study["standard_version"],
            )
        )
        if study.get("ct_version"):
            stds_container.append(
                self._build_standard(
                    _CT_OID,
                    "CDISC/NCI",
                    "CT",
                    study["ct_version"],
                    publishing_set="SEND" if study["standard"] == "SENDIG" else "SDTM",
                )
            )
        if study.get("adam_ct_version"):
            stds_container.append(
                self._build_standard(
                    _ADAM_CT_OID,
                    "CDISC/NCI",
                    "CT",
                    study["adam_ct_version"],
                    publishing_set="ADaM",
                )
            )

        # AnnotatedCRF — emitted when study.documents.annotated_crf is set
        acrf_cfg = self._get_acrf_config()
        if acrf_cfg:
            acrf_elem = ET.SubElement(mdv, "def:AnnotatedCRF")
            ET.SubElement(acrf_elem, "def:DocumentRef", {"leafID": self._acrf_leaf_id()})

        # SupplementalDoc — additional supporting documents
        docs = self._data.get("study", {}).get("documents", {})
        supp_docs = docs.get("supplemental_docs", [])
        if supp_docs:
            supp_elem = ET.SubElement(mdv, "def:SupplementalDoc")
            for sd in supp_docs:
                ET.SubElement(supp_elem, "def:DocumentRef", {"leafID": sd["id"]})

        datasets: list[dict[str, Any]] = self._data.get("datasets", [])
        self._vlm_parents = {
            (ds["name"], var["name"])
            for ds in datasets
            for entry in ds.get("value_level") or []
            for var in entry.get("variables", [])
        }

        # Value-level metadata (def:ValueListDef / def:WhereClauseDef) —
        # placed before ItemGroupDefs per the Define-XML 2.1 element order.
        # Must run before ItemDefs so def:ValueListRef wiring is known.
        vl_defs, wc_defs, vl_item_defs = self._build_value_level(datasets)
        mdv.extend(vl_defs)
        mdv.extend(wc_defs)

        # ItemGroupDefs (one per dataset)
        for ds in datasets:
            mdv.append(self._build_item_group_def(ds, study["id"]))

        # ItemDefs (collect all unique variables across datasets), then the
        # value-level ItemDefs referenced from the ValueListDefs.
        mdv.extend(self._build_all_item_defs(datasets))
        mdv.extend(vl_item_defs)

        # CodeLists
        for cl in self._data.get("codelists", []):
            mdv.append(self._build_codelist(cl))

        # MethodDefs (only populated when enrich_methods=True; lazily
        # registered by _build_item_def via _register_method).
        for method_oid in sorted(self._method_defs):
            mdv.append(self._build_method_def(method_oid, self._method_defs[method_oid]))

        # def:CommentDefs: the record selection of each dataset (row_steps, ADR-0034).
        for ds in datasets:
            if ds.get("row_steps"):
                comment = ET.Element("def:CommentDef", {"OID": f"COM.{ds['name']}.ROWS"})
                desc = ET.SubElement(comment, "Description")
                ET.SubElement(desc, "TranslatedText", {"xml:lang": "en"}).text = _row_steps_text(
                    ds["row_steps"]
                )
                mdv.append(comment)

        # Annotated CRF leaf
        if acrf_cfg:
            acrf_leaf = ET.Element(
                "def:leaf",
                {
                    "ID": self._acrf_leaf_id(),
                    "xlink:href": acrf_cfg["href"],
                },
            )
            ET.SubElement(acrf_leaf, "def:title").text = acrf_cfg.get(
                "title", "Annotated Case Report Form"
            )
            mdv.append(acrf_leaf)

        # Supplemental document leaves
        for sd in supp_docs:
            sd_leaf = ET.Element("def:leaf", {"ID": sd["id"], "xlink:href": sd["href"]})
            ET.SubElement(sd_leaf, "def:title").text = sd["title"]
            mdv.append(sd_leaf)

        return mdv

    # ------------------------------------------------------------------ #
    # Element builders                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_standard(
        oid: str, name: str, kind: str, version: str, publishing_set: str | None = None
    ) -> ET.Element:
        attribs: dict[str, str] = {
            "OID": oid,
            "Name": name,
            "Type": kind,
            "Version": version,
            "Status": "Final",
        }
        if publishing_set:
            attribs["PublishingSet"] = publishing_set
        return ET.Element("def:Standard", attrib=attribs)

    def _build_item_group_def(self, ds: dict[str, Any], study_id: str) -> ET.Element:
        name = ds["name"]
        ig_oid = f"IG.{name}"
        leaf_id = f"LF.{name}"
        std_oid = _STANDARD_OIDS.get(self._data["study"]["standard"], "STD.IG")
        repeating = ds.get("repeating")
        if repeating is None:
            repeating = default_repeating(name)
        reference = ds.get("is_reference_data")
        if reference is None:
            reference = default_is_reference_data(name, ds.get("class"))
        # A SUPP-- dataset describes its parent domain (SUPPAE: Domain AE).
        domain = name[4:] if name.startswith("SUPP") and len(name) > 4 else name

        attribs: dict[str, str] = {
            "OID": ig_oid,
            "Name": name,
            "Repeating": "Yes" if repeating else "No",
            "IsReferenceData": "Yes" if reference else "No",
            "SASDatasetName": name,
            "Domain": domain,
            "def:Structure": ds["structure"],
            "Purpose": "Tabulation" if self._data["study"]["standard"] == "SDTMIG" else "Analysis",
            "def:StandardOID": std_oid,
            "def:ArchiveLocationID": leaf_id,
        }
        if ds.get("row_steps"):
            attribs["def:CommentOID"] = f"COM.{name}.ROWS"
        elem = ET.Element("ItemGroupDef", attrib=attribs)

        desc = ET.SubElement(elem, "Description")
        ET.SubElement(desc, "TranslatedText", {"xml:lang": "en"}).text = ds["label"]

        key_vars: set[str] = set(ds.get("keys", []))
        key_order: dict[str, int] = {v: i + 1 for i, v in enumerate(ds.get("keys", []))}

        for order, var in enumerate(ds["variables"], start=1):
            var_name = var["name"]
            item_oid = self._item_oid(name, var_name)
            ref_attrs: dict[str, str] = {
                "ItemOID": item_oid,
                "OrderNumber": str(order),
                "Mandatory": "Yes" if var.get("mandatory") else "No",
            }
            if var_name in key_vars:
                ref_attrs["KeySequence"] = str(key_order[var_name])
            # Define-XML 2.1 places MethodOID on the ItemRef (usage site),
            # not on the ItemDef — and only Derived-origin variables carry
            # a computational method (a collected column rename is not a
            # MethodDef).  A parent with value-level metadata is judged there.
            if (
                var.get("origin", "Derived") == "Derived"
                and (name, var_name) not in self._vlm_parents
            ):
                method_oid = self._method_ref(
                    var, dataset=name, target=var_name, label=f"{name}.{var_name}"
                )
                if method_oid:
                    ref_attrs["MethodOID"] = method_oid
            ET.SubElement(elem, "ItemRef", attrib=ref_attrs)

        # Define-XML 2.1 orders ItemGroupDef children Description → ItemRef*
        # → def:Class → def:leaf; emitting Class earlier invalidates the file.
        if ds.get("class"):
            ET.SubElement(elem, "def:Class", {"Name": ds["class"]})

        # Leaf reference — href follows the actual export format
        href = self._leaf_href(ds)
        leaf = ET.SubElement(elem, "def:leaf", {"ID": leaf_id, "xlink:href": href})
        ET.SubElement(leaf, "def:title").text = href

        return elem

    def _build_all_item_defs(self, datasets: list[dict[str, Any]]) -> list[ET.Element]:
        """Build one ItemDef per dataset variable, from that dataset's metadata."""
        seen: dict[str, ET.Element] = {}  # item_oid → element
        result: list[ET.Element] = []
        for ds in datasets:
            for var in ds["variables"]:
                item_oid = self._item_oid(ds["name"], var["name"])
                if item_oid not in seen:
                    elem = self._build_item_def(item_oid, var, ds["name"])
                    seen[item_oid] = elem
                    result.append(elem)
        return result

    def _build_item_def(
        self,
        item_oid: str,
        var: dict[str, Any],
        dataset_name: str,
        *,
        vl_key: str | None = None,
        label: str | None = None,
    ) -> ET.Element:
        attribs: dict[str, str] = {
            "OID": item_oid,
            "Name": var["name"],
            "DataType": _TYPE_TO_ODM[var["type"]],
            "SASFieldName": var["name"],
        }
        where = label or f"{dataset_name}.{var['name']}"
        if var.get("length") is not None:
            attribs["Length"] = str(var["length"])
        elif var["type"] in ("text", "integer", "float"):
            self._gaps.append(f"{where}: no Length (required on text, integer and float)")
        if var.get("significant_digits") is not None:
            attribs["SignificantDigits"] = str(var["significant_digits"])
        elif var["type"] == "float":
            self._gaps.append(f"{where}: no SignificantDigits (required on float)")

        elem = ET.Element("ItemDef", attrib=attribs)

        desc = ET.SubElement(elem, "Description")
        ET.SubElement(desc, "TranslatedText", {"xml:lang": "en"}).text = var["label"]

        if var.get("codelist"):
            ET.SubElement(elem, "CodeListRef", {"CodeListOID": var["codelist"]})

        origin_type = var.get("origin", "Derived")
        origin_attrs = {"Type": origin_type}
        # Define-XML 2.1 pairs a collected value with its source; CRF data
        # (the common case) is Investigator-provided unless stated.
        if origin_type == "Collected":
            origin_attrs["Source"] = var.get("origin_source") or "Investigator"
        orig_elem = ET.SubElement(elem, "def:Origin", origin_attrs)

        # Origin description — study-authored text only, never Fleet
        # docstrings.  Precedence: a Predecessor names its
        # DATASET.VARIABLE source; a comment: that already became this
        # variable's MethodDef description is not repeated here; a
        # value-level parent points reviewers at the VLM section; a
        # CRF-collected variable with no page reference still names its
        # source document.  (MethodDefs are registered before ItemDefs
        # are built — see _build_metadata_version ordering.)
        vl_oid = self._value_list_refs.get(item_oid)
        comment = var.get("comment") or ""
        if origin_type == "Predecessor":
            desc_text = var.get("predecessor") or comment
        elif self._method_oid(dataset_name, var["name"], vl_key) in self._method_defs:
            desc_text = ""
        else:
            desc_text = comment
        if not desc_text and vl_oid:
            desc_text = "See Value Level Metadata"
        crf_ref = self._crf_page_ref(dataset_name, var["name"], vl_key)
        if (
            not desc_text
            and origin_type == "Collected"
            and origin_attrs["Source"] == "Investigator"
            and crf_ref is None
        ):
            desc_text = "Case Report Form"
        if desc_text:
            orig_desc = ET.SubElement(orig_elem, "Description")
            ET.SubElement(orig_desc, "TranslatedText", {"xml:lang": "en"}).text = desc_text

        # CRF page references — emit DocumentRef/PDFPageRef inside Origin
        if crf_ref is not None:
            self._append_crf_page_ref(orig_elem, *crf_ref)

        # Value-level metadata: point the parent ItemDef at its ValueListDef
        if vl_oid:
            ET.SubElement(elem, "def:ValueListRef", {"ValueListOID": vl_oid})

        return elem

    def _method_ref(
        self,
        var: dict[str, Any],
        *,
        dataset: str,
        target: str,
        label: str,
        vl_key: str | None = None,
    ) -> str | None:
        """Return the MethodOID of one Derived variable, or record why it has none."""
        if not self._enrich_methods:
            self._gaps.append(f"{label}: no MethodDef (enrich_methods=False)")
            return None
        derivation = var.get("derivation") or {}
        if not derivation and not var.get("comment"):
            self._gaps.append(f"{label}: no method text (add a comment: or a derivation: block)")
            return None
        method_oid, problem = self._register_method(
            derivation,
            dataset=dataset,
            target=target,
            comment=var.get("comment"),
            vl_key=vl_key,
            codelist=var.get("codelist"),
        )
        if problem:
            self._gaps.append(f"{label}: {problem}")
        return method_oid

    @staticmethod
    def _method_oid(dataset: str, target: str, vl_key: str | None = None) -> str:
        """Per-variable MethodDef OID: ``MT.<dataset>.<target>[.<vl_key>]``."""
        oid = f"MT.{dataset}.{target}"
        return f"{oid}.{vl_key}" if vl_key else oid

    @staticmethod
    def _resolve_callable(callable_path: str) -> tuple[str | None, str | None]:
        """Summary + dotted path for a ``callable:`` derivation.

        Prefers a registered ``Derivation`` object's own docstring and
        ``dotted_path``; falls back to importing the dotted path.  This
        is *study-authored* text (unlike Fleet verb docstrings, which are
        never used in a define).
        """
        try:
            from fleet.adam.transforms import get_transform

            obj = get_transform(callable_path)
            if hasattr(obj, "dotted_path"):
                return (docstring_summary(obj.fn.__doc__), obj.dotted_path)
        except Exception:
            pass
        return resolve_callable_docstring(callable_path)

    def _register_method(
        self,
        derivation: dict[str, Any],
        *,
        dataset: str,
        target: str,
        comment: str | None = None,
        vl_key: str | None = None,
        codelist: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Register the MethodDef for one derived variable; return its OID and a problem.

        One MethodDef per derived variable, named ``Algorithm for
        <target>`` — never Fleet's internal algorithm id.  Description
        precedence: the spec ``comment:``, then the study callable's
        docstring (``callable:`` escape hatch), then the registry's
        submission-facing template / synthesised text
        (:func:`fleet.core.spec_registry.render_method_text`).  The OID is
        ``None`` when no reviewer-facing text can be produced — the
        variable then ships without a MethodDef rather than with API
        prose.  The problem names what the define reviewer must fix (a
        callable that does not import is a problem even with a comment).
        """
        callable_path = derivation.get("callable")
        algorithm = str(derivation.get("algorithm") or "")
        description = (comment or "").strip()
        context = "Python/Fleet"
        expression = ""
        problem: str | None = None

        if callable_path and algorithm in ("", "derivation") and not self._import_study_code:
            # No study import: the comment, or the dotted path, describes it.
            description = description or f"Study derivation {callable_path}."
            expression = str(callable_path)
            context = "Python"
        elif callable_path and algorithm in ("", "derivation"):
            summary, dotted = self._resolve_callable(str(callable_path))
            if summary is None and dotted is None:
                problem = f"callable {callable_path} does not import"
            elif summary is None and not description:
                problem = f"callable {callable_path} has no docstring"
            description = description or _strip_rest_markup(summary or "")
            expression = dotted or ""
            context = "Python"
        elif algorithm:
            std = _REGISTRY_STANDARDS.get(self._data["study"]["standard"], "sdtm")
            # The variable's codelist: is the ct: of its assign (ADR-0008), so the
            # method text says "mapped to controlled terminology" when it applies.
            try:
                block = spec_registry.with_codelist(std, derivation, codelist)
            except ValueError:
                block = dict(derivation)
            params = {k: v for k, v in block.items() if k != "algorithm"}
            description = description or (
                spec_registry.render_method_text(std, algorithm, params, target=target) or ""
            )
            expression = (
                spec_registry.render_formal_expression(std, algorithm, params, target=target)
                or algorithm
            )

        if not description:
            return None, problem or "no method text (add a comment:)"

        method_oid = self._method_oid(dataset, target, vl_key)
        self._method_defs.setdefault(
            method_oid,
            {
                "name": f"Algorithm for {target}",
                "description": description,
                "expression": expression,
                "context": context,
            },
        )
        return method_oid, problem

    @staticmethod
    def _build_method_def(method_oid: str, info: dict[str, str]) -> ET.Element:
        """Render a Define-XML 2.1 ``MethodDef`` element.

        See CDISC Define-XML 2.1 §4.2.2 for the FormalExpression contract.
        FormalExpression is optional: a method described only in words
        (a ``comment:``) has none, as in the CDISC ADaM example define.
        """
        elem = ET.Element(
            "MethodDef",
            {"OID": method_oid, "Name": info["name"], "Type": "Computation"},
        )
        desc = ET.SubElement(elem, "Description")
        ET.SubElement(desc, "TranslatedText", {"xml:lang": "en"}).text = info["description"]
        if info["expression"]:
            formal = ET.SubElement(elem, "FormalExpression", {"Context": info["context"]})
            formal.text = info["expression"]
        return elem

    def _build_codelist(self, cl: dict[str, Any]) -> ET.Element:
        """Render one CodeList in the form its terms call for.

        Every term with a decode gives ``CodeListItem``; no term with a
        decode gives ``EnumeratedItem``; ``external:`` gives
        ``ExternalCodeList`` (MedDRA).  ``nci_code`` gives the NCI
        ``Alias``, ``extended: true`` marks a sponsor term.

        Raises:
            SpecError: When some terms have a decode and some do not.
        """
        attribs: dict[str, str] = {
            "OID": cl["oid"],
            "Name": cl["name"],
            "DataType": _TYPE_TO_ODM[cl["type"]],
        }
        standard = cl.get("standard_oid")
        if not standard and _CT_OID in self._declared_standards() and _NCI_CODE.match(cl["oid"]):
            standard = _CT_OID
        if standard:
            attribs["def:StandardOID"] = standard
        elem = ET.Element("CodeList", attrib=attribs)
        external = cl.get("external")
        if external:
            ET.SubElement(
                elem,
                "ExternalCodeList",
                {"Dictionary": external["dictionary"], "Version": str(external["version"])},
            )
        items = [] if external else cl.get("items", [])
        undecoded = [item["coded_value"] for item in items if not item.get("decode")]
        if undecoded and len(undecoded) < len(items):
            raise SpecError(
                f"{self._path}: codelist {cl['oid']} mixes terms with and without a decode "
                f"(term {undecoded[0]!r} has none). Give every term a decode "
                "(CodeListItem) or none (EnumeratedItem)."
            )
        tag = "EnumeratedItem" if undecoded else "CodeListItem"
        for item in items:
            item_attrs = {"CodedValue": item["coded_value"]}
            if item.get("extended"):
                item_attrs["def:ExtendedValue"] = "Yes"
            ci = ET.SubElement(elem, tag, item_attrs)
            if item.get("decode"):
                decode = ET.SubElement(ci, "Decode")
                ET.SubElement(decode, "TranslatedText", {"xml:lang": "en"}).text = item["decode"]
            if item.get("nci_code"):
                ET.SubElement(ci, "Alias", {"Context": "nci:ExtCodeID", "Name": item["nci_code"]})
        if cl.get("nci_code"):
            ET.SubElement(elem, "Alias", {"Context": "nci:ExtCodeID", "Name": cl["nci_code"]})
        return elem

    # ------------------------------------------------------------------ #
    # Value-level metadata (def:ValueListDef / def:WhereClauseDef)         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalise_where(ds_name: str, entry: dict[str, Any]) -> tuple[str, str, list[str]]:
        """Resolve a value-level entry's condition to (wc_oid, variable, values).

        ``param: SYSBP`` is sugar for ``where: {variable: PARAMCD,
        value: SYSBP}`` — the idiomatic BDS case.
        """
        if entry.get("param") is not None:
            wc_var, values = "PARAMCD", [str(entry["param"])]
        else:
            where = entry["where"]
            wc_var = where["variable"]
            raw = where["value"]
            values = [str(v) for v in raw] if isinstance(raw, list) else [str(raw)]
        key = "_".join(values)
        return f"WC.{ds_name}.{wc_var}.{key}", wc_var, values

    def _build_value_level(
        self, datasets: list[dict[str, Any]]
    ) -> tuple[list[ET.Element], list[ET.Element], list[ET.Element]]:
        """Build value-level metadata elements from ``value_level:`` specs.

        For each dataset entry ``{param|where, variables}``, emits:

        * one ``def:WhereClauseDef`` per condition (``RangeCheck`` with
          ``EQ`` for a single value, ``IN`` for a list);
        * per value-level variable, an ``ItemRef`` (with
          ``def:WhereClauseRef`` and, when method enrichment is on, a
          ``MethodOID``) inside that variable's ``def:ValueListDef``;
        * one ``ItemDef`` per (variable, condition) pair.

        Also populates ``self._value_list_refs`` so the parent ItemDefs
        emit their ``def:ValueListRef``.

        Returns:
            tuple: ``(value_list_defs, where_clause_defs, item_defs)``.
        """
        value_lists: dict[str, ET.Element] = {}  # VL OID → element
        vl_counters: dict[str, int] = {}
        where_defs: dict[str, ET.Element] = {}  # WC OID → element
        item_defs: list[ET.Element] = []

        for ds in datasets:
            ds_name = ds["name"]
            for entry in ds.get("value_level", []) or []:
                wc_oid, wc_var, values = self._normalise_where(ds_name, entry)

                if wc_oid not in where_defs:
                    wc_elem = ET.Element("def:WhereClauseDef", {"OID": wc_oid})
                    rc = ET.SubElement(
                        wc_elem,
                        "RangeCheck",
                        {
                            "Comparator": "EQ" if len(values) == 1 else "IN",
                            "SoftHard": "Soft",
                            "def:ItemOID": self._item_oid(ds_name, wc_var),
                        },
                    )
                    for value in values:
                        ET.SubElement(rc, "CheckValue").text = value
                    where_defs[wc_oid] = wc_elem

                for var in entry.get("variables", []):
                    var_name = var["name"]
                    parent_oid = self._item_oid(ds_name, var_name)
                    vl_oid = f"VL.{ds_name}.{var_name}"
                    self._value_list_refs[parent_oid] = vl_oid
                    if vl_oid not in value_lists:
                        value_lists[vl_oid] = ET.Element("def:ValueListDef", {"OID": vl_oid})
                        vl_counters[vl_oid] = 0

                    key = "_".join(values)
                    item_oid = f"IT.{ds_name}.{var_name}.{key}"
                    label = f"{ds_name}.{var_name} ({wc_var} = {', '.join(values)})"

                    vl_counters[vl_oid] += 1
                    ref_attrs: dict[str, str] = {
                        "ItemOID": item_oid,
                        "OrderNumber": str(vl_counters[vl_oid]),
                        "Mandatory": "Yes" if var.get("mandatory") else "No",
                    }
                    if var.get("origin", "Derived") == "Derived":
                        method_oid = self._method_ref(
                            var, dataset=ds_name, target=var_name, label=label, vl_key=key
                        )
                        if method_oid:
                            ref_attrs["MethodOID"] = method_oid
                    item_ref = ET.SubElement(value_lists[vl_oid], "ItemRef", ref_attrs)
                    ET.SubElement(item_ref, "def:WhereClauseRef", {"WhereClauseOID": wc_oid})
                    # Built after _register_method so the ItemDef knows its
                    # comment: was consumed by the MethodDef.
                    item_defs.append(
                        self._build_item_def(item_oid, var, ds_name, vl_key=key, label=label)
                    )

        return list(value_lists.values()), list(where_defs.values()), item_defs

    def _crf_page_ref(
        self, dataset_name: str, var_name: str, vl_key: str | None = None
    ) -> tuple[str, dict[str, Any]] | None:
        """Return the leaf ID and page reference of one variable, or None.

        A value-level item reads ``DATASET.VARIABLE.<where values>`` first,
        then its parent ``DATASET.VARIABLE``.  ``doc:`` names the href of
        the annotated CRF or of a supplemental document.

        Raises:
            SpecError: When ``doc:`` matches no declared document href.
        """
        key = f"{dataset_name}.{var_name}"
        crf_ref = self._page_map.get(f"{key}.{vl_key}") if vl_key else None
        if crf_ref is None:
            crf_ref = self._page_map.get(key)
        if crf_ref is None:
            return None
        acrf_cfg = self._get_acrf_config()
        doc_href = crf_ref.get("doc")
        if not doc_href:
            # No annotated CRF: _load_page_map warned that the page is lost.
            return (self._acrf_leaf_id(), crf_ref) if acrf_cfg else None
        if acrf_cfg and doc_href == acrf_cfg.get("href"):
            return self._acrf_leaf_id(), crf_ref
        docs = self._data.get("study", {}).get("documents", {})
        for sd in docs.get("supplemental_docs", []):
            if sd["href"] == doc_href:
                return sd["id"], crf_ref
        raise SpecError(
            f"{self._path}: {key} crf_pages doc {doc_href} matches no annotated_crf or "
            "supplemental_docs href. Declare the document under study.documents."
        )

    @staticmethod
    def _append_crf_page_ref(origin_elem: ET.Element, leaf_id: str, crf_ref: dict) -> None:
        """Append a ``def:DocumentRef`` with ``def:PDFPageRef`` to an Origin element."""
        doc_ref = ET.SubElement(origin_elem, "def:DocumentRef", {"leafID": leaf_id})
        pages = crf_ref.get("pages")
        first_page = crf_ref.get("first_page")
        last_page = crf_ref.get("last_page")
        if pages or first_page:
            pr_attrs: dict[str, str] = {"Type": crf_ref.get("type", "PhysicalRef")}
            if pages:
                pr_attrs["PageRefs"] = pages
            if first_page:
                pr_attrs["FirstPage"] = first_page
            if last_page:
                pr_attrs["LastPage"] = last_page
            ET.SubElement(doc_ref, "def:PDFPageRef", pr_attrs)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _item_oid(dataset_name: str, var_name: str) -> str:
        """Build the ItemDef OID ``IT.<DATASET>.<VARIABLE>``.

        Each dataset variable has its own ItemDef, so ADSL.AGE and ADAE.AGE
        each keep their own type, length, origin and codelist.
        """
        return f"IT.{dataset_name}.{var_name}"

    @staticmethod
    def _to_pretty_xml(root: ET.Element) -> str:
        raw = ET.tostring(root, encoding="unicode", method="xml")
        dom = xml.dom.minidom.parseString(raw)
        pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        lines = [ln for ln in pretty.split("\n") if ln.strip()]
        if lines and lines[0].startswith("<?xml"):
            lines.insert(1, '<?xml-stylesheet type="text/xsl" href="define2-1.xsl"?>')
        return "\n".join(lines)
