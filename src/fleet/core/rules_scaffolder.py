"""CDISC conformance rules scaffolder — caches rules as human-readable YAML.

Queries the CDISC Library for all conformance rules associated with a
given SDTM or ADaM IG version, groups them by domain/dataset, and writes
one YAML file per domain under the study's ``rules_sdtm`` or ``rules_adam``
directory.

Usage::

    from fleet.ct.api import CDISCClient
    from fleet.core.rules_scaffolder import RulesScaffolder
    from fleet.core.study_context import load_study_context

    ctx = load_study_context(Path("study_config.yaml"))
    with CDISCClient() as client:
        scaffolder = RulesScaffolder(client)
        scaffolder.scaffold_sdtm(ctx, force=False)
        scaffolder.scaffold_adam(ctx, force=False)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from fleet.core.study_context import StudyContext
    from fleet.ct.api import CDISCClient

logger = logging.getLogger(__name__)


def _normalise_ig_version(dotted: str) -> str:
    """Convert ``"3.4"`` → ``"3-4"`` for API endpoint construction."""
    return dotted.replace(".", "-")


def _read_define_version(define_path: Path) -> str:
    """Read ``study.standard_version`` from a ``define.yaml``.

    Returns the raw version string (e.g. ``"3.4"`` or ``"1.1"``).

    Raises:
        FileNotFoundError: If the define.yaml does not exist.
        KeyError: If the version key is missing.
    """
    with open(define_path, encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}
    study = spec.get("study", {})
    version = study.get("standard_version")
    if not version:
        raise KeyError(
            f"Missing study.standard_version in {define_path}. Run `fleet init define` first."
        )
    return str(version)


def _extract_rule(rule_id: str, rule: dict[str, Any]) -> dict[str, Any]:
    """Flatten a CDISC Library rule into a lean YAML-friendly dict."""
    core = rule.get("Core", {})
    outcome = rule.get("Outcome", {})
    scope = rule.get("Scope", {})

    entry: dict[str, Any] = {
        "core_id": core.get("Id", rule_id),
        "version": core.get("Version", "1"),
        "status": core.get("Status", ""),
        "description": rule.get("Description", ""),
        "message": outcome.get("Message", ""),
        "rule_type": rule.get("Rule_Type", ""),
        "sensitivity": rule.get("Sensitivity", ""),
        "executability": rule.get("Executability", ""),
    }

    output_vars = outcome.get("Output_Variables")
    if output_vars:
        entry["output_variables"] = output_vars

    check = rule.get("Check")
    if check:
        entry["check"] = check

    operations = rule.get("Operations")
    if operations:
        entry["operations"] = operations

    # Scope metadata
    classes = scope.get("Classes", {}).get("Include", [])
    if classes:
        entry["classes"] = classes

    domains_include = scope.get("Domains", {}).get("Include", [])
    if domains_include:
        entry["domains"] = domains_include

    domains_exclude = scope.get("Domains", {}).get("Exclude", [])
    if domains_exclude:
        entry["domains_exclude"] = domains_exclude

    use_case = scope.get("Use_Case")
    if use_case:
        entry["use_case"] = use_case

    # First authority citation (lightweight)
    authorities = rule.get("Authorities", [])
    if authorities:
        refs = []
        for auth in authorities:
            for std in auth.get("Standards", []):
                for ref in std.get("References", []):
                    for cit in ref.get("Citations", []):
                        refs.append(
                            {
                                "section": cit.get("Section", ""),
                                "document": cit.get("Document", ""),
                            }
                        )
                    break  # first reference only
                break  # first standard only
            break  # first authority only
        if refs:
            entry["references"] = refs[:3]  # cap at 3

    return entry


def _group_rules_by_domain(
    rules: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Group rules by their domain scope.

    Rules scoped to ``["ALL"]`` are placed in an ``_ALL`` bucket.
    Rules listing multiple specific domains are duplicated into each.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for rule_id, rule in rules.items():
        entry = _extract_rule(rule_id, rule)
        scope = rule.get("Scope", {})
        domains = scope.get("Domains", {}).get("Include", [])

        if not domains or domains == ["ALL"]:
            grouped["_ALL"].append(entry)
        else:
            for dom in domains:
                grouped[dom].append(entry)

    return dict(grouped)


def _write_domain_file(
    path: Path,
    standard: str,
    version: str,
    domain: str,
    rules: list[dict[str, Any]],
    *,
    force: bool = False,
) -> bool:
    """Write a single domain rules YAML file.

    Returns True if the file was written, False if skipped.
    """
    if path.exists() and not force:
        logger.info("Skipping %s (already exists, use --force to overwrite)", path)
        return False

    # Sort rules by core_id for deterministic output
    rules_sorted = sorted(rules, key=lambda r: r.get("core_id", ""))

    doc = {
        "standard": standard,
        "version": version,
        "domain": domain,
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule_count": len(rules_sorted),
        "rules": rules_sorted,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return True


class RulesScaffolder:
    """Downloads CDISC conformance rules and writes them as domain YAML files.

    Args:
        client: An authenticated ``CDISCClient`` instance.
    """

    def __init__(self, client: CDISCClient) -> None:
        self._client = client

    def scaffold_sdtm(
        self,
        context: StudyContext,
        *,
        force: bool = False,
    ) -> Path:
        """Fetch SDTM conformance rules and write per-domain YAML files.

        The IG version is read from the SDTM ``define.yaml``
        (``study.standard_version``).

        Args:
            context: Resolved study context.
            force: Overwrite existing rule files.

        Returns:
            Path to the rules output directory.
        """
        define_path = context.metadata_sdtm_dir / "define.yaml"
        if not define_path.is_file():
            raise FileNotFoundError(
                f"SDTM define.yaml not found: {define_path}\nRun `fleet init define` first."
            )

        version_dotted = _read_define_version(define_path)
        version_api = _normalise_ig_version(version_dotted)
        api_path = f"/mdr/rules/sdtmig/{version_api}"

        logger.info("Fetching SDTM rules from %s", api_path)
        data = self._client.get(api_path)
        rules = data.get("rules", {})

        if not rules:
            logger.warning("No SDTM rules returned for IG version %s", version_api)
            print(f"Warning: No SDTM rules found for SDTMIG {version_api}.")
            return context.rules_sdtm_dir

        grouped = _group_rules_by_domain(rules)
        out_dir = context.rules_sdtm_dir
        written = 0

        for domain, domain_rules in sorted(grouped.items()):
            filename = f"{domain}.yaml"
            path = out_dir / filename
            if _write_domain_file(
                path, "SDTMIG", version_dotted, domain, domain_rules, force=force
            ):
                written += 1
                print(f"  {filename} ({len(domain_rules)} rules)")

        print(
            f"\nSDTM rules: {sum(len(r) for r in grouped.values())} rules "
            f"across {len(grouped)} files → {out_dir}"
        )
        if written == 0:
            print("  (all files already exist — use --force to overwrite)")

        return out_dir

    def scaffold_adam(
        self,
        context: StudyContext,
        *,
        force: bool = False,
    ) -> Path:
        """Fetch ADaM conformance rules and write per-dataset YAML files.

        Tries two CDISC Library API endpoints in order:

        1. Legacy standalone: ``/mdr/rules/adam/adamig-{version}``
        2. TIG (integrated): ``/mdr/rules/tig/1-0`` filtered to ADaM substandard

        The TIG endpoint was introduced in CORE v0.16 and is where CDISC now
        publishes ADaM rules.

        Args:
            context: Resolved study context.
            force: Overwrite existing rule files.

        Returns:
            Path to the rules output directory.
        """
        define_path = context.metadata_adam_dir / "define.yaml"
        if not define_path.is_file():
            raise FileNotFoundError(
                f"ADaM define.yaml not found: {define_path}\nRun `fleet init define` first."
            )

        version_dotted = _read_define_version(define_path)
        version_api = _normalise_ig_version(version_dotted)

        rules: dict[str, Any] = {}

        # Strategy 1: Legacy standalone endpoint
        api_path = f"/mdr/rules/adam/adamig-{version_api}"
        logger.info("Fetching ADaM rules from %s", api_path)
        try:
            data = self._client.get(api_path)
            rules = data.get("rules", {})
        except Exception as exc:
            logger.info("Legacy ADaM endpoint failed: %s", exc)

        # Strategy 2: TIG endpoint with ADaM substandard (CORE v0.16+)
        if not rules:
            tig_path = "/mdr/rules/tig/1-0"
            logger.info(
                "Legacy endpoint returned no rules; trying TIG endpoint: %s (substandard=ADaM)",
                tig_path,
            )
            try:
                data = self._client.get(tig_path)
                all_rules = data.get("rules", {})
                # Filter to ADaM-scoped rules: look for ANALYSIS use-case
                # or ADaM-specific class markers
                for rule_id, rule in all_rules.items():
                    scope = rule.get("Scope", {})
                    use_case = str(scope.get("Use_Case", "")).upper()
                    classes = [c.upper() for c in scope.get("Classes", {}).get("Include", [])]
                    if "ANALYSIS" in use_case or any(
                        c in ("ADAM", "BDS", "OCCDS", "ADSL") for c in classes
                    ):
                        rules[rule_id] = rule
                if rules:
                    logger.info("Found %d ADaM rules via TIG endpoint", len(rules))
                else:
                    logger.info(
                        "TIG endpoint returned %d rules but none matched ADaM filters",
                        len(all_rules),
                    )
            except Exception as exc:
                logger.warning("TIG endpoint also failed: %s", exc)
                print(
                    f"Warning: Could not fetch ADaM rules from ADAMIG {version_api} "
                    f"or TIG endpoint: {exc}"
                )
                print("  ADaM rules may not be available for this IG version.")
                return context.rules_adam_dir

        if not rules:
            logger.warning("No ADaM rules returned for IG version %s", version_api)
            print(f"No ADaM rules found for ADAMIG {version_api}.")
            print("  Note: CDISC has not yet published machine-executable ADaM conformance")
            print("  rules in the Library API. Consider writing custom rules for ADaM")
            print("  validation (see `fleet add-rule`).")
            return context.rules_adam_dir

        grouped = _group_rules_by_domain(rules)
        out_dir = context.rules_adam_dir
        written = 0

        for domain, domain_rules in sorted(grouped.items()):
            filename = f"{domain}.yaml"
            path = out_dir / filename
            if _write_domain_file(
                path, "ADAMIG", version_dotted, domain, domain_rules, force=force
            ):
                written += 1
                print(f"  {filename} ({len(domain_rules)} rules)")

        print(
            f"\nADaM rules: {sum(len(r) for r in grouped.values())} rules "
            f"across {len(grouped)} files → {out_dir}"
        )
        if written == 0:
            print("  (all files already exist — use --force to overwrite)")

        return out_dir
