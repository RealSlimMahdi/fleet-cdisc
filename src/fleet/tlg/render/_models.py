"""
Render data models and ARD → display shaping utilities.

Phase 1 (display contract) and Phase 2 (shaping) live here.

Display contract (derived from NEST AET01 / pharma conventions)
----------------------------------------------------------------

**Summary table layout:**

    ┌───────────────────────────────────────────────────────────────┐
    │  Title                                                       │
    │  Subtitle                                                    │
    ├──────────────────────┬──────────────┬──────────────┬─────────┤
    │                      │ Placebo      │ Drug A       │ Total   │
    │                      │ (N=xx)       │ (N=xx)       │ (N=xx)  │
    ├──────────────────────┼──────────────┼──────────────┼─────────┤
    │ Subjects with any AE │  xx (xx.x%)  │  xx (xx.x%)  │  ...    │  ← header row
    │ ≥1 SAE               │  xx (xx.x%)  │  ... ...     │  ...    │  ← header row
    ├──────────────────────┼──────────────┼──────────────┼─────────┤
    │ SOC Label            │              │              │         │  ← group2 stub
    │   PT Label           │  xx (xx.x%)  │  xx (xx.x%)  │  ...    │  ← data row
    │   PT Label           │  xx (xx.x%)  │  ...         │  ...    │
    │ SOC Label            │              │              │         │
    │   PT Label           │  xx (xx.x%)  │  ...         │  ...    │
    ├──────────────────────┴──────────────┴──────────────┴─────────┤
    │  Footnote 1                                                  │
    │  Footnote 2                                                  │
    └──────────────────────────────────────────────────────────────┘

**Listing layout:**

    ┌──────────┬───────────┬──────────┬──────────┐
    │  Title   │           │          │          │
    │  Subtitle│           │          │          │
    ├──────────┼───────────┼──────────┼──────────┤
    │ Subject  │ Treatment │ SOC      │ PT       │
    ├──────────┼───────────┼──────────┼──────────┤
    │ 01-001   │ Placebo   │ ...      │ ...      │
    │ 01-002   │ Drug A    │ ...      │ ...      │
    ├──────────┴───────────┴──────────┴──────────┤
    │  Footnote                                   │
    └─────────────────────────────────────────────┘

**Column roles** (ARD → display mapping):

  - ``group1_level``     → column headers (one column per arm)
  - Big-N (stat_name=N)  → appended to arm header as "(N=xx)"
  - ``variable``         → row type discriminator:
      - ``""`` + stat_name ``"N"``   → big-N (consumed into headers, not rendered as row)
      - ``""`` + other stat          → header row (no indent, label from variable_level)
      - non-empty                    → hierarchy row
  - ``variable_level``   → left-stub row label
  - ``stat_fmt`` / ``stat`` → cell values (formatted string preferred)

**Row types and indentation:**

  - ``header``: ``variable == ""`` — no indent, bold, optional separator above hierarchy
  - ``group``:  first ``rows`` field — level-0 indent, bold (SOC or PARAMCD)
  - ``data``:   second ``rows`` field — level-1 indent (PT or AVISIT)
  - ``flat``:   single ``rows`` field — level-0 indent, not bold

**Stat merging for display:**

  When ``n`` and ``pct`` stats exist for the same cell, they are merged into
  ``"n (xx.x%)"`` format.  Other stats occupy individual cells.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

# ------------------------------------------------------------------ #
# Phase 1 — Display contract models                                    #
# ------------------------------------------------------------------ #


@dataclass
class RenderMetadata:
    """Metadata for rendering a TLG output.

    Args:
        title: Table/listing title (e.g. "Table 14.3.1.1").
        subtitle: Subtitle line (e.g. "Summary of AEs — Safety Population").
        footnotes: List of footnote strings.
        page_by: Column to page-break on (future use).
        population: Population label (e.g. "Safety Population").
        datasource: Data source label (e.g. "ADAE").
    """

    title: str = ""
    subtitle: str = ""
    footnotes: list[str] = field(default_factory=list)
    page_by: str | None = None
    population: str = ""
    datasource: str = ""


@dataclass
class ColumnHeader:
    """A single column header in the display table.

    Args:
        label: Arm label (e.g. "Placebo").
        big_n: Subject count for denominator display.
    """

    label: str
    big_n: int | None = None

    @property
    def display(self) -> str:
        """Header text with optional (N=xx) suffix."""
        if self.big_n is not None:
            return f"{self.label}\n(N={self.big_n})"
        return self.label


@dataclass
class TableRow:
    """A single row in the display table.

    Args:
        label: Left-stub text.
        row_type: One of ``"header"``, ``"group"``, ``"data"``, ``"flat"``.
        indent: Indentation level (0, 1, 2).
        cells: Mapping from arm label → formatted cell string.
        bold: Whether the row label should be bold.
    """

    label: str
    row_type: str  # "header", "group", "data", "flat"
    indent: int = 0
    cells: dict[str, str] = field(default_factory=dict)
    bold: bool = False


@dataclass
class TableModel:
    """Display-ready wide-format table model.

    This is the intermediate representation between ARD and rendered output.
    Renderers (HTML, PDF, slides) consume this model — not the raw ARD.

    Args:
        metadata: Title, subtitle, footnotes, etc.
        columns: Ordered list of column headers.
        rows: Ordered list of table rows.
        stub_label: Label for the left-stub column (e.g. "" or "Term").
    """

    metadata: RenderMetadata
    columns: list[ColumnHeader]
    rows: list[TableRow]
    stub_label: str = ""


@dataclass
class ListingModel:
    """Display-ready listing model.

    Args:
        metadata: Title, subtitle, footnotes, etc.
        column_labels: Ordered column display labels.
        data: List of row dicts (label → value).
    """

    metadata: RenderMetadata
    column_labels: list[str]
    data: list[dict[str, str]]


# ------------------------------------------------------------------ #
# Phase 2 — ARD → TableModel shaping                                  #
# ------------------------------------------------------------------ #


def _merge_n_pct(n_val: str, pct_val: str) -> str:
    """Merge n and pct formatted values into ``"n (xx.x%)"`` string.

    Args:
        n_val: Formatted n count string.
        pct_val: Formatted percentage string.

    Returns:
        str: Merged display string, or just n if pct is empty/zero.
    """
    n_str = n_val.strip() if n_val else ""
    pct_str = pct_val.strip() if pct_val else ""

    if not n_str:
        return ""

    if not pct_str or pct_str == "0.0":
        return f"{n_str} (  0%)" if n_str != "0" else "0"

    return f"{n_str} ({pct_str}%)"


def ard_to_table_model(
    ard: pl.DataFrame,
    metadata: RenderMetadata | None = None,
) -> TableModel:
    """Shape a long-format ARD into a display-ready ``TableModel``.

    This is the core Phase 2 shaping function.  It:
    1. Extracts big-N from ``stat_name == "N"`` rows → column headers.
    2. Identifies header rows (``variable == ""``) → ``TableRow(row_type="header")``.
    3. Identifies hierarchy rows → ``"group"`` or ``"data"`` row types.
    4. Merges ``n`` + ``pct`` stats into single display cells.

    Args:
        ard: A {cards}-compatible ARD DataFrame.
        metadata: Optional render metadata.  If ``None``, a blank
            ``RenderMetadata`` is used.

    Returns:
        TableModel: A display-ready table model suitable for any renderer.
    """
    meta = metadata or RenderMetadata()

    # ── 1. Extract column order (arms) ──
    # Respect the order already present in the ARD (set by column_order in spec)
    arm_order: list[str] = []
    seen: set[str] = set()
    for val in ard["group1_level"].to_list():
        if val and val not in seen:
            arm_order.append(val)
            seen.add(val)

    # ── 2. Extract big-N for column headers ──
    big_n_rows = ard.filter((pl.col("stat_name") == "N") & (pl.col("variable") == ""))
    big_n_map: dict[str, int] = {}
    for row in big_n_rows.iter_rows(named=True):
        arm = row["group1_level"]
        val = row["stat"]
        if arm and val is not None:
            big_n_map[arm] = int(val)

    columns = [ColumnHeader(label=arm, big_n=big_n_map.get(arm)) for arm in arm_order]

    # ── 3. Get non-big-N rows ──
    data_rows = ard.filter(~((pl.col("stat_name") == "N") & (pl.col("variable") == "")))

    # ── 4. Determine row hierarchy structure ──
    # Unique (variable, variable_level) pairs in order
    row_keys: list[tuple[str, str]] = []
    row_keys_seen: set[tuple[str, str]] = set()
    for row in data_rows.iter_rows(named=True):
        key = (row["variable"], row["variable_level"])
        if key not in row_keys_seen:
            row_keys.append(key)
            row_keys_seen.add(key)

    # Determine which variables are "groups" (have children)
    all_variables = [k[0] for k in row_keys if k[0]]
    unique_variables = list(dict.fromkeys(all_variables))
    # If there are 2+ distinct non-empty variables, the first is group level
    has_hierarchy = len(unique_variables) >= 2

    # ── 5. Build display rows ──
    table_rows: list[TableRow] = []

    for variable, variable_level in row_keys:
        # Determine row type
        if variable == "":
            # Header row (OverallStat)
            row_type = "header"
            indent = 0
            bold = False
            label = variable_level
        elif has_hierarchy and variable == unique_variables[0]:
            # First variable = group level (SOC), show as group stub
            # Only emit group stub once per variable_level
            row_type = "group"
            indent = 0
            bold = True
            label = variable_level
        elif has_hierarchy:
            # Second+ variable = data level (PT), indented
            row_type = "data"
            indent = 1
            bold = False
            label = variable_level
        else:
            # Single variable = flat
            row_type = "flat"
            indent = 0
            bold = False
            label = variable_level

        # ── Collect cell values per arm ──
        cells: dict[str, str] = {}

        # Filter ARD to this (variable, variable_level)
        vl_rows = data_rows.filter(
            (pl.col("variable") == variable) & (pl.col("variable_level") == variable_level)
        )

        for arm in arm_order:
            arm_rows = vl_rows.filter(pl.col("group1_level") == arm)
            if arm_rows.is_empty():
                cells[arm] = ""
                continue

            # Collect stats for this cell
            stats: dict[str, str] = {}
            for sr in arm_rows.iter_rows(named=True):
                sname = sr["stat_name"]
                # Prefer stat_fmt, fall back to stat
                sfmt = sr.get("stat_fmt") or ""
                if not sfmt and sr["stat"] is not None:
                    sfmt = (
                        str(int(sr["stat"])) if sr["stat"] == int(sr["stat"]) else str(sr["stat"])
                    )
                stats[sname] = sfmt

            # Merge n + pct into single display string
            if "n" in stats and "pct" in stats:
                cells[arm] = _merge_n_pct(stats["n"], stats["pct"])
            elif "n" in stats:
                cells[arm] = stats["n"]
            elif "pct" in stats:
                cells[arm] = stats["pct"]
            elif "mean" in stats:
                # Continuous stats — show each on its own row
                # This path is for when we iterate per stat
                cells[arm] = stats.get("mean", "")
            else:
                # Single stat (n_events, or other)
                val = next(iter(stats.values()), "")
                cells[arm] = val

        # For group stubs in a hierarchy, don't show cells (empty row)
        if row_type == "group":
            cells = {arm: "" for arm in arm_order}

        table_rows.append(
            TableRow(
                label=label,
                row_type=row_type,
                indent=indent,
                cells=cells,
                bold=bold,
            )
        )

    return TableModel(metadata=meta, columns=columns, rows=table_rows)


def listing_to_model(
    listing: pl.DataFrame,
    metadata: RenderMetadata | None = None,
) -> ListingModel:
    """Shape a listing DataFrame into a display-ready ``ListingModel``.

    Args:
        listing: A Polars DataFrame from ``l_listing()``.
        metadata: Optional render metadata.

    Returns:
        ListingModel: A display-ready listing model.
    """
    meta = metadata or RenderMetadata()
    col_labels = list(listing.columns)

    data: list[dict[str, str]] = []
    for row in listing.iter_rows(named=True):
        data.append({col: str(v) if v is not None else "" for col, v in row.items()})

    return ListingModel(metadata=meta, column_labels=col_labels, data=data)
