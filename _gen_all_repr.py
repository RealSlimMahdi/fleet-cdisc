"""Generate from_repr strings for all test DataFrame replacements."""
import polars as pl

pl.Config.set_tbl_cols(20)
pl.Config.set_tbl_width_chars(500)
pl.Config.set_fmt_str_lengths(100)

frames = {}

# === test_adam_namespace.py ===
frames["adam_vs_frame"] = pl.DataFrame({
    "USUBJID": ["01-701-1015", "01-701-1015", "01-701-1023"],
    "PARAMCD": ["SYSBP", "DIABP", "SYSBP"],
    "PARAM": ["Systolic BP", "Diastolic BP", "Systolic BP"],
    "VSSTRESN": [120.0, 80.0, 118.0],
    "vsorresu": ["mmHg", "mmHg", "mmHg"],
    "vsdtc": ["2014-01-02", "2014-01-02", "2014-01-03"],
    "TRTSDT": ["2014-01-02", "2014-01-02", "2014-01-03"],
    "ABLFL": ["Y", "Y", "Y"],
})

frames["adam_chg"] = pl.DataFrame({"AVAL": [120.0, 118.0], "BASE": [120.0, 120.0]})
frames["adam_pchg"] = pl.DataFrame({"AVAL": [130.0, 120.0], "BASE": [100.0, 100.0]})
frames["adam_bmi"] = pl.DataFrame({"weight_kg": [70.0], "height_cm": [175.0]})
frames["adam_nrind"] = pl.DataFrame({
    "LBSTRESN": [3.0, 5.0, 9.0],
    "LBSTNRLO": [4.0, 4.0, 4.0],
    "LBSTNRHI": [8.0, 8.0, 8.0],
})
frames["adam_ontreatment"] = pl.DataFrame({
    "ADT": ["2024-01-15", "2024-01-05", "2024-02-01"],
    "TRTSDT": ["2024-01-10", "2024-01-10", "2024-01-10"],
    "TRTEDT": ["2024-01-31", "2024-01-31", "2024-01-31"],
})
frames["adam_shift"] = pl.DataFrame({
    "BNRIND": ["NORMAL", "LOW"],
    "NRIND": ["HIGH", "NORMAL"],
})
frames["adam_shift_custom"] = pl.DataFrame({"B": ["NORMAL"], "P": ["HIGH"]})
frames["adam_deriv_null"] = pl.DataFrame({
    "USUBJID": ["S01", "S02", "S03"],
    "VSSTRESN": [120.0, None, 115.0],
})
frames["adam_deriv_null2"] = pl.DataFrame({
    "USUBJID": ["S01", "S02"],
    "VSSTRESN": [120.0, None],
})
frames["adam_recode_null"] = pl.DataFrame({"CODE": ["A", None, "B"]})
frames["adam_recode_unmapped"] = pl.DataFrame({"CODE": ["A", "X"]})
frames["adam_order_source"] = pl.DataFrame({
    "USUBJID": ["S01", "S02", "S03"],
    "PARAM": ["SYSBP", "DIABP", "SYSBP"],
    "AVAL": [120.0, 80.0, 118.0],
})
frames["adam_order_chained"] = pl.DataFrame({
    "USUBJID": ["S01", "S02", "S03"],
    "PARAMCD": ["SYSBP", "DIABP", "SYSBP"],
    "VSSTRESN": [120.0, 80.0, 118.0],
    "vsdtc": ["2014-01-02", "2014-01-02", "2014-01-03"],
})
frames["adam_condderiv"] = pl.DataFrame({
    "USUBJID": ["S01", "S02", "S03"],
    "ABLFL": ["Y", None, "Y"],
    "VSSTRESN": [120.0, 80.0, 115.0],
})

