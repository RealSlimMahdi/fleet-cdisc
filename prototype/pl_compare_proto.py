"""Pure-Polars PROC COMPARE prototype (feasibility spike, not production code)."""
from __future__ import annotations
import time
import polars as pl

NUMERIC = (pl.Float32, pl.Float64, pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64, pl.Decimal)

# SYSINFO-style bits (subset of SAS PROC COMPARE codes)
BIT_TYPE = 2; BIT_BASE_OBS_NOT_IN_COMP = 64; BIT_COMP_OBS_NOT_IN_BASE = 128
BIT_BASE_VAR_NOT_IN_COMP = 256; BIT_COMP_VAR_NOT_IN_BASE = 512; BIT_VALUES_DIFFER = 4096


def compare(base: pl.LazyFrame, comp: pl.LazyFrame, id: list[str], *, abs_tol=0.0, rel_tol=0.0, max_print=50):
    bs, cs = base.collect_schema(), comp.collect_schema()
    common = [c for c in bs if c in cs and c not in id]
    base_only = [c for c in bs if c not in cs]
    comp_only = [c for c in cs if c not in bs]
    conflicting = [c for c in common if (bs[c] in NUMERIC) != (cs[c] in NUMERIC)]
    comparable = [c for c in common if c not in conflicting]

    b = base.select(id + comparable).with_row_index("_b_idx")
    c = comp.select(id + comparable).with_row_index("_c_idx")
    # observation matching on ID (SAS: ID statement); duplicate-key check like SAS's "duplicate ID" note
    dup_b = b.group_by(id).len().filter(pl.col("len") > 1).select(pl.len()).collect().item()
    dup_c = c.group_by(id).len().filter(pl.col("len") > 1).select(pl.len()).collect().item()
    base_only_obs = b.join(c, on=id, how="anti").select(pl.len()).collect().item()
    comp_only_obs = c.join(b, on=id, how="anti").select(pl.len()).collect().item()
    both = b.join(c, on=id, how="inner", suffix="_comp")

    # per-column difference flags, tolerance for numerics (SAS CRITERION/METHOD ABSOLUTE|RELATIVE)
    flags = []
    for col in comparable:
        l, r = pl.col(col), pl.col(f"{col}_comp")
        if bs[col] in NUMERIC and (abs_tol or rel_tol):
            tol = pl.max_horizontal(pl.lit(abs_tol), (rel_tol * r.abs()))
            neq = ((l - r).abs() > tol)
        else:
            neq = l != r
        # null semantics: both null -> equal; one null -> differ (SAS treats missing==missing as equal)
        neq = pl.when(l.is_null() & r.is_null()).then(False).otherwise(neq.fill_null(True))
        flags.append(neq.alias(f"_neq_{col}"))
    both = both.with_columns(flags)

    per_var = both.select([pl.col(f"_neq_{col}").sum().alias(col) for col in comparable]).collect()
    per_var = per_var.unpivot(variable_name="variable", value_name="n_diff").filter(pl.col("n_diff") > 0)
    obs_with_diff = both.filter(pl.any_horizontal([pl.col(f"_neq_{c}") for c in comparable])).select(pl.len()).collect().item()

    # value comparison listing (long format, like OUT=... OUTNOEQUAL then transposed)
    listings = []
    for col in per_var["variable"].to_list():
        listings.append(
            both.filter(pl.col(f"_neq_{col}"))
                .select(id + [pl.lit(col).alias("variable"),
                              pl.col(col).cast(pl.String).alias("base"),
                              pl.col(f"{col}_comp").cast(pl.String).alias("compare")]
                        + ([(pl.col(f"{col}_comp") - pl.col(col)).cast(pl.Float64).alias("diff"),
                            ((pl.col(f"{col}_comp") - pl.col(col)) / pl.col(col) * 100).alias("pct_diff")]
                           if bs[col] in NUMERIC else [pl.lit(None, pl.Float64).alias("diff"), pl.lit(None, pl.Float64).alias("pct_diff")]))
                .head(max_print)
        )
    values = pl.concat(listings).collect() if listings else pl.DataFrame()

    sysinfo = 0
    if conflicting: sysinfo |= BIT_TYPE
    if base_only_obs: sysinfo |= BIT_BASE_OBS_NOT_IN_COMP
    if comp_only_obs: sysinfo |= BIT_COMP_OBS_NOT_IN_BASE
    if base_only: sysinfo |= BIT_BASE_VAR_NOT_IN_COMP
    if comp_only: sysinfo |= BIT_COMP_VAR_NOT_IN_BASE
    if per_var.height: sysinfo |= BIT_VALUES_DIFFER
    return {
        "variables": {"common": len(common), "base_only": base_only, "comp_only": comp_only, "conflicting_type": conflicting},
        "observations": {"matched": both.select(pl.len()).collect().item(), "base_only": base_only_obs, "comp_only": comp_only_obs,
                          "dup_keys_base": dup_b, "dup_keys_comp": dup_c, "with_diff": obs_with_diff},
        "per_variable": per_var, "values": values, "sysinfo": sysinfo,
    }


if __name__ == "__main__":
    # small worked example
    base = pl.LazyFrame({"USUBJID": ["01","02","03","04"], "AGE": [34,45,52,61], "SEX": ["M","F","F","M"], "WT": [70.1,55.2,60.3,80.0]})
    comp = pl.LazyFrame({"USUBJID": ["01","02","03","05"], "AGE": [34,46,52,70], "SEX": ["M","F","M","F"], "WT": [70.1,55.2,60.30001,75.0], "RACE": ["W","B","W","A"]})
    r = compare(base, comp, ["USUBJID"], rel_tol=1e-6)
    for k in ("variables", "observations", "sysinfo"): print(k, r[k])
    print(r["per_variable"]); print(r["values"])

    # benchmark: 1M rows x 20 cols, ~0.1% cells perturbed, 1k rows added/removed each side
    N, K = 1_000_000, 20
    rng = pl.LazyFrame({"USUBJID": pl.arange(0, N, eager=True).cast(pl.String)})
    base = rng.with_columns([(pl.col("USUBJID").cast(pl.Int64) * (i + 1) % 9973).cast(pl.Float64).alias(f"V{i}") for i in range(K - 10)]
                            + [(pl.col("USUBJID").cast(pl.Int64) % (7 + i)).cast(pl.String).alias(f"C{i}") for i in range(10)]).collect()
    comp = base.with_columns([pl.when(pl.col("USUBJID").cast(pl.Int64) % 1000 == 0).then(pl.col("V0") + 1e-3).otherwise(pl.col("V0")).alias("V0"),
                              pl.when(pl.col("USUBJID").cast(pl.Int64) % 777 == 0).then(pl.lit("X")).otherwise(pl.col("C3")).alias("C3")])
    comp = pl.concat([comp.slice(1000), comp.head(1000).with_columns((pl.col("USUBJID") + "_new").alias("USUBJID"))])
    t0 = time.perf_counter(); r = compare(base.lazy(), comp.lazy(), ["USUBJID"], rel_tol=1e-9); dt = time.perf_counter() - t0
    print(f"\nbenchmark {N:,} rows x {K} cols: {dt:.2f}s  obs={r['observations']}  sysinfo={r['sysinfo']}")
    print(r["per_variable"])
