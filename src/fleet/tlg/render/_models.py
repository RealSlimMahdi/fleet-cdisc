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

  - ``header``:  ``variable == ""`` — no indent, bold, optional separator above hierarchy
  - ``group``:   parent stub row — level-0 indent, bold (SOC or PARAMCD)
  - ``section``: variable-label heading above a flat block — level-0 indent, bold
  - ``data``:    level row under a group/section — level-1 indent
  - ``flat``:    level row without a section — level-0 indent, not bold
  - ``stat``:    one statistic of a continuous level — one deeper than its level row

**Stat handling for display:**

  - Count cells: ``n`` and ``pct`` merge into ``"n (xx.x%)"``; a nonzero
    percentage that would display as zero renders ``"n (<0.1%)"``.
  - Continuous cells (any stat beyond N/n/pct/n_events): the level
    becomes a stub row and every statistic gets its own display row
    (label from ``stat_label``, order following the ARD) — the
    universal pharma layout for VS/LB/EG summaries.
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
        page_by: ARD variable to page-break on (e.g. ``"PARAMCD"``) —
            honoured by :func:`paginate` and every renderer.
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
        row_type: One of ``"header"``, ``"group"``, ``"section"``,
            ``"data"``, ``"flat"``, ``"stat"``.
        indent: Indentation level (0, 1, 2).
        cells: Mapping from arm label → formatted cell string.
        bold: Whether the row label should be bold.
        variable: Source ARD variable this row belongs to (used by
            :func:`paginate` to honour ``page_by``).
    """

    label: str
    row_type: str  # "header", "group", "section", "data", "flat", "stat"
    indent: int = 0
    cells: dict[str, str] = field(default_factory=dict)
    bold: bool = False
    variable: str = ""


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


def _sub_threshold(pct_str: str) -> str:
    """``"<0.1"``-style display for a formatted percentage of zero.

    The threshold matches the display precision: ``"0.0"`` → ``"<0.1"``,
    ``"0.00"`` → ``"<0.01"``, ``"0"`` → ``"<1"``.
    """
    decimals = len(pct_str.split(".")[1]) if "." in pct_str else 0
    return f"<{10**-decimals:.{decimals}f}" if decimals else "<1"


def _formats_to_zero(pct_str: str) -> bool:
    """Whether a formatted percentage string displays as zero."""
    try:
        return float(pct_str) == 0.0
    except ValueError:
        return False


def _merge_n_pct(n_val: str, pct_val: str) -> str:
    """Merge n and pct formatted values into ``"n (xx.x%)"`` string.

    A missing percentage (no denominator) shows the count alone — never
    a fabricated ``0%``.  A nonzero count whose percentage displays as
    zero renders the sub-threshold form ``"n (<0.1%)"``.

    Args:
        n_val: Formatted n count string.
        pct_val: Formatted percentage string.

    Returns:
        str: Merged display string.
    """
    n_str = n_val.strip() if n_val else ""
    pct_str = pct_val.strip() if pct_val else ""

    if not n_str:
        return ""
    if n_str == "0":
        return "0"
    if not pct_str:
        return n_str
    if _formats_to_zero(pct_str):
        # n > 0 with a computed denominator ⇒ the true pct is > 0; it
        # merely rounds below the display precision.
        return f"{n_str} ({_sub_threshold(pct_str)}%)"
    return f"{n_str} ({pct_str}%)"


def _pct_display(pct_str: str, pct_raw: float | None) -> str:
    """Standalone percentage display, identical in behaviour to merged cells."""
    if not pct_str:
        return ""
    if pct_raw is not None and pct_raw > 0 and _formats_to_zero(pct_str):
        return f"{_sub_threshold(pct_str)}%"
    return f"{pct_str}%"


#: Count-type stat names — everything else is a continuous statistic.
_COUNT_STAT_NAMES = frozenset({"N", "n", "pct", "n_events"})

#: Display-row identity: (group2, group2_level, variable, variable_level).
_RowKey = tuple[str, str, str, str]


def _collect_cell_stats(
    vl_rows: pl.DataFrame,
    arm_order: list[str],
) -> tuple[list[str], dict[str, str], dict[str, dict[str, tuple[str, float | None]]]]:
    """Per-arm statistics for one display key.

    Returns:
        Tuple of (stat order, stat_name → stat_label, arm → stat_name →
        (formatted string, raw value)).
    """
    stat_order: list[str] = []
    stat_labels: dict[str, str] = {}
    per_arm: dict[str, dict[str, tuple[str, float | None]]] = {arm: {} for arm in arm_order}
    for sr in vl_rows.iter_rows(named=True):
        sname = sr["stat_name"]
        if sname not in stat_labels:
            stat_order.append(sname)
            stat_labels[sname] = sr["stat_label"] or sname
        arm = sr["group1_level"]
        if arm not in per_arm:
            continue
        # Prefer stat_fmt, fall back to stat
        sfmt = sr.get("stat_fmt") or ""
        if not sfmt and sr["stat"] is not None:
            sfmt = str(int(sr["stat"])) if sr["stat"] == int(sr["stat"]) else str(sr["stat"])
        per_arm[arm][sname] = (sfmt, sr["stat"])
    return stat_order, stat_labels, per_arm


def _merged_cells(
    arm_order: list[str],
    per_arm: dict[str, dict[str, tuple[str, float | None]]],
) -> dict[str, str]:
    """One display string per arm for a count-type key (n/pct merge)."""
    cells: dict[str, str] = {}
    for arm in arm_order:
        stats = per_arm.get(arm, {})
        if not stats:
            cells[arm] = ""
        elif "n" in stats and "pct" in stats:
            cells[arm] = _merge_n_pct(stats["n"][0], stats["pct"][0])
        elif "n" in stats:
            cells[arm] = stats["n"][0]
        elif "pct" in stats:
            cells[arm] = _pct_display(*stats["pct"])
        else:
            cells[arm] = next(iter(stats.values()), ("", None))[0]
    return cells


def _stat_rows(
    stat_order: list[str],
    stat_labels: dict[str, str],
    arm_order: list[str],
    per_arm: dict[str, dict[str, tuple[str, float | None]]],
    *,
    indent: int,
    variable: str,
) -> list[TableRow]:
    """One display row per statistic — the continuous-cell layout.

    ``n`` and ``pct`` still merge into a single ``"n (%)"`` row; every
    other statistic gets its own row labelled from ``stat_label``, in
    the ARD's statistic order.
    """
    rows: list[TableRow] = []
    merge_n_pct = "n" in stat_order and "pct" in stat_order
    for sname in stat_order:
        if merge_n_pct and sname == "pct":
            continue  # consumed into the "n (%)" row
        if merge_n_pct and sname == "n":
            label = stat_labels.get("pct", "n (%)")
            cells = {
                arm: _merge_n_pct(
                    per_arm.get(arm, {}).get("n", ("", None))[0],
                    per_arm.get(arm, {}).get("pct", ("", None))[0],
                )
                for arm in arm_order
            }
        else:
            label = stat_labels[sname]
            cells = {arm: per_arm.get(arm, {}).get(sname, ("", None))[0] for arm in arm_order}
            if sname == "pct":
                cells = {
                    arm: _pct_display(*per_arm.get(arm, {}).get(sname, ("", None)))
                    for arm in arm_order
                }
        rows.append(
            TableRow(
                label=label,
                row_type="stat",
                indent=indent,
                cells=cells,
                variable=variable,
            )
        )
    return rows


def _ordered_display_keys(row_keys: list[_RowKey]) -> list[_RowKey]:
    """Group children directly under their parent stub, preserving order.

    Nested ARDs emit all parent rows first and all child rows after —
    for display each parent must be followed by its own children.
    """
    variable_set = {k[2] for k in row_keys}
    consumed: set[_RowKey] = set()
    ordered: list[_RowKey] = []

    def _children_of(parent_var: str, parent_level: str) -> list[_RowKey]:
        return [k for k in row_keys if k[0] == parent_var and k[1] == parent_level]

    for key in row_keys:
        if key in consumed:
            continue
        g2, _g2l, variable, variable_level = key
        if not g2 and variable in {k[0] for k in row_keys if k[0]}:
            # Explicit parent stub: emit it, then its children.
            ordered.append(key)
            consumed.add(key)
            for child in _children_of(variable, variable_level):
                ordered.append(child)
                consumed.add(child)
        elif g2 and g2 not in variable_set:
            # Child without explicit parent rows (synthetic parent):
            # keep all children of the same parent level together.
            for child in _children_of(g2, _g2l):
                if child not in consumed:
                    ordered.append(child)
                    consumed.add(child)
        else:
            ordered.append(key)
            consumed.add(key)
    return ordered


def ard_to_table_model(
    ard: pl.DataFrame,
    metadata: RenderMetadata | None = None,
) -> TableModel:
    """Shape a long-format ARD into a display-ready ``TableModel``.

    This is the core Phase 2 shaping function.  It:
    1. Extracts big-N from ``stat_name == "N"`` rows → column headers.
    2. Identifies header rows (``variable == ""``) → ``TableRow(row_type="header")``.
    3. Emits parent stubs (``"group"``), flat-block headings
       (``"section"`` from ``variable_label``), and level rows.
    4. Merges ``n`` + ``pct`` count stats into single display cells;
       expands continuous statistics into one display row per statistic
       under the level stub (the universal pharma layout).

    Args:
        ard: A {cards}-compatible ARD DataFrame.
        metadata: Optional render metadata.  If ``None``, a blank
            ``RenderMetadata`` is used.

    Returns:
        TableModel: A display-ready table model suitable for any renderer.

    Examples:
        Shape an ARD for rendering::

            ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
            model = ard_to_table_model(ard, RenderMetadata(title="Table 14.3.1.1"))
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

    # ── 4. Display-row identity in appearance order ──
    # Nested ARDs emit the same child level once per parent, so the
    # parent lineage must be part of the display-row identity or cells
    # from different parents collapse into one row (last-write-wins).
    row_keys: list[_RowKey] = []
    row_keys_seen: set[_RowKey] = set()
    var_labels: dict[str, str] = {}
    has_var_label = "variable_label" in ard.columns
    for row in data_rows.iter_rows(named=True):
        key = (
            row.get("group2") or "",
            row.get("group2_level") or "",
            row["variable"],
            row["variable_level"],
        )
        if key not in row_keys_seen:
            row_keys.append(key)
            row_keys_seen.add(key)
        if has_var_label and row["variable"] not in var_labels:
            var_labels[row["variable"]] = row.get("variable_label") or ""

    variable_set = {k[2] for k in row_keys}
    parent_vars = {k[0] for k in row_keys if k[0]}
    explicit_parents = parent_vars & variable_set

    # Stub column heading: the top-level hierarchy variable's label.
    stub_label = ""
    for k in row_keys:
        if not k[0] and k[2] in explicit_parents:
            stub_label = var_labels.get(k[2], "")
            break

    # ── 5. Build display rows ──
    table_rows: list[TableRow] = []
    current_section: str | None = None
    current_synth_parent: tuple[str, str] | None = None

    for g2, g2l, variable, variable_level in _ordered_display_keys(row_keys):
        vl_rows = data_rows.filter(
            (pl.col("group2").fill_null("") == g2)
            & (pl.col("group2_level").fill_null("") == g2l)
            & (pl.col("variable") == variable)
            & (pl.col("variable_level") == variable_level)
        )
        stat_order, stat_labels, per_arm = _collect_cell_stats(vl_rows, arm_order)
        continuous = any(s not in _COUNT_STAT_NAMES for s in stat_order)
        empty_cells = {arm: "" for arm in arm_order}

        # ── Structure: header / group stub / synthetic parent / section ──
        if variable == "":
            # Header row (OverallStat)
            current_section = None
            current_synth_parent = None
            row_type, indent, bold = "header", 0, False
        elif variable in explicit_parents and not g2:
            # Parent stub row (SOC / PARAMCD): label only, no cells.
            current_section = None
            current_synth_parent = None
            table_rows.append(
                TableRow(
                    label=variable_level,
                    row_type="group",
                    indent=0,
                    cells=dict(empty_cells),
                    bold=True,
                    variable=variable,
                )
            )
            continue
        elif g2:
            # Child level inside a hierarchy.
            current_section = None
            if g2 not in explicit_parents:
                # No explicit parent rows — synthesise the stub from the
                # parent level so children don't float unanchored.
                if current_synth_parent != (g2, g2l):
                    table_rows.append(
                        TableRow(
                            label=g2l,
                            row_type="group",
                            indent=0,
                            cells=dict(empty_cells),
                            bold=True,
                            variable=g2,
                        )
                    )
                    current_synth_parent = (g2, g2l)
            else:
                current_synth_parent = None
            row_type, indent, bold = "data", 1, False
        else:
            # Flat block — emit the variable label as a section heading.
            current_synth_parent = None
            section_label = var_labels.get(variable, "")
            if section_label:
                if current_section != variable:
                    table_rows.append(
                        TableRow(
                            label=section_label,
                            row_type="section",
                            indent=0,
                            cells=dict(empty_cells),
                            bold=True,
                            variable=variable,
                        )
                    )
                    current_section = variable
                row_type, indent, bold = "data", 1, False
            else:
                current_section = None
                row_type, indent, bold = "flat", 0, False

        # ── Cells: merged count cell, or one row per statistic ──
        if continuous:
            table_rows.append(
                TableRow(
                    label=variable_level,
                    row_type=row_type,
                    indent=indent,
                    cells=dict(empty_cells),
                    bold=bold,
                    variable=variable,
                )
            )
            table_rows += _stat_rows(
                stat_order,
                stat_labels,
                arm_order,
                per_arm,
                indent=indent + 1,
                variable=variable,
            )
        else:
            table_rows.append(
                TableRow(
                    label=variable_level,
                    row_type=row_type,
                    indent=indent,
                    cells=_merged_cells(arm_order, per_arm),
                    bold=bold,
                    variable=variable,
                )
            )

    return TableModel(metadata=meta, columns=columns, rows=table_rows, stub_label=stub_label)


