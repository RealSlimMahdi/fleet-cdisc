# Growth reference tables

`peds.bmi_percentile_category` reads these files. Do not edit them by hand. Run `uv run python scripts/regen_growth_references.py` to download them again, and compare the SHA-256 values below.

## cdc2000_bmiagerev.csv

- Source: CDC National Center for Health Statistics, "BMI-for-age charts, 2 to 20 years, LMS parameters and selected smoothed BMI percentiles, by sex and age", file `bmiagerev.csv`.
- URL: https://www.cdc.gov/growthcharts/data/zscore/bmiagerev.csv (listed on https://www.cdc.gov/growthcharts/cdc-data-files.htm).
- Version: CDC 2000 growth charts. CDC states that the data are unchanged since the release of 30 May 2000.
- Retrieved: 4 November 2026. SHA-256 of the download: `cbeea0e8d500ee15c652f3fdc45bcd02cb9c15d4d1e86f4d8048bbfea8d166e5`.
- Stored byte for byte. The file repeats its header line before the girls' rows (line 221).
- Layout: Sex 1 = male, 2 = female. Agemos is the half-month point: 24.5 stands for 24.0 to 24.99 months. Columns P5, P85 and P95 are the smoothed percentiles that the verb compares with.

## who2007_bmi_for_age.csv

- Source: WHO Growth reference data for 5-19 years, BMI-for-age, z-score tables, expanded (monthly) LMS: `bmi-boys-z-who-2007-exp.xlsx` and `bmi-girls-z-who-2007-exp.xlsx`.
- URLs: https://cdn.who.int/media/docs/default-source/child-growth/growth-reference-5-19-years/bmi-for-age-(5-19-years)/bmi-boys-z-who-2007-exp.xlsx and the same path with `girls`.
- Version: WHO 2007 growth reference (de Onis M et al. Bull World Health Organ. 2007;85:660-667).
- Retrieved: 4 November 2026. SHA-256 of the downloads: boys `0a60849673f34a06b8e2fe4defe5d00348de687b6c9fce0278f1525fff89eb6d`, girls `66f5c6284b44579ad6135fc639f22c09e36fe5a695b04390377113f6a00deb72`.
- Converted: the columns Month, L, M and S of both workbooks, with Sex 1 = boys and 2 = girls. Each value is the shortest decimal text of the number in the workbook. Months 61 to 228.
