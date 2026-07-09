"""
Static TLG explorer — the whole declared variant space in one HTML file.

``render_explorer`` runs every variant of every entry through the *same*
engine path as the batch run (``run_spec`` → ``ard_to_table_model`` →
``render_html``) and embeds the pre-rendered fragments into one
self-contained page.  The embedded JavaScript only toggles visibility of
those fragments — no statistic or layout logic exists client-side, so
the interactive view cannot drift from the submission output (the
default variant *is* the batch output, byte for byte).

No server, no dependency, no external request: the file works from a
shared drive, SharePoint, or an e-mail attachment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.core.exceptions import SchemaError

from .._registry import TEMPLATES, OutputType
from .._runner import run_spec
from .._variants import Variant, enumerate_variants
from ._models import RenderMetadata, ard_to_table_model, listing_to_model
from .html import _esc, render_html, render_listing_html

if TYPE_CHECKING:
    from collections.abc import Sequence

    import polars as pl

    from .._specs import TLGSpec

#: Axis key → widget legend shown in the explorer.
_AXIS_LEGENDS = {
    "groupby": "Group by",
    "population": "Population",
    "dataset_filter": "Dataset filter",
    "stats": "Statistics",
}

#: Page chrome only — table styling ships inside each embedded fragment
#: (``_SUMMARY_CSS``), untouched, to keep fragments byte-identical to
#: the batch renderer's output.
_EXPLORER_CSS = """\
<style>
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
       margin: 0; background: #fafafa; color: #111; }
.fleet-explorer-header { background: #1a1a2e; color: #fff; padding: 10px 20px; }
.fleet-explorer-header h1 { font-size: 15px; margin: 0 0 4px; font-weight: 600; }
.fleet-explorer-header .fleet-tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.fleet-tab { background: transparent; color: #ccc; border: 1px solid #555;
             border-radius: 4px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
.fleet-tab.active { background: #fff; color: #1a1a2e; border-color: #fff; }
main { max-width: 1100px; margin: 0 auto; padding: 16px 20px; }
.fleet-axes { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.fleet-axes fieldset { border: 1px solid #ccc; border-radius: 6px; margin: 0;
                       padding: 6px 10px 8px; background: #fff; }
.fleet-axes legend { font-size: 11px; text-transform: uppercase; color: #666;
                     padding: 0 4px; letter-spacing: 0.04em; }
.fleet-axes label { font-size: 13px; margin-right: 10px; cursor: pointer;
                    white-space: nowrap; }
.fleet-variant { background: #fff; border: 1px solid #ddd; border-radius: 6px;
                 padding: 14px 16px; }
.fleet-variant-tools { margin-top: 12px; border-top: 1px dashed #ccc;
                       padding-top: 8px; font-size: 12px; }
.fleet-variant-tools details { margin-top: 6px; }
.fleet-variant-tools summary { cursor: pointer; color: #1a5276; }
.fleet-variant-tools pre { background: #f4f4f4; border: 1px solid #ddd;
                           border-radius: 4px; padding: 8px; overflow-x: auto;
                           font-size: 11px; }
.fleet-dl { background: #1a5276; color: #fff; border: none; border-radius: 4px;
            padding: 4px 10px; font-size: 12px; cursor: pointer; }
.fleet-default-badge { display: inline-block; background: #eaf3ea; color: #1e6b1e;
                       border: 1px solid #bcd9bc; border-radius: 4px;
                       font-size: 11px; padding: 1px 6px; margin-left: 8px; }
@media print { .fleet-explorer-header, .fleet-axes, .fleet-variant-tools { display: none; } }
</style>"""

# The only client-side behaviour: show/hide pre-rendered fragments and
# download embedded ARD JSON.  Anything smarter than visibility here
# would be a second table engine — the exact disease this design cures.
_EXPLORER_JS = """\
<script>
(function () {
  "use strict";
  function syncEntry(entry) {
    var sel = {};
    document
      .querySelectorAll('.fleet-axes[data-entry="' + entry + '"] input:checked')
      .forEach(function (inp) { sel[inp.dataset.axis] = inp.value; });
    document
      .querySelectorAll('.fleet-variant[data-entry="' + entry + '"]')
      .forEach(function (sec) {
        var show = true;
        for (var axis in sel) {
          if (sec.dataset[axis] !== sel[axis]) { show = false; break; }
        }
        sec.hidden = !show;
      });
  }
  document.addEventListener("change", function (ev) {
    var form = ev.target.closest(".fleet-axes");
    if (form) { syncEntry(form.dataset.entry); }
  });
  document.querySelectorAll(".fleet-tab").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".fleet-tab").forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });
      document.querySelectorAll(".fleet-entry").forEach(function (sec) {
        sec.hidden = sec.dataset.entry !== btn.dataset.entry;
      });
    });
  });
  document.querySelectorAll(".fleet-dl").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var payload = document.getElementById(btn.dataset.target).textContent;
      var url = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
      var a = document.createElement("a");
      a.href = url;
      a.download = btn.dataset.filename;
      a.click();
      URL.revokeObjectURL(url);
    });
  });
})();
</script>"""


@dataclass
class ExplorerEntry:
    """One spec (and its data wiring) to include in the explorer.

    Args:
        name: Short identifier — tab label, element-id base, and ARD
            download filename stem (typically the spec file stem).
        spec: A template-carrying spec, with or without an
            ``interactive:`` block.
        df: The primary analysis dataset (e.g. ADAE for ``aet01``).
        adsl: ADSL population for big-N denominators (tables).
        groupby: Treatment-arm column used when the spec declares *no*
            ``groupby`` axis; ignored otherwise (the variant's own
            ``columns`` choice wins, exactly as in the batch run).
        metadata: Render metadata (title/subtitle/footnotes) applied to
            every variant.  Defaults to the template's registry title.
    """

    name: str
    spec: TLGSpec
    df: pl.DataFrame
    adsl: pl.DataFrame | None = None
    groupby: str | None = None
    metadata: RenderMetadata | None = None


def _slug(text: str) -> str:
    """Reduce *text* to an HTML id/name-safe token."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text)