# ------------------------------------------------------------------ #
# Pagination — model layer, inherited by every renderer                 #
# ------------------------------------------------------------------ #


def _is_stub_only(row: TableRow) -> bool:
    """Whether a row carries no cell values (pure stub / heading row)."""
    return all(v == "" for v in row.cells.values())


def _chunk_rows(rows: list[TableRow], rows_per_page: int) -> list[list[TableRow]]:
    """Split *rows* into chunks, never orphaning a stub row at a page end."""
    chunks: list[list[TableRow]] = []
    chunk: list[TableRow] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= rows_per_page:
            carried: list[TableRow] = []
            while chunk and _is_stub_only(chunk[-1]):
                carried.append(chunk.pop())
            if not chunk:
                # A page of nothing but stubs — keep it whole rather
                # than looping forever.
                chunk = list(reversed(carried))
                carried = []
            chunks.append(chunk)
            chunk = list(reversed(carried))
    if chunk:
        chunks.append(chunk)
    return chunks


def paginate(
    model: TableModel,
    *,
    rows_per_page: int | None = None,
    page_by: str | None = None,
) -> list[TableModel]:
    """Split a ``TableModel`` into display pages.

    Pagination lives in the model layer so every renderer (HTML, PDF,
    RTF, PPTX) inherits identical page composition: each page repeats
    the title, subtitle, column headers, and footnote blocks.

    Args:
        model: The display-ready table model.
        rows_per_page: Maximum body rows per page.  A stub-only row
            (group/section heading) is never left orphaned at the bottom
            of a page.  ``None`` means no row-count splitting.
        page_by: ARD variable whose stub rows force a page break (e.g.
            ``"PARAMCD"`` → one page per parameter).  Defaults to
            ``model.metadata.page_by``.

    Returns:
        list[TableModel]: One model per page (a single-element list when
        no pagination applies).

    Examples:
        One page per lab parameter, at most 20 rows each::

            from fleet.tlg.render import ard_to_table_model, paginate

            model = ard_to_table_model(ard)
            pages = paginate(model, rows_per_page=20, page_by="PARAMCD")
    """
    effective_page_by = page_by or model.metadata.page_by
    if rows_per_page is None and not effective_page_by:
        return [model]

    # ── 1. Split into blocks at page_by stub boundaries ──
    blocks: list[list[TableRow]] = [[]]
    for row in model.rows:
        if (
            effective_page_by
            and row.variable == effective_page_by
            and row.row_type in ("group", "section")
            and blocks[-1]
        ):
            blocks.append([])
        blocks[-1].append(row)

    # ── 2. Split blocks by row count ──
    pages_rows: list[list[TableRow]] = []
    for block in blocks:
        if not block:
            continue
        if rows_per_page is None:
            pages_rows.append(block)
        else:
            pages_rows.extend(_chunk_rows(block, rows_per_page))

    if not pages_rows:
        return [model]
    return [
        TableModel(
            metadata=model.metadata,
            columns=model.columns,
            rows=rows,
            stub_label=model.stub_label,
        )
        for rows in pages_rows
    ]


