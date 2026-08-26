# Carrying `editors/vscode/` history into `fleet-vscode`

**Status:** established, not executed. Resolves [issue #58](https://github.com/RealSlimMahdi/fleet-cdisc/issues/58).
**Measured against:** `RealSlimMahdi/fleet-cdisc` @ `origin/main` (146 commits) and local `HEAD` `04eba66` on `chore/agent-skills-setup`, 2026-08-26.

---

## 1. Recommendation

Use **`git filter-repo --subdirectory-filter editors/vscode`** on a **fresh clone**. Do not use `git subtree split`. Do not use `git filter-branch`.

### Why not `git filter-branch`

The git project itself tells you not to. From the man page's `WARNING` section: *"git filter-branch has a plethora of pitfalls that can produce non-obvious manglings of the intended history rewrite… its use is not recommended. Please use an alternative history filtering tool such as git filter-repo."* ([git-filter-branch](https://git-scm.com/docs/git-filter-branch)) The `SAFETY` section of the same page lists concrete corruption modes, including that commit messages referencing other commits by hash silently come to point at commits that no longer exist. Closed question.

### Why not `git subtree split`

Three documented reasons, all from the `git-subtree` man page source ([git-subtree.adoc](https://github.com/git/git/blob/master/contrib/subtree/git-subtree.adoc)):

1. **It creates synthetic commits, and only claims to preserve the message.** `split` is documented as: *"Extract a new, **synthetic** project history from the history of the `<prefix>` subtree."* The `--annotate` option is described as existing because *"we're creating new commits with the same commit message, but possibly different content, from the original commits."* The documentation makes **no** guarantee about author identity, committer identity, or dates. `filter-repo`, by contrast, documents exactly which metadata it will touch and requires you to opt in (§3 below).

2. **Its own docs warn that mixed commits produce nonsense.** The man page carries this TIP: *"In order to keep your commit messages clean, we recommend that people split their commits between the subtrees and the main project as much as possible. That is, if you make a change that affects both the library and the main application, commit it in two pieces. That way, when you split the library commits out later, their descriptions will still make sense."* Fleet's subtree history is **100% mixed commits** (§2), and the sole real commit's message is about the Python side, not the extension. This is precisely the case the docs warn about — and no tool fixes it, so it is a wash between the two tools, but `subtree` is the one that flags it as a known defect.

3. **GitHub's own instructions use `filter-repo`, not `subtree`.** GitHub's *Splitting a subfolder out into a new repository* documents `git filter-repo --subdirectory-filter FOLDER-NAME` as the way to make a subfolder the root of a new repo ([GitHub Docs](https://docs.github.com/en/get-started/using-git/splitting-a-subfolder-out-into-a-new-repository)).

### What `filter-repo` gives you for free

Per the man page ([`git filter-repo --help`](https://htmlpreview.github.io/?https://github.com/newren/git-filter-repo/blob/docs/html/git-filter-repo.html), v2.47.0) and the README ([newren/git-filter-repo](https://github.com/newren/git-filter-repo/blob/main/README.md)):

- rewriting commit messages that reference now-stale commit IDs to reference the new ones,
- pruning commits that *become* empty (but not ones that *started* empty),
- pruning merge commits that *become* degenerate,
- stripping the old history and repacking, so old and new can't be accidentally mixed,
- `refs/remotes/origin/*` promoted to `refs/heads/*` and the `origin` remote removed, so you cannot push the rewrite back over the source repo by accident.

---

## 2. What is actually in the subtree (measured)

| Measurement | Command | Value |
| --- | --- | --- |
| Commits on `origin/main` | `git rev-list --count origin/main` | **146** |
| Commits touching `editors/vscode/` (default simplification) | `git rev-list --count origin/main -- editors/vscode/` | **1** |
| Commits touching `editors/vscode/` (`--full-history --all`) | `git rev-list --count --full-history --all -- editors/vscode/` | **2** |
| Of those, commits that *also* touch paths outside the subtree | see below | **2 of 2 (100%)** |
| Distinct author identities in that history | `git shortlog -sne --full-history --all -- editors/vscode/` | **2** |
| Tracked files in the subtree at HEAD | `git ls-tree -r --name-only HEAD -- editors/vscode/` | **7** |
| Tags in the repo | `git tag` | **0** |
| Remote branches | `git branch -r` | 21 (7 contain the subtree) |

The two commits:

| Commit | Kind | Paths total | Inside subtree | Outside | Author |
| --- | --- | --- | --- | --- | --- |
| `aa38aa0` `feat: Add static TLG explorer for variant space visualization` | non-merge | 141 | 7 | **134** | `Mahdi About <mahdi.about@roche.com>`, 2026-07-09 17:11:23 +0200 |
| `b5f1bf5` `Merge pull request #40 from RealSlimMahdi/feat/dx-review-7-8` | merge | 246 (vs first parent) | 7 | **239** | `Mahdi About <36238571+RealSlimMahdi@users.noreply.github.com>`, 2026-07-09 20:13:58 +0200 |

The seven files: `.gitignore`, `.vscodeignore`, `README.md`, `package-lock.json`, `package.json`, `src/extension.ts`, `tsconfig.json`.

### What this means for the rewrite

**Every commit that touches the extension is a mixed commit.** There is no clean-cut extension commit anywhere in the history. `filter-repo` handles this the only way any path-filter can: it **keeps the commit and drops the unselected paths from its tree**. The commit survives with its original author, committer, dates and message; only its diff shrinks to the seven extension files.

Concretely, applying the documented pruning rules:

- `aa38aa0` selects paths → **kept**, tree reduced to the 7 files at root.
- All ~140 ancestors select nothing → become empty → **pruned** (`--prune-empty auto` default). `aa38aa0` therefore becomes a **root commit**.
- `b5f1bf5` is a merge whose first-parent side is pruned entirely, leaving it with one parent and no file changes of its own → **pruned** (`--prune-degenerate auto` default: *"they can become degenerate (having fewer than two parents…). If such merge commits have no file changes, they can be pruned."*).

**Predicted result: a 1-commit repository with 1 author identity** (`Mahdi About <mahdi.about@roche.com>`). The GitHub-noreply identity disappears along with the pruned merge. This is expected and correct — but it means a naive "commit count must equal 2" assertion will fail. §6 gives a verification that accounts for it.

> **Merge topology is a non-question here.** The subtree touches one merge and one commit. There is no topology to preserve. Neither tool's merge handling is a deciding factor for this repo.

---

## 3. Authorship, dates, and what gets modified

`filter-repo` changes commit metadata **only when you ask it to**. The man page exposes author/committer name, email and date exclusively through opt-in options:

- `--mailmap <filename>` / `--use-mailmap` — *"when rewriting author, committer, and tagger names and emails"*
- `--name-callback`, `--email-callback` — under the heading *"Filtering of names & emails"*
- `--commit-callback` — raw access, e.g. `commit.author_name` ([cheat sheet](https://github.com/newren/git-filter-repo/blob/main/Documentation/converting-from-filter-branch.md))

No option in the documented option list alters author or committer **dates** at all outside `--commit-callback`. A pure path filter passes all four identity fields and both timestamps through untouched. **The command in §5 uses none of these options**, so authorship and dates are preserved by construction.

Two things *do* change unavoidably, for both tools, because history rewriting changes object IDs:

- **Every commit SHA changes.** From the man page: *"all commit IDs (starting with the first one where changes are made) are modified."*
- **Commit-message hash references are rewritten** to the new IDs. This is `filter-repo`'s default and is a feature; `--preserve-commit-hashes` disables it. Leave it on — `aa38aa0`'s message contains no hash references, so this is a no-op here either way.

---

## 4. Path rewriting: does the proposed invocation work?

**Yes.** The ticket proposes `--path editors/vscode --path-rename editors/vscode/:`. That is the *exact documented expansion* of the shortcut. From the man page:

> `--subdirectory-filter <directory>` — Only look at history that touches the given subdirectory and treat that directory as the project root. **Equivalent to using `--path <directory>/ --path-rename <directory>/:`**

Use the shortcut; it is shorter and cannot be mistyped into a half-filter.

Three sub-questions, all answered from the man page:

**Trailing slashes.** *"As with `--path`, directories can be specified with or without a trailing slash for `--path-rename`."* So `editors/vscode` and `editors/vscode/` behave identically.

**Will `editors/vscode/README.md` → `README.md` collide with Fleet's root `README.md`?** No. *"Note that path renaming does not do path filtering"* — the rename only says how to rename paths that the **filters** selected. The filter selects only `editors/vscode/`, so Fleet's root `README.md`, `.gitignore`, `package.json` equivalents etc. are never in the stream and cannot be clobbered. (The man page's own worked example makes this explicit: `--path src/main/ --path-rename tools/:scripts/` *"would not result in the tools or scripts directories being present, because the single filter selected only `src/main/`"*.)

**The extension's `.gitignore`.** `editors/vscode/.gitignore` is a tracked file inside the subtree; it moves to the new root like any other file, carrying its history. Its contents are `node_modules/`, `out/`, `*.vsix` — which is exactly right for a standalone extension repo, and now applies repo-wide instead of to one subdirectory. Note the consequence: **Fleet's root `.gitignore` is not selected and does not carry over**, so the new repo inherits no Python/`.venv`/`site/` ignore rules. For a TypeScript extension that is the desired outcome; nothing needs to be added.

**The committed `package-lock.json`.** Verified tracked, and its entire history is the single add in `aa38aa0` (`git log --full-history --oneline -- editors/vscode/package-lock.json`). It is an ordinary blob and carries over intact. `filter-repo` only strips blobs when explicitly told to (`--strip-blobs-bigger-than`, `--strip-blobs-with-ids`); no size filter is used here, so the full lockfile blob history is preserved.

---

## 5. Installation and safety

### Installation (macOS)

`git-filter-repo` is **not** bundled with git. **It is already installed on this machine:**

```
$ which git-filter-repo
/opt/homebrew/bin/git-filter-repo
$ brew list --versions git-filter-repo
git-filter-repo 2.47.0
$ git --version
git version 2.55.0
```

If absent on another machine:

```bash
brew install git-filter-repo
```

Prerequisites are satisfied: the README requires `git >= 2.36.0` and `python3 >= 3.6`; GitHub's docs require `git >= 2.22.0`. Local git is 2.55.0.

### The fresh-clone rule

`filter-repo` *"abort[s] if run from a repo that is not a fresh clone (to prevent accidental data loss from rewriting local history that doesn't exist anywhere else)."* Working on a fresh clone is not a workaround for the check — it is the intended workflow, and the check exists to enforce it. The design rationale spells this out: *"Almost everyone I've ever seen do a repository filtering operation has done so with a fresh clone, because wiping out the clone in case of error is a vastly easier recovery mechanism. Strongly encourage that workflow by detecting and bailing if we're not in a fresh clone."*

**`--force` is not part of this procedure.** The man page is emphatic: *"It is a really bad idea to get in the habit of always specifying `--force`… it is definitely NOT okay to recommend `--force` on forums, Q&A sites, or in emails to other users without first carefully explaining that `--force` means putting your repositories' data at risk."* If the check trips, the correct response is **delete the clone and re-clone**, never to add `--force`. Cloning over SSH from GitHub satisfies the check natively (`--no-local` is only relevant when cloning from a local filesystem path).

### Interaction with the current Fleet working tree

**None.** The working tree at `/Users/aboutm/Code/Python/Fleet` is dirty (7 modified files) and sits on `chore/agent-skills-setup`. This is irrelevant to the procedure because every command below runs inside a throwaway clone in scratch space. Two facts confirm nothing is lost by ignoring the local state:

- None of the 7 modified files is under `editors/vscode/` (they are `STRUCTURE.md`, `docs/examples/r2r_strategy.md`, two `outputs/cdiscpilot01/*.xml`, `src/fleet/core/_verb_mixin.py`, `src/fleet/validation/lineage_join.py`, `tests/unit/test_error_experience.py`).
- Both subtree commits are ancestors of `origin/main` (`git merge-base --is-ancestor` confirms), so the local branch holds no unpushed extension work.

**Never run `git filter-repo` in `/Users/aboutm/Code/Python/Fleet`.** There is no scenario in this procedure that requires it.

---

## 6. The exact command sequence

Run top to bottom. Nothing here touches the Fleet working repo.

### Step 0 — prerequisite

```bash
command -v git-filter-repo || brew install git-filter-repo
```

### Step 1 — fresh clone into scratch space

```bash
WORK="$(mktemp -d)" && cd "$WORK"
git clone --single-branch --branch main \
    git@github.com:RealSlimMahdi/fleet-cdisc.git fleet-vscode
cd fleet-vscode
```

`--single-branch --branch main` keeps the other 20 remote branches (including `gh-pages`) out of the rewrite entirely. Fleet has zero tags, so no `--tag-rename` is needed.

### Step 2 — capture the baseline BEFORE rewriting

```bash
BASE=/tmp/fleet-vscode-baseline && mkdir -p "$BASE"

# Simplified history: what the extraction is expected to reproduce exactly.
git --no-pager log --reverse \
    --format='%an <%ae>|%aI|%cn <%ce>|%cI|%s' \
    main -- editors/vscode/ > "$BASE"/commits-simplified.txt

# Full history: the upper bound, including the merge that may be pruned.
git --no-pager log --reverse --full-history \
    --format='%an <%ae>|%aI|%cn <%ce>|%cI|%s' \
    main -- editors/vscode/ > "$BASE"/commits-full.txt

git --no-pager shortlog -sne main -- editors/vscode/ > "$BASE"/authors.txt
git --no-pager ls-tree -r --name-only main -- editors/vscode/ \
    | sed 's|^editors/vscode/||' | sort > "$BASE"/files.txt

wc -l "$BASE"/*.txt
```

Expected today: `commits-simplified.txt` = 1 line, `commits-full.txt` = 2 lines, `authors.txt` = 1 line, `files.txt` = 7 lines.

### Step 3 — the rewrite

```bash
git filter-repo --subdirectory-filter editors/vscode
```

Equivalent long form, if you prefer it spelled out:

```bash
git filter-repo --path editors/vscode --path-rename editors/vscode/:
```

No `--force`. No `--prune-empty` / `--prune-degenerate` overrides — the `auto` defaults are what you want.

### Step 4 — verify (§7) before publishing

### Step 5 — publish

```bash
gh repo create RealSlimMahdi/fleet-vscode --public --disable-wiki
git remote add origin git@github.com:RealSlimMahdi/fleet-vscode.git
git push -u origin main
```

`filter-repo` removed the `fleet-cdisc` `origin` remote and promoted `refs/remotes/origin/main` to `refs/heads/main`, so this pushes a normal branch and cannot target the source repo.

### Step 6 — clean up

```bash
cd / && rm -rf "$WORK"
```

---

## 7. Verification commands

Run these in the rewritten clone, **before** step 5.

### 7a. Authorship and dates carried, byte for byte

```bash
git --no-pager log --reverse --format='%an <%ae>|%aI|%cn <%ce>|%cI|%s' \
    > /tmp/fleet-vscode-baseline/commits-after.txt

diff /tmp/fleet-vscode-baseline/commits-simplified.txt \
     /tmp/fleet-vscode-baseline/commits-after.txt \
  && echo "PASS: author, committer, both dates and subjects identical"
```

This compares author name+email, author date (strict ISO), committer name+email, committer date and subject for every commit. It is the proof that history was *carried*, not re-created.

If it does **not** match, diff against the full-history baseline instead — a surviving merge commit is the only expected difference:

```bash
diff /tmp/fleet-vscode-baseline/commits-full.txt \
     /tmp/fleet-vscode-baseline/commits-after.txt
```

A clean match against either file is a pass. Anything else means stop, `rm -rf` the clone, and re-diagnose.

### 7b. Commit count

```bash
git --no-pager rev-list --count HEAD
```

Expected **1** (see §2 for why it is not 2). Sanity-check the bounds:

```bash
[ "$(git rev-list --count HEAD)" -ge 1 ] \
  && [ "$(git rev-list --count HEAD)" -le "$(wc -l < /tmp/fleet-vscode-baseline/commits-full.txt)" ] \
  && echo "PASS: count within [simplified, full-history] bounds"
```

### 7c. Author list

```bash
git --no-pager shortlog -sne HEAD
diff /tmp/fleet-vscode-baseline/authors.txt <(git --no-pager shortlog -sne HEAD) \
  && echo "PASS: author list identical"
```

Expected: `1  Mahdi About <mahdi.about@roche.com>`.

### 7d. Layout is at the root, and nothing leaked

```bash
git --no-pager ls-files | sort > /tmp/fleet-vscode-baseline/files-after.txt
diff /tmp/fleet-vscode-baseline/files.txt /tmp/fleet-vscode-baseline/files-after.txt \
  && echo "PASS: exactly the 7 subtree files, at the root"

# No path from any commit in history is outside the extension.
git --no-pager log --all --name-only --format= | sort -u | grep -v '^$'
```

The second command must print only the seven filenames. Any `src/fleet/…`, `docs/…` or `editors/` path means the filter did not apply.

### 7e. Content is byte-identical to the source

```bash
git --no-pager rev-parse HEAD^{tree}
# compare with, in the Fleet repo:
#   git rev-parse origin/main:editors/vscode
```

Both must print `8d20c150d8e08b55cf4c4c7d317fcb0f4869a16d` (measured 2026-08-26; identical at `origin/main` and at `aa38aa0`, since nothing has touched the subtree since). Git trees are content-addressed, so equality proves the extracted root tree is bit-for-bit the source subtree.

---

## Sources

All primary. Every claim above traces to one of these.

| # | Source | URL |
| --- | --- | --- |
| 1 | `git-filter-repo(1)` man page, v2.47.0 (read locally via `git filter-repo --help`; canonical HTML) | <https://htmlpreview.github.io/?https://github.com/newren/git-filter-repo/blob/docs/html/git-filter-repo.html> |
| 2 | `git-filter-repo` README — prerequisites, installation, design rationale | <https://github.com/newren/git-filter-repo/blob/main/README.md> |
| 3 | `git-filter-repo` — *Cheat Sheet: Converting from filter-branch* | <https://github.com/newren/git-filter-repo/blob/main/Documentation/converting-from-filter-branch.md> |
| 4 | `git-filter-branch(1)` man page — `WARNING`, `SAFETY`, `PERFORMANCE` | <https://git-scm.com/docs/git-filter-branch> |
| 5 | `git-subtree(1)` man page source | <https://github.com/git/git/blob/master/contrib/subtree/git-subtree.adoc> |
| 6 | GitHub Docs — *Splitting a subfolder out into a new repository* | <https://docs.github.com/en/get-started/using-git/splitting-a-subfolder-out-into-a-new-repository> |

Repository measurements in §2 and §5 were taken with read-only `git` commands against `/Users/aboutm/Code/Python/Fleet` on 2026-08-26. No history-rewriting command was executed.
