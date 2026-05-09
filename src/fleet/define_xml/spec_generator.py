"""Generate Define-XML 2.1 from a simplified Fleet define YAML spec.

Converts the compact ``specs/<study>/<sdtm|adam>/define.yaml`` format into a
fully-compliant CDISC Define-XML 2.1 ODM document.

Simplified YAML format is enforced by:
    ``src/fleet/define_xml/schemas/define_spec_schema.json``

Usage::

    from fleet import DefineSpecGenerator
    from pathlib import Path

    gen = DefineSpecGenerator("specs/cdiscpilot01/sdtm/define.yaml")
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
    """

    def __init__(
        self,
        define_yaml_path: str | Path,
        *,
        validate_schema: bool = True,
        enrich_methods: bool = False,
    ) -> None:
        self._path = Path(define_yaml_path)
        self._data: dict[str, Any] = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        self._enrich_methods = enrich_methods
        # Populated by _build_item_def via _register_method when
        # enrich_methods is True; rendered into MethodDef elements at the
        # end of MetaDataVersion.
        self._method_defs: dict[str, dict[str, str]] = {}
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
        xml_str = self._to_pretty_xml(root)
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
        return self._to_pretty_xml(self._build_odm())

    # ------------------------------------------------------------------ #
    # Schema validation                                                    #
    # ------------------------------------------------------------------ #

    def _validate(self) -> None:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(self._data))
        if errors:
            msgs = "\n".join(f"  - {e.json_path}: {e.message}" for e in errors[:5])
            raise ValueError(f"define YAML failed schema validation:\n{msgs}")

    # ------------------------------------------------------------------ #
    # ODM root                                                             #
    # ------------------------------------------------------------------ #

    def _build_odm(self) -> ET.Element:
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
            self._build_standard(std_oid, study["standard"], "IG", study["standard_version"])
        )
        if study.get("ct_version"):
            stds_container.append(
                self._build_standard(
                    _CT_OID,
                    "CDISC/NCI",
                    "CT",
                    study["ct_version"],
                    publishing_set=study["standard"],
                )
            )

        # ItemGroupDefs (one per dataset)
        datasets: list[dict[str, Any]] = self._data.get("datasets", [])
        for ds in datasets:
            mdv.append(self._build_item_group_def(ds, study["id"]))

        # ItemDefs (collect all unique variables across datasets)
        mdv.extend(self._build_all_item_defs(datasets))

        # CodeLists
        for cl in self._data.get("codelists", []):
            mdv.append(self._build_codelist(cl))

        # MethodDefs (only populated when enrich_methods=True; lazily
        # registered by _build_item_def via _register_method).
        for method_oid in sorted(self._method_defs):
            mdv.append(self._build_method_def(method_oid, self._method_defs[method_oid]))

        # LeafDefs (one per dataset)
        for ds in datasets:
            mdv.append(self._build_leaf(ds))

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

        if ds.get("class"):
            ET.SubElement(elem, "def:Class", {"Name": ds["class"]})

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
            ET.SubElement(elem, "ItemRef", attrib=ref_attrs)

        # Leaf reference
        ET.SubElement(
            elem,
            "def:leaf",
            {
                "ID": leaf_id,
                "xlink:href": f"{name.lower()}.xpt",
                "xlink:title": f"{name.lower()}.xpt",
            },
        )

        return elem

    def _build_all_item_defs(self, datasets: list[dict[str, Any]]) -> list[ET.Element]:
        """Build ItemDef elements; shared variables (same name & type) share an OID."""
        seen: dict[str, ET.Element] = {}  # item_oid → element
        result: list[ET.Element] = []
        for ds in datasets:
            for var in ds["variables"]:
                item_oid = self._item_oid(ds["name"], var["name"])
                if item_oid not in seen:
                    elem = self._build_item_def(item_oid, var)
                    seen[item_oid] = elem
                    result.append(elem)
        return result

    def _build_item_def(self, item_oid: str, var: dict[str, Any]) -> ET.Element:
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
        orig_elem = ET.SubElement(elem, "def:Origin", {"Type": origin_type})

        # Build the human-readable origin description.  When
        # enrich_methods is on we resolve the verb (or callable) docstring
        # so reviewers see the exact computational method without leaving
        # the Define-XML.
        comment = var.get("comment") or ""
        derivation = var.get("derivation") or {}
        method_oid: str | None = None
        if self._enrich_methods and derivation:
            method_oid, summary = self._register_method(derivation)
            if summary:
                comment = f"{comment} {summary}".strip() if comment else summary
        if comment:
            orig_desc = ET.SubElement(orig_elem, "Description")
            ET.SubElement(orig_desc, "TranslatedText", {"xml:lang": "en"}).text = comment

        # MethodOID is an ItemDef attribute per Define-XML 2.1; emit only
        # when enrichment produced one.
        if method_oid:
            elem.set("MethodOID", method_oid)

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
        method_oid = f"MT.{algorithm}"
        self._method_defs.setdefault(
            method_oid,
            {
                "name": algorithm,
                "description": summary or f"Fleet verb: {algorithm}",
                "expression": expression or f".{algorithm}(...)",
                "context": "Python/Fleet",
            },
        )
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

    @staticmethod
    def _build_leaf(ds: dict[str, Any]) -> ET.Element:
        name = ds["name"]
        leaf_id = f"LF.{name}"
        href = f"{name.lower()}.xpt"
        return ET.Element("def:leaf", {"ID": leaf_id, "xlink:href": href, "xlink:title": href})

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
