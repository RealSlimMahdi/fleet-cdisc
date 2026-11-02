"""Code generator that converts CDISC Library JSON into Python constants.

The generated module contains one class per codelist whose attributes are
the permitted submission values.  This gives developers and AI agents
statically typed, IDE-autocomplete-friendly access to CDISC CT.

Each generated class also exposes ``_cdisc_url`` and embeds the CDISC
Library Browser URL in its docstring so reviewers can navigate from
pipeline code straight to the authoritative codelist definition.  When
every codelist comes from one CT package, the module opens with a
``__ct_package__`` marker naming it (see :mod:`fleet.ct.study_codelists`).

Example generated output::

    __ct_package__ = "sdtmct-2023-12-15"


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
    generator.write("examples/cdiscpilot01/sdtm/codelists.py")
"""

from __future__ import annotations

import keyword
import logging
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterator

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


_NCI_ID = re.compile(r"^C\d+$")


def extract_concept_ids(define_path: str | Path) -> set[str]:
    """Extract NCI concept IDs from a ``define.yaml`` spec file.

    Scans the ``codelists`` section (``oid`` fields), per-variable
    ``codelist`` references, and per-variable ``derivation.ct``
    references.  Only IDs matching the ``C\\d+`` pattern are returned.

    Args:
        define_path: Path to a ``define.yaml`` file.

    Returns:
        Set of concept ID strings (e.g. ``{"C66731", "C74457"}``).
    """
    spec = _load_spec(define_path)
    ids = {str(cl.get("oid", "")) for cl in spec.get("codelists") or []}
    ids |= {concept_id for _, _, concept_id in _references(spec)}
    return {i for i in ids if _NCI_ID.match(i)}


def codelist_references(define_path: str | Path) -> list[tuple[str, str, str]]:
    """List the NCI codelist each variable of a ``define.yaml`` references.

    Reads the variable-level ``codelist`` and the derivation-level
    ``ct``; only IDs matching the ``C\\d+`` pattern count.

    Args:
        define_path: Path to a ``define.yaml`` file.

    Returns:
        ``(dataset, variable, concept_id)`` tuples in spec order, one per
        reference.

    Examples:
        Name the variables that need a class in ``codelists.py``::

            for dataset, variable, concept_id in codelist_references("define.yaml"):
                print(f"{dataset}.{variable} -> {concept_id}")
    """
    return list(_references(_load_spec(define_path)))


