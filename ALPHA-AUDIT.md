# Fleet alpha audit

Audit commit: `6e9bb3f`, branch `feat/146-verb-is-the-algorithm`, Polars 1.41.0. Date: 2 November 2026.

This file is a report and a plan. No Fleet code changed. No commit, push, issue or PR was made. Implementation waits for your "implement".

Every finding, with its full evidence and fix: `/Users/aboutm/Code/Python/fleet-alpha-audit/FINDINGS.md`. IDs such as `c1-3` point to that file.

## 1. Result

- **Do not tag 0.2.0a1 yet.** 53 confirmed blockers are open. Most give a wrong clinical number with no warning.
- **Do not make the repository public yet.** It holds fonts and history that must not go public. See section 2.
- **Correct the deck now.** The talk is on 15 to 18 November, in 13 days. Some deck claims are false at this commit. See section 6.

| Lens | Blocker | High | Medium | Low | Total |
|---|---:|---:|---:|---:|---:|
| Statistical programmer | 49 | 194 | 253 | 122 | 618 |
| Software engineer | 4 | 22 | 95 | 120 | 241 |
| **Total** | **53** | **216** | **348** | **242** | **859** |

The 859 clusters come from 1,440 raw findings. A cluster is one root cause, so one fix is one item. Reviewers refuted 12 more clusters.

### What this means

The core works on clean data. Auditors recorded 1,019 correct behaviours (section 7). For example, TLG counts on clean data matched an independent count on 61,126 cells, and ADTTE matched admiral 1.4.1 cell by cell.

The defects appear on normal SDTM shapes: a time part, a partial date, a null, a SAS blank, a tie. Clean test data does not hold these shapes. So all 2,558 tests pass, and the first real study fails. Example, rerun by me on the real CDISC pilot LB:

- 59,355 of 59,580 `LBDTC` values have a time part.
- `study_day` gives null on all 59,355 rows, with no warning.

Five patterns explain most findings:

1. **No shared `--DTC` reader.** `src/fleet` has 43 date parse sites, and each treats text differently.
2. **Polars null rules, not SAS rules.** A null fails a comparison and a join. A SAS programmer does not expect this.
3. **Silence.** A wrong result comes with no warning. The tool does not tell the user that a record was lost.
4. **Tests confirm the code, not the rule.** All candidate fixes of one audit area together break 1 of 2,558 tests. `test_admiral_parity.py` never runs admiral. The grading tests run 4 of 399 criteria rows.
5. **Text written from intent, not from a run.** README blocks, recipes and clips show results that no run gives.

Good news: 33 of the 53 blockers are small fixes (S), and 19 are medium (M). Only 1 is large (L). Reviewers tried many of the fixes on a private copy, and the tests still passed.

## 2. Two steps you cannot undo

### 2.1 Repository visibility

The repository is private today. If you make it public as it is:

- `assets/Roche Sans/` goes public. The font metadata says "All rights reserved" and limits use to Roche and its partners. `CONTRIBUTING.md` says these files must not be published.
- About 195 of 339 commits show a roche.com address. Your talk affiliation is "Independent".
- A tracked file holds an internal draft mail (`.github/prompts/fleet_alpha_comm_plan.prompt.md`).
- Wheel docstrings name a Roche template source (`c1-628`).

A history rewrite on this same GitHub repository is not enough. GitHub keeps `refs/pull/*/head` (78 refs here), and old commits stay readable by SHA.

**Proposed solution:**

1. Ask your employer how to treat what is already on GitHub.
2. Remove the fonts and the mail file with `git filter-repo`.
3. Push the result to a **new** repository, and make that one public.
4. Replace the `ROCHE-AE-*` sample names with `ACME-AE-*`, and reword the docstrings (`c1-627`, `c1-628`).

This is your decision, and possibly your employer's. Fleet code does not depend on it. Nothing uses the fonts.

### 2.2 The PyPI tag

PyPI never accepts the same version twice. Before the tag:

| ID | Defect, rerun by me | Fix |
|---|---|---|
| `c1-153` | A clean install gets Polars 2.1.0. `treatment_emergent` then stops with `InvalidOperationError`. The publish smoke test still passes. | Merge PR #185 (`polars<2`). |
| `c1-182` | `--prerelease=allow` brings httpx 1.0.dev6. `fleet install-engine` stops with `TypeError`. | Add `httpx>=0.27,<1`, and change the install lines. |
| `c1-154` | With the #185 pin, Python 3.15 gets Polars 1.x, and 350 tests fail (reviewer run). | Add `requires-python = ">=3.12,<3.15"` and an import guard. |
| `c1-479` | The install lines in the paper and deck fail, also after the upload, because the yanked 0.1.0 blocks the fallback. | Use a line that works, and test it on a clean machine. |

