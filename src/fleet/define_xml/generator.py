"""Define-XML 2.1 generator from YAML specifications.

Uses *lxml* for namespace-aware XML construction and native pretty-printing,
replacing the previous stdlib approach that relied on ``xml.dom.minidom`` for
formatting.
"""

from pathlib import Path
from typing import Any

from lxml import etree

from fleet.core.define_spec import load_spec_yaml

# Namespace URIs for Define-XML 2.1
_ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
_DEF_NS = "http://www.cdisc.org/ns/def/v2.1"
_XLINK_NS = "http://www.w3.org/1999/xlink"

_NSMAP = {None: _ODM_NS, "def": _DEF_NS, "xlink": _XLINK_NS}


# Clark-notation helpers — turn namespace prefix usage into proper
# ``{uri}local`` strings so lxml renders prefixes automatically.
def _odm(tag: str) -> str:
    return f"{{{_ODM_NS}}}{tag}"


def _def(tag: str) -> str:
    return f"{{{_DEF_NS}}}{tag}"


def _xl(attr: str) -> str:
    return f"{{{_XLINK_NS}}}{attr}"


class DefineXMLGenerator:
    """Generate CDISC Define-XML 2.1 from a YAML specification file."""

    def __init__(self, define_yaml_path: Path) -> None:
        self.define_data = load_spec_yaml(Path(define_yaml_path).read_text())

    def generate(self, output_path: Path) -> None:
        """Write a Define-XML 2.1 ODM XML file to *output_path*."""
        root = self._build_odm()
        xml_bytes = self._serialize(root)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(xml_bytes)
        print(f"Define-XML generated: {output_path}")

    # ------------------------------------------------------------------ #
    # ODM / Study / MetaDataVersion                                       #
    # ------------------------------------------------------------------ #

    def _build_odm(self) -> etree._Element:
        hdr = self.define_data["odm_header"]
        attribs: dict[str, str] = {
            "ODMVersion": hdr["odm_version"],
            "FileOID": hdr["file_oid"],
            "FileType": hdr["file_type"],
            "CreationDateTime": hdr["creation_date_time"],
            "Originator": hdr["originator"],
            _def("Context"): hdr["def_context"],
        }
        if hdr.get("source_system"):
            attribs["SourceSystem"] = hdr["source_system"]
        if hdr.get("source_system_version"):
            attribs["SourceSystemVersion"] = hdr["source_system_version"]

        odm = etree.Element(_odm("ODM"), attrib=attribs, nsmap=_NSMAP)
        odm.append(
            self._build_study(self.define_data["study"], self.define_data["metadata_version"])
        )
        return odm

    def _build_study(self, study_data: dict[str, Any], metadata: dict[str, Any]) -> etree._Element:
        study = etree.Element(_odm("Study"), {"OID": study_data["oid"]})
        gv_data = study_data["global_variables"]
        gv = etree.SubElement(study, _odm("GlobalVariables"))
        etree.SubElement(gv, _odm("StudyName")).text = gv_data["study_name"]
        etree.SubElement(gv, _odm("StudyDescription")).text = gv_data["study_description"]
        etree.SubElement(gv, _odm("ProtocolName")).text = gv_data["protocol_name"]
        study.append(self._build_metadata_version(metadata))
        return study

    def _build_metadata_version(self, metadata: dict[str, Any]) -> etree._Element:
        attribs = {
            "OID": metadata["oid"],
            "Name": metadata["name"],
            "Description": metadata["description"],
            _def("DefineVersion"): metadata["define_version"],
        }
        mdv = etree.Element(_odm("MetaDataVersion"), attrib=attribs)

        standards = metadata.get("standards", [])
        if standards:
            stds_container = etree.SubElement(mdv, _def("Standards"))
            for std in standards:
                stds_container.append(self._build_standard(std))

        if metadata.get("supporting_documents"):
            acrf = etree.SubElement(mdv, _def("AnnotatedCRF"))
            for doc_ref in metadata["supporting_documents"]:
                etree.SubElement(acrf, _def("DocumentRef"), {"leafID": doc_ref["leaf_id"]})

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
    def _build_standard(std: dict[str, Any]) -> etree._Element:
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
            attribs[_def("CommentOID")] = std["comment_oid"]
        return etree.Element(_def("Standard"), attrib=attribs)

    def _build_item_group_def(self, ig: dict[str, Any]) -> etree._Element:
        attribs = {
            "OID": ig["oid"],
            "Name": ig["name"],
            "Repeating": ig["repeating"],
            "IsReferenceData": ig["is_reference_data"],
            "SASDatasetName": ig["sas_dataset_name"],
            "Domain": ig.get("domain", ig["name"]),
            _def("Structure"): ig["structure"],
        }
        for k, a in [
            ("purpose", "Purpose"),
            ("standard_oid", _def("StandardOID")),
            ("archive_location_id", _def("ArchiveLocationID")),
            ("comment_oid", _def("CommentOID")),
        ]:
            if ig.get(k):
                attribs[a] = ig[k]

        elem = etree.Element(_odm("ItemGroupDef"), attrib=attribs)
        self._append_description(elem, ig.get("description", {}))

        if ig.get("class"):
            cls_elem = etree.SubElement(elem, _def("Class"), {"Name": ig["class"]["name"]})
            if ig["class"].get("subclass"):
                etree.SubElement(cls_elem, _def("SubClass")).text = ig["class"]["subclass"]

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
            etree.SubElement(elem, _odm("ItemRef"), attrib=ref_attribs)

        if ig.get("leaf"):
            leaf_d = ig["leaf"]
            leaf_attrs: dict[str, str] = {"ID": leaf_d["id"], _xl("href"): leaf_d["href"]}
            if leaf_d.get("title"):
                leaf_attrs[_xl("title")] = leaf_d["title"]
            etree.SubElement(elem, _def("leaf"), attrib=leaf_attrs)

        return elem

    def _build_item_def(self, item: dict[str, Any]) -> etree._Element:
        attribs: dict[str, str] = {
            "OID": item["oid"],
            "Name": item["name"],
            "DataType": item["data_type"],
        }
        for k, a in [
            ("length", "Length"),
            ("sas_field_name", "SASFieldName"),
            ("significant_digits", "SignificantDigits"),
            ("display_format", _def("DisplayFormat")),
            ("comment_oid", _def("CommentOID")),
        ]:
            if item.get(k) is not None:
                attribs[a] = str(item[k])

        elem = etree.Element(_odm("ItemDef"), attrib=attribs)
        self._append_description(elem, item.get("description", {}))

        cl_ref = item.get("codelist_ref", {})
        if isinstance(cl_ref, dict) and cl_ref.get("codelist_oid"):
            etree.SubElement(elem, _odm("CodeListRef"), {"CodeListOID": cl_ref["codelist_oid"]})

        origin = item.get("origin", {})
        if origin and origin.get("type"):
            orig_attrs: dict[str, str] = {"Type": origin["type"]}
            if origin.get("source"):
                orig_attrs["Source"] = origin["source"]
            orig_elem = etree.SubElement(elem, _def("Origin"), attrib=orig_attrs)
            if origin.get("description"):
                d = etree.SubElement(orig_elem, _odm("Description"))
                tt = etree.SubElement(
                    d,
                    _odm("TranslatedText"),
                    {"{http://www.w3.org/XML/1998/namespace}lang": origin.get("lang", "en")},
                )
                tt.text = origin["description"]
            for doc_ref in origin.get("document_refs", []):
                self._append_doc_ref(orig_elem, doc_ref)

        if item.get("value_list_ref"):
            etree.SubElement(elem, _def("ValueListRef"), {"ValueListOID": item["value_list_ref"]})

        # fleet_algorithm is intentionally not emitted in the XML output
        return elem

    def _build_codelist(self, cl: dict[str, Any]) -> etree._Element:
        attribs: dict[str, str] = {
            "OID": cl["oid"],
            "Name": cl["name"],
            "DataType": cl["data_type"],
        }
        if cl.get("standard_oid"):
            attribs[_def("StandardOID")] = cl["standard_oid"]
        if cl.get("comment_oid"):
            attribs[_def("CommentOID")] = cl["comment_oid"]

        elem = etree.Element(_odm("CodeList"), attrib=attribs)

        for item in cl.get("code_list_items", []):
            ia: dict[str, str] = {"CodedValue": item["coded_value"]}
            for k, a in [("rank", "Rank"), ("order_number", "OrderNumber")]:
                if item.get(k) is not None:
                    ia[a] = str(item[k])
            if item.get("extended_value"):
                ia[_def("ExtendedValue")] = item["extended_value"]
            item_elem = etree.SubElement(elem, _odm("CodeListItem"), attrib=ia)
            decode = item.get("decode", {})
            if decode and decode.get("text"):
                d = etree.SubElement(item_elem, _odm("Decode"))
                tt = etree.SubElement(
                    d,
                    _odm("TranslatedText"),
                    {"{http://www.w3.org/XML/1998/namespace}lang": decode.get("lang", "en")},
                )
                tt.text = decode["text"]
            alias = item.get("alias", {})
            if alias and alias.get("name"):
                alias_attrs: dict[str, str] = {"Name": alias["name"]}
                if alias.get("context"):
                    alias_attrs["Context"] = alias["context"]
                etree.SubElement(item_elem, _odm("Alias"), attrib=alias_attrs)

        for enum in cl.get("enumerated_items", []):
            ea: dict[str, str] = {"CodedValue": enum["coded_value"]}
            for k, a in [("rank", "Rank"), ("order_number", "OrderNumber")]:
                if enum.get(k) is not None:
                    ea[a] = str(enum[k])
            enum_elem = etree.SubElement(elem, _odm("EnumeratedItem"), attrib=ea)
            if enum.get("alias"):
                alias_attrs = {"Name": enum["alias"]["name"]}
                if enum["alias"].get("context"):
                    alias_attrs["Context"] = enum["alias"]["context"]
                etree.SubElement(enum_elem, _odm("Alias"), attrib=alias_attrs)

        return elem

    def _build_method_def(self, method: dict[str, Any]) -> etree._Element:
        attribs: dict[str, str] = {
            "OID": method["oid"],
            "Name": method["name"],
            "Type": method["type"],
        }
        if method.get("comment_oid"):
            attribs[_def("CommentOID")] = method["comment_oid"]
        elem = etree.Element(_odm("MethodDef"), attrib=attribs)
        self._append_description(elem, method.get("description", {}))
        for expr in method.get("formal_expressions", []):
            expr_elem = etree.SubElement(
                elem, _odm("FormalExpression"), {"Context": expr["context"]}
            )
            expr_elem.text = expr["expression"]
        for doc_ref in method.get("document_refs", []):
            self._append_doc_ref(elem, doc_ref)
        return elem

    def _build_comment_def(self, comment: dict[str, Any]) -> etree._Element:
        elem = etree.Element(_def("CommentDef"), {"OID": comment["oid"]})
        self._append_description(elem, comment.get("description", {}))
        for doc_ref in comment.get("document_refs", []):
            self._append_doc_ref(elem, doc_ref)
        return elem

    def _build_leaf(self, leaf: dict[str, Any]) -> etree._Element:
        attribs: dict[str, str] = {"ID": leaf["id"], _xl("href"): leaf["href"]}
        elem = etree.Element(_def("leaf"), attrib=attribs)
        if leaf.get("title"):
            if leaf["href"].lower().endswith(".xpt"):
                elem.set(_xl("title"), leaf["title"])
            else:
                etree.SubElement(elem, _def("title")).text = leaf["title"]
        return elem

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _append_description(parent: etree._Element, desc: dict[str, Any]) -> None:
        if desc and desc.get("text"):
            d = etree.SubElement(parent, _odm("Description"))
            tt = etree.SubElement(
                d,
                _odm("TranslatedText"),
                {"{http://www.w3.org/XML/1998/namespace}lang": desc.get("lang", "en")},
            )
            tt.text = desc["text"]

    @staticmethod
    def _append_doc_ref(parent: etree._Element, doc_ref: dict[str, Any]) -> etree._Element:
        dr = etree.SubElement(parent, _def("DocumentRef"), {"leafID": doc_ref["leaf_id"]})
        for pr in doc_ref.get("pdf_page_refs", []):
            pr_attrs: dict[str, str] = {"PageRefs": pr["page_ref"], "Type": pr["type"]}
            if pr.get("first_page"):
                pr_attrs["FirstPage"] = pr["first_page"]
            if pr.get("last_page"):
                pr_attrs["LastPage"] = pr["last_page"]
            etree.SubElement(dr, _def("PDFPageRef"), attrib=pr_attrs)
        return dr

    @staticmethod
    def _serialize(root: etree._Element) -> bytes:
        """Serialize the element tree to pretty-printed UTF-8 XML bytes."""
        xml_bytes = etree.tostring(
            root,
            pretty_print=True,
            xml_declaration=True,
            encoding="utf-8",
        )
        # Insert XSL processing instruction after the XML declaration
        decl_end = xml_bytes.index(b"?>") + 2
        pi = b'\n<?xml-stylesheet type="text/xsl" href="define2-1.xsl"?>'
        return xml_bytes[:decl_end] + pi + xml_bytes[decl_end:]
