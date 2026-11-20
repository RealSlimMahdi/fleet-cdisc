# Handoff: Fleet alpha audit and fixes

Paste this file into the new session. Read it in full before you act. Repository: `/Users/aboutm/Code/Python/Fleet`. The rules in `AGENTS.md` apply to all work: uv only, Polars only, Ruff only, the verification order, and the PR footer lines.

## Who you work for

Mahdi is a statistical programmer, a SAS and CDISC expert and a Python beginner. Write to him in ASD-STE100 Simplified Technical English: short sentences, headings and lists, no emoji, no em dashes. Ask before an architecture or clinical-logic decision. Implement only when he says "implement". Commit, push or open a PR only when he asks.

## What happened so far (2026-11-01 to 2026-11-02)

1. **Audit.** A multi-agent audit of commit `6e9bb3f` (branch `feat/146-verb-is-the-algorithm`, open PR #184) found 859 confirmed root-cause clusters: 53 blocker, 216 high, 348 medium, 242 low. The lead reran all 53 blockers on its own data, and all reproduce.
   - Report and plan: `ALPHA-AUDIT.md` at the repository root. It is untracked. Read sections 1, 3, 4 and 8 first.
   - All findings, by ID (for example `c1-3`): `/Users/aboutm/Code/Python/fleet-alpha-audit/FINDINGS.md`. Each entry gives the expected value, what Fleet gives, the fix, the tests that pin today's behaviour, and the evidence.
   - The same data with full text: `/Users/aboutm/Code/Python/fleet-alpha-audit/findings.json`.
   - Repro scripts and verdicts: `/Users/aboutm/Code/Python/fleet-alpha-audit/evidence.tar.gz`.
2. **Talk material corrected.** The PHUSE EU Connect 2026 talk OS12 is in Glasgow, 15 to 18 November 2026. The paper, the deck with its clips and the Q&A are now true for commit `6e9bb3f`. The talk material is no longer in this repository: on 2026-11-09 it moved to the sibling repository `../fleet-talks`, and on 2026-11-20 into `talks/2026-phuse-eu-os12/` there. The paths below are in that folder.
   - Paper: `paper/phuse_EU_2026_OS12.md`, built to `submission/PAP_OS12.pdf` with `bash kit/paper/build_pdf.sh talks/2026-phuse-eu-os12 <out.pdf>` from the fleet-talks root (14 pages on 2026-11-02).
   - Deck: `deck/os12_presentation_final.md` is the hand-edited draft. Then `deck/os12-clips/build-deck.py` generates `deck/os12_presentation_clips.md`, and `bash kit/deck/build-pptx.sh talks/2026-phuse-eu-os12 <out-dir>` builds `submission/PRE_OS12.pptx`. The steps are in fleet-talks `kit/deck/README.md`, and the clip sources are `deck/os12-clips/src/clips/batch*.tsx`.
   - Q&A: `paper/phuse_EU_2026_OS12.chair-questions.md`. It has 22 questions. Q21 is the careful version that Mahdi asked for. Q23 is removed.
   - Change logs and backups: `paper/archive/v4-pre-audit-2026-11-02/` (`CHANGES.md`, `CHANGES-QA.md`, `RUN-PROOF.md`, `verification/`) and `deck/archive/v3-pre-audit-2026-11-02/` (`CHANGES.md`, `verification/`).
   - Mahdi's decisions on the talk: keep the `uv add fleet-cdisc` line, because it works after release. Keep the timeline statements, because the proof of concept predates git. Leave the small editorial points as they are. Rerun the benchmark later, not now. The benchmark scripts still print 37 and 54 lines and "real pilot data", but the paper says 55 and 89 and synthetic data.
3. **PRs merged on 2026-11-02:** #175 (`fleet run` study-run module), #183 and #184 (ADR-0008, the verb is the algorithm), #185 (`polars>=1.41,<2`), #186 and #187 (below). Still open: #176 (admission bar, #160) and #83 (pygls floor). No tag exists yet. `origin/main` is at `a67b7bc`. The local checkout may still be on the old branch `feat/146-verb-is-the-algorithm`, so switch to an updated `main` before new work. Line numbers in `FINDINGS.md` refer to `6e9bb3f`; recheck each location on `main`, because #175 changed `fleet run` (c1-288 may be fixed).
   - #186 `fix/engine-default-version` (merged), worktree `/Users/aboutm/Code/Python/fleet-worktrees/engine-default`. `fleet install-engine` now installs CORE `v0.15` (0.15.0), and `--version latest` warns. Still open from c1-521: removing `-rr`, reading the engine return code first, and a warning for engine versions that are not tested. The paper and the Q&A already show the plain `fleet install-engine` command.
   - #187 `chore/remove-roche-references` (merged), worktree `/Users/aboutm/Code/Python/fleet-worktrees/remove-roche`. It removes the Roche fonts, the internal draft mail, the `ROCHE-*` sample IDs (now `ACME-*`), and the Roche template names in two docstrings, and it credits "pharmaverse sdtmchecks" in the rule headers. Mahdi wants no reference to Roche material anywhere. The public author citations of {admiral} stay, and so does the employer disclosure in paper line 670.
4. **Git identity.** The repository now commits with Mahdi's GitHub no-reply address, set in `.git/config`. `gh` has two accounts. Use `RealSlimMahdi` (personal, active) only, and never `aboutm_roche`.

## Open decisions (waiting for Mahdi)

- **Round 1 domain questions: ANSWERED by Mahdi on 2026-11-02.** Apply these:
  - **Q1, `c1-144` (TEAE, missing start date):** follow admiral `derive_var_trtemfl`, with all its edge cases. Those cases carry the clinical meaning. A missing AE start is treatment-emergent unless the AE end is before TRTSDT. A missing TRTSDT gives no flag. A missing TRTEDT means an open window. Add `end_date` and `end_window` as admiral has them.
  - **Q2, `c1-424` (population filter):** option A. Drop records outside the population from the numerator, by a semi-join on USUBJID to the filtered ADSL, and report the count at NOTE level, as SAS `WHERE` does. Update the glossary entry "Population filter" in `CONTEXT.md` and record the change in an ADR.
  - **Q3, `c1-90` (raw value that cannot become ISO 8601):** option A, conservative. Write null to `--DTC`, and warn once at `.to_frame()` with the variable, the count and the first five raw values. The reviewer's `on_invalid=` argument is optional; ask before adding it.
  - **Q4, `c1-118` (`first_date` and `last_date` with a partial `--DTC`):** with no `impute=`, ignore partial dates and use complete dates only. With `impute=`, impute, write the `*DTF` flag, and warn the user that imputation took place, with the count. This is option A plus a warning on imputation.
  - **Q5, `c1-261` (which CORE findings stop the job):** option A. Every finding blocks, so the status is not PASS, `fleet validate` exits 1 and `on_fail='raise'` raises, unless `study_config.yaml` lists the rule ID and dataset with a reason, like an SDRG explanation. Add an easy escape for a programmer who wants to run everything, for example a `--no-block` flag on the CLI and `on_fail='warn'` on the verb. It reports all findings and exits 0. Ask Mahdi to confirm the name.
  - The 20 remaining blocker questions follow, five per round, in `FINDINGS.md`. Use the question rules in `AGENTS.md`.
- **Engineering decisions: ACCEPTED by Mahdi on 2026-11-02.** Apply the whole table in `ALPHA-AUDIT.md` section 8, and record each one in an ADR when you implement it:
  - `c1-124`: the top-level `order` and `mode` of `pick` act across events, as in admiral.
  - `c1-121`: the `recode` output type follows the map values, and a mixed map raises.
  - `c1-1`, `c1-2`: `select(spec=)` never casts `--DTC` and never imputes.
  - `c1-150`, `c1-234`: XPT goes through the Polars route of pyreadstat. Write V5, with the member name equal to the file name. Stop on a name over 8 characters or a value over 200.
  - `c1-521`: the default engine pin is done (#186). Reading the engine return code first is still open.
  - `c1-774`: delete the retired DefineXMLGenerator and DefineValidator. `fleet check` fails when the generator refuses.
  - `c1-776`: add `significant_digits`. A gap warns at generation and fails in `fleet check`.
  - `c1-31`: `ct_map` warns by default, and `validate: false` silences the warning.
  - `c1-822`: the VS default rows are PARAMCD and AVISIT.
  - `c2-865`: no blank rule in the TLG engine; the SAS reader handles blanks.
- **Repository visibility:** do not make this repository public. The fonts and about 195 roche.com commits stay in history and in `refs/pull/*`. A public repository must be a new one, built from a `git filter-repo` copy, after Mahdi checks with his employer.
- **Dependabot:** recommended, but not yet decided. First switch on alerts and security updates. Add version updates after the tag, grouped weekly, with Polars and httpx limited to their current major version.

## Next steps, in order

1. Done: #184, #185, #186 and #187 are merged.
2. Rebase the two open PRs on `main`, then Mahdi merges them:
   - #83 (`fix/69-pygls-floor`, pygls floor for `fleet lsp`): one conflict, in `tests/unit/test_cli.py`. Merge it before the tag.
   - #176 (`docs/160-verb-admission-bar`): one conflict, in `CONTEXT.md`. Its ADR is numbered 0005, but `main` already has ADR-0005 (summary specs), so renumber it to 0009 and fix every reference. Rebuild `llms.txt`, because `verbs()` gains an `origin` column. Merge it before package G, which also edits `CONTEXT.md`.
3. Before any tag, open a small PR on `main` with `httpx>=0.27,<1` (c1-182) and `requires-python = ">=3.12,<3.15"` plus an import guard (c1-154). Today `main` has `polars>=1.41,<2`, `httpx>=0.27.0` and `requires-python = ">=3.12"`.
4. Fix one package at a time, only after Mahdi says "implement package X". Each package is one branch from updated `main` and one PR. Write the tests first, use real data shapes, and run the full verification order. The order and the content are in `ALPHA-AUDIT.md` section 4:
   - **F:** SAS and CSV input and output. Blank to null, the Polars route for XPT, XPT V5 dates, encoding.
   - **A:** one shared `--DTC` reader for all date verbs.
   - **B:** ADSL and OCCDS. TEAE, `pick`, the SAFFL recipes, `recode` types.
   - **C:** SDTM flags and BDS. `baseline_flag`, `flag` with ties, `derive_param` null keys, the `qtc` unit.
   - **D:** grading.
   - **E:** PK BLQ and confirmed response.
   - **G:** TLG numbers. Population filter, n, Q1 and Q3, and the default rows.
   - **H:** Define-XML MethodDef and SignificantDigits, validate status, the bootstrap, `fleet run`.
5. Before the tag, add the CI gates in section 5.3: real-shape tests, an R oracle job, examples and a clean-install smoke test in CI, and README blocks run in CI.

## How to check a fix

- Each finding in `FINDINGS.md` has a scenario and an expected value. Turn that into a failing test first.
- The verification order in `AGENTS.md` applies after every change: lint, tests, the six examples, `llms.txt`, docs. The examples rewrite tracked files in `outputs/`, so restore them with `git checkout -- outputs` before you commit.
- Every PR body ends with the `Tool:` and `Verified:` lines, as `AGENTS.md` asks.

## Do not

- Do not run `fleet install-engine` or `uninstall-engine` without `HOME` set to a scratch folder.
- Do not print or copy `CDISC_API_KEY` from `.env`.
- Do not edit `talks/2026-phuse-eu-os12/paper/phuse_EU_2026_OS12.chair-review-response.md` in fleet-talks. It is the record of what was sent to the chair.
- Do not change `promo/fleet-shorts2/` or `promo/fleet-launch-video/` in fleet-talks without asking. Both still hold old claims, listed in `c2-898` and `c2-894`.
- Do not stage `ALPHA-AUDIT.md` or `HANDOFF.md` in a commit unless Mahdi asks.