**My recommendation: do not tie the tag to the talk.** The talk date is fixed. The tag is one-way, and a wrong number on PyPI stays there. The deck can say that the alpha follows the talk. You decide.

## 3. Order of work

**Gate 1: today, no code.**

1. Decide on section 2.1.
2. Answer the five questions in section 8.
3. Accept or change the engineering decisions in section 8.

**Gate 2: before the talk.**

4. Correct the deck, paper and clips (section 6).
5. Fix what the talk shows live.

**Gate 3: before the tag.**

6. Merge in this order: #184, then #185 with the two packaging lines, then #175 (`fleet run`). Each PR needs its own review.
7. Fix the packages in this order. Later packages depend on earlier ones.
   1. Package F, because the blank rule and the XPT route change the input of every verb.
   2. Package A, because the `--DTC` reader serves all date verbs.
   3. Packages B, C, D, E.
   4. Package G.
   5. Package H.
8. Add the release gates in section 5.3, so that these defects cannot return.

**Gate 4: after the tag.** The other high, medium and low findings. 100 of the 216 highs need no decision.

## 4. Statistical programmer findings: all 49 blockers

"Fleet gives" is what my own script printed on the frozen commit, unless the row says otherwise. The expected values come from admiral, the IG, SAS rules or a hand calculation. D marks a domain decision, and E an engineering decision. The full fix for each row is in `FINDINGS.md`.

### Package A: one `--DTC` reader

Root cause: each verb parses `--DTC` text its own way. **Solution:** one tested helper for the date part and one for the date-time. It keeps partial values, it never guesses, and it warns once with the variable, the count and the first values.

| ID | Input | Fleet gives | Correct | Effort |
|---|---|---|---|---|
| `c1-3` | `VSDTC 2021-03-20T08:30`, `RFSTDTC 2021-03-15` | `VSDY` null | 6 (SDTMIG 4.4.4) | S, D |
| `c1-219` | `epoch_assign`, `LBDTC 2021-01-20T09:00` | `EPOCH` null. The date-only row is right. | TREATMENT | S, D |
| `c1-65` | `.date("ASTDTM")`, `2021-03-15T10:30` | `00:00:00`, flag S | `10:30:00` (admiral) | M, D |
| `c1-66` | `min_date=TRTSDT`, complete `2021-02-20` | moves to `2021-03-15`, no flag | stays. A pre-dose AE becomes TEAE today. | S |
| `c1-6` | `duration` months, 85 days | 3.76 | 2.79 = 85 / 30.4375 | S, D |
| `c1-89` | `.sdtm.date`, `03/04/2021`, `15-MAR-21` | `2021-04-03`, `0021-03-15` | no silent guess | S, D |
| `c1-90` | `UNK`, `2021-02-30`, `foo` | copied into `--DTC` | not silent | M, D |
| `c1-94` | `.date(time=)` with a null time | null, date lost | `2021-03-15` (4.4.2) | S, D |
| `c1-118` | `first_date`, EXSTDTC `2021-03`, `2021-03-15`, a blank | text. `2021-03`, and a blank wins. | numeric date, a blank never wins | M, D |
| `c1-1`, `c1-2` | `select(spec=)`, `fleet run` | partial `--DTC` lost or a `ComputeError`. TRTSDT with a time part is null. | no cast on `--DTC` | M + S, E |

### Package B: ADSL and OCCDS