def _load_spec(define_path: str | Path) -> dict[str, Any]:
    with open(define_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _references(spec: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    for ds in spec.get("datasets") or []:
        for var in ds.get("variables") or []:
            derivation = var.get("derivation") or {}
            for ref in (var.get("codelist"), derivation.get("ct")):
                if isinstance(ref, str) and _NCI_ID.match(ref):
                    yield str(ds.get("name", "")), str(var.get("name", "")), ref


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

    found: set[str] = set()
    ids: set[str] = set()
    for ds in ds_links:
        domain = ds["href"].split("/")[-1]
        if domain not in domains_upper:
            continue
        found.add(domain)
        detail = client._get(ds["href"])
        for var in detail.get("datasetVariables", []):
            for cl in var.get("_links", {}).get("codelist", []):
                m = re.search(r"codelists/(C\d+)", cl.get("href", ""))
                if m:
                    ids.add(m.group(1))

    # Warn about non-standard domains that were not found in the IG
    missing = domains_upper - found
    for d in sorted(missing):
        logger.warning(
            "Domain '%s' not found in SDTM IG %s — no codelists extracted. "
            "If this is a company-specific domain, add codelists manually.",
            d,
            ig_version,
        )
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
        cdisc_url_template: URL template used to build the
            ``_cdisc_url`` class attribute and the ``See:`` reference in
            each codelist's docstring.  Substitution fields available:
            ``{concept_id}``, ``{package}`` (e.g. ``sdtmct-2024-12-13``),
            and ``{date}`` (the package date suffix).  Defaults to the
            CDISC Library Browser deep link, which requires all three.
    """

    include_docs: bool = True
    cdisc_url_template: str = (
        "https://library.cdisc.org/browser/#/mdr/ct/{date}/packages/"
        "{package}/codelists/{concept_id}"
    )
    _codelists: list[dict[str, Any]] = field(default_factory=list, init=False)

    def add_codelist(
        self,
        codelist_json: dict[str, Any],
        *,
        package: str | None = None,
    ) -> None:
        """Register a raw CDISC Library codelist JSON response.

        Args:
            codelist_json: Dict returned by ``CDISCClient.get_codelist``.
                Must contain at least ``conceptId`` and ``terms``.
            package: Optional CT package the codelist was fetched from
                (e.g. ``"sdtmct-2024-12-13"``).  Stored on the codelist
                dict as ``_package`` so the rendered ``_cdisc_url`` can
                include the correct package + date context required by
                the CDISC Library Browser.

        Raises:
            ValueError: If required keys are missing.
        """
        if "conceptId" not in codelist_json:
            raise ValueError("codelist JSON must contain 'conceptId'")
        if package is not None:
            codelist_json = {**codelist_json, "_package": package}
        self._codelists.append(codelist_json)

    @property
    def concept_ids(self) -> set[str]:
        """Return the set of concept IDs already loaded."""
        return {cl["conceptId"] for cl in self._codelists}

    @property
    def codelist_count(self) -> int:
        """Return the number of codelists registered so far."""
        return len(self._codelists)

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
                gen.add_codelist(
                    client.get_codelist(cid, package=package),
                    package=package,
                )
            except Exception:
                logger.warning(
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
                    gen.write("examples/cdiscpilot01/sdtm/codelists.py")
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
        # Marker for the stale checks of fleet.ct.study_codelists; mixed packages get none.
        packages = {cl.get("_package") for cl in sorted_cls}
        if len(packages) == 1 and None not in packages:
            lines += [f"__ct_package__ = {packages.pop()!r}", "", ""]

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
        cdisc_url: str | None = self._build_cdisc_url(cl)

        # Class docstring
        doc_parts = [f"{submission_value} ({concept_id})."]
        if self.include_docs and definition:
            doc_parts.append("")
            doc_parts.append(textwrap.fill(definition, width=76))
        # Always add the CDISC Library reference so reviewers can jump from
        # generated code to the authoritative source-of-truth definition.
        if cdisc_url:
            doc_parts.append("")
            doc_parts.append(f"See: {cdisc_url}")

        class_doc = "\n    ".join(doc_parts)
        lines = [
            f"class {class_name}:",
            f'    """{class_doc}"""',
            "",
            f"    _concept_id = {concept_id!r}",
        ]
        if cdisc_url:
            lines.append(f"    _cdisc_url = {cdisc_url!r}")

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

    def _build_cdisc_url(self, cl: dict[str, Any]) -> str | None:
        """Format the CDISC Library Browser URL for *cl*.

        Returns ``None`` when the template requires a ``{package}`` or
        ``{date}`` field but no package was recorded for this codelist
        (e.g. when ``add_codelist`` was called without ``package=``).
        """
        concept_id: str = cl["conceptId"]
        package: str | None = cl.get("_package")
        date: str | None = None
        if package and "-" in package:
            # e.g. "sdtmct-2024-12-13" -> "2024-12-13"
            _, _, date = package.partition("-")
        # If the template needs package/date context but none was
        # recorded, skip the URL rather than emit a broken link.
        needs_package = "{package}" in self.cdisc_url_template
        needs_date = "{date}" in self.cdisc_url_template
        if (needs_package and not package) or (needs_date and not date):
            return None
        try:
            return self.cdisc_url_template.format(
                concept_id=concept_id,
                package=package or "",
                date=date or "",
            )
        except KeyError:
            return None

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