# === test_nodup.py ===
frames["nodup_with_dups"] = pl.DataFrame({
    "USUBJID": ["01-001", "01-001", "01-001", "01-002", "01-002", "01-003"],
    "AEDECOD": ["HEADACHE", "HEADACHE", "NAUSEA", "HEADACHE", "HEADACHE", "RASH"],
    "AESTDTC": ["2014-01-05", "2014-01-05", "2014-02-10", "2014-03-01", "2014-03-01", "2014-04-15"],
    "ASEQ": [1, 2, 3, 1, 2, 1],
})
frames["nodup_no_dups"] = pl.DataFrame({
    "USUBJID": ["01-001", "01-002", "01-003"],
    "AEDECOD": ["HEADACHE", "NAUSEA", "RASH"],
    "AESTDTC": ["2014-01-05", "2014-02-10", "2014-03-01"],
})
frames["nodup_adsl"] = pl.DataFrame({
    "USUBJID": ["01-001", "01-001", "01-002"],
    "AGE": [45, 45, 62],
    "SEX": ["F", "F", "M"],
})
frames["nodup_adjacent"] = pl.DataFrame({
    "USUBJID": ["01-001", "01-001", "01-001", "01-002"],
    "AEDECOD": ["HEADACHE", "HEADACHE", "NAUSEA", "RASH"],
    "AESTDTC": ["2014-01-05", "2014-01-05", "2014-02-01", "2014-03-01"],
    "AESEQ": [1, 2, 3, 1],
})
frames["nodup_unsched"] = pl.DataFrame({
    "USUBJID": ["01-001", "01-001", "01-001"],
    "VSTESTCD": ["SYSBP", "SYSBP", "DIABP"],
    "VISITNUM": [3, 99, 3],
    "VSDTC": ["2014-02-01", "2014-02-01", "2014-02-01"],
    "VSSTRESN": [120.0, 125.0, 80.0],
})
frames["nodup_edc"] = pl.DataFrame({
    "USUBJID": ["01-001", "01-001"],
    "AEDECOD": ["HEADACHE", "HEADACHE"],
    "AESTDTC": ["2014-01-05", "2014-01-05"],
    "AESEQ": [1, 1],
    "AEENDTC": ["2014-01-10", "2014-01-12"],
})
frames["nodup_null_key"] = pl.DataFrame({
    "USUBJID": ["01-001", "01-001", "01-002"],
    "AEDECOD": [None, None, "RASH"],
    "AESEQ": [1, 2, 1],
})
frames["nodup_ae_dupseq"] = pl.DataFrame({
    "USUBJID": ["01-701-1015", "01-701-1015", "01-701-1015", "01-701-1016", "01-701-1016", "01-701-1017", "01-701-1017"],
    "AESEQ": [1, 2, 1, 1, 2, 1, 2],
    "AETERM": ["HEADACHE", "NAUSEA", "DIARRHEA", "HEADACHE", "NAUSEA", "HEADACHE", "NAUSEA"],
    "AESEV": ["MILD", "MODERATE", "MILD", "MILD", "MODERATE", "MILD", "SEVERE"],
    "AESTDTC": ["2014-01-10", "2014-02-05", "2014-01-10", "2014-01-11", "2014-02-06", "2014-01-12", "2014-02-07"],
    "AEENDTC": ["2014-01-15", "2014-02-10", "2014-01-15", "2014-01-16", "2014-02-11", "2014-01-17", "2014-02-12"],
    "AEREL": ["PROBABLE", "POSSIBLE", "UNLIKELY", "PROBABLE", "POSSIBLE", "PROBABLE", "POSSIBLE"],
    "AESER": ["N", "N", "N", "N", "N", "N", "N"],
})

# === test_robustness.py ===
frames["robust_adam"] = pl.DataFrame({
    "USUBJID": [f"S{i:02d}" for i in range(10)],
    "PARAMCD": ["SYSBP"] * 5 + ["DIABP"] * 5,
    "VSSTRESN": [120.0 + i for i in range(10)],
    "vsdtc": [f"2014-01-{i + 1:02d}" for i in range(10)],
})
frames["robust_nodup"] = pl.DataFrame({
    "USUBJID": ["S01", "S01", "S02", "S02", "S03"],
    "AEDECOD": ["HA", "HA", "NA", "NA", "RA"],
    "AESEQ": [1, 2, 1, 2, 1],
})

# === test_sdtm_namespace.py ===
frames["sdtm_partial_date"] = pl.DataFrame({"dtc": ["2014-01", "2014", "2014-01-02", None]})
frames["sdtm_aerel"] = pl.DataFrame({"ae_relationship": ["yes", "no", "possibly related", None]})
frames["sdtm_aerel_custom"] = pl.DataFrame({"rel": ["yes", "no"]})
frames["sdtm_nodup"] = pl.DataFrame({"id": [1, 1, 2], "val": ["a", "a", "b"]})
frames["sdtm_multi_resp"] = pl.DataFrame({"USUBJID": ["S01"], "ae_terms": ["fever|rash"]})
frames["sdtm_year_only"] = pl.DataFrame({"dtc": ["2014"]})
frames["sdtm_year_month"] = pl.DataFrame({"dtc": ["2014-03"]})
frames["sdtm_null_date"] = pl.DataFrame({"dtc": [None]}, schema={"dtc": pl.Utf8})
frames["sdtm_mixed_dates"] = pl.DataFrame({"dtc": ["2014", "2014-01", "2014-01-15", None]})
frames["sdtm_null_src"] = pl.DataFrame({"src": ["A", None, "C"]})
frames["sdtm_all_null"] = pl.DataFrame({"src": [None, None, None]})
frames["sdtm_tied"] = pl.DataFrame({
    "USUBJID": ["S01", "S01", "S01"],
    "VISITNUM": [1, 1, 1],
    "VSSTRESN": [120.0, 121.0, 119.0],
})

for name, df in frames.items():
    print(f"=== {name} ===")
    print(repr(df))
    print()
