"""Trial design builders: TS split, ctgov enrollment, YAML loader, arm paths, Mermaid, USDM."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fleet.sdtm.tdd import (
    TrialElement,
    TrialElements,
    TrialParameter,
    TrialParameters,
    _ctgov_to_parameters,
)
from fleet.sdtm.tdd_audit import audit


class TestTsvalSplit:
    """c1-246: TSVAL over 200 characters splits; TSPARM holds 40 at most."""

    def test_long_tsval_splits_at_a_word_boundary(self):
        text = "word " * 90 + "end"  # 453 characters
        ts = TrialParameters(
            parameters=[
                TrialParameter(tsparmcd="TITLE", tsparm="Trial Title", tsval=text),
                TrialParameter(tsparmcd="REGID", tsparm="Registry Identifier", tsval="NCT1"),
            ]
        ).to_polars()
        assert ts.columns[ts.columns.index("TSVAL") : ts.columns.index("TSVAL") + 3] == [
            "TSVAL",
            "TSVAL1",
            "TSVAL2",
        ]
        title = ts.row(0, named=True)
        pieces = [title["TSVAL"], title["TSVAL1"], title["TSVAL2"]]
        assert "".join(pieces) == text
        assert all(len(p) <= 200 for p in pieces)
        assert pieces[1].startswith(" ") and not pieces[0].endswith(" ")
        assert ts.row(1, named=True)["TSVAL1"] == ""

    def test_one_word_over_200_is_cut_at_200(self):
        ts = TrialParameters(
            parameters=[TrialParameter(tsparmcd="TITLE", tsparm="Trial Title", tsval="x" * 250)]
        ).to_polars()
        assert (len(ts["TSVAL"][0]), len(ts["TSVAL1"][0])) == (200, 50)

    def test_short_tsval_adds_no_column(self):
        ts = TrialParameters(
            parameters=[TrialParameter(tsparmcd="REGID", tsparm="Registry Identifier", tsval="N")]
        ).to_polars()
        assert "TSVAL1" not in ts.columns

    def test_tsparm_over_40_is_refused(self):
        with pytest.raises(ValidationError, match="40"):
            TrialParameter(tsparmcd="TITLE", tsparm="T" * 41, tsval="x")

    def test_audit_names_another_char_value_over_200(self):
        ts = TrialParameters(
            parameters=[TrialParameter(tsparmcd="TITLE", tsparm="Trial Title", tsval="x " * 150)]
        ).to_polars()
        assert "FLEETTD03" not in audit(ts=ts)["rule_id"].to_list()
        te = TrialElements(
            elements=[
                TrialElement(etcd="SCRN", element="Screening", testrl="r" * 201, epoch="SCREENING")
            ]
        ).to_polars()
        found = audit(te=te).filter(rule_id="FLEETTD03")
        assert found["message"].to_list() == [
            "TE.TESTRL holds 1 value(s) over 200 characters, the XPT V5 limit. Reword the "
            "text; only TSVAL splits into TSVAL1-TSVALn."
        ]


class TestCtgovEnrollment:
    """c1-249: ACTUAL enrollment is ACTSUB, not PLANSUB."""

    @staticmethod
    def _rows(info: dict) -> dict[str, str]:
        record = {"protocolSection": {"designModule": {"enrollmentInfo": info}}}
        return {r.tsparmcd: r.tsval for r in _ctgov_to_parameters(record)}

    def test_actual_gives_actsub(self):
        assert self._rows({"count": 1062, "type": "ACTUAL"}) == {"ACTSUB": "1062"}

    def test_estimated_gives_plansub(self):
        assert self._rows({"count": 300, "type": "ESTIMATED"}) == {"PLANSUB": "300"}

    def test_no_type_gives_neither(self):
        assert self._rows({"count": 300}) == {}
