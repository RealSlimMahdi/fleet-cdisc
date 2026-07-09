"""Interactive explorer tests (DX-review §8): declared degrees of freedom,
variant enumeration, and the anti-drift golden.

The core guarantee under test: the explorer's default-variant fragment is
byte-identical to the table HTML the batch path (``run_spec`` →
``ard_to_table_model`` → ``render_html``) produces for the same spec and
data — same functions, same build, no second body of table logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest
import yaml
from pydantic import ValidationError

import fleet  # noqa: F401 — registers df.tlg
from fleet.core.exceptions import SchemaError
from fleet.tlg import (
    AEListingSpec,
    ChoiceOption,
    InteractiveBlock,
    RenderMetadata,
    ard_to_table_model,
    enumerate_variants,
    load_spec,
    render_html,
    run_spec,
)
from fleet.tlg.ae_namespace import AEOverviewSpec
from fleet.tlg.render.explorer import ExplorerEntry, render_explorer

sys.path.insert(0, str(Path(__file__).parent.parent))
from fixtures.study import ADAE, ADSL  # noqa: E402

SPEC_DIR = Path(__file__).parent.parent.parent / "examples" / "tlg_specs"

#: Four-axis spec over the frozen fixture study (2*2*2*2 = 16 variants).
#: The dataset_filter default is deliberately listed SECOND to pin
#: default-first reordering.
_FOUR_AXIS_YAML = """\
template: aet01
adsl_filter: 'pl.col("SAFFL") == "Y"'
header_rows:
  - label: Subjects with at least one adverse event
  - label: Subjects with at least one serious adverse event
    filter: 'pl.col("AESER") == "Y"'
rows: []
statistics: [n_subjects, n_pct]
interactive:
  groupby: {choices: [TRTA, TRT01P], default: TRTA}
  population:
    - {label: Safety, filter: 'pl.col("SAFFL") == "Y"', default: true}
    - {label: All subjects, filter: null}
  dataset_filter:
    - {label: Serious only, filter: 'pl.col("AESER") == "Y"'}
    - {label: All AEs, filter: null, default: true}
  stats:
    - {label: "n (%)", statistics: [n_subjects, n_pct], default: true}
    - {label: "+ events", statistics: [n_subjects, n_pct, n_events]}
