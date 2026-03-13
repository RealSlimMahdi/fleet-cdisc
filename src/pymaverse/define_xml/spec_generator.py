"""Generate Define-XML 2.1 from a simplified Pymaverse define YAML spec.

Converts the compact ``specs/<study>/<sdtm|adam>/define.yaml`` format into a
fully-compliant CDISC Define-XML 2.1 ODM document.

Simplified YAML format is enforced by:
    ``src/pymaverse/define_xml/schemas/define_spec_schema.json``

Usage::

    from pymaverse import DefineSpecGenerator
    from pathlib import Path

    gen = DefineSpecGenerator("specs/cdiscpilot01/sdtm/define.yaml")
    gen.generate("outputs/define_sdtm.xml")
"""

from __future__ import annotations

import json
import xml.dom.minidom
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import yaml

_SCHEMA_PATH = Path(__file__).parent / "schemas" / "define_spec_schema.json"

# ODM/Define-XML 2.1 namespaces
_NS_ODM = "http://www.cdisc.org/ns/odm/v1.3"
_NS_DEF = "http://www.cdisc.org/ns/def/v2.1"
_NS_XLINK = "http://www.w3.org/1999/xlink"

ET.register_namespace("def", _NS_DEF)
ET.register_namespace("xlink", _NS_XLINK)

# Map simplified type → ODM DataType attribute
_TYPE_TO_ODM: dict[str, str] = {
    "text":     "text",
    "integer":  "integer",
    "float":    "float",
    "date":     "date",
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
    """Generate Define-XML 2.1 from a simplified Pymaverse define YAML spec.

    Parameters
    ----------
    define_yaml_path:
        Path to a simplified define YAML file that conforms to
        ``define_spec_schema.json``.
    validate_schema:
        When *True* (default), validates the YAML against the JSON schema
        before generating and raises ``ValueError`` on schema violations.
    """

    def __init__(self, define_yaml_path: str | Path, *, validate_schema: bool = True) -> None:
        self._path = Path(define_yaml_path)
        self._data: dict[str, Any] = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        if validate_schema:
            self._validate()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def generate(self, output_path: str | Path) -> None:
        """Write a Define-XML 2.1 document to *output_path*."""
        root = self._build_odm()
        xml_str = self._to_pretty_xml(root)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(xml_str, encoding="utf-8")
        print(f"Define-XML generated: {out}")

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
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        file_oid = (
            f"CDISC.{study['id']}.1.Define-XML_2.1.0"
        )
        attribs: dict[str, str] = {
            "xmlns":              _NS_ODM,
            "xmlns:xlink":        _NS_XLINK,
            "xmlns:def":          _NS_DEF,
            "ODMVersion":         "1.3.2",
            "FileOID":            file_oid,
            "FileType":           "Snapshot",
            "CreationDateTime":   ts,
            "Originator":         study["originator"],
            "SourceSystem":       study.get("source_system", "Pymaverse"),
            "SourceSystemVersion": study.get("source_system_version", "0.1.0"),
            "def:Context":        "Submission",
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
            "OID":                mdv_oid,
            "Name":               f"{study['id']} {ig} Data Definitions",
            "Description":        f"Dataset metadata for {study['id']} {ig} datasets",
            "def:DefineVersion":  "2.1.0",
        }
        mdv = ET.Element("MetaDataVersion", attrib=attribs)

        # Standards list — must be wrapped in def:Standards per Define-XML 2.1 spec
        stds_container = ET.SubElement(mdv, "def:Standards")
        stds_container.append(self._build_standard(std_oid, study["standard"], "IG", study["standard_version"]))
        if study.get("ct_version"):
            stds_container.append(self._build_standard(_CT_OID, "CDISC/NCI", "CT", study["ct_version"],
                                                       publishing_set=study["standard"]))

        # ItemGroupDefs (one per dataset)
        datasets: list[dict[str, Any]] = self._data.get("datasets", [])
        for ds in datasets:
            mdv.append(self._build_item_group_def(ds, study["id"]))

        # ItemDefs (collect all unique variables across datasets)
        mdv.extend(self._build_all_item_defs(datasets))

        # CodeLists
        for cl in self._data.get("codelists", []):
            mdv.append(self._build_codelist(cl))

        # LeafDefs (one per dataset)
        for ds in datasets:
            mdv.append(self._build_leaf(ds))

        return mdv

    # ------------------------------------------------------------------ #
    # Element builders                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_standard(oid: str, name: str, kind: str, version: str,
                        publishing_set: str | None = None) -> ET.Element:
        attribs: dict[str, str] = {
            "OID": oid, "Name": name, "Type": kind, "Version": version, "Status": "Final",
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
            "OID":                  ig_oid,
            "Name":                 name,
            "Repeating":            repeating,
            "IsReferenceData":      "No",
            "SASDatasetName":       name,
            "Domain":               name,
            "def:Structure":        ds["structure"],
            "Purpose":              "Tabulation" if self._data["study"]["standard"] == "SDTMIG" else "Analysis",
            "def:StandardOID":      std_oid,
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
                "ItemOID":    item_oid,
                "OrderNumber": str(order),
                "Mandatory":  "Yes" if var.get("mandatory") else "No",
            }
            if var_name in key_vars:
                ref_attrs["KeySequence"] = str(key_order[var_name])
            ET.SubElement(elem, "ItemRef", attrib=ref_attrs)

        # Leaf reference
        ET.SubElement(elem, "def:leaf", {
            "ID": leaf_id,
            "xlink:href": f"{name.lower()}.xpt",
            "xlink:title": f"{name.lower()}.xpt",
        })

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
            "OID":          item_oid,
            "Name":         var["name"],
            "DataType":     _TYPE_TO_ODM[var["type"]],
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
        if var.get("comment"):
            orig_desc = ET.SubElement(orig_elem, "Description")
            ET.SubElement(orig_desc, "TranslatedText", {"xml:lang": "en"}).text = var["comment"]

        return elem

    @staticmethod
    def _build_codelist(cl: dict[str, Any]) -> ET.Element:
        attribs: dict[str, str] = {
            "OID":      cl["oid"],
            "Name":     cl["name"],
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
            "STUDYID", "USUBJID", "DOMAIN", "SUBJID", "SITEID",
            "AGE", "AGEU", "SEX", "RACE", "ETHNIC",
            "ARMCD", "ARM", "ACTARMCD", "ACTARM",
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
