"""Join validation issues with variable-level lineage.

Closes the loop between :class:`fleet.validation.models.ValidationIssue`
and :class:`fleet.core.dag.VariableNode`: when a CDISC rule fails on a
variable, the issue is enriched with the verb that produced the column
plus a dotted Python path so reviewers can navigate straight from the
validation report to the source code (or its docstring on the docs site).

The ``validate()`` verb applies this automatically using the chain's own
lineage, so the ``Producing verb`` line appears without extra wiring.
Call it directly only when the result and the lineage come from
different places (e.g. a spec-driven run reporting against a
``define.yaml`` reference)::

    from fleet.core.lineage import lineage_of
    from fleet.validation.lineage_join import enrich_with_lineage

    enrich_with_lineage(result, lineage_of(ns), spec_ref="define.yaml -> DM")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fleet.core.dag import VariableNode
    from fleet.validation.models import ValidationResult


#: A finding that names more variables than this gets no producing verb:
#: the list is a rule's context, not the variable the programmer must fix.
_MAX_NAMES = 5


def enrich_with_lineage(
    result: ValidationResult,
    lineage: list[VariableNode],
    *,
    spec_ref: str | None = None,
) -> ValidationResult:
    """Annotate validation issues with the verb that produced each variable.

    Mutates *result* in-place (and returns it for chaining).  The
    ``variable`` of an issue can name one variable or several
    (``"AESEQ, USUBJID, POOLID"``); each name is looked up in the lineage.
    One matched variable gives ``producing_verb`` its verb (``"assign"``).
    Several give each distinct verb with its variables
    (``"assign (AESEQ, USUBJID)"``).  An issue that names more than five
    variables, or none the chain made, is left untouched.

    Args:
        result: A populated ``ValidationResult`` from a CDISC rules run.
        lineage: Lineage entries collected from the SDTM/ADaM namespace
            (see :func:`fleet.core.lineage.lineage_of`).
        spec_ref: Optional human-readable spec reference applied to every
            enriched issue (e.g. ``"define.yaml -> VS -> SYSBP"``).

    Returns:
        The same ``ValidationResult`` instance, with issues mutated.
    """
    by_name = {entry.name: entry for entry in lineage}
    for bucket in (result.errors, result.warnings, result.infos):
        for issue in bucket:
            names = [n.strip() for n in (issue.variable or "").split(",") if n.strip()]
            if len(names) > _MAX_NAMES:
                continue
            entries = [by_name[n] for n in names if n in by_name]
            if not entries:
                continue
            if len(names) == 1:
                issue.producing_verb = entries[0].verb
                issue.verb_method = entries[0].method
            else:
                by_verb: dict[str, list[str]] = {}
                for entry in entries:
                    by_verb.setdefault(entry.verb, []).append(entry.name)
                issue.producing_verb = "; ".join(
                    f"{verb} ({', '.join(variables)})" for verb, variables in by_verb.items()
                )
                issue.verb_method = ", ".join(dict.fromkeys(e.method for e in entries))
            if spec_ref and not issue.spec_ref:
                issue.spec_ref = spec_ref
    return result
