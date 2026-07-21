import polars as pl

import fleet  # noqa: F401
from fleet.core.derivation import derivation
from fleet.core.lineage import lineage_of

df = pl.DataFrame(
    {
        "USUBJID": ["S1", "S2"],
        "WEIGHT": [70.0, 80.0],
        "HEIGHT": [175.0, 180.0],
        "AGE": [40, 70],
    }
)

print("=== CASE A: frame derivation WITH declared targets+sources ===")


@derivation(targets=["BMI_CAT"], sources=["WEIGHT", "HEIGHT"])
def good(df: pl.DataFrame) -> pl.DataFrame:
    "Categorise BMI."
    return df.with_columns(pl.lit("NORMAL").alias("BMI_CAT"))


ns = df.adam.derivation(good)
for n in lineage_of(ns):
    print(f"  name={n.name!r} verb={n.verb!r} sources={n.sources} method={n.method!r}")

print("\n=== CASE B: frame derivation, NO sources declared ===")


@derivation(targets=["FLAG1"])
def no_src(df: pl.DataFrame) -> pl.DataFrame:
    "Add a flag from WEIGHT and HEIGHT."
    return df.with_columns((pl.col("WEIGHT") > 75).cast(pl.Utf8).alias("FLAG1"))


ns = df.adam.derivation(no_src)
for n in lineage_of(ns):
    print(f"  name={n.name!r} verb={n.verb!r} sources={n.sources} method={n.method!r}")

print("\n=== CASE C: frame derivation, NO targets declared ===")


@derivation
def no_tgt(df: pl.DataFrame) -> pl.DataFrame:
    "Add MYSTERY column without declaring it."
    return df.with_columns(pl.lit("?").alias("MYSTERY"))


ns = df.adam.derivation(no_tgt)
nodes = lineage_of(ns)
print(f"  lineage nodes for this derivation: {len(nodes)}")
print(f"  MYSTERY present in frame: {'MYSTERY' in ns.to_frame().columns}")
for n in nodes:
    print(f"  name={n.name!r} verb={n.verb!r} sources={n.sources}")

print("\n=== CASE D: param derivation (set_values_to PARAMCD) ===")


@derivation(by=["USUBJID"], set_values_to={"PARAMCD": "BMI", "PARAM": "Body Mass Index"})
def bmi(df: pl.DataFrame) -> pl.DataFrame:
    "Compute BMI per subject."
    return df.with_columns((pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2).alias("AVAL"))


ns = df.adam.derivation(bmi)
print(f"  columns after: {ns.to_frame().columns}")
for n in lineage_of(ns):
    print(f"  name={n.name!r} verb={n.verb!r} sources={n.sources}")
print(f"  total lineage nodes: {len(lineage_of(ns))}")
