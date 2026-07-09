"""Join validation issues with variable-level lineage.

Closes the loop between :class:`fleet.validation.models.ValidationIssue`
and :class:`fleet.core.dag.VariableNode`: when a CDISC rule fails on a
variable, the issue is enriched with the verb that produced the column
plus a dotted Python path so reviewers can navigate straight from the
validation report to the source code (or its docstring on the docs site).

Examples:
    Run validation, then enrich issues with lineage::

        from fleet.core.lineage import lineage_of
        from fleet.validation.lineage_join import enrich_with_lineage

        ns = raw_df.sdtm.assign("USUBJID", source="subject_id")
        result = run_validation(ns.to_frame(), ...)  # produces ValidationResult
        enrich_with_lineage(result, lineage_of(ns), spec_ref="define.yaml -> DM")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fleet.core.dag import VariableNode
    from fleet.validation.models import ValidationResult


def enrich_with_lineage(
    result: ValidationResult,
    lineage: list[VariableNode],
    *,
    spec_ref: str | None = None,
) -> ValidationResult:
    """Annotate validation issues with the verb that produced each variable.

    Mutates *result* in-place (and returns it for chaining).  Issues whose
    ``variable`` matches a lineage entry by name receive the
    ``producing_verb``, ``verb_method``, and ``spec_ref`` fields.  Issues
    without a matching lineage entry are left untouched.

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
            entry = by_name.get(issue.variable or "")
            if entry is None:
                continue
            issue.producing_verb = entry.verb
            issue.verb_method = entry.method
            if spec_ref and not issue.spec_ref:
                issue.spec_ref = spec_ref
    return result