def _variant_fragment(
    entry: ExplorerEntry, variant: Variant, *, is_listing: bool
) -> tuple[str, pl.DataFrame]:
    """Run one variant through the batch engine path and render its fragment."""
    groupby = None
    block = entry.spec.interactive
    if block is None or block.groupby is None:
        groupby = entry.groupby
    result = run_spec(variant.spec, entry.df, adsl=entry.adsl, groupby=groupby)
    meta = entry.metadata or RenderMetadata(title=TEMPLATES[entry.spec.template].title)
    if is_listing:
        return render_listing_html(listing_to_model(result, meta)), result
    return render_html(ard_to_table_model(result, meta)), result


def _variant_section(
    entry_id: str,
    entry_name: str,
    variant: Variant,
    fragment: str,
    ard_json: str,
    axis_order: list[str],
) -> str:
    """The container for one pre-rendered variant: fragment + QC tools."""
    vid = f"{entry_id}-{variant.variant_id}"
    sel_attrs = "".join(
        f' data-a{i}="{_esc(variant.axis_labels[axis])}"'
        for i, axis in enumerate(axis_order)
        if axis in variant.axis_labels
    )
    hidden = "" if variant.is_default else " hidden"
    badge = (
        '<span class="fleet-default-badge">default — batch output</span>'
        if variant.is_default and variant.axis_labels
        else ""
    )
    # `</` must not terminate the embedding <script>; < is a legal
    # JSON escape and JSON text carries "<" only inside strings.
    safe_json = ard_json.replace("<", "\\u003c")
    return "\n".join(
        [
            f'<div class="fleet-variant" data-entry="{entry_id}"{sel_attrs} id="var-{vid}"{hidden}>',
            fragment,
            '<div class="fleet-variant-tools">',
            f'<button class="fleet-dl" data-target="ard-{vid}" '
            f'data-filename="{_esc(entry_name)}_{variant.variant_id}_ard.json">'
            f"Download ARD (JSON)</button>{badge}",
            "<details><summary>Show definition (spec YAML)</summary>",
            f"<pre>{_esc(variant.spec.to_yaml())}</pre></details>",
            f'<script type="application/json" id="ard-{vid}">{safe_json}</script>',
            "</div>",
            "</div>",
        ]
    )


