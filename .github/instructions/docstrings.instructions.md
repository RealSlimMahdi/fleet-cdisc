---
description: "Use when writing or reviewing docstrings in Python source files under src/"
applyTo: "src/**/*.py"
---
# Docstring Convention (Google-style)

All public functions and methods MUST use Google-style docstrings.

## Required Sections (in order)

1. **One-sentence summary** (imperative mood)
2. **Extended description** (optional, 2–3 sentences max)
3. **Args:** — one line per parameter
4. **Returns:** — type and short description
5. **Raises:** — only if non-obvious exceptions
6. **Examples:** — at least one complete pipeline snippet ending with `.to_frame()`

## Rules

- Use `Examples:` (plural, no trailing `::`) as section header, followed by description and `::` for code block.
- Every example must be a **complete pipeline snippet** (not a bare `.verb(...)` fragment).
- NEVER use NumPy/Sphinx `Parameters ----------` style.
- NEVER use bare `Example::` (singular with double colon).
- Private helpers (`_chain`, `_materialise_then`, etc.) are exempt.

## Template

```python
def verb_name(self, target: str, *, source: str) -> Self:
    """One-sentence summary of what the verb does.

    Longer description if needed (2-3 sentences max).

    Args:
        target: Name of the output column to create.
        source: Name of the input column.

    Returns:
        Self: The namespace with *target* appended; call ``.to_frame()``
            to materialise.

    Examples:
        Copy the raw subject ID to USUBJID::

            dm = (
                raw_df.sdtm
                .assign_no_ct("USUBJID", source="subject_id")
                .to_frame()
            )
    """
```