"""


def _four_axis_spec() -> AEOverviewSpec:
    return AEOverviewSpec.model_validate(yaml.safe_load(_FOUR_AXIS_YAML))


def _options(n: int) -> list[ChoiceOption]:
    return [ChoiceOption(label=f"o{i}", default=(i == 0)) for i in range(n)]


# ================================================================== #
# Variant enumeration                                                  #
# ================================================================== #


class TestEnumerateVariants:
    def test_cartesian_count_and_unique_ids(self) -> None:
        variants = enumerate_variants(_four_axis_spec())
        assert len(variants) == 16
        assert len({v.variant_id for v in variants}) == 16

    def test_all_defaults_combination_is_first_and_flagged(self) -> None:
        variants = enumerate_variants(_four_axis_spec())
        assert variants[0].is_default
        # 'All AEs' is the default despite being listed second in YAML.
        assert variants[0].axis_labels == {
            "groupby": "TRTA",
            "population": "Safety",
            "dataset_filter": "All AEs",
            "stats": "n (%)",
        }
        assert not any(v.is_default for v in variants[1:])

    def test_default_variant_spec_equals_base_spec(self) -> None:
        """The all-defaults variant IS the batch spec — field for field."""
        spec = _four_axis_spec()
        default = enumerate_variants(spec)[0].spec
        assert default.model_dump() == spec.model_dump()

    def test_variant_specs_carry_the_choice(self) -> None:
        spec = _four_axis_spec()
        by_labels = {tuple(v.axis_labels.values()): v.spec for v in enumerate_variants(spec)}
        serious = by_labels[("TRT01P", "All subjects", "Serious only", "+ events")]
        assert serious.columns == ["TRT01P"]
        assert serious.adsl_filter is None
        assert serious.dataset_filter == 'pl.col("AESER") == "Y"'
        assert [s.value for s in serious.statistics] == ["n_subjects", "n_pct", "n_events"]

    def test_no_interactive_block_yields_single_default(self) -> None:
        spec = AEOverviewSpec()
        variants = enumerate_variants(spec)
        assert len(variants) == 1
        assert variants[0].is_default
        assert variants[0].axis_labels == {}
        assert variants[0].spec is spec

    def test_hard_cap_raises(self) -> None:
        spec = AEOverviewSpec(interactive=InteractiveBlock(dataset_filter=_options(501)))
        with pytest.raises(SchemaError, match="500"):
            enumerate_variants(spec)

    def test_soft_cap_warns(self) -> None:
        spec = AEOverviewSpec(interactive=InteractiveBlock(dataset_filter=_options(101)))
        with pytest.warns(UserWarning, match="101 variants"):
            variants = enumerate_variants(spec)
        assert len(variants) == 101


# ================================================================== #
# interactive: block validation                                        #
# ================================================================== #


class TestInteractiveValidation:
    def test_two_defaults_rejected(self) -> None:
        opts = [ChoiceOption(label="a", default=True), ChoiceOption(label="b", default=True)]
        with pytest.raises(ValidationError, match="exactly one option"):
            InteractiveBlock(population=opts)

    def test_zero_defaults_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly one option"):
            InteractiveBlock(population=[ChoiceOption(label="a"), ChoiceOption(label="b")])

    def test_groupby_default_must_be_a_choice(self) -> None:
        with pytest.raises(ValidationError, match="not in choices"):
            InteractiveBlock(groupby={"choices": ["TRTA"], "default": "TRT01A"})

    def test_stats_options_need_statistics(self) -> None:
        with pytest.raises(ValidationError, match="statistics"):
            InteractiveBlock(stats=[ChoiceOption(label="bare", default=True)])

    def test_bad_stat_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChoiceOption(label="x", statistics=["not_a_stat"], default=True)

    def test_bad_filter_string_names_field(self) -> None:
        with pytest.raises(ValidationError, match="filter"):
            ChoiceOption(label="x", filter="import os")

    def test_empty_block_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one axis"):
            InteractiveBlock()

    def test_population_axis_on_listing_rejected(self) -> None:
        with pytest.raises(ValidationError, match="does not consume"):
            AEListingSpec(
                interactive=InteractiveBlock(
                    population=[ChoiceOption(label="Safety", default=True)]
                )
            )

    def test_groupby_axis_on_listing_rejected(self) -> None:
        with pytest.raises(ValidationError, match="no.*column grouping"):
            AEListingSpec(
                interactive=InteractiveBlock(groupby={"choices": ["TRTA"], "default": "TRTA"})
            )


# ================================================================== #
# Anti-drift golden — the explorer's default fragment IS batch HTML     #
# ================================================================== #


class TestAntiDriftGolden:
    def test_default_fragment_byte_identical_to_batch_html(self) -> None:
        """Explorer default variant == run_spec + render_html, byte for byte."""
        spec = load_spec(SPEC_DIR / "aet01.yaml")
        rmeta = RenderMetadata(title="Overview of Adverse Events")

        batch_html = render_html(
            ard_to_table_model(run_spec(spec, ADAE, adsl=ADSL, groupby="TRTA"), rmeta)
        )
        explorer_html = render_explorer(
            [ExplorerEntry(name="aet01", spec=spec, df=ADAE, adsl=ADSL, groupby="TRTA",
                           metadata=rmeta)]
        )
        # Embedded untouched inside the default (visible, v0) container.
        assert f'id="var-aet01-v0">\n{batch_html}' in explorer_html

    def test_four_axis_default_fragment_matches_batch(self) -> None:
        """Same guarantee when a groupby axis supplies the arm column."""
        spec = _four_axis_spec()
        rmeta = RenderMetadata(title="AET01")
        batch_html = render_html(
            ard_to_table_model(run_spec(spec, ADAE, adsl=ADSL, groupby="TRTA"), rmeta)
        )
        explorer_html = render_explorer(
            [ExplorerEntry(name="aet01", spec=spec, df=ADAE, adsl=ADSL, metadata=rmeta)]
        )
        assert f'id="var-aet01-v0">\n{batch_html}' in explorer_html

    def test_non_default_variants_hidden_and_qc_panels_present(self) -> None:
        spec = _four_axis_spec()
        html = render_explorer(
            [ExplorerEntry(name="aet01", spec=spec, df=ADAE, adsl=ADSL)]
        )
        assert html.count('class="fleet-variant"') == 16
        assert html.count(" hidden>") >= 15  # every non-default fragment starts hidden
        assert html.count("Download ARD (JSON)") == 16
        assert html.count("Show definition (spec YAML)") == 16
        # No external requests of any kind.
        assert "http://" not in html and "https://" not in html

    def test_explorer_writes_file(self, tmp_path: Path) -> None:
        out = tmp_path / "explorer.html"
        spec = load_spec(SPEC_DIR / "aet01.yaml")
        html = render_explorer(
            [ExplorerEntry(name="aet01", spec=spec, df=ADAE, adsl=ADSL, groupby="TRTA")],
            path=out,
        )
        assert out.read_text(encoding="utf-8") == html


# ================================================================== #
# YAML round-trip + builder parity                                     #
# ================================================================== #


class TestRoundTripAndBuilder:
    def test_interactive_yaml_round_trip(self) -> None:
        spec = _four_axis_spec()
        reloaded = AEOverviewSpec.from_yaml(spec.to_yaml())
        assert reloaded == spec
        assert reloaded.interactive == spec.interactive

    def test_shipped_example_carries_interactive_block(self) -> None:
        spec = load_spec(SPEC_DIR / "aet01.yaml")
        assert spec.interactive is not None
        assert len(enumerate_variants(spec)) == 8
        # Defaults mirror the fixed spec values → batch output unchanged.
        default = enumerate_variants(spec)[0].spec
        assert default.model_dump() == spec.model_dump()

    def test_builder_interactive_matches_yaml_spec(self) -> None:
        yaml_spec = _four_axis_spec()
        built = (
            ADAE.tlg.ae.population(ADSL, adsl_filter='pl.col("SAFFL") == "Y"')
            .by("TRTA")
            .template("aet01")
            .header_rows(yaml_spec.header_rows)
            .interactive(
                groupby={"choices": ["TRTA", "TRT01P"], "default": "TRTA"},
                population=[
                    {"label": "Safety", "filter": 'pl.col("SAFFL") == "Y"', "default": True},
                    {"label": "All subjects", "filter": None},
                ],
                dataset_filter=[
                    {"label": "Serious only", "filter": 'pl.col("AESER") == "Y"'},
                    {"label": "All AEs", "filter": None, "default": True},
                ],
                stats=[
                    {"label": "n (%)", "statistics": ["n_subjects", "n_pct"], "default": True},
                    {"label": "+ events", "statistics": ["n_subjects", "n_pct", "n_events"]},
                ],
            )
            .to_spec()
        )
        assert built == yaml_spec

    def test_builder_interactive_survives_to_yaml(self) -> None:
        built = (
            ADAE.tlg.ae.template("aet01")
            .interactive(groupby={"choices": ["TRTA", "TRT01P"], "default": "TRTA"})
            .to_spec()
        )
        reloaded = AEOverviewSpec.from_yaml(built.to_yaml())
        assert reloaded.interactive == built.interactive


# ================================================================== #
# Every variant runs through the real engine                           #
# ================================================================== #


def test_every_variant_runs_and_default_matches_batch_ard() -> None:
    """All 16 variants execute; the default's ARD equals the batch ARD."""
    from polars.testing import assert_frame_equal

    spec = _four_axis_spec()
    batch_ard = run_spec(spec, ADAE, adsl=ADSL, groupby="TRTA")
    for variant in enumerate_variants(spec):
        ard = run_spec(variant.spec, ADAE, adsl=ADSL)
        assert isinstance(ard, pl.DataFrame)
        assert ard.height > 0
        if variant.is_default:
            assert_frame_equal(ard, batch_ard)
