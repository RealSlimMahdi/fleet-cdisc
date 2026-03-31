"""Code generator that converts CDISC Library JSON into Python constants.

The generated module contains one class per codelist whose attributes are
the permitted submission values.  This gives developers and AI agents
statically typed, IDE-autocomplete-friendly access to CDISC CT.

Example generated output::

    class C66731:
        \"\"\"Sex (C66731).\"\"\"
        F = "F"
        M = "M"
        U = "U"
        UNDIFFERENTIATED = "UNDIFFERENTIATED"

    # Human-readable aliases
    SEX = C66731

    __all__ = ["C66731", "SEX"]

Usage::

    from fleet.ct.api import CDISCClient
    from fleet.ct.generator import CodelistGenerator

    client = CDISCClient()
    generator = CodelistGenerator()
    generator.add_codelist(client.get_codelist("C66731"))
    generator.write("specs/cdiscpilot01/sdtm/codelists.py")
"""

from __future__ import annotations

import keyword
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from fleet.ct.api import CDISCClient


def _safe_identifier(name: str) -> str:
    """Convert an arbitrary string into a valid Python identifier.

    Replaces non-alphanumeric characters with underscores, strips leading
    digits, and appends a trailing underscore if the result is a reserved
    keyword.
    """
    ident = re.sub(r"[^0-9A-Za-z_]", "_", name)
    ident = re.sub(r"^[0-9]+", "", ident)
    if not ident:
        ident = "_EMPTY"
    if keyword.iskeyword(ident) or keyword.issoftkeyword(ident):
        ident += "_"
    return ident


def extract_concept_ids(define_path: str | Path) -> set[str]:
    """Extract NCI concept IDs from a ``define.yaml`` spec file.

    Scans the ``codelists`` section (``oid`` fields), per-variable
    ``codelist`` references, and per-variable ``derivation.ct_codelist``
    references.  Only IDs matching the ``C\\d+`` pattern are returned.

    Args:
        define_path: Path to a ``define.yaml`` file.

    Returns:
        Set of concept ID strings (e.g. ``{"C66731", "C74457"}``).
    """
    path = Path(define_path)
    with open(path) as f:
        spec = yaml.safe_load(f)

    nci_pattern = re.compile(r"^C\d+$")
    ids: set[str] = set()

    for cl in spec.get("codelists", []):
        oid = cl.get("oid", "")
        if nci_pattern.match(oid):
            ids.add(oid)

    for ds in spec.get("datasets", []):
        for var in ds.get("variables", []):
            # Variable-level codelist reference
            cl_ref = var.get("codelist", "")
            if isinstance(cl_ref, str) and nci_pattern.match(cl_ref):
                ids.add(cl_ref)
            # Derivation-level ct_codelist reference
            deriv = var.get("derivation") or {}
            ct_ref = deriv.get("ct_codelist", "")
            if isinstance(ct_ref, str) and nci_pattern.match(ct_ref):
                ids.add(ct_ref)

    return ids


def extract_ig_concept_ids(
    client: CDISCClient,
    ig_version: str,
    domains: list[str],
) -> set[str]:
    """Query the CDISC Library SDTM IG and extract codelist concept IDs.

    Args:
        client: An authenticated ``CDISCClient``.
        ig_version: IG version string (e.g. ``"3-4"``).
        domains: Domain abbreviations to scan.

    Returns:
        Set of NCI concept ID strings.
    """
    ig = client._get(f"/mdr/sdtmig/{ig_version}/datasets")
    ds_links = ig.get("_links", {}).get("datasets", [])
    domains_upper = {d.upper() for d in domains}

    ids: set[str] = set()
    for ds in ds_links:
        domain = ds["href"].split("/")[-1]
        if domain not in domains_upper:
            continue
        detail = client._get(ds["href"])
        for var in detail.get("datasetVariables", []):
            for cl in var.get("_links", {}).get("codelist", []):
                m = re.search(r"codelists/(C\d+)", cl.get("href", ""))
                if m:
                    ids.add(m.group(1))
    return ids


