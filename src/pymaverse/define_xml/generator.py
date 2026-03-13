"""Define-XML 2.1 generator from YAML specifications."""

import xml.dom.minidom
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

# Namespace map for Define-XML 2.1
_NS = {
    "odm": "http://www.cdisc.org/ns/odm/v1.3",
    "xlink": "http://www.w3.org/1999/xlink",
    "def": "http://www.cdisc.org/ns/def/v2.1",
}

for _prefix, _uri in _NS.items():
    if _prefix != "odm":
        ET.register_namespace(_prefix, _uri)


class DefineXMLGenerator:
    """Generate CDISC Define-XML 2.1 from a YAML specification file."""

    def __init__(self, define_yaml_path: Path) -> None:
        self.define_data = yaml.safe_load(Path(define_yaml_path).read_text())

    def generate(self, output_path: Path) -> None:
        """Write a Define-XML 2.1 ODM XML file to *output_path*."""
        root = self._build_odm()
        xml_string = self._to_xml_string(root)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(xml_string, encoding="utf-8")
        print(f"Define-XML generated: {output_path}")

    # ------------------------------------------------------------------ #
    # ODM / Study / MetaDataVersion                                       #
    # ------------------------------------------------------------------ #

    def _build_odm(self) -> ET.Element:
        hdr = self.define_data["odm_header"]
        attribs: dict[str, str] = {
            "xmlns": _NS["odm"],
            "xmlns:xlink": _NS["xlink"],
            "xmlns:def": _NS["def"],
            "ODMVersion": hdr["odm_version"],
            "FileOID": hdr["file_oid"],
            "FileType": hdr["file_type"],
            "CreationDateTime": hdr["creation_date_time"],
            "Originator": hdr["originator"],
            "def:Context": hdr["def_context"],
        }
        if hdr.get("source_system"):
            attribs["SourceSystem"] = hdr["source_system"]
        if hdr.get("source_system_version"):
            attribs["SourceSystemVersion"] = hdr["source_system_version"]

        odm = ET.Element("ODM", attrib=attribs)
        odm.append(self._build_study(self.define_data["study"], self.define_data["metadata_version"]))
        return odm

    def _build_study(self, study_data: dict[str, Any], metadata: dict[str, Any]) -> ET.Element:
        study = ET.Element("Study", {"OID": study_data["oid"]})
        gv_data = study_data["global_variables"]
        gv = ET.SubElement(study, "GlobalVariables")
        ET.SubElement(gv, "StudyName").text = gv_data["study_name"]
        ET.SubElement(gv, "StudyDescription").text = gv_data["study_description"]
        ET.SubElement(gv, "ProtocolName").text = gv_data["protocol_name"]
        study.append(self._build_metadata_version(metadata))
        return study

    def _build_metadata_version(self, metadata: dict[str, Any]) -> ET.Element:
        attribs = {
            "OID": metadata["oid"],
            "Name": metadata["name"],
            "Description": metadata["description"],
            "def:DefineVersion": metadata["define_version"],
        }
        mdv = ET.Element("MetaDataVersion", attrib=attribs)

        standards = metadata.get("standards", [])
        if standards:
            stds_container = ET.SubElement(mdv, "def:Standards")
            for std in standards:
                stds_container.append(self._build_standard(std))

        if metadata.get("supporting_documents"):
            acrf = ET.SubElement(mdv, "def:AnnotatedCRF")
            for doc_ref in metadata["supporting_documents"]:
                ET.SubElement(acrf, "def:DocumentRef", {"leafID": doc_ref["leaf_id"]})

        for ig in metadata.get("item_group_defs", []):
            mdv.append(self._build_item_group_def(ig))
        for item in metadata.get("item_defs", []):
            mdv.append(self._build_item_def(item))
        for cl in metadata.get("code_lists", []):
            mdv.append(self._build_codelist(cl))
        for method in metadata.get("method_defs", []):
            mdv.append(self._build_method_def(method))
        for comment in metadata.get("comment_defs", []):
            mdv.append(self._build_comment_def(comment))
        for leaf in metadata.get("leaf_defs", []):
            mdv.append(self._build_leaf(leaf))

        return mdv

    # ------------------------------------------------------------------ #
    # Element builders                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_standard(std: dict[str, Any]) -> ET.Element:
        attribs = {
            "OID": std["oid"],
            "Name": std["name"],
            "Type": std["type"],
            "Version": std["version"],
        }
        if std.get("status"):
            attribs["Status"] = std["status"]
        if std.get("publishing_set"):
            attribs["PublishingSet"] = std["publishing_set"]
        if std.get("comment_oid"):
            attribs["def:CommentOID"] = std["comment_oid"]
        return ET.Element("def:Standard", attrib=attribs)

    def _build_item_group_def(self, ig: dict[str, Any]) -> ET.Element:
        attribs = {
            "OID": ig["oid"],
            "Name": ig["name"],
            "Repeating": ig["repeating"],
            "IsReferenceData": ig["is_reference_data"],
            "SASDatasetName": ig["sas_dataset_name"],
            "Domain": ig.get("domain", ig["name"]),
            "def:Structure": ig["structure"],
        }
        for k, a in [("purpose", "Purpose"), ("standard_oid", "def:StandardOID"),
                     ("archive_location_id", "def:ArchiveLocationID"), ("comment_oid", "def:CommentOID")]:
            if ig.get(k):
                attribs[a] = ig[k]

        elem = ET.Element("ItemGroupDef", attrib=attribs)
        self._append_description(elem, ig.get("description", {}))

        if ig.get("class"):
            cls_elem = ET.SubElement(elem, "def:Class", {"Name": ig["class"]["name"]})
            if ig["class"].get("subclass"):
                ET.SubElement(cls_elem, "def:SubClass").text = ig["class"]["subclass"]

        for ref in ig.get("item_refs", []):
            ref_attribs = {
                "ItemOID": ref["item_oid"],
                "OrderNumber": str(ref["order_number"]),
                "Mandatory": ref.get("mandatory", "No"),
            }
            if ref.get("key_sequence") is not None:
                ref_attribs["KeySequence"] = str(ref["key_sequence"])
            if ref.get("method_oid"):
                ref_attribs["MethodOID"] = ref["method_oid"]
            if ref.get("role"):
                ref_attribs["Role"] = ref["role"]
            ET.SubElement(elem, "ItemRef", attrib=ref_attribs)

        if ig.get("leaf"):
            leaf_d = ig["leaf"]
            leaf_attrs = {"ID": leaf_d["id"], "xlink:href": leaf_d["href"]}
            if leaf_d.get("title"):
                leaf_attrs["xlink:title"] = leaf_d["title"]
            ET.SubElement(elem, "def:leaf", attrib=leaf_attrs)

        return elem

    def _build_item_def(self, item: dict[str, Any]) -> ET.Element:
        attribs = {"OID": item["oid"], "Name": item["name"], "DataType": item["data_type"]}
        for k, a in [("length", "Length"), ("sas_field_name", "SASFieldName"),
                     ("significant_digits", "SignificantDigits"), ("display_format", "def:DisplayFormat"),
                     ("comment_oid", "def:CommentOID")]:
            if item.get(k) is not None:
                attribs[a] = str(item[k])

        elem = ET.Element("ItemDef", attrib=attribs)
        self._append_description(elem, item.get("description", {}))

        cl_ref = item.get("codelist_ref", {})
        if isinstance(cl_ref, dict) and cl_ref.get("codelist_oid"):
            ET.SubElement(elem, "CodeListRef", {"CodeListOID": cl_ref["codelist_oid"]})

        origin = item.get("origin", {})
        if origin and origin.get("type"):
            orig_attrs = {"Type": origin["type"]}
            if origin.get("source"):
                orig_attrs["Source"] = origin["source"]
            orig_elem = ET.SubElement(elem, "def:Origin", attrib=orig_attrs)
            if origin.get("description"):
                d = ET.SubElement(orig_elem, "Description")
                tt = ET.SubElement(d, "TranslatedText", {"xml:lang": origin.get("lang", "en")})
                tt.text = origin["description"]
            for doc_ref in origin.get("document_refs", []):
                self._append_doc_ref(orig_elem, doc_ref)

        if item.get("value_list_ref"):
            ET.SubElement(elem, "def:ValueListRef", {"ValueListOID": item["value_list_ref"]})

        # pymaverse_algorithm is intentionally not emitted in the XML output
        return elem

    def _build_codelist(self, cl: dict[str, Any]) -> ET.Element:
        attribs = {"OID": cl["oid"], "Name": cl["name"], "DataType": cl["data_type"]}
        if cl.get("standard_oid"):
            attribs["def:StandardOID"] = cl["standard_oid"]
        if cl.get("comment_oid"):
            attribs["def:CommentOID"] = cl["comment_oid"]

        elem = ET.Element("CodeList", attrib=attribs)

        for item in cl.get("code_list_items", []):
            ia = {"CodedValue": item["coded_value"]}
            for k, a in [("rank", "Rank"), ("order_number", "OrderNumber")]:
                if item.get(k) is not None:
                    ia[a] = str(item[k])
            if item.get("extended_value"):
                ia["def:ExtendedValue"] = item["extended_value"]
            item_elem = ET.SubElement(elem, "CodeListItem", attrib=ia)
            decode = item.get("decode", {})
            if decode and decode.get("text"):
                d = ET.SubElement(item_elem, "Decode")
                tt = ET.SubElement(d, "TranslatedText", {"xml:lang": decode.get("lang", "en")})
                tt.text = decode["text"]
            alias = item.get("alias", {})
            if alias and alias.get("name"):
                alias_attrs = {"Name": alias["name"]}
                if alias.get("context"):
                    alias_attrs["Context"] = alias["context"]
                ET.SubElement(item_elem, "Alias", attrib=alias_attrs)

        for enum in cl.get("enumerated_items", []):
            ea = {"CodedValue": enum["coded_value"]}
            for k, a in [("rank", "Rank"), ("order_number", "OrderNumber")]:
                if enum.get(k) is not None:
                    ea[a] = str(enum[k])
            enum_elem = ET.SubElement(elem, "EnumeratedItem", attrib=ea)
            if enum.get("alias"):
                alias_attrs = {"Name": enum["alias"]["name"]}
                if enum["alias"].get("context"):
                    alias_attrs["Context"] = enum["alias"]["context"]
                ET.SubElement(enum_elem, "Alias", attrib=alias_attrs)

        return elem

    def _build_method_def(self, method: dict[str, Any]) -> ET.Element:
        attribs = {"OID": method["oid"], "Name": method["name"], "Type": method["type"]}
        if method.get("comment_oid"):
            attribs["def:CommentOID"] = method["comment_oid"]
        elem = ET.Element("MethodDef", attrib=attribs)
        self._append_description(elem, method.get("description", {}))
        for expr in method.get("formal_expressions", []):
            expr_elem = ET.SubElement(elem, "FormalExpression", {"Context": expr["context"]})
            expr_elem.text = expr["expression"]
        for doc_ref in method.get("document_refs", []):
            self._append_doc_ref(elem, doc_ref)
        return elem

    def _build_comment_def(self, comment: dict[str, Any]) -> ET.Element:
        elem = ET.Element("def:CommentDef", {"OID": comment["oid"]})
        self._append_description(elem, comment.get("description", {}))
        for doc_ref in comment.get("document_refs", []):
            self._append_doc_ref(elem, doc_ref)
        return elem

    def _build_leaf(self, leaf: dict[str, Any]) -> ET.Element:
        attribs = {"ID": leaf["id"], "xlink:href": leaf["href"]}
        elem = ET.Element("def:leaf", attrib=attribs)
        if leaf.get("title"):
            if leaf["href"].lower().endswith(".xpt"):
                attribs["xlink:title"] = leaf["title"]
            else:
                ET.SubElement(elem, "def:title").text = leaf["title"]
        return elem

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _append_description(parent: ET.Element, desc: dict[str, Any]) -> None:
        if desc and desc.get("text"):
            d = ET.SubElement(parent, "Description")
            tt = ET.SubElement(d, "TranslatedText", {"xml:lang": desc.get("lang", "en")})
            tt.text = desc["text"]

    @staticmethod
    def _append_doc_ref(parent: ET.Element, doc_ref: dict[str, Any]) -> ET.Element:
        dr = ET.SubElement(parent, "def:DocumentRef", {"leafID": doc_ref["leaf_id"]})
        for pr in doc_ref.get("pdf_page_refs", []):
            pr_attrs = {"PageRefs": pr["page_ref"], "Type": pr["type"]}
            if pr.get("first_page"):
                pr_attrs["FirstPage"] = pr["first_page"]
            if pr.get("last_page"):
                pr_attrs["LastPage"] = pr["last_page"]
            ET.SubElement(dr, "def:PDFPageRef", attrib=pr_attrs)
        return dr

    @staticmethod
    def _to_xml_string(root: ET.Element) -> str:
        xml_str = ET.tostring(root, encoding="unicode", method="xml")
        dom = xml.dom.minidom.parseString(xml_str)
        pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        lines = [line for line in pretty.split("\n") if line.strip()]
        if lines and lines[0].startswith("<?xml"):
            lines.insert(1, '<?xml-stylesheet type="text/xsl" href="define2-1.xsl"?>')
        return "\n".join(lines)
