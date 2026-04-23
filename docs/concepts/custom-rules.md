# Custom Validation Rules

When the standard CDISC CORE conformance rule set does not cover a study-specific requirement — a sponsor SOP constraint, an FDA Technical Conformance Guide (TCG) gap, or a protocol-specific range check — you can author **custom rules** and run them alongside the official rules.

---

## When to write custom rules

- **Sponsor SOPs** require checks not covered by CDISC CORE (e.g. mandatory SUPPQUAL variables).
- **FDA TCG requirements** that have not yet been formalised as CORE rules.
- **Protocol-specific constraints** such as custom reference ranges, visit windows, or dose limits.
- **Interim quality gates** during study setup before official validation.

---

## Rule anatomy

A custom rule follows the same YAML schema as CDISC CORE rules. Here is an annotated example:

```yaml
core_id: SPONSOR-000001 # Company prefix to avoid CORE-XXXXXX collisions
version: "1"
status: Published
description: >
  AESTDTC must not be before RFSTDTC for on-treatment AE records.
message: >
  AE start date falls before the first study treatment date.
rule_type: Record Data
sensitivity: Record
executability: Fully Executable

# The check DSL — same operators as CDISC CORE
check:
  all:
    - name: AESTDTC
      operator: date_less_than
      value: RFSTDTC

# Scope restricts which domains/classes the rule applies to
classes:
  - EVENTS
domains:
  - AE
use_case: INDH
```

---

## The check DSL

CDISC CORE rules use a JSON/YAML check DSL built from composable operators:

| Combinator | Meaning                             |
| ---------- | ----------------------------------- |
| `all`      | All conditions must be true (AND)   |
| `any`      | At least one condition is true (OR) |
| `not`      | Negates the enclosed condition      |

Each leaf condition specifies a **variable name**, an **operator**, and optionally a **value**:

```yaml
check:
  all:
    - name: AESEV
      operator: is_contained_by
      value: ["MILD", "MODERATE", "SEVERE"]
    - name: AESER
      operator: equal_to
      value: "Y"
```

Common operators: `equal_to`, `not_equal_to`, `exists`, `non_empty`, `empty`, `is_contained_by`, `longer_than`, `date_less_than`, `date_greater_than`.

For the full operator reference, see the [CDISC CORE Rule Editor](https://rule-editor.cdisc.org/).

---

## Storing custom rules

Place custom rule files in a dedicated directory, separate from the CDISC-sourced rules:

```
metadata/
  sdtm/
    rules/             ← CDISC CORE rules (from fleet init rules)
    custom_rules/      ← Your sponsor-specific rules
  adam/
    rules/
    custom_rules/
```

Commit both directories to VCS so the complete rule inventory is versioned alongside the study.

---

## Running custom rules with Fleet

Pass custom rules to the CDISC Rules Engine via the `-lr` flag (ephemeral) or `update-cache` (persistent):

```bash
# Ephemeral: load for a single validation run
cdisc-rules-engine validate -s 3-4 -dp ./data/sdtm \
  -lr metadata/sdtm/custom_rules/

# Persistent: add to the engine's rule cache
cdisc-rules-engine update-cache -lr metadata/sdtm/custom_rules/
```

Custom rules are executed alongside CDISC CORE rules in the same pass. Results appear in the same validation report.

---

## ID naming convention

| Prefix         | Range           | Owner             |
| -------------- | --------------- | ----------------- |
| `CORE-XXXXXX`  | 000001–999999   | CDISC (official)  |
| `SPONSOR-XXXX` | Company-defined | Your organisation |

Never reuse a `CORE-` prefix for custom rules — use your company name or abbreviation.

---

## Contributing upstream

If your custom rule addresses a gap that would benefit the broader CDISC community, consider contributing it back via the [CDISC Rule Editor](https://rule-editor.cdisc.org/) or the CORE GitHub repository.