def _widget_bar(entry_id: str, variants: list[Variant], spec: TLGSpec) -> str:
    """Radio-group fieldsets for the entry's declared axes."""
    block = spec.interactive
    if block is None:
        return ""
    default_labels = variants[0].axis_labels
    parts = [f'<form class="fleet-axes" data-entry="{entry_id}">']
    axis_index = 0
    for axis in _AXIS_LEGENDS:
        axis_value = getattr(block, axis)
        if axis_value is None:
            continue
        labels = list(axis_value.choices) if axis == "groupby" else [o.label for o in axis_value]
        parts.append(f"<fieldset><legend>{_esc(_AXIS_LEGENDS[axis])}</legend>")
        for label in labels:
            checked = " checked" if label == default_labels[axis] else ""
            parts.append(
                f'<label><input type="radio" name="{entry_id}-a{axis_index}" '
                f'data-axis="a{axis_index}" value="{_esc(label)}"{checked}> '
                f"{_esc(label)}</label>"
            )
        parts.append("</fieldset>")
        axis_index += 1
    parts.append("</form>")
    return "\n".join(parts)


def render_explorer(
    entries: Sequence[ExplorerEntry],
    path: str | Path | None = None,
) -> str:
    """Render the declared variant space of one or more specs to HTML.

    For every entry, enumerates its ``interactive:`` variants
    ([`enumerate_variants`][fleet.tlg._variants.enumerate_variants]),
    runs each through the identical engine path used by ``fleet tlg
    run`` (``run_spec`` → ``ard_to_table_model`` → ``render_html``), and
    embeds the pre-rendered fragments — plus each variant's ARD as
    downloadable JSON and its exact spec YAML in a "show definition"
    panel — into one self-contained HTML file.  The client-side script
    only toggles fragment visibility.

    Args:
        entries: One :class:`ExplorerEntry` per spec.
        path: Optional output file path; the HTML is also returned.

    Returns:
        str: The complete explorer HTML document.

    Raises:
        SchemaError: If a spec has no template id, or its variant space
            exceeds the hard cap (500).

    Examples:
        Build a two-axis AE overview explorer::

            import fleet.tlg as tlg
            from fleet.tlg.render.explorer import ExplorerEntry, render_explorer

            spec = tlg.load_spec("specs/aet01.yaml")
            render_explorer(
                [ExplorerEntry(name="aet01", spec=spec, df=adae, adsl=adsl)],
                path="explorer.html",
            )
    """
    body: list[str] = []
    tabs: list[str] = []
    seen_ids: set[str] = set()

    for idx, entry in enumerate(entries):
        entry_id = _slug(entry.name)
        if entry_id in seen_ids:
            entry_id = f"{entry_id}-{idx}"
        seen_ids.add(entry_id)
        if entry.spec.template is None or entry.spec.template not in TEMPLATES:
            raise SchemaError(
                f"Explorer entry {entry.name!r}: spec needs a registered "
                f"'template:' id to dispatch through run_spec(). Known ids: "
                f"{sorted(TEMPLATES)}"
            )
        meta = TEMPLATES[entry.spec.template]
        is_listing = meta.output_type is OutputType.LISTING
        variants = enumerate_variants(entry.spec)
        axis_order = list(variants[0].axis_labels)

        hidden = "" if idx == 0 else " hidden"
        body.append(f'<section class="fleet-entry" data-entry="{entry_id}"{hidden}>')
        body.append(_widget_bar(entry_id, variants, entry.spec))
        for variant in variants:
            fragment, result = _variant_fragment(entry, variant, is_listing=is_listing)
            body.append(
                _variant_section(
                    entry_id, entry.name, variant, fragment, result.write_json(), axis_order
                )
            )
        body.append("</section>")
        active = " active" if idx == 0 else ""
        tabs.append(
            f'<button class="fleet-tab{active}" data-entry="{entry_id}">{_esc(entry.name)}</button>'
        )

    tab_bar = f'<nav class="fleet-tabs">{"".join(tabs)}</nav>' if len(entries) > 1 else ""
    html = "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="en">',
            '<head><meta charset="utf-8">',
            "<title>Fleet TLG Explorer</title>",
            _EXPLORER_CSS,
            "</head>",
            "<body>",
            f'<header class="fleet-explorer-header"><h1>Fleet TLG Explorer</h1>{tab_bar}</header>',
            "<main>",
            *body,
            "</main>",
            _EXPLORER_JS,
            "</body>",
            "</html>",
        ]
    )
    if path is not None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
    return html
