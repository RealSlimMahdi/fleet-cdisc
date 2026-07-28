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
import xml.dom.minidom
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from lxml import etree as lxml_etree

from fleet.core.algorithm_resolver import (
    resolve_algorithm_docstring,
    resolve_callable_docstring,
)
from fleet.core.exceptions import SpecError

_SCHEMA_PATH = Path(__file__).parent / "schemas" / "define_spec_schema.json"

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

#: Spec ``study.standard`` → the ``def:Standard/@Name`` value Define-XML 2.1
#: enumerates (note the lower-case 'a' in ADaMIG).
_STANDARD_NAMES: dict[str, str] = {
    "SDTMIG": "SDTMIG",
    "ADAMIG": "ADaMIG",
    "SENDIG": "SENDIG",
}

#: Spec ``study.standard`` → the ``def:Standard/@PublishingSet`` value, a
#: separate and smaller enumeration than the IG names.
_PUBLISHING_SETS: dict[str, str] = {
    "SDTMIG": "SDTM",
    "ADAMIG": "ADaM",
    "SENDIG": "SEND",
}

# Map export format (spec key ``output_format``) → def:leaf href extension.
_FORMAT_EXT: dict[str, str] = {
    "parquet": ".parquet",
    "xpt": ".xpt",
    "dataset-json": ".json",
}


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
    """

    def __init__(
        self,
        define_yaml_path: str | Path,
        *,
        validate_schema: bool = True,
        validate_xml: bool = True,
        enrich_methods: bool = False,
    ) -> None:
        self._path = Path(define_yaml_path)
        self._data: dict[str, Any] = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        self._check_spec_version()
        self._enrich_methods = enrich_methods
        self._validate_xml = validate_xml
        # Populated via _register_method when enrich_methods is True;
        # rendered into MethodDef elements at the end of MetaDataVersion.
        self._method_defs: dict[str, dict[str, str]] = {}
        # ItemDef OID → ValueListDef OID (populated by _build_value_level;
        # consumed by _build_item_def to emit def:ValueListRef).
        self._value_list_refs: dict[str, str] = {}
        # Resolve the CRF page map once (merges external page_map with
        # inline crf_pages; inline takes precedence).
        self._page_map: dict[str, str | dict[str, Any]] = self._load_page_map()
        if validate_schema:
            self._validate()

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
        """Apply the define2-1.xsl transform and write an HTML preview file."""
        resolved_xsl = Path(xsl_path) if xsl_path else xml_path.parent / "define2-1.xsl"

        if not resolved_xsl.exists():
            print(
                f"HTML preview skipped: XSL stylesheet not found at '{resolved_xsl}'. "
                "Place define2-1.xsl in the same directory as the XML output, "
                "or pass xsl_path= explicitly."
            )
            return

        xml_doc = lxml_etree.parse(str(xml_path))  # noqa: S320 — local file, not user input
        xsl_doc = lxml_etree.parse(str(resolved_xsl))  # noqa: S320 — local file, not user input
        transform = lxml_etree.XSLT(xsl_doc)
        html_doc = transform(xml_doc)

        html_path = xml_path.with_name(xml_path.stem + "_preview.html")
        html_path.write_bytes(lxml_etree.tostring(html_doc, pretty_print=True, method="html"))
        print(f"HTML preview generated: {html_path}")

    def to_xml_string(self) -> str:
        """Return the Define-XML as a formatted string without writing a file."""
        return self._serialise(self._build_odm())

    def _serialise(self, root: ET.Element) -> str:
        """Format *root* and, unless disabled, XSD-validate before returning."""
        xml_str = self._to_pretty_xml(root)
        if not self._validate_xml:
            return xml_str

        from fleet.core.exceptions import SpecError
        from fleet.define_xml.xsd import validate_define_xml

        errors = validate_define_xml(xml_str)
        if errors:
            shown = "\n  ".join(errors[:10])
            more = f"\n  ... and {len(errors) - 10} more" if len(errors) > 10 else ""
            raise SpecError(
                f"{self._path}: generated Define-XML is not valid against the "
                f"Define-XML 2.1 schema ({len(errors)} error(s)):\n  {shown}{more}\n"
                "Pass validate_xml=False to generate it anyway."
            )
        return xml_str

    # ------------------------------------------------------------------ #
    # CRF page map                                                         #
    # ------------------------------------------------------------------ #

    def _load_page_map(self) -> dict[str, str | dict[str, Any]]:
        """Build a merged CRF page map from external file and inline values.

        Returns a dict keyed by ``"DOMAIN.VARIABLE"`` whose values are
        either a plain page-number string (Layer 1) or a dict with rich
        reference info (Layer 2).  Inline ``crf_pages`` on each variable
        take precedence over entries in the external ``page_map`` file.
        """
        merged: dict[str, str | dict[str, Any]] = {}

        # Layer 3: external page_map YAML
        docs = self._data.get("study", {}).get("documents", {})
        acrf = docs.get("annotated_crf", {})
        page_map_path = acrf.get("page_map")
        if page_map_path:
            resolved = (self._path.parent / page_map_path).resolve()
            if resolved.is_file():
                raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    merged.update(raw)

        # Layer 1 / 2: inline crf_pages on each variable (overrides external)
        for ds in self._data.get("datasets", []):
            ds_name = ds["name"]
            for var in ds.get("variables", []):
                crf = var.get("crf_pages")
                if crf is not None:
                    merged[f"{ds_name}.{var['name']}"] = crf

        return merged

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
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(self._data))
        if errors:
            msgs = "\n".join(f"  - {e.json_path}: {e.message}" for e in errors[:5])
            raise ValueError(f"define YAML failed schema validation:\n{msgs}")

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

    def _build_odm(self) -> ET.Element:
        self._validate_codelist_refs()
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
        return odm

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
                    publishing_set=_PUBLISHING_SETS.get(study["standard"]),
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
        repeating = "Yes" if ds.get("repeating", True) else "No"

        attribs: dict[str, str] = {
            "OID": ig_oid,
            "Name": name,
            "Repeating": repeating,
            "IsReferenceData": "No",
            "SASDatasetName": name,
            "Domain": name,
            "def:Structure": ds["structure"],
            "Purpose": "Tabulation" if self._data["study"]["standard"] == "SDTMIG" else "Analysis",
            "def:StandardOID": std_oid,
            "def:ArchiveLocationID": leaf_id,
        }
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
            # not on the ItemDef.
            derivation = var.get("derivation")
            if self._enrich_methods and derivation:
                method_oid, _ = self._register_method(derivation)
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
        """Build ItemDef elements; shared variables (same name & type) share an OID."""
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

    def _build_item_def(self, item_oid: str, var: dict[str, Any], dataset_name: str) -> ET.Element:
        attribs: dict[str, str] = {
            "OID": item_oid,
            "Name": var["name"],
            "DataType": _TYPE_TO_ODM[var["type"]],
            "SASFieldName": var["name"],
        }
        if var.get("length") is not None:
            attribs["Length"] = str(var["length"])

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

        # Build the human-readable origin description.  When
        # enrich_methods is on we resolve the verb (or callable) docstring
        # so reviewers see the exact computational method without leaving
        # the Define-XML.  (The MethodOID itself lives on the ItemRef per
        # Define-XML 2.1 — see _build_item_group_def / _build_value_level.)
        comment = var.get("comment") or ""
        derivation = var.get("derivation") or {}
        if self._enrich_methods and derivation:
            _, summary = self._register_method(derivation)
            if summary:
                comment = f"{comment} {summary}".strip() if comment else summary
        if comment:
            orig_desc = ET.SubElement(orig_elem, "Description")
            ET.SubElement(orig_desc, "TranslatedText", {"xml:lang": "en"}).text = comment

        # CRF page references — emit DocumentRef/PDFPageRef inside Origin
        self._append_crf_page_ref(orig_elem, dataset_name, var["name"])

        # Value-level metadata: point the parent ItemDef at its ValueListDef
        vl_oid = self._value_list_refs.get(item_oid)
        if vl_oid:
            ET.SubElement(elem, "def:ValueListRef", {"ValueListOID": vl_oid})

        return elem

    def _register_method(
        self,
        derivation: dict[str, Any],
    ) -> tuple[str | None, str]:
        """Resolve a derivation block to a MethodDef and return its OID + summary.

        Looks up either the ``callable`` dotted path (UC-5) or the
        ``algorithm`` verb name (UC-4) and registers a MethodDef entry on
        ``self._method_defs`` keyed by a stable OID.  Returns the OID and
        the docstring summary so the caller can also append the summary
        to the Origin description.
        """
        callable_path = derivation.get("callable")
        algorithm = derivation.get("algorithm") or ""
        expression = derivation.get("expression") or ""

        if callable_path:
            # Prefer Derivation.dotted_path when the object is registered.
            try:
                from fleet.adam.transforms import get_transform

                obj = get_transform(str(callable_path))
                if hasattr(obj, "dotted_path"):
                    # Derivation object — use its dotted_path and fn docstring.
                    summary = (obj.fn.__doc__ or "").splitlines()[0].strip()
                    dotted = obj.dotted_path
                else:
                    summary, dotted = resolve_callable_docstring(str(callable_path))
            except (KeyError, Exception):
                summary, dotted = resolve_callable_docstring(str(callable_path))
            if not dotted:
                return (None, "")
            method_name = dotted.rsplit(".", 1)[-1]
            method_oid = f"MT.{method_name}"
            self._method_defs.setdefault(
                method_oid,
                {
                    "name": method_name,
                    "description": summary or f"Custom callable: {dotted}",
                    "expression": expression or dotted,
                    "context": "Python",
                },
            )
            return (method_oid, summary or "")

        if not algorithm:
            return (None, "")

        summary, dotted = resolve_algorithm_docstring(str(algorithm))
        if not dotted:
            return (None, "")
        info = {
            "name": algorithm,
            "description": summary or f"Fleet verb: {algorithm}",
            "expression": expression or f".{algorithm}(...)",
            "context": "Python/Fleet",
        }
        # Same algorithm, different expression (e.g. per-PARAMCD value-level
        # derivations) → distinct MethodDef OIDs; identical calls share one.
        method_oid = f"MT.{algorithm}"
        suffix = 2
        while (
            method_oid in self._method_defs
            and self._method_defs[method_oid]["expression"] != info["expression"]
        ):
            method_oid = f"MT.{algorithm}.{suffix}"
            suffix += 1
        self._method_defs.setdefault(method_oid, info)
        return (method_oid, summary or "")

    @staticmethod
    def _build_method_def(method_oid: str, info: dict[str, str]) -> ET.Element:
        """Render a Define-XML 2.1 ``MethodDef`` element.

        See CDISC Define-XML 2.1 §4.2.2 for the FormalExpression contract.
        """
        elem = ET.Element(
            "MethodDef",
            {"OID": method_oid, "Name": info["name"], "Type": "Computation"},
        )
        desc = ET.SubElement(elem, "Description")
        ET.SubElement(desc, "TranslatedText", {"xml:lang": "en"}).text = info["description"]
        formal = ET.SubElement(elem, "FormalExpression", {"Context": info["context"]})
        formal.text = info["expression"]
        return elem

    @staticmethod
    def _build_codelist(cl: dict[str, Any]) -> ET.Element:
        attribs: dict[str, str] = {
            "OID": cl["oid"],
            "Name": cl["name"],
            "DataType": _TYPE_TO_ODM[cl["type"]],
        }
        elem = ET.Element("CodeList", attrib=attribs)
        for item in cl.get("items", []):
            ci = ET.SubElement(elem, "CodeListItem", {"CodedValue": item["coded_value"]})
            if item.get("decode"):
                decode = ET.SubElement(ci, "Decode")
                ET.SubElement(decode, "TranslatedText", {"xml:lang": "en"}).text = item["decode"]
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
                    item_defs.append(self._build_item_def(item_oid, var, ds_name))

                    vl_counters[vl_oid] += 1
                    ref_attrs: dict[str, str] = {
                        "ItemOID": item_oid,
                        "OrderNumber": str(vl_counters[vl_oid]),
                        "Mandatory": "Yes" if var.get("mandatory") else "No",
                    }
                    derivation = var.get("derivation")
                    if self._enrich_methods and derivation:
                        method_oid, _ = self._register_method(derivation)
                        if method_oid:
                            ref_attrs["MethodOID"] = method_oid
                    item_ref = ET.SubElement(value_lists[vl_oid], "ItemRef", ref_attrs)
                    ET.SubElement(item_ref, "def:WhereClauseRef", {"WhereClauseOID": wc_oid})

        return list(value_lists.values()), list(where_defs.values()), item_defs

    def _append_crf_page_ref(
        self, origin_elem: ET.Element, dataset_name: str, var_name: str
    ) -> None:
        """Append a ``def:DocumentRef`` with ``def:PDFPageRef`` to an Origin element.

        Resolves CRF page info from the merged page map.  Supports both
        the simple string form (Layer 1) and the rich dict form (Layer 2).
        """
        key = f"{dataset_name}.{var_name}"
        crf_ref = self._page_map.get(key)
        if crf_ref is None:
            return

        acrf_cfg = self._get_acrf_config()
        default_leaf_id = self._acrf_leaf_id()

        if isinstance(crf_ref, str):
            # Layer 1: simple page string — "7" or "8 9"
            if not acrf_cfg:
                return  # no aCRF document configured; skip silently
            doc_ref = ET.SubElement(origin_elem, "def:DocumentRef", {"leafID": default_leaf_id})
            ET.SubElement(
                doc_ref,
                "def:PDFPageRef",
                {"PageRefs": crf_ref, "Type": "PhysicalRef"},
            )
        elif isinstance(crf_ref, dict):
            # Layer 2: rich reference with optional doc, type, ranges
            doc_href = crf_ref.get("doc")
            if doc_href and acrf_cfg and doc_href != acrf_cfg.get("href"):
                # Reference to a non-default document — resolve leaf ID
                leaf_id = f"LF.{Path(doc_href).stem}"
            else:
                leaf_id = default_leaf_id

            if not acrf_cfg and leaf_id == default_leaf_id:
                return

            doc_ref = ET.SubElement(origin_elem, "def:DocumentRef", {"leafID": leaf_id})
            pages = crf_ref.get("pages")
            ref_type = crf_ref.get("type", "PhysicalRef")
            first_page = crf_ref.get("first_page")
            last_page = crf_ref.get("last_page")

            if pages or first_page:
                pr_attrs: dict[str, str] = {"Type": ref_type}
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
        """Build a stable ItemDef OID.

        Common variables (STUDYID, USUBJID, ...) that appear in multiple datasets
        are given a shared OID *without* the dataset prefix so they share a single
        ItemDef element in the XML — matching CDISC best practice.
        """
        _SHARED = {
            "STUDYID",
            "USUBJID",
            "DOMAIN",
            "SUBJID",
            "SITEID",
            "AGE",
            "AGEU",
            "SEX",
            "RACE",
            "ETHNIC",
            "ARMCD",
            "ARM",
            "ACTARMCD",
            "ACTARM",
        }
        if var_name in _SHARED:
            return f"IT.{var_name}"
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
