"""XSD validation for generated Define-XML documents.

Fleet validates the *spec* (Pydantic + JSON Schema) and the *datasets*
(CDISC Rules Engine), but nothing checked the define.xml it emits.  This
module closes that gap: the ODM 1.3.2 + Define-XML 2.1 schema set ships
inside the package, so validation works offline with no setup.

Schema location is resolved in the same order Fleet uses for the rules
engine, so a site can override the packaged copy without reinstalling:

1. ``FLEET_DEFINE_XSD`` environment variable.
2. ``~/.fleet/xsd/`` (populated by ``fleet install-xsd``).
3. The copy shipped inside this package.

The files must keep the directory layout CDISC publishes them in:
Define-XML's schemas import ODM's by relative path (``../../odm/1.3.2``),
so ``define/2.1`` and ``odm/1.3.2`` have to sit side by side.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from fleet.core.exceptions import SpecError

#: Root schema of the set — the file handed to the XSD parser.  Relative to
#: the schema directory, because Define-XML reaches ODM as ``../../odm/1.3.2``.
ROOT_XSD = "define/2.1/define2-1-0.xsd"

#: Every file the set needs.  The layout matters as much as the contents:
#: the ``define/2.1`` schemas import ODM by relative path, so the two
#: directories must sit side by side exactly as CDISC publishes them.
REQUIRED_FILES: tuple[str, ...] = (
    ROOT_XSD,
    "define/2.1/define-extension.xsd",
    "define/2.1/define-ns.xsd",
    "define/2.1/define-enumerations.xsd",
    "define/2.1/xlink.xsd",
    "define/2.1/xml.xsd",
    "define/2.1/xmldsig-core-schema.xsd",
    "odm/1.3.2/ODM1-3-2.xsd",
    "odm/1.3.2/ODM1-3-2-foundation.xsd",
    "odm/1.3.2/xml.xsd",
    "odm/1.3.2/xmldsig-core-schema.xsd",
)


@contextmanager
def xsd_dir() -> Iterator[Path]:
    """Yield the directory holding the ODM / Define-XML schema set.

    Resolution order: ``FLEET_DEFINE_XSD`` → ``~/.fleet/xsd`` → the
    packaged copy.  The packaged copy is accessed through
    :mod:`importlib.resources`, so it resolves to a real filesystem path
    whether Fleet is installed as a directory, a wheel, or a zip.

    Yields:
        Path: Directory containing the schema files.

    Examples:
        Locate the shipped schema set::

            from fleet.define_xml.xsd import xsd_dir

            with xsd_dir() as d:
                print(sorted(p.name for p in d.glob("*.xsd")))
    """
    override = os.environ.get("FLEET_DEFINE_XSD")
    if override:
        yield Path(override)
        return

    managed = Path.home() / ".fleet" / "xsd"
    if (managed / ROOT_XSD).is_file():
        yield managed
        return

    with resources.as_file(resources.files(__package__) / "schemas" / "xsd") as packaged:
        yield packaged


def missing_files() -> list[str]:
    """Return the schema files that are not present in the resolved directory.

    Returns:
        list[str]: Missing filenames; empty when the set is complete.

    Examples:
        Skip validation when the schema set is unavailable::

            from fleet.define_xml.xsd import missing_files

            if not missing_files():
                ...  # safe to call validate_define_xml()
    """
    with xsd_dir() as d:
        return [name for name in REQUIRED_FILES if not (d / name).is_file()]


def validate_define_xml(xml: str | bytes | Path) -> list[str]:
    """Validate a Define-XML document against the ODM / Define-XML 2.1 XSDs.

    Structural validation only — element order, required attributes, and
    enumerated attribute values (an ``Origin Type`` outside the 2.1
    vocabulary fails here).  Conformance rules (P21 / CORE) are a
    separate layer; see :meth:`fleet.sdtm.SDTMNamespace.validate`.

    Args:
        xml: Define-XML document as a string, bytes, or a path to a file.

    Returns:
        list[str]: Validation errors, each naming line and message.
            Empty when the document is valid.

    Raises:
        SpecError: When the schema set is incomplete — the message names
            the missing files and where they were looked for.

    Examples:
        Validate a generated define.xml::

            from fleet.define_xml import DefineSpecGenerator
            from fleet.define_xml.xsd import validate_define_xml

            xml = DefineSpecGenerator("define.yaml").to_xml_string()
            for problem in validate_define_xml(xml):
                print(problem)
    """
    from lxml import etree

    missing = missing_files()
    if missing:
        with xsd_dir() as d:
            raise SpecError(
                f"Define-XML schema set incomplete in {d} — missing {', '.join(missing)}. "
                "Install the CDISC ODM 1.3.2 + Define-XML 2.1 schemas there, or point "
                "FLEET_DEFINE_XSD at a directory that holds them."
            )

    if isinstance(xml, Path):
        doc = etree.parse(str(xml))
    else:
        data = xml.encode("utf-8") if isinstance(xml, str) else xml
        doc = etree.fromstring(data).getroottree()

    with xsd_dir() as d:
        schema = etree.XMLSchema(etree.parse(str(d / ROOT_XSD)))
    if schema.validate(doc):
        return []
    return [f"line {e.line}: {e.message}" for e in schema.error_log]
