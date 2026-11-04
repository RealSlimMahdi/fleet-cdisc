"""Semantic conformance lint for generated Define-XML documents.

The XSD layer (:mod:`fleet.define_xml.xsd`) catches structural mistakes;
this module catches documents that are schema-valid but *semantically*
wrong in reviewer-facing content — the defects a regulatory reviewer
would flag, not a parser:

* a ``MethodOID`` on a non-Derived variable (a collected column rename
  is not a ``MethodDef Type="Computation"``);
* API markup (reST emphasis, backticks) leaking into ``TranslatedText``;
* a ``MethodDef/@Name`` that is a Fleet-internal algorithm id instead of
  reviewer-facing text;
* a ``Predecessor`` origin whose description is not a
  ``DATASET.VARIABLE`` reference;
* an OID or leaf reference to an element that does not exist, and a
  ``def:ValueListDef`` that no ItemDef uses;
* a value-level ItemDef longer than its parent variable;
* a CodeList whose DataType differs from a variable that uses it.

:class:`~fleet.define_xml.spec_generator.DefineSpecGenerator` runs this
lint automatically alongside XSD validation (``validate_xml=False``
bypasses both), so every generated define is checked — not just Fleet's
own CI examples.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_ODM = "{http://www.cdisc.org/ns/odm/v1.3}"
_DEF = "{http://www.cdisc.org/ns/def/v2.1}"

#: reST emphasis (``*target*``) — a lone asterisk (e.g. multiplication) is fine.
_REST_EMPHASIS = re.compile(r"\*\S[^*]*\*")

#: ``Predecessor`` descriptions must name their source as DATASET.VARIABLE.
_PREDECESSOR_REF = re.compile(r"^[A-Z_][A-Z0-9_]{0,7}\.[A-Z_][A-Z0-9_]{0,7}$")


def _origin_types(root: ET.Element) -> dict[str, str | None]:
    """Map ItemDef OID → its ``def:Origin`` Type (None when absent)."""
    origins: dict[str, str | None] = {}
    for item in root.iter(f"{_ODM}ItemDef"):
        origin = item.find(f"{_DEF}Origin")
        origins[item.get("OID", "")] = origin.get("Type") if origin is not None else None
    return origins


def semantic_errors(xml: str | bytes) -> list[str]:
    """Lint a Define-XML document for reviewer-facing conformance defects.

    Complements :func:`fleet.define_xml.xsd.validate_define_xml` — run
    both before shipping a define.

    Args:
        xml: The Define-XML document as a string or bytes.

    Returns:
        list[str]: Human-readable problems; empty when the document is
        clean.

    Examples:
        Lint a generated define alongside XSD validation::

            from fleet.define_xml import DefineSpecGenerator, semantic_errors

            xml = DefineSpecGenerator("define.yaml", validate_xml=False).to_xml_string()
            assert semantic_errors(xml) == []
    """
    data = xml.encode("utf-8") if isinstance(xml, str) else xml
    root = ET.fromstring(data)
    errors: list[str] = []

    # 1. MethodOID only on Derived-origin variables.
    origins = _origin_types(root)
    for ref in root.iter(f"{_ODM}ItemRef"):
        method_oid = ref.get("MethodOID")
        if not method_oid:
            continue
        origin = origins.get(ref.get("ItemOID", ""))
        if origin != "Derived":
            errors.append(
                f"ItemRef {ref.get('ItemOID')} carries MethodOID {method_oid} but its "
                f"Origin Type is {origin or 'missing'} — only Derived variables have "
                "computational methods"
            )

    # 2. No API markup in any reviewer-facing text.
    for text_elem in root.iter(f"{_ODM}TranslatedText"):
        text = text_elem.text or ""
        if "`" in text or _REST_EMPHASIS.search(text):
            errors.append(f"TranslatedText contains API markup: {text[:80]!r}")

    # 3. MethodDef names are reviewer-facing, not Fleet algorithm ids.  The
    # ids are verb names (ADR-0008), ordinary words such as `map` or `date`,
    # so only a method Fleet produced (its FormalExpression says so) counts.
    from fleet.core.spec_registry import algorithm_names

    algo_ids = set(algorithm_names("sdtm")) | set(algorithm_names("adam"))
    for method in root.iter(f"{_ODM}MethodDef"):
        name = method.get("Name", "")
        contexts = {f.get("Context") for f in method.iter(f"{_ODM}FormalExpression")}
        if name in algo_ids and "Python/Fleet" in contexts:
            errors.append(
                f"MethodDef {method.get('OID')} Name {name!r} is a Fleet-internal "
                "algorithm id, not reviewer-facing text"
            )

    # 4. Predecessor origins name their DATASET.VARIABLE source.
    for item in root.iter(f"{_ODM}ItemDef"):
        origin = item.find(f"{_DEF}Origin")
        if origin is None or origin.get("Type") != "Predecessor":
            continue
        desc = origin.find(f"{_ODM}Description/{_ODM}TranslatedText")
        ref = (desc.text or "").strip() if desc is not None else ""
        if not _PREDECESSOR_REF.match(ref):
            errors.append(
                f"ItemDef {item.get('OID')} has Origin Type='Predecessor' but its "
                f"description {ref!r} is not a DATASET.VARIABLE reference"
            )

    errors += _reference_errors(root)
    errors += _value_level_length_errors(root)
    errors += _codelist_type_errors(root)
    return errors


#: Element tag → its ID attribute, for every element another one points at.
_TARGETS: dict[str, str] = {
    f"{_ODM}ItemDef": "OID",
    f"{_ODM}ItemGroupDef": "OID",
    f"{_ODM}CodeList": "OID",
    f"{_ODM}MethodDef": "OID",
    f"{_DEF}ValueListDef": "OID",
    f"{_DEF}WhereClauseDef": "OID",
    f"{_DEF}CommentDef": "OID",
    f"{_DEF}Standard": "OID",
    f"{_DEF}leaf": "ID",
}

#: (element tag or None for any element, reference attribute) pairs.
_REFERENCES: tuple[tuple[str | None, str], ...] = (
    (f"{_ODM}ItemRef", "ItemOID"),
    (f"{_ODM}ItemRef", "MethodOID"),
    (f"{_ODM}CodeListRef", "CodeListOID"),
    (f"{_DEF}ValueListRef", "ValueListOID"),
    (f"{_DEF}WhereClauseRef", "WhereClauseOID"),
    (f"{_ODM}RangeCheck", f"{_DEF}ItemOID"),
    (f"{_DEF}DocumentRef", "leafID"),
    (None, f"{_DEF}StandardOID"),
    (None, f"{_DEF}CommentOID"),
    (None, f"{_DEF}ArchiveLocationID"),
)


def _reference_errors(root: ET.Element) -> list[str]:
    """Every OID or leaf reference resolves, and every ValueListDef is used."""
    declared = {elem.get(attr) for tag, attr in _TARGETS.items() for elem in root.iter(tag)} - {
        None
    }
    errors: list[str] = []
    for tag, attr in _REFERENCES:
        for elem in root.iter(tag) if tag else root.iter():
            target = elem.get(attr)
            if target is not None and target not in declared:
                name = attr.removeprefix(_DEF).removeprefix(_ODM)
                errors.append(f"{name} {target} refers to an element that does not exist")
    used = {ref.get("ValueListOID") for ref in root.iter(f"{_DEF}ValueListRef")}
    for vl in root.iter(f"{_DEF}ValueListDef"):
        if vl.get("OID") not in used:
            errors.append(f"ValueListDef {vl.get('OID')} is not referenced by any ItemDef")
    return errors


def _value_level_length_errors(root: ET.Element) -> list[str]:
    """A value-level ItemDef is not longer than its parent variable."""
    items = {item.get("OID"): item for item in root.iter(f"{_ODM}ItemDef")}
    errors: list[str] = []
    for parent in items.values():
        ref = parent.find(f"{_DEF}ValueListRef")
        parent_length = parent.get("Length")
        if ref is None or parent_length is None:
            continue
        vl = next(
            (
                v
                for v in root.iter(f"{_DEF}ValueListDef")
                if v.get("OID") == ref.get("ValueListOID")
            ),
            None,
        )
        for item_ref in vl.iter(f"{_ODM}ItemRef") if vl is not None else ():
            child = items.get(item_ref.get("ItemOID"))
            length = child.get("Length") if child is not None else None
            if length is not None and int(length) > int(parent_length):
                errors.append(
                    f"ItemDef {child.get('OID')} has Length {length}, more than the Length "
                    f"{parent_length} of its parent {parent.get('OID')}"
                )
    return errors


def _codelist_type_errors(root: ET.Element) -> list[str]:
    """A CodeList has the DataType of each variable that references it."""
    codelists = {cl.get("OID"): cl.get("DataType") for cl in root.iter(f"{_ODM}CodeList")}
    errors: list[str] = []
    for item in root.iter(f"{_ODM}ItemDef"):
        ref = item.find(f"{_ODM}CodeListRef")
        if ref is None:
            continue
        cl_type = codelists.get(ref.get("CodeListOID"))
        if cl_type is not None and cl_type != item.get("DataType"):
            errors.append(
                f"ItemDef {item.get('OID')} has DataType {item.get('DataType')} but its "
                f"CodeList {ref.get('CodeListOID')} has DataType {cl_type}"
            )
    return errors