def existing_concept_ids(path: Path) -> set[str]:
    """Extract concept IDs already defined in an existing ``codelists.py``.

    Args:
        path: Path to the generated codelists file.

    Returns:
        Set of concept ID strings found in the file.
    """
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"_concept_id\s*=\s*['\"]([^'\"]+)['\"]", text))


@dataclass
class CodelistGenerator:
    """Accumulates CDISC codelist JSON responses and renders them as Python.

    Args:
        include_docs: If ``True`` (default), inject ``definition`` and
            ``preferredTerm`` from the CDISC JSON into class/attribute
            docstrings for richer AI context.
    """

    include_docs: bool = True
    _codelists: list[dict[str, Any]] = field(default_factory=list, init=False)

    def add_codelist(self, codelist_json: dict[str, Any]) -> None:
        """Register a raw CDISC Library codelist JSON response.

        Args:
            codelist_json: Dict returned by ``CDISCClient.get_codelist``.
                Must contain at least ``conceptId`` and ``terms``.

        Raises:
            ValueError: If required keys are missing.
        """
        if "conceptId" not in codelist_json:
            raise ValueError("codelist JSON must contain 'conceptId'")
        self._codelists.append(codelist_json)

    @property
    def concept_ids(self) -> set[str]:
        """Return the set of concept IDs already loaded."""
        return {cl["conceptId"] for cl in self._codelists}

    @classmethod
    def from_concept_ids(
        cls,
        client: CDISCClient,
        concept_ids: set[str],
        *,
        package: str = "sdtmct-2023-12-15",
        include_docs: bool = True,
    ) -> CodelistGenerator:
        """Build a generator from an explicit set of NCI concept IDs.

        Args:
            client: An authenticated ``CDISCClient`` instance.
            concept_ids: Set of NCI concept ID strings to download.
            package: CT package version to download from.
            include_docs: Whether to include definitions in generated output.

        Returns:
            A ``CodelistGenerator`` populated with the requested codelists.

        Examples:
            Generate codelists for specific concept IDs::

                from fleet.ct.api import CDISCClient
                from fleet.ct.generator import CodelistGenerator

                with CDISCClient() as client:
                    gen = CodelistGenerator.from_concept_ids(
                        client,
                        {"C66731", "C74457"},
                    )
                    gen.write("codelists.py")
        """
        gen = cls(include_docs=include_docs)
        for cid in sorted(concept_ids):
            try:
                gen.add_codelist(client.get_codelist(cid, package=package))
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "Codelist %s not found in package %s — skipping.",
                    cid,
                    package,
                )
        return gen

    @classmethod
    def from_sdtm_ig(
        cls,
        client: CDISCClient,
        domains: list[str],
        *,
        ig_version: str = "3-4",
        package: str = "sdtmct-2023-12-15",
        include_docs: bool = True,
    ) -> CodelistGenerator:
        """Build a generator from the SDTM IG — the authoritative source of truth.

        Queries the CDISC Library for the specified SDTM IG version,
        extracts every codelist referenced by variables in the requested
        domains, and downloads the corresponding CT definitions.

        Args:
            client: An authenticated ``CDISCClient`` instance.
            domains: List of SDTM domain abbreviations to include
                (e.g. ``["DM", "AE", "VS", "EX"]``).
            ig_version: SDTM IG version (default ``"3-4"``).
            package: CT package version to download terms from.
            include_docs: Whether to include definitions in generated output.

        Returns:
            A ``CodelistGenerator`` populated with all referenced codelists.

        Examples:
            Generate codelists for DM and AE from SDTM IG 3.4::

                from fleet.ct.api import CDISCClient
                from fleet.ct.generator import CodelistGenerator

                with CDISCClient() as client:
                    gen = CodelistGenerator.from_sdtm_ig(
                        client,
                        domains=["DM", "AE", "VS", "EX"],
                    )
                    gen.write("specs/cdiscpilot01/sdtm/codelists.py")
        """
        concept_ids = extract_ig_concept_ids(client, ig_version, domains)
        return cls.from_concept_ids(
            client,
            concept_ids,
            package=package,
            include_docs=include_docs,
        )

    def render(self) -> str:
        """Render accumulated codelists as a Python module string.

        Returns:
            A complete, syntactically valid Python source string.
        """
        sorted_cls = sorted(self._codelists, key=lambda c: c["conceptId"])

        lines: list[str] = [
            '"""Auto-generated CDISC Controlled Terminology constants.',
            "",
            "Do not edit manually — regenerate with ``fleet.ct.generator``.",
            '"""',
            "",
        ]

        # Class definitions
        for cl in sorted_cls:
            lines.extend(self._render_class(cl))
            lines.append("")

        # Human-readable aliases  (e.g.  SEX = C66731)
        aliases: list[tuple[str, str]] = []
        for cl in sorted_cls:
            concept_id = cl["conceptId"]
            class_name = _safe_identifier(concept_id)
            alias = self._alias_for(cl)
            if alias and alias != class_name:
                aliases.append((alias, class_name))

        if aliases:
            lines.append("")
            lines.append("# Human-readable aliases")
            for alias, class_name in sorted(aliases):
                lines.append(f"{alias} = {class_name}")
            lines.append("")

        # __all__
        all_names: list[str] = [_safe_identifier(cl["conceptId"]) for cl in sorted_cls]
        all_names.extend(alias for alias, _ in sorted(aliases))
        all_names.sort()
        all_repr = ", ".join(f'"{n}"' for n in all_names)
        lines.append(f"__all__ = [{all_repr}]")
        lines.append("")

        return "\n".join(lines) + "\n"

    def write(self, path: str | Path) -> Path:
        """Render and write the module to *path*.

        Parent directories are created if they do not exist.

        Args:
            path: Destination file path.

        Returns:
            Resolved ``Path`` of the written file.
        """
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.render(), encoding="utf-8")
        return dest.resolve()

    # -- private -------------------------------------------------------- #

    def _render_class(self, cl: dict[str, Any]) -> list[str]:
        concept_id: str = cl["conceptId"]
        class_name = _safe_identifier(concept_id)
        submission_value: str = cl.get("submissionValue", concept_id)
        preferred_term: str = cl.get("preferredTerm", "")
        definition: str = cl.get("definition", "")

        # Class docstring
        doc_parts = [f"{submission_value} ({concept_id})."]
        if self.include_docs and definition:
            doc_parts.append("")
            doc_parts.append(textwrap.fill(definition, width=76))

        class_doc = "\n    ".join(doc_parts)
        lines = [
            f"class {class_name}:",
            f'    """{class_doc}"""',
            "",
            f"    _concept_id = {concept_id!r}",
        ]

        if self.include_docs and preferred_term:
            lines.append(f"    _preferred_term = {preferred_term!r}")
        lines.append("")

        terms: list[dict[str, Any]] = cl.get("terms", [])
        if not terms:
            lines.append("    pass")
            return lines

        for term in sorted(terms, key=lambda t: t.get("submissionValue", "")):
            sv: str = term.get("submissionValue", "")
            if not sv:
                continue
            attr = _safe_identifier(sv)
            lines.append(f"    {attr} = {sv!r}")

            if self.include_docs:
                term_def = term.get("definition", "")
                if term_def:
                    comment = textwrap.shorten(term_def, width=72)
                    lines.append(f"    # {comment}")

        return lines

    @staticmethod
    def _alias_for(cl: dict[str, Any]) -> str | None:
        """Derive a human-readable alias from the codelist submission value.

        Returns a valid Python identifier (e.g. ``"SEX"``, ``"RACE"``,
        ``"ETHNIC"``) or ``None`` when no usable name can be derived.
        """
        sv: str = cl.get("submissionValue", "")
        if not sv:
            return None
        return _safe_identifier(sv)
