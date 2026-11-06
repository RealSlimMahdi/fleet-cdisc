"""One lookup for the terms of a codelist, across the stores Fleet keeps.

Codelist terms live in three places: the loaded ``CTValidator`` cache, the
classes of a study's ``codelists.py`` (``fleet init ct``), and the
``codelists:`` items of a define.yaml.  :func:`terms_for` asks them in one
fixed order, so every check that uses it sees the same terms.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fleet.ct.validator import CTValidator

#: Metadata attributes of a generated codelist class, not terms.
_CLASS_META = frozenset({"_concept_id", "_cdisc_url", "_preferred_term"})


def class_terms(cls: type) -> frozenset[str]:
    """Return the terms of a generated codelist class (``codelists.py``).

    A class keeps its terms in ``_terms`` when a term is not a valid
    attribute name (``10^9/L``); otherwise each public string attribute is
    a term.

    Args:
        cls: A codelist class, for example ``SEX``.

    Returns:
        frozenset[str]: The terms; empty when the class holds none.
    """
    terms = getattr(cls, "_terms", None)
    if terms:
        return frozenset(str(t) for t in terms)
    return frozenset(
        v
        for k, v in vars(cls).items()
        if not k.startswith("__") and k not in _CLASS_META and isinstance(v, str)
    )


def terms_for(
    ct: str | type,
    validator: CTValidator | None = None,
    study_classes: Mapping[str, type] | None = None,
    define_items: Mapping[str, Iterable[str]] | None = None,
) -> frozenset[str] | None:
    """Return the terms of codelist *ct*, or ``None`` when no store holds it.

    The stores are asked in this order: the loaded validator, the class
    given as *ct*, the study's ``codelists.py`` classes by concept ID, and
    the define.yaml ``codelists:`` items by ID.  The first store that holds
    the codelist gives the terms.

    Args:
        ct: The codelist: an ID such as ``"C66731"`` or a codelist class.
        validator: A loaded ``CTValidator``.
        study_classes: The study's codelist classes, keyed by concept ID.
        define_items: The coded values of the define.yaml codelists, by ID.

    Returns:
        frozenset[str] | None: The terms, or ``None`` when no store holds
            the codelist.

    Examples:
        Look up SEX with the global validator and the study classes::

            from fleet.ct.terms import terms_for
            from fleet.ct.validator import get_validator

            terms = terms_for("C66731", validator=get_validator())
    """
    ct_id = ct if isinstance(ct, str) else str(getattr(ct, "_concept_id", None) or ct.__name__)
    if validator is not None and validator.has_codelist(ct_id):
        return frozenset(validator.get_valid_values(ct_id))
    if not isinstance(ct, str):
        terms = class_terms(ct)
        if terms:
            return terms
    if study_classes and ct_id in study_classes:
        terms = class_terms(study_classes[ct_id])
        if terms:
            return terms
    if define_items and ct_id in define_items:
        return frozenset(str(v) for v in define_items[ct_id])
    return None


def study_codelist_classes(start: Path | None = None) -> dict[str, type]:
    """Return the ``codelists.py`` classes of the study found from *start*, by concept ID.

    Args:
        start: Folder to search from; the working directory when ``None``.

    Returns:
        dict[str, type]: The classes; empty outside a study or before
            ``fleet init ct``.
    """
    from fleet.core.study_context import find_study_config, load_study_context
    from fleet.ct.study_codelists import load_codelists

    config = find_study_config(start)
    if config is None:
        return {}
    path = load_study_context(config).codelists_file
    return load_codelists(path)[1] if path.is_file() else {}
