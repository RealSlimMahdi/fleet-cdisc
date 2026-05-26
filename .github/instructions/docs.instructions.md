---
description: "Use when editing documentation files under docs/, especially mkdocstrings API pages"
applyTo: "docs/**/*.md"
---
# Documentation Files — Formatting Rules

Files under `docs/api/` contain **mkdocstrings directives** — special YAML blocks that reference Python module paths. These are NOT regular Markdown.

## Critical Rules

1. **NEVER escape underscores in `:::` directives.** The `:::` line is a Python dotted path.

   ```markdown
   <!-- WRONG --> ::: fleet.sdtm.\_tdd_mixin
   <!-- CORRECT --> ::: fleet.sdtm._tdd_mixin
   ```

2. **NEVER replace underscores with asterisks in YAML option blocks.** Markdown formatters may interpret `_word_` as emphasis.

   ```yaml
   # WRONG
   show*root_heading: true
   filters: ["!^*"]

   # CORRECT
   show_root_heading: true
   filters: ["!^_"]
   ```

3. **After editing any `docs/api/*.md` file, verify:**

   ```bash
   uv run mkdocs build --clean
   ```

## Standard Block Template

```markdown
::: fleet.<module>.<ClassName>
    options:
      show_root_heading: true
      heading_level: 3
      filters: ["!^_"]
```

## Known Corruption

Markdown formatters (Prettier, markdownlint --fix) auto-replace `_` with `*` in option blocks and escape `_` with `\_` in `:::` directives. Fix immediately if spotted.