| ID | Input | Fleet gives | Correct | Effort |
|---|---|---|---|---|
| `c1-144` | `treatment_emergent`, null start, AE in window | null | Y (admiral) | S, D |
| `c1-124` | documented LSTALVDT recipe, TRTEDT `2023-06-30` | `2023-03-05` | `2023-06-30` | M, E |
| `c1-677`, `c2-878` | documented recipes on a placebo subject, EXDOSE 0 | SAFFL and TRTSDT null | dosed placebo is safety population, and a flag is never blank | S + S |
| `c1-121` | `recode` to a numeric map | ASEVN is String | numeric (#130) | S, E |

Solution for `c1-677`: correct the recipes with the admiral rule `EXDOSE > 0 OR (EXDOSE = 0 AND EXTRT contains PLACEBO)`, and add `false_value="N"`. Auditor run on the published pilot: all 86 placebo subjects lose TRTSDT.

### Package C: SDTM flags and BDS

| ID | Input | Fleet gives | Correct | Effort |
|---|---|---|---|---|
| `c1-99` | `baseline_flag`, last record NOT DONE | flags the NOT DONE row | the last row with a result (SDTMIG) | S, D |
| `c2-937` | `flag(criteria="last", where=)` on a tie | no flag in the group | last eligible row. ABLFL, BASE and CHG are lost today. | S |
| `c1-319` | `derive_param` with a null ATPT | 1 of 2 MAP records | 2 (admiral, SAS BY) | S |
| `c1-75` | `qtc`, RR 1000 ms | 40.0 | 400 | S, D |

### Package D: toxicity grading

| ID | Input | Fleet gives | Correct | Effort |
|---|---|---|---|---|
| `c1-380` | ALT 900, ULN 40, null BNRIND | grade 0 | grade 4 | S |
| `c1-381` | Hyperkalemia 7.5, unit `mmol/L` | null. `MMOL/L` gives 4. | grade 4 in any case | S |
| `c1-382` | DAIDS `Hemoglobin, Low` 60, adult male | null | grade 4 | M, E |
| `c1-392` | shipped term `Hemoglobin increased` | `ValueError` | a grade. Only 4 of 399 rows are tested. | L, D |

`c1-380` and `c1-381` are one-line fixes. Reviewers tried them, and the differences against admiral drop by a large margin. `c1-392` is the only L, because it needs a review of all shipped criteria against the admiral tables.

### Package E: PK and oncology

| ID | Input | Fleet gives | Correct | Effort |
|---|---|---|---|---|
| `c1-394` | `PCSTRESC <0.1`, `PCSTRESN` null | BLQFL null | Y. Read the text in `--STRESC`. | M, D |
| `c1-405` | `confirmed_response_flag`, `by=[STUDYID, USUBJID]` | Y on S2, who has one PR | S1 only. Join on all by columns. | S |

### Package F: SAS and CSV input and output

| ID | Input | Fleet gives | Correct | Effort |
|---|---|---|---|---|
| `c1-150` | `save_xpt` on a documented install | `No module named 'pyarrow'` | writes the file | M, E |
| `c1-234` | `save_xpt` with pyarrow | V8 file, member `DATASET` | V5, member equals file name (FDA TCG 3.1.1) | M, E |
| `c1-235` | ADT `2021-03-15` to XPT | 1931385600, DATETIME | 22354, DATE9 | S |
| `c1-236`, `c2-865` | blank SAS character value | `""`, an extra row in tables | null, the SAS missing value | S + M, D |
| `c1-237` | `fleet compare`, SITEID `001` against `1` in CSV | EQUAL | not equal for a text variable | M, D |

Solution for `c1-150`, `c1-234`, `c1-235`: use the Polars route of pyreadstat, and remove pandas. This also makes the "Zero Pandas" claim closer to true. Solution for `c1-236`: one line at `loaders.py:143` that converts `""` to null, plus `nulls_equal=True` on the verb joins.

Also here: `c1-238`, raised to high by me. The real pilot `ts.xpt` cannot be read by any Fleet command, because of byte 0x92, and no encoding reaches pyreadstat. So `fleet validate` stops on the real pilot folder.

### Package G: TLG numbers

| ID | Input | Fleet gives | Correct | Effort |
|---|---|---|---|---|
| `c1-424` | population filter, 2 subjects out of population with AEs | `n=3`, `N=1`, 300% | `n=1`, 100% | S, D |
| `c1-425` | 5 subjects, 1 null AVAL | `n=5` | `n=4` | S, D |
| `c1-426` | 3 records for 2 subjects | `n=2`, mean 20, SD 10 | a pair that PROC MEANS gives | M, D |
| `c1-427` | values 1, 2, 3, 4 | Q1 2.0, Q3 3.0 | 1.5, 3.5 (QNTLDEF=5, R type 2) | S |
| `c1-433` | subject with NOT RELATED and RELATED | counted NOT RELATED | RELATED, or a refusal | S, D |
| `c1-500` | `t_shift`, screening HIGH, later NORMAL | NORMAL to HIGH | NORMAL to NORMAL, or a refusal | M, D |
| `c1-808` | `t_qtcat` | pools HR with QTcF and all visits | per PARAMCD and AVISIT | M, D |
| `c1-822` | `vs.t_summary` by default | mean 132.5 over all visits | per visit: 105, 160 | S, E |

`c1-424` has the largest effect. CONTEXT.md says the population filter is "applied to ADSL only, never to the analysis dataset". The auditor's run on the real pilot shows the cost: Week 24 ADAS-Cog prints `n=86, 84, 84` under `N=79, 74, 81`, and the High Dose mean is 23.4 where the efficacy population gives 22.8. This is the primary endpoint. The solution keeps ADSL as the only place of the filter: a semi-join on `USUBJID` to the filtered ADSL. The glossary needs an update, and an ADR must record it.

For `c1-808`, a small safe step exists for the tag: withdraw `egt05`, and raise an error that gives the route through `t_summary`.

### Package H: Define-XML, validation and bootstrap

| ID | Action | Fleet gives | Correct | Effort |
|---|---|---|---|---|
| `c1-261` | `fleet validate` on an AE with planted defects | `Status: PASS`, exit 0, with 2 findings | not PASS when findings exist | S, D |
| `c1-557` | `fleet define-xml` on the shipped ADaM define | 42 Derived ItemRefs, 0 MethodOID, 0 MethodDef | each Derived ItemRef has a method | M, D |
| `c1-776` | same | 6 float ItemDefs, 0 SignificantDigits, 0 Length | Define-XML 2.1 needs them | M, E |
| `c1-533` | `fleet new`, then `fleet define-xml` | raw `ValueError` traceback, empty description | a study that generates | S, D |
| `c1-297` | `fleet new` with ADaM, then `fleet check` | 13 failures, and the printed fix cannot help | a fresh study that passes | M, D |
| `c1-521` | `fleet install-engine`, then `fleet validate` | CORE v0.17.1, `ERROR-001` | a tested engine version | M, E |
| `c1-288` | `fleet run` on the shipped pilot | exit 1 | runs. PR #175 fixes the general defect. | S |
| `c1-31` | `assign(ct=, ct_map=)`, raw value outside the map | SEX = `Unknown`, no warning | a warning, as the README says | S, E |
| `c1-179` | README Quick Demo, first lines | `No module named 'codelists'` | the PyPI page runs as written. Inline the data. | S |

The other two statistical programmer blockers are `c1-182` (section 2.2) and `c1-347` (section 6).

Also here: `c1-266`, raised to high by me. On the real pilot SDTM (21 XPT files, without `ts.xpt`), `fleet validate` gives 21 of 21 `Status: FAIL` with `TIMEOUT-001` after 304 seconds, and exit 1. The limit is fixed at 300 seconds, and no flag changes it. Three engine workers stayed alive after the timeout. So the tool cannot validate the reference study today. **Fix:** a `--timeout` flag and a config key, kill the process group, and report a timeout as "could not run", not as a data failure.

### Selected high findings

The full list of 194 is in `FINDINGS.md`.

- **Dates:** `c1-138` age is a rounded decimal, not completed years. `c1-143` raw Polars errors on partial text. `c1-69` legal forms such as `2021---15` give null. `c1-678` a partial AE end date falls before the start. `c1-145` `offset_days` moves the window start.
- **Flags and merge:** `c1-206`, `c1-207` null and tie rules against SAS `LAST.`. `c1-12`, `c1-13`, `c1-14` merge with `_right` columns, null keys and repeated ADSL keys. `c1-17` `merge(keep=)` drops every left column (#91). `c1-204` a null condition gives `N`.
- **BDS:** `c1-317` `derive_locf_records` adds no records and sets no DTYPE. `c1-76` hidden rounding in `bmi`, `bsa`, `map`, `qtc`. `c1-84` NaN and inf on a zero denominator.
- **Therapeutic areas:** `c1-407` no minimum SD duration in BOR. `c1-406` confirmation counts records after PD. `c1-416` seroconversion rule. `c1-417` fever at 38.0 (#177). `c1-158` `bmi_category` gives Obese for a missing BMI. `c1-161` adult cut-offs in peds (#178).
- **Grading:** `c1-384` admiral AND became OR in the bundled JSON, so grades are false. `c1-329` no unit check by default.
- **TLG:** `c1-428` half-even rounding against SAS ROUND. `c1-442` a null category drops with no row. `c1-432` the CLI cannot run ADAE.TRTA with ADSL.TRT01A, so all safety tables refuse on the pilot files. `c1-447` the ARD is not cards-compatible as claimed. `c1-803` (raised by me) `cm` counts prior medications as concomitant.
- **SDTM:** `c1-101` IDVARVAL `1.0` in SUPP. `c1-105` the SUPP path is incomplete. `c1-226` `element_boundaries` depends on file order.
- **Fleet run:** `c1-286`, `c1-290`, `c1-291`, `c1-287` wrong input file, multiplied records, stale input, ignored output format.

## 5. Software engineer findings

Reviewers rated each finding by its present cost, and they downgraded many. I report no metric without a consequence. `cli.py` and `_verb_mixin.py` are large, but no confirmed maintainability finding is above medium.

### 5.1 The four engineering blockers

| ID | Defect | Fix | Effort |
|---|---|---|---|
| `c1-153` | No upper bound on Polars. | PR #185. | S |
| `c1-392` | The grading tests do not see shipped criteria that crash. | Test each shipped row against admiral. | L |
| `c1-533` | Scaffold writes an invalid define, and the CLI shows a traceback. | Raise a `SpecError` subclass, add `--description`. | S |
| `c1-774` | `DefineXMLGenerator` and `DefineValidator` read a retired YAML dialect. Every documented call fails: `gen.write` does not exist, and `DefineValidator` returns False on the shipped specs. | Delete both and the old schema. Make `fleet check` fail when the generator refuses. | S |

### 5.2 Security

Local CLI, one user. So the risk is a study package that you receive from someone else. Fix these before the repository is public.

- `c1-88`: an expression string can run OS commands. I reran it: `pl.dataframe.frame.os.system(...)` in `derivation(expression=)` raises an error, but the command has already run. The docstring and the paper claim a whitelist. **Fix:** widen the AST check, add tests on the escape forms, and correct the text.
- `c1-298`: a `dotenv.py` in the study folder runs on `fleet doctor`.
- `c1-744`: dataset names in `define.yaml` reach file paths with no check.
- `c1-768`, `c1-835`: `fleet check` and `fleet doctor` run code that a study file names.
- `c1-575`: a stylesheet in a received package can write files.
- `c1-763`: a `.env` in a received package can send your CDISC key to another host.

Checked and correct: YAML loaders refuse python tags, XXE is blocked, and HTML output escapes values. The bandit `eval` hit at `spec_registry.py:280` is not reachable from a study file.

### 5.3 Tests and CI

This is the most valuable engineering work, because it stops the same defects from returning.

- `c1-842`: test fakes feed `_parse_report` a `Severity` key that CORE never writes. So exit 1 is proved only on a fake report.
- `c1-621` (#142): CI runs no example, although the docs say that it does.
- `c1-617`: the CI legs 3.13 and 3.14 run on Python 3.12.
- `c1-620`: CI omits the extras, so 67 tests do not run.
- `c1-618`: CI tests only a yanked Polars 1.41.0.
- `c1-619`: stacked PRs get no checks.
- `c1-841`: the suite kills 338 of 516 clinical logic mutants (65.5%).
- `c1-848`: the docs guardrail runs 17 of about 180 Python blocks.
- `c2-972` to `c2-975`: no test reads a third-party file or a real data shape.
- `c1-860`: no test reads a number back from RTF, PPTX or PDF.

**Proposed gates:**

1. One test set of real shapes (time part, partial, blank, tie, null key) that runs through every date and flag verb.
2. An R oracle job that runs admiral on a small grid, so that the parity tests become real parity.
3. Examples and a clean-install smoke test in CI, on the versions that users get.
4. Each Python block of the README and quickstart runs in CI.

### 5.4 Reproducibility

- `c1-21`, `c1-325`, `c1-389`: some sorts and group-bys do not keep input order. Row order can change from run to run, so a later `seq` can give a record a different number. A QC programmer sees a difference that no one can explain. **Fix:** `maintain_order=True` on these paths, and a test that runs in a new process.

### 5.5 Cohesion, with a present cost

- `c1-87`: the study day formula lives in five places. `core/seq.py` and `utils.study_day` are dead code.
- `c1-203`: lineage lives in two stores, so `trail` shows false origins.
- `c1-35`: CT terms live in three stores.
- `c1-689`: the examples rewrite tracked goldens under `outputs/`. I saw this myself during the audit.

The Package A helper removes the first one. Do the others after the tag.

## 6. Talk, paper and shorts

Your rule is: only claims that the repository can prove. These fail that rule at this commit. All are confirmed by a reviewer. None needs a code change to correct.

| ID | Where | Claim | Fact |
|---|---|---|---|
| `c1-347` | Slide 17, clip | `fleet run` with five ticks and "9 s" | Exit 1 on the pilot. No run gave this. The CLI has no timing code. |
| `c1-693` | Clips s02, s15 | "Real output" | Hand-typed. Leaves out the only serious event. |
| `c1-341`, `c1-342`, `c1-343` | Deck, Q&A | Each ADaM verb equals admiral, 400+ parity tests | 39 tests that never run admiral. |
| `c1-351` | Slide 7 | CORE checks ADaM and ARD. Same code on Lambda, Databricks, Snowflake, Spark. | No executable ADaM rule. No proof for those platforms. |
| `c1-344`, `c1-268` | Deck, paper | CORE is the authority for CT, and it checks Define-XML 2.1 | No generic codelist rule. Fleet cannot pass a define to the engine. |
| `c1-488`, `c1-345`, `c1-482` | Paper, slide 16 | Each derived variable gets a MethodDef | 21 of 42 with methods on, 0 of 42 by default. The printed text is not what Fleet writes. |
| `c1-483`, `c1-484`, `c1-487` | Slide 18, paper | Benchmark on CDISC Pilot 01, identical logic, R super-linear | A 64-row AE extract from STUDY001. TRTEMFL and ASEQ differ. |
| `c1-696`, `c1-695` | Paper, clip s12 | Three gates before any derivation. Nothing disappears in silence. | `from_spec` runs no schema. A round trip drops AESEQ. |
| `c2-918`, `c2-919` | Deck | 81 rules ported from sdtmchecks, 14 more in CORE | 20 hold the conditions of the R function, and 15 are inverted or cannot do their job. 7 tracker rows. |
| `c1-447` | Paper, deck | ARD shares the cards contract | False for cards 0.8.0, both directions. |
| `c1-489`, `c1-493` | Paper | ADAE chain is standard logic. Validation gates. | Crashes on a timed AESTDTC. PASS with findings. |
| `c1-476` | Paper, deck, clip s12 | Old spec spellings | Refused on the PR #184 branch. |
| `c1-479` | Paper, deck | Install lines, public repository | Fail today. The repository is private. |
| `c2-894` | Launch video, scene 8 | Shows a table as a success | The table that the talk calls wrong. |
| `c2-898` | All shorts | "On-screen output is real" | 18 shorts show a false result or a chain that stops. Do not post them yet. Short 18 shows LSTALVDT `2014-07-02`, and the code gives `2014-03-02`. |

**What you can say with proof:** see section 7. One honest line that the repository can support after the fixes: "An audit with independent oracles found these defects, and here is how the tool now checks itself." Use it only when the fixes and the gates exist.

## 7. What is correct

Auditors recorded these against an independent oracle. All 1,019 entries are in `findings.json`. I did not rerun them.

- **TTE:** 20-subject scenario set equals admiral `derive_param_tte` on each cell. All 12 prebuilt sources match.
- **AE tables on clean data:** 61,126 cells on 200 random studies match an independent count. `t_soc_pt`, `t_overview` and `t_severity` match tern.
- **Compare:** null, NaN and tolerance rules match PROC COMPARE on the full matrix. 800 random datasets match a plain Python oracle. Tolerance formulas equal METHOD=ABSOLUTE and PERCENT.
- **Spec engine:** the inline verb equals the `define.yaml` block on 98 cases over all 39 algorithms. ADR-0008 holds: YAML keys equal the signature on all 39. `#87` is fixed and can close.
- **Define-XML:** the XSD passes, OIDs are unique, output is stable across runs.
- **Lineage and DAG:** build order, named cycles and `impacted_by` are right. The slide matches.
- **Laziness and speed:** the namespace adds little over plain Polars at 10M rows. No `map_elements` in `src/fleet`.
- **Error messages:** column typos name the verb, the column and a did-you-mean in 9 of 9 cases.
- **IDE typing:** Pyright resolves 37 of 37 `reveal_type` calls through `fleet.frame`.
- **Clinical basics on a careful path:** with typed dates and the admiral exposure filter, ADSL equals admiral on 12 subjects. On the published pilot, ADAE dates and durations match on 1,191 of 1,191 records.
- **Rendering:** the explorer works offline, with 0 external requests. Hostile values are escaped.
- **Published data anomaly:** Fleet gives AESTDY 1 for `01-716-1063`, where the published value is 366. Fleet is right. This is a good story for the talk, with care: credit first.

## 8. Decisions

### Round 1: five questions

All five are **domain**. They block the most fixes. Reply with the letters.

**Q1. `c1-144` (domain). `treatment_emergent`, missing start date.** ADAE row: USUBJID 01-701-1028, AESTDTC null, AEENDTC null, TRTSDT 2014-01-04. The programmer gives no choice.

- A: flag Y, as admiral does. Null only if the AE end is before TRTSDT. What goes wrong for QC: a plain SAS chain `IF ASTDT >= TRTSDT > .` shows a difference, and the TEAE count is one higher.
- B: leave null, as today. What goes wrong for QC: an admiral QC finds one more TEAE, and the AE leaves the table with no warning.
- C: no default, the argument is required. What goes wrong for QC: a programmer can copy the value from an example, so QC must check it against the SAP in each call.
- Reviewer view: A or C.

**Q2. `c1-424` (domain). Population filter and the numerator.** The spec says `adsl_filter: SAFFL == 'Y'`. USUBJID 01-005 has SAFFL N and one HEADACHE row in ADAE.

- A: drop the row from the numerator, and print the count as a NOTE, as SAS `WHERE` does. What goes wrong for QC: a wrong SAFFL removes an AE with only a NOTE.
- B: stop with an error, and ask for a dataset filter. What goes wrong for QC: the shipped `aet01.yaml` and each subgroup table stop on real data.
- C: keep the row, and warn. What goes wrong for QC: the table prints 2 (100.0%) where the double program has 1 (50.0%).
- Reviewer view: A.

**Q3. `c1-90` (domain). Raw value that cannot become ISO 8601.** AE row USUBJID S05, raw `31FEB2021`. Fleet reports the value in all options.

- A: null in AESTDTC, plus one warning with the count and values. What goes wrong for QC: if the warning is ignored, the AE has no start date and leaves the TEAE count.
- B: keep the raw text, plus the warning. What goes wrong for QC: the text can reach the XPT while `fleet validate` still says PASS.
- C: stop with an error. What goes wrong for QC: one bad entry stops the AE domain at an interim cut, so a programmer may add a filter that hides the row.
- Reviewer view: A, with an `on_invalid=` argument.

**Q4. `c1-118` (domain). `first_date` and a partial `--DTC`.** USUBJID 1015 has EXSTDTC `2014-01` and `2014-01-15`. USUBJID 1023 has only `2014-01`. The call has no `impute=`.

- A: leave out the partial value, and warn. TRTSDT is `2014-01-15` and null. What goes wrong for QC: 1023 had a dose but has a null TRTSDT, and only a warning says so.
- B: impute the first day, with TRTSDTF. Both get `2014-01-01`. What goes wrong for QC: TRTSDT moves 14 days on 1015 with no SAP rule, and PROC COMPARE shows differences that the tool caused.
- C: stop until the call states a rule. What goes wrong for QC: the documented chain stops on real data, and a programmer adds the argument by reflex.
- Reviewer view: A.

**Q5. `c1-261` (domain). Which CORE findings stop the job?** CORE gives no severity. A DM without COUNTRY fires CORE-000355. A correct AE in a study with no RELREC fires CORE-000767. Both have the same shape.

- A: every finding blocks, unless `study_config.yaml` lists its rule and dataset with a reason, like an SDRG explanation. What goes wrong for QC: the first run of any study with an AE fails, and a waived rule can hide a later true hit.
- B: nothing blocks by default. The status says FINDINGS, and exit is 0. What goes wrong for QC: a CI job stays green on a DM without COUNTRY.
- C: Fleet ships a fixed list of blocking rules. What goes wrong for QC: QC must defend a list that no CDISC document states.
- D: the engine's executability field decides. What goes wrong for QC: a duplicate USUBJID does not block, and the false CORE-000767 does.
- Reviewer view: A.

### Next rounds

20 more domain questions on blockers are in `FINDINGS.md`, each with options: `c1-75` RR unit, `c1-6` negative span, `c1-426` repeated records, `c1-500` ABLFL-only ADLB, `c1-433` relationship order, `c1-808`, `c1-3`, `c1-65`, `c1-89`, `c1-94`, `c1-99`, `c1-219`, `c1-236`, `c1-237`, `c1-297`, `c1-392`, `c1-394`, `c1-425`, `c1-533`, `c1-557`. The highs add 47 more. I will send five at a time.

### Decisions taken on your behalf

**Engineering, each with a recommendation. "ok" accepts all. An ADR then records the reason. Say which to change.**

| ID | Decision | Reason |
|---|---|---|
| `c1-124` | Top-level `order` and `mode` of `pick` act across events, as in admiral. | Otherwise an admiral port gives a wrong LSTALVDT with no warning. |
| `c1-121` | `recode` type follows the map values, and a mixed map raises. This overrides the text of #130. | A typing slip must not give a text AESEVN. |
| `c1-1`, `c1-2` | `select(spec=)` never casts `--DTC`, and it never imputes. | SDTMIG: `--DTC` is text. |
| `c1-150`, `c1-234` | XPT goes through the Polars route of pyreadstat. V5. Member equals file name. Stop on a name over 8 or a value over 200. | FDA TCG 3.1.1. |
| `c1-521` | Pin the default engine to `v0.15`, and read the engine return code first. | v0.17.1 fails. |
| `c1-774` | Delete the retired generator and validator. `fleet check` fails when the generator refuses. | No file uses that dialect. |
| `c1-776` | Add `significant_digits`. A gap warns at generation, and fails in `fleet check`. | A hard stop blocks early drafts. |
| `c1-31` | Warn by default on `ct_map`. `validate: false` silences. | Same rule inline and in the spec (ADR-0008). |
| `c1-822` | VS default rows are PARAMCD and AVISIT. | Same as LB and EG, ICH E3. |
| `c2-865` | No blank rule in the TLG engine. The SAS reader solves it. | One fix at the source. |

**How I ran the audit:**

- Severity follows the rules in section 9.
- I raised `c1-238`, `c1-266` and `c1-803` to high on real-data evidence. I added `predose_flag` (`c2-lead-1`), which the merge step had dropped.
- I stopped the orphan engine processes that the audit and my reruns left behind.
- I put the full findings outside the repository, so `git status` stays clean except for this file.
- I opened no issues. 79 clusters cite an open issue, and a confirmed finding cites 42 of the 64 open issues.

## 9. How the findings were checked, and the limits

**Method.** 45 auditors each ran Fleet against an independent oracle (admiral 1.4.1, admiralonco, tern, cards, survival, sdtm.oak, CORE, plain Python). Clustering grouped the findings by root cause. Then:

- Each blocker got its own reproduction reviewer. Most also got a domain or engineering skeptic.
- High, medium and low clusters went to a reviewer in batches of 3, 6 and 10.
- A completeness critic added 7 follow-up audits, on real CDISC pilot and pharmaverse files.

**My own check.**

- I reran the core claim of all 53 blockers with my own scripts, on the frozen commit, with the expected value written first. All 53 reproduce. For a cluster with many members, I checked the core claim, not every member.
- From a random sample of 17 lower-severity clusters, I reran the 8 that a short script can test. All 8 reproduce. I read the other 9 only.

**Severity rules.** Blocker: a wrong clinical number, lost records or invalid submission output with no warning on a common path, or a crash on a first-run path. High: the same on a less common path, a false claim on the PyPI page or deck, or a security hole reachable from a study file. Medium: an API that leads to likely user error, debt with a present cost, a missing test on clinical logic. Low: a real but small issue.

**Limits. Please read these.**

1. **The confirmation rate is very high.** Only 12 of 870 clusters were refuted, and none of the 73 clusters rated blocker by an auditor was refuted. Auditors had to run each claim first, so a high rate is plausible. But reviewers read the auditor's claim, so a shared wrong framing can survive. Reviewers did correct severity on 157 clusters, and 20 blockers went down. My rerun tests "does it happen", and it partly tests "is it wrong". A blocker with a D mark can still be your choice, not a defect.
2. **Lower severities had a lighter check.** One reviewer, in a batch. Expect some wrong findings among the medium and low clusters.
3. **No SAS on this machine.** SAS statements come from documented rules and from R type 2 for QNTLDEF=5. Your double-programming knowledge outranks them.
4. **Memory, not a run.** admiralvaccine, admiralophtha, admiralneuro, admiralmetabolic, admiralpeds and chevron are not installed. Some IG text was read from the CDISC Library, and some comes from knowledge. Each finding says which.
5. **42 repeats have no verdict of their own.** The follow-up round reported them, and the merge step matched them to a parent cluster. Many give real-data sizes. I read the list, and it holds. Their numbers are auditor numbers, unless this report says that I reran them. I reran the LB count, the `ts.xpt` failure and the validation timeout.
6. **Scope of the commit.** The audit ran on PR #184, not on `main`. `c1-476` and `c1-168` exist only on this branch. PR states change, so recheck before you act.
7. **Fix proposals are proposals.** Many were tried on a private copy, and `FINDINGS.md` says which. Few were tried together, and some interact. Package A and Package F need a design pass first.

## 10. Files

- `ALPHA-AUDIT.md`: this report. Untracked. Move or delete it after use, because root plan files are already a concern in #144.
- `/Users/aboutm/Code/Python/fleet-alpha-audit/FINDINGS.md`: all clusters with expected value, result, fix, tests that pin today's behaviour, and evidence.
- `/Users/aboutm/Code/Python/fleet-alpha-audit/findings.json`: the same with the full text, plus the 1,019 correct behaviours and what each auditor did not check.
- `/Users/aboutm/Code/Python/fleet-alpha-audit/evidence.tar.gz`: repro scripts, outputs and all verdicts.