def paginate_listing(
    model: ListingModel,
    *,
    rows_per_page: int | None = None,
) -> list[ListingModel]:
    """Split a ``ListingModel`` into display pages of *rows_per_page* rows.

    Args:
        model: The display-ready listing model.
        rows_per_page: Maximum data rows per page; ``None`` disables
            splitting.

    Returns:
        list[ListingModel]: One model per page.

    Examples:
        Split a long listing into 40-row pages::

            pages = paginate_listing(model, rows_per_page=40)
    """
    if rows_per_page is None or len(model.data) <= rows_per_page:
        return [model]
    return [
        ListingModel(
            metadata=model.metadata,
            column_labels=model.column_labels,
            data=model.data[i : i + rows_per_page],
        )
        for i in range(0, len(model.data), rows_per_page)
    ]


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

    Examples:
        Shape a listing for rendering::

            listing = adae.tlg.ae.template("ael01").to_listing()
            model = listing_to_model(listing, RenderMetadata(title="Listing 16.2.7"))
    """
    meta = metadata or RenderMetadata()
    col_labels = list(listing.columns)

    data: list[dict[str, str]] = []
    for row in listing.iter_rows(named=True):
        data.append({col: str(v) if v is not None else "" for col, v in row.items()})

    return ListingModel(metadata=meta, column_labels=col_labels, data=data)
