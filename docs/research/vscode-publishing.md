# VS Code extension repo conventions and publish prerequisites

**Research ticket:** [RealSlimMahdi/fleet-cdisc#57](https://github.com/RealSlimMahdi/fleet-cdisc/issues/57)
**Date of research:** 2026-08-26
**Subject:** extracting `editors/vscode/` (a 65-line TypeScript LSP client) into a standalone repo `RealSlimMahdi/fleet-vscode`, publisher id `fleet-vscode`, publish-**ready** but **not** published.

Every claim below is followed by the primary source that owns it. No secondary write-ups were used.

---

## 0. Executive summary of things that constrain repo layout or CI design

| Constraint | Consequence |
| --- | --- |
| Global Azure DevOps PATs retire **2026-12-01** | A `VSCE_PAT` secret is a dead end. Design CI around `vsce publish --oidc` (GitHub Actions trusted publishing) from day one. |
| `vsce publish --oidc` needs `permissions: id-token: write` and a Marketplace trusted-publishing policy pinned to *repo + workflow* | The publishing workflow file **name and path are part of the trust policy**. Pick `.github/workflows/publish.yml` and don't rename it later. |
| `@vscode/test-cli` and `@vscode/test-electron` both declare `engines.node >= 22` | CI matrix must use Node 22+. `actions/setup-node` with `node-version: 22`. |
| Extension Host tests need a display on Linux | `xvfb-run -a npm test` on `ubuntu-latest`, plain `npm test` elsewhere. |
| `vsce` refuses to package if `main`/`browser` exists without `activationEvents` (below 1.74 semantics) and vice-versa | The activation-events block interacts with `engines.vscode`. See §6. |
| `vscode-languageclient@9.0.1` declares `engines.vscode: ^1.82.0` | The current manifest's `engines.vscode: ^1.75.0` is **wrong**. See §5.1. |
| Open VSX needs an Eclipse account + signed Publisher Agreement before *anything* can be published | This is a human, days-scale prerequisite. Start it early if Cursor/VSCodium reach matters. |
| `.vscodeignore` and `package.json` `"files"` are **mutually exclusive** in vsce | Pick one. `.vscodeignore` is the conventional choice. |

---

## 1. Publisher creation

### 1.1 The flow

A publisher is created **in the Marketplace web UI**, not by a CLI:

1. Go to <https://marketplace.visualstudio.com/manage>.
2. Log in with the same Microsoft account used to create the Personal Access Token.
3. Click **Create publisher**.
4. Supply the mandatory **ID** and **Name**. "ID: the unique identifier for your publisher in Marketplace that will be used in your extension URLs. **ID cannot be changed once created.**"
5. Verify with `vsce login <publisher id>`.

Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Create a publisher")

The `vsce create-publisher` command **no longer exists**. vsce prints: `The 'create-publisher' command is no longer available. You can create a publisher directly in the Marketplace: https://aka.ms/vscode-create-publisher`.
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/main.ts> (`program.on('command:*')` handler)

An Azure DevOps organization is a prerequisite for the PAT route: "If you don't have an Azure DevOps organization yet, follow the steps in the *Create an organization* article."
Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Get a Personal Access Token")

### 1.2 Is `fleet-vscode` claimable?

vsce validates publisher ids against `^[a-z0-9][a-z0-9\-]*$` (case-insensitive). `fleet-vscode` matches — it is a **syntactically valid** publisher id.
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/validation.ts> (`nameRegex`, `validatePublisher`)

Availability probes run 2026-08-26:

| Probe | Result |
| --- | --- |
| `GET https://marketplace.visualstudio.com/publishers/fleet-vscode` | `404` |
| `GET https://marketplace.visualstudio.com/publishers/fleet-cdisc` | `404` |
| Marketplace `extensionquery` API, `Microsoft.VisualStudio.Code` target + search text `fleet-vscode` | `0` matches |
| `GET https://open-vsx.org/api/fleet-vscode` | `404` (namespace does not exist) |
| `GET https://open-vsx.org/api/fleet-cdisc` | `404` (namespace does not exist) |

Marketplace gallery API used for the query: `POST https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery`, the same endpoint vsce itself uses.
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/publicgalleryapi.ts>

**Verdict: `fleet-vscode` appears claimable on both registries, with one caveat.** A 404 on `/publishers/<id>` proves no *published extensions* exist under that id; it does **not** definitively prove the id is unreserved, because a publisher created with zero published extensions may not be publicly listed. The only authoritative check is attempting **Create publisher** at <https://marketplace.visualstudio.com/manage>. The Open VSX 404 *is* authoritative for that registry — the wiki states "If you are unable to create the namespace, it is likely because it already exists."
Source: <https://github.com/EclipseFdn/open-vsx.org/wiki/Publishing-Extensions> ("2. Create the namespace")

⚠️ Also note: the current manifest declares `"publisher": "fleet-cdisc"`, but the ticket specifies `fleet-vscode`. This must be changed before packaging, and **`vsce` will not warn about it** — a wrong-but-valid publisher id packages fine and only fails at publish time with 403.

### 1.3 Verified publisher (the blue check)

Requires domain ownership verification, and has a hard time gate:

> "To become verified, a publisher must have one or more extensions on the VS Marketplace for a minimum of **6 months**, and the registration of the domain must also be at least **6 months old**."

Flow: Manage page → select publisher → **Details** tab → enter eligible domain → **Save** then **Verify** → add the supplied TXT record to DNS → click **Verify** in the dialog. "Once your TXT record has been validated, the Marketplace team will review your request and let you know the result **within 5 business days**."

Eligible domains must satisfy all of:
- You can manage DNS and add a TXT record.
- It is **not a subdomain** (`{subdomain}.github.io`, `{subdomain}.contoso.com` etc. are ineligible).
- It uses HTTPS.
- It responds `HTTP 200` to a `HEAD` request.

Revocation triggers: "Any changes to the publisher display name will revoke the verified badge."

Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Verify a publisher", "Eligible domains")

**Implication for this ticket:** verification is out of reach for a not-yet-published extension. It is a ≥6-month-later item, and the `github.io` exclusion means a docs site on GitHub Pages under a subdomain won't qualify.

---

## 2. Credentials

### 2.1 PAT scopes (the legacy route)

When creating the token in the Azure DevOps portal:
- **Organization:** *All accessible organizations* (not a specific org).
- **Scopes:** Custom defined → *Show all scopes* → **Marketplace** → **Manage**.

Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Get a Personal Access Token")

The two common failure modes are explicitly documented: "One easy mistake to make when creating the PAT is to select a specific organization instead of *All accessible organizations*… Another possible mistake is incorrect scope — you should set the Authorized Scopes to `Marketplace (Manage)`."
Source: same page, "I get 403 Forbidden (or 401 Unauthorized) error…"

### 2.2 PATs are being retired

> **Important:** "On December 1, 2026, global Personal Access Tokens (PATs) in Azure DevOps are retired. To keep publishing extensions, use secure automated publishing with Microsoft Entra ID instead of PATs."

Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Publishing extensions")
Underlying announcement: <https://devblogs.microsoft.com/devops/retirement-of-global-personal-access-tokens-in-azure-devops/>

### 2.3 Storing a PAT as a GitHub Actions secret (documented but discouraged)

1. Set up `VSCE_PAT` as an encrypted repository secret.
2. Install `vsce` as a `devDependency`.
3. Declare a `deploy` script that does **not** embed the token (vsce reads `VSCE_PAT` from the environment).
4. Gate the publish step:

```yaml
- name: Publish
  if: success() && startsWith(github.ref, 'refs/tags/') && matrix.os == 'ubuntu-latest'
  run: npm run deploy
  env:
    VSCE_PAT: ${{ secrets.VSCE_PAT }}
```

Source: <https://code.visualstudio.com/api/working-with-extensions/continuous-integration> ("GitHub Actions automated publishing")

### 2.4 ✅ A federated/OIDC option **does** now exist for GitHub Actions

This is the single most important finding for CI design. `@vscode/vsce` supports **trusted publishing** with no long-lived secret:

```yaml
jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci
      - run: npx @vscode/vsce publish --oidc
```

> "`vsce publish --oidc` publishes from GitHub Actions without storing a Personal Access Token. Configure a trusted publishing policy for the repository and workflow on the Visual Studio Marketplace, then grant the workflow permission to request an OIDC token… OIDC publishing requests a GitHub Actions token for the `marketplace.visualstudio.com` audience and exchanges it for a short-lived Marketplace credential. **It does not fall back to a PAT** when token acquisition or exchange fails."

Source: <https://github.com/microsoft/vscode-vsce/blob/main/README.md> ("Trusted publishing")

Mechanics, from the implementation:
- Audience constant: `OIDC_AUDIENCE = 'marketplace.visualstudio.com'`.
- Only GitHub Actions is supported: `'No supported OIDC provider was detected. OIDC publishing currently supports GitHub Actions only.'`
- It reads `ACTIONS_ID_TOKEN_REQUEST_URL` / `ACTIONS_ID_TOKEN_REQUEST_TOKEN`; if absent it errors with `'…Add permissions: id-token: write to the workflow or job.'`
- It POSTs the ID token to `<marketplace>/_apis/gallery/token` with body `{ publisherName }` and receives a short-lived `credential`.
- A missing policy surfaces as `Marketplace OIDC token exchange failed with 401 Unauthorized: No matching trusted publishing policy.`

Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/oidc.ts>, <https://github.com/microsoft/vscode-vsce/blob/main/src/test/oidc.test.ts>

⚠️ **Caveat worth recording:** the `--oidc` flag is registered with `.conflicts(['pat','azureCredential'])` **and `.hideHelp(true)`** — it does not appear in `vsce --help`, and it is not yet documented on code.visualstudio.com. Treat it as functional-but-soft-launched; keep the PAT path documented as a fallback in the repo's RELEASING notes.
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/main.ts>

### 2.5 The Entra ID / workload-identity route (Azure Pipelines only)

VS Code's own recommendation is `vsce publish --azure-credential` backed by workload identity federation + a user-assigned managed identity, added as a **Contributor** member of the publisher. The documented walkthrough is entirely Azure Pipelines–shaped (Service Connections, `AzureCLI@2` tasks) and requires `vsce >= v2.26.1`.

Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Secure automated publishing to Visual Studio Marketplace")

For a GitHub-hosted repo, `--oidc` is the right tool; `--azure-credential` would mean standing up Azure DevOps + Azure infrastructure for one 65-line extension.

---

## 3. Manifest requirements

### 3.1 Mandatory vs optional

Only four fields are marked required in the manifest reference:

| Field | Required | Notes |
| --- | --- | --- |
| `name` | **Y** | all lowercase, no spaces, unique in Marketplace |
| `version` | **Y** | SemVer-compatible |
| `publisher` | **Y** | the publisher identifier |
| `engines` | **Y** | must contain `vscode`; **cannot be `*`** |

Source: <https://code.visualstudio.com/api/references/extension-manifest> ("Fields")

Everything else — `license`, `displayName`, `description`, `categories`, `keywords`, `galleryBanner`, `icon`, `badges`, `qna`, `sponsor`, `pricing`, `repository`, `bugs`, `homepage`, `markdown`, `preview`, `capabilities` — is optional *in the schema*. Several of them, however, produce vsce warnings or blocking prompts (§4).

### 3.2 Field-by-field, as asked in the ticket

**`icon`** — "The path to the icon of at least **128x128 pixels** (256x256 for Retina screens)." The publishing guide restates: "Set an icon by specifying a relative path to a **PNG** file of at least 128x128px."
SVG is a **hard error**, not a warning: `SVGs can't be used as icons: ${manifest.icon}`. And a declared icon that isn't packaged is also a hard error: `The specified icon '<path>' wasn't found in the extension.`
Sources: <https://code.visualstudio.com/api/references/extension-manifest>; <https://code.visualstudio.com/api/working-with-extensions/publishing-extension>; <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts> (`validateManifestForPackaging`, `IconProcessor`)

**`galleryBanner`** — `{ "color": "#C80000", "theme": "dark" }`. "The `theme` attribute refers to the font to be used in the banner — `dark` or `light`."
Source: <https://code.visualstudio.com/api/references/extension-manifest> ("Marketplace Presentation Tips")

**`categories`** — allowed values are a closed set: `Programming Languages, Snippets, Linters, Themes, Debuggers, Formatters, Keymaps, SCM Providers, Other, Extension Packs, Language Packs, Data Science, Machine Learning, Visualization, Notebooks, Education, Testing`. "Use `Programming Languages` for general language features like syntax highlighting and code completions." `Language Packs` is reserved for display-language extensions.
Source: <https://code.visualstudio.com/api/references/extension-manifest>
→ The current `["Programming Languages", "Linters"]` is valid and appropriate for a diagnostics + completions LSP client.

**`keywords`** — "This list is currently limited to **30** keywords." Exceeding it produces `You exceeded the number of allowed tags of 30`.
Sources: <https://code.visualstudio.com/api/references/extension-manifest>; <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Common questions")

**`badges`** — array of `{ url, href, description }`. Only badges from an allow-list of trusted hosts are permitted, and non-HTTPS or untrusted-SVG badge URLs throw at package time. The allow-list (from both the docs and the vsce source `TrustedSVGSources`) includes: `api.travis-ci.com`, `app.fossa.io`, `badge.buildkite.com`, `badge.fury.io`, `badgen.net`, `badges.frapsoft.com`, `badges.gitter.im`, `cdn.travis-ci.com`, `ci.appveyor.com`, `circleci.com`, `cla.opensource.microsoft.com`, `codacy.com`, `codeclimate.com`, `codecov.io`, `coveralls.io`, `david-dm.org`, `deepscan.io`, `dev.azure.com`, `docs.rs`, `flat.badgen.net`, **`github.com` (from Workflows only)**, `gitlab.com`, `godoc.org`, `goreportcard.com`, `img.shields.io`, `isitmaintained.com`, `marketplace.visualstudio.com`, `nodesecurity.io`, `opencollective.com`, `snyk.io`, `travis-ci.com`, `visualstudio.com`, `vsmarketplacebadges.dev`.
Sources: <https://code.visualstudio.com/api/references/extension-manifest> ("Approved Badges"); <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts> (`TrustedSVGSources`)
→ Practical rule: `img.shields.io` and `marketplace.visualstudio.com` badges are safe; a GitHub Actions status badge is safe **only** in the `.../actions/workflows/<name>/badge.svg` (or legacy `.../workflows/<name>/badge.svg`) form.

**`qna`** — `marketplace` (default) | a custom URL string | `false` to disable. Note vsce's behaviour when unset: if `repository` points at GitHub and `qna` is omitted, neither `EnableMarketplaceQnA` nor `CustomerQnALink` is emitted — i.e. GitHub-hosted extensions do **not** silently get the Marketplace Q&A tab.
Sources: <https://code.visualstudio.com/api/references/extension-manifest>; <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts> (`ManifestProcessor`) and its tests
→ For a repo with GitHub Issues enabled, `"qna": false` is the honest setting; it routes users to `bugs.url` instead of a dead Q&A tab.

**`sponsor`** — `{ "url": "https://…" }`. Requires **`vsce >= 2.9.1`**. vsce validates the URL and rejects non-URL strings (`hello`, `www.foo.com`); `https://` and `http://www…` forms are accepted.
Sources: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Extension Sponsor"); vsce test `should validate sponsor`

**`pricing`** — `Free` | `Trial`, case-sensitive; default `Free`. Requires **`vsce >= 2.10.0`**. Anything else is a hard error: `Pricing can only be "Free" or "Trial"`.
Sources: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Extension pricing label"); <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts>

**`repository` / `bugs` / `homepage`** — "There are several optional links (`bugs`, `homepage`, `repository`) you can set and these are displayed under the **Resources** section of the Marketplace." The mapping is `Issues → bugs:url`, `Repository → repository:url`, `Homepage → homepage`, `License → license`.
Source: <https://code.visualstudio.com/api/references/extension-manifest>
`repository` does triple duty: Resources link, **automatic relative-link rewriting in README** (§4), and GitHub issue-reference expansion. A missing `repository` triggers an interactive vsce prompt (§4).

**`license`** — "If you do have a LICENSE file in the root of your extension, the value for `license` should be `"SEE LICENSE IN <filename>"`." vsce otherwise auto-detects `LICENSE`, `LICENSE.md`, `LICENSE.txt` (and, per its tests, the British spelling `LICENCE.md`).
Sources: <https://code.visualstudio.com/api/references/extension-manifest>; <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts> (`LicenseProcessor`)

**`markdown`** — `github` (default) or `standard`. Controls the Marketplace's Markdown rendering engine.
Source: <https://code.visualstudio.com/api/references/extension-manifest>

**Name uniqueness** — both `name` and `displayName` must be unique across the whole Marketplace: `ERROR The extension 'name' already exists in the Marketplace.` "The same rule applies for the display name."
Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Common questions")
→ ⚠️ The current `displayName` is `"Fleet CDISC"`. Worth checking for collisions before the first publish, since it is an unrecoverable rename afterwards.

**Name removal is irreversible** — "Once an extension is removed, its extension name is **permanently reserved and cannot be reused, even by the original publisher**."
Source: same page, "Removing extensions"

### 3.3 Version and pre-release rules

- Pre-release versions in the SemVer sense are rejected at publish: `The VS Marketplace doesn't support prerelease versions: '<v>'`.
  Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/publish.ts> (`validateManifestForPublishing`)
- The `--pre-release` *channel* is separate and supports only `major.minor.patch`. Recommendation: "extensions use `major.EVEN_NUMBER.patch` for release versions and `major.ODD_NUMBER.patch` for pre-release versions." Pre-release requires `engines.vscode >= 1.63.0`.
  Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Pre-release extensions")
- A specific published version can be deleted, but "you can't reuse this version number for a new publish" and "you cannot delete the latest version of an extension."
  Source: same page, "Removing specific extension versions"

---

## 4. `vsce ls` / `vsce package` warnings and `.vscodeignore`

### 4.1 `.vscodeignore` guidance

> "You should ignore all files not needed at runtime. For example, if your extension is written in TypeScript, you should ignore all `**/*.ts` files… **Development dependencies listed in `devDependencies` will be automatically ignored**, so you don't need to add them explicitly."

Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Using .vscodeignore")

For a bundled extension the recommended file is:

```
.vscode
node_modules
out/
src/
tsconfig.json
webpack.config.js
esbuild.js
```

Source: <https://code.visualstudio.com/api/working-with-extensions/bundling-extension> ("Publishing")

Bundling matters beyond size: "**Only bundled extensions can be used in VS Code for Web** environments like github.dev and vscode.dev."
Source: same page (intro)

### 4.2 Exactly what `vsce package` complains about

From `printAndValidatePackagedFiles` and the processors in <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts>:

**Warnings (non-fatal, printed):**
- *No ignore strategy at all*: "Neither a `.vscodeignore` file nor a `"files"` property in package.json was found. To ensure only necessary files are included in your extension, add a .vscodeignore file or specify the "files" property in package.json. More info: https://aka.ms/vscode-vscodeignore"
- *Too many files*: triggered when `files.length > 5000` **or** `jsFiles.length > 100` — "For performance reasons, you should bundle your extension: https://aka.ms/vscode-bundle-extension."
- *Large single file*: the tree output appends `The file <path> is large (<size>)` when one file exceeds **85 %** of the package's total bytes. Files over 20 % are coloured yellow, over 85 % red.
  Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/util.ts> (`FILE_SIZE_WARNING_THRESHOLD = 0.85`, `FILE_SIZE_LARGE_THRESHOLD = 0.2`)
- *`extensionKind` as a string*: "The `extensionKind` property should be of type `string[]`."

**Warnings that become blocking prompts** (`Do you want to continue? [y/N]` — which in non-TTY CI auto-answers `y`, but in an interactive terminal will hang a release):
- **`*` activation**: "Using `'*'` activation is usually a bad idea as it impacts performance… Use `--allow-star-activation` to bypass."
- **Missing `repository`**: "A `'repository'` field is missing from the `'package.json'` manifest file. Use `--allow-missing-repository` to bypass."
- **Missing LICENSE**: warns `LICENSE, LICENSE.md, or LICENSE.txt not found` (or the exact filename from `SEE LICENSE IN …`), bypass with `--skip-license`.

Note the prompt short-circuits: `read()` returns `'y'` automatically when `process.stdout` is not a TTY. So CI will silently proceed; a developer's terminal will not.
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/util.ts> (`read`)

**Hard errors / `process.exit(1)`:**
- Both `.vscodeignore` **and** `"files"` present: "VSCE does not support combining both strategies."
- A `"files"` include pattern that matches nothing — bypass `--allow-unused-files-pattern`.
- Secret detection (secretlint): private keys, npm tokens etc. — bypass `--allow-package-secrets <name>` / `--allow-package-all-secrets`.
- A packaged `.env` file — bypass `--allow-package-env-file`.
- Two files differing only in case: "The following files have the same case insensitive path, which isn't supported by the VSIX format."
- The `main` entry point not actually present in the package (`LaunchEntryPointProcessor`).
- Publisher `vscode-samples` is forbidden outright.

### 4.3 `vsce ls`

`vsce ls` "Lists all the files that will be published/packaged"; `vsce ls --tree` prints a size-annotated tree. `vsce package` itself prints "Files included in the VSIX:" capped at 35 entries and then tells you to run `vsce ls --tree` for the rest.
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/main.ts>, <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts>

### 4.4 Toolchain requirements

- vsce README: "[Node.js] at least **`22.x.x`**". The published `@vscode/vsce@3.9.2` package declares `engines.node: >= 20`. Use **Node 22** to satisfy both.
  Sources: <https://github.com/microsoft/vscode-vsce/blob/main/README.md>; `https://registry.npmjs.org/@vscode/vsce` (`dist-tags.latest` = `3.9.2`, checked 2026-08-26)
- Supported package managers: `npm >= 6`, `yarn >= 1 < 2`. The docs restate: "You can either use npm or **yarn v1**."
  Sources: vsce README; <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Common questions")
- On Linux, vsce stores credentials via `@napi-rs/keyring`; `VSCE_STORE=file` or using `VSCE_PAT` avoids the system credential store. Relevant if anyone runs vsce inside a container.
  Source: vsce README ("Linux")
- "when building and publishing your extension from **Windows**, all the files included in the extension package will lack POSIX file attributes, namely the executable bit… Publishing from Linux and macOS works as expected."
  Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Common questions")
  → Another reason to pin the publish job to `ubuntu-latest`.

---

## 5. `engines.vscode`

### 5.1 ⚠️ The current declaration is inconsistent with its own dependency

`editors/vscode/package.json` declares `engines.vscode: ^1.75.0` and `dependencies: { "vscode-languageclient": "^9.0.1" }`.

`vscode-languageclient@9.0.0` and `9.0.1` both declare `engines: { "vscode": "^1.82.0" }`.
Source: `https://registry.npmjs.org/vscode-languageclient` (checked 2026-08-26)

So the extension advertises compatibility with VS Code 1.75–1.81 while depending on a client library that requires 1.82+. Either raise `engines.vscode` to `^1.82.0` (minimum) or move to `vscode-languageclient@10.x`, which requires `^1.91.0`.

### 5.2 `@types/vscode` is checked against `engines.vscode`

vsce validates that `devDependencies["@types/vscode"]` is not *newer* than `engines.vscode`, "enforced at the major and minor level" (patch is ignored because DefinitelyTyped auto-increments it).
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/validation.ts> (`validateVSCodeTypesCompatibility`)
→ Keep `@types/vscode` pinned to the same major.minor as `engines.vscode`. (Latest published is `1.134.0` as of 2026-08-26.)

### 5.3 Semantics

- `1.8.0` = that exact version only; `^1.8.0` = that version and onwards.
- `engines.vscode` "Cannot be `*`."
Sources: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Visual Studio Code compatibility"); <https://code.visualstudio.com/api/references/extension-manifest>

---

## 6. Activation events

### 6.1 Are `workspaceContains:**/define.yaml` + `onLanguage:yaml` still idiomatic?

**Yes — both are still required here, and neither is redundant.**

The 1.74 implicit-activation change is narrower than it is often assumed to be. The docs state it only for events that mirror something the extension **contributes**:

> "Beginning with VS Code 1.74.0, **languages contributed by your extension** do not require a corresponding `onLanguage` activation event declaration."

and equivalently for `onCommand` (contributed commands), `onView` (contributed views), `onCustomEditor`, `onAuthenticationRequest`, and — from 1.76.0 — `onTaskType`.
Source: <https://code.visualstudio.com/api/references/activation-events>

The Fleet extension **does not contribute a `yaml` language** — `yaml` comes from another extension or from VS Code's built-in language contributions. Therefore `onLanguage:yaml` is **not** implicit and must stay declared.

`workspaceContains` has **no** implicit form at all. It is documented plainly: "`workspaceContains:path` is emitted and interested extensions will be activated whenever a folder is opened and the folder contains at least one file that matches a glob pattern."
Source: same page

vsce confirms the narrowness in code: only `contributes.languages`, `contributes.commands`, `contributes.authentication`, `contributes.customEditors` and `contributes.views` count as implicit activation events, and only when `engines.vscode` is `*` or satisfies `>=1.74`.
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts> (`validateManifestForPackaging`)

### 6.2 What *would* trigger a `vsce package` warning or error

- `"*"` in `activationEvents` → the blocking `--allow-star-activation` prompt (§4.2). **The current manifest does not use `*`, so no warning.**
- Having `main` (or `browser`) with **no** `activationEvents` and no implicit contributions → hard error: `Manifest needs the 'activationEvents' property, given it has a 'main' property.`
- Having `activationEvents` but **no** `main`/`browser` → hard error: `Manifest needs either a 'main' or 'browser' property, given it has a 'activationEvents' property.`
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts>

**Conclusion:** `["workspaceContains:**/define.yaml", "onLanguage:yaml"]` packages cleanly and warns about nothing. It is also the *better* design than `onStartupFinished` or `*` — the docs say "It is best practice to activate only when a user needs your extension. If your extension works on a subset of languages, it is better for the user to list that subset than to activate on all languages."

One refinement worth considering: `onLanguage:yaml` fires on *every* YAML file the user opens, in every workspace, whether or not it's a Fleet spec. If the client only ever does anything useful for Fleet `define.yaml` files, `workspaceContains:**/define.yaml` alone would be a lighter footprint. That is a design call, not a packaging blocker.

---

## 7. README rendering rules

### 7.1 What the Marketplace renders

> "Have a `README.md` Markdown file in your extension's root folder and we will include the contents in the body of the extension details (on the Marketplace). You can provide relative path image links in the `README.md`."

Rendering engine is selected by the `markdown` field: `github` (default) or `standard`.
Sources: <https://code.visualstudio.com/api/references/extension-manifest> ("Marketplace Presentation Tips", "Fields")

Also picked up automatically from the extension root, each as a separate Marketplace asset: `LICENSE`, `CHANGELOG.md`, `SUPPORT.md`.
Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Marketplace integration")

### 7.2 What is rejected outright

vsce refuses to publish any of these — these are `throw`s, not warnings:

- **Non-HTTPS images**: `Images in README.md must come from an HTTPS source: <src>` (applies to both Markdown `![]()` and raw `<img>`/`<video>` tags).
- **SVG images from untrusted hosts**: `SVGs are restricted in README.md; please use other file image formats, such as PNG: <src>`. The trusted-host list is the same badge allow-list from §3.2. Notably `https://github.com/<user>/<repo>/blob/…/x.svg` is **rejected**, while `https://github.com/<user>/<repo>/actions/workflows/<wf>/badge.svg` is allowed.
- **Inline `<svg>` tags**: `SVG tags are not allowed in README.md.`
- **SVG data URLs**: `SVG data URLs are not allowed in README.md: <src>`.
- **Images with no `src`**: `Images in README.md must have a source.`
- **Leftover template text**: any README containing the string `This is the README for your extension ` throws `It seems the README.md still contains template text. Make sure to edit the README.md file before you package or publish your extension.`

Sources: <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts> (`MarkdownProcessor.processFile`); the summary in <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Publishing extensions") confirms: image URLs "need to resolve to `https` URLs" and may not be SVGs unless from trusted badge providers.

### 7.3 Relative links and images

vsce **rewrites** relative links and image sources at package time, using the `repository` field:

> "If you have a `repository` property in your `package.json` that points to a public GitHub repository, `vsce` will automatically detect it and adjust relative links accordingly, **using the `main` branch by default**. You can override this with the `--githubBranch` flag… You can also set base URLs for links and images with the `--baseContentUrl` and `--baseImagesUrl` flags."

Source: <https://code.visualstudio.com/api/working-with-extensions/publishing-extension> ("Marketplace integration")

If it cannot infer a base URL, a relative link is a **hard error**:

> `Couldn't detect the repository where this extension is published. The <link|image> '<x>' will be broken in README.md. GitHub/GitLab repositories will be automatically detected. Otherwise, please provide the repository URL in package.json or use the --baseContentUrl and --baseImagesUrl options.`

Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts>

Relevant flags: `--githubBranch`, `--gitlabBranch`, `--baseContentUrl`, `--baseImagesUrl`, and `--no-rewrite-relative-links` to opt out entirely.
Source: <https://github.com/microsoft/vscode-vsce/blob/main/src/main.ts>

⚠️ **Repo-layout consequence:** the new repo's default branch determines whether relative README links resolve. vsce defaults to `main`. If `fleet-vscode` uses a different default branch, the publish workflow must pass `--githubBranch <name>`.

### 7.4 Issue-reference expansion

For GitHub/GitLab repos, vsce expands `#123` and `owner/repo#123` in README/CHANGELOG into real issue links. Disable with `--no-gitHubIssueLinking` / `--no-gitLabIssueLinking`.
Sources: <https://github.com/microsoft/vscode-vsce/blob/main/src/main.ts>, <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts>

### 7.5 Badge conventions

Badges reach the Marketplace two ways: the `badges` manifest array (rendered in the Marketplace **sidebar**) and plain Markdown images in the README (rendered in the body). Both are subject to the HTTPS + trusted-SVG-host rules. The docs specifically note: "Replace `vsmarketplacebadge.apphb.com` badge with `vsmarketplacebadges.dev` badge."
Source: <https://code.visualstudio.com/api/references/extension-manifest> ("Approved Badges")

---

## 8. Testing

### 8.1 `@vscode/test-cli` vs `@vscode/test-electron` — current state

They are **complementary, not alternatives**. The official quick-setup instruction installs both:

```bash
npm install --save-dev @vscode/test-cli @vscode/test-electron
```

> "To get started, you'll want to first install the `@vscode/test-cli` module, as well as `@vscode/test-electron` module **that enables tests to be run in VS Code Desktop**."

Source: <https://code.visualstudio.com/api/working-with-extensions/testing-extension> ("Quick Setup: The test CLI")

- `@vscode/test-cli` is the **configuration-driven runner** — "It provides a simple, configuration-driven interface for running tests, and has its own VS Code extension that allows running tests in the UI. The CLI **exclusively uses Mocha** under the hood." It exposes the `vscode-test` binary and reads `.vscode-test.{js,mjs,cjs,json}`.
- `@vscode/test-electron` is the **lower-level library** (`runTests`, `downloadAndUnzipVSCode`, `resolveCliArgsFromVSCodeExecutablePath`) used when you need a custom runner — e.g. installing another extension before the run, or a non-Mocha framework.

The docs frame these as "Quick Setup: The test CLI" vs "**Advanced setup: Your own runner**". For a 65-line LSP client, the test CLI is the correct choice.
Sources: <https://code.visualstudio.com/api/working-with-extensions/testing-extension>; <https://github.com/microsoft/vscode-test-cli/blob/main/README.md>

Minimal config:

```js
// .vscode-test.mjs
import { defineConfig } from '@vscode/test-cli';

export default defineConfig({ files: 'out/test/**/*.test.js' });
```

Documented options: `files` (**required**), `version` (defaults to `stable`), `workspaceFolder`, `extensionDevelopmentPath` (defaults to the config file's directory), `mocha`, `label`, `launchArgs`, `installExtensions`. Multiple configs run sequentially and can be filtered with `vscode-test --label <name>`. `extensionDependencies` from `package.json` are installed automatically.
Sources: <https://code.visualstudio.com/api/working-with-extensions/testing-extension>; <https://github.com/microsoft/vscode-test-cli/blob/main/README.md>; config schema at <https://github.com/microsoft/vscode-test-cli/blob/main/src/config.cts>

Scripts and debug config:

```json
"scripts": {
  "compile-tests": "tsc -p . --outDir out",
  "pretest": "npm run compile-tests",
  "test": "vscode-test"
}
```

```jsonc
{
  "type": "extensionHost",
  "request": "launch",
  "name": "My extension tests",
  "testConfiguration": "${workspaceFolder}/.vscode-test.js",
  "args": ["--extensionDevelopmentPath=${workspaceFolder}"]
}
```

Sources: <https://code.visualstudio.com/api/working-with-extensions/bundling-extension> ("Tests"); <https://github.com/microsoft/vscode-test-cli/blob/main/README.md> ("Debugging")

Companion editor extension for running tests from the Testing view: `ms-vscode.extension-test-runner`.
Source: <https://code.visualstudio.com/api/working-with-extensions/testing-extension>

**Node version:** `@vscode/test-cli@0.0.15` and `@vscode/test-electron@3.1.0` both declare `engines.node: >=22`.
Source: `https://registry.npmjs.org/@vscode/test-cli`, `https://registry.npmjs.org/@vscode/test-electron` (checked 2026-08-26)

### 8.2 GitHub Actions OS matrix, with the Linux `xvfb` requirement

The documented workflow, verbatim in shape:

```yaml
on:
  push:
    branches:
      - main

jobs:
  build:
    strategy:
      matrix:
        os: [macos-latest, ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Install Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 18.x   # ← raise to 22.x, see §8.1
      - run: npm install
      - run: xvfb-run -a npm test
        if: runner.os == 'Linux'
      - run: npm test
        if: runner.os != 'Linux'
```

> "In headless Linux CI machines **`xvfb` is required to run VS Code**, so if Linux is the current OS run the tests in an Xvfb enabled environment."

Source: <https://code.visualstudio.com/api/working-with-extensions/continuous-integration> ("GitHub Actions")

Note the docs' sample pins `node-version: 18.x`; that predates the `>=22` engines requirements in §8.1. Use `22.x`.

Docker/self-hosted variants additionally need `libasound2 libgbm1 libgtk-3-0 libnss3 xvfb` — useful to know if the CI ever moves to a container.
Source: same page ("GitLab CI")

### 8.3 The "no other instance of Code is running" trap

> "if you are using VS Code stable release and try to run the integration test on CLI, it will throw an error: `Running extension tests from the command line is currently only supported if no other instance of Code is running.`"

Workarounds: develop in Insiders and run tests against Stable, or run tests from the debug launch configuration. Also pass `--disable-extensions` (via `launchArgs`) so locally installed extensions don't perturb the run.
Source: <https://code.visualstudio.com/api/working-with-extensions/testing-extension> ("Tips")
→ Not a CI problem, but it *is* a contributor-docs problem. Put it in CONTRIBUTING.md.

---

## 9. Open VSX (Cursor / VSCodium reach)

Publishing to Open VSX requires meaningfully more setup than the Marketplace, and most of it is human and asynchronous.

### 9.1 One-time prerequisites

1. **Create an eclipse.org account.** "It is important to fill in the GitHub Username field and to use exactly the same GitHub account as when you log in to open-vsx.org."
2. **Sign the Publisher Agreement.** Log in to open-vsx.org with GitHub → Settings → *Log in with Eclipse* → *Show Publisher Agreement* → read to the bottom → *Agree*. (This is **not** the ECA.)
3. **Create an access token** at <https://open-vsx.org/user-settings/tokens>. "We recommend to generate a new token for each environment… Note that the value is never displayed again after you close the dialog!"
4. **Create the namespace**: `npx ovsx create-namespace fleet-vscode -p <token>`. Valid namespace names may contain only letters, numbers, and `-`, `+`, `$`, `~`. "If you are unable to create the namespace, it is likely because it already exists. You will not be able to use this namespace."

Source: <https://github.com/EclipseFdn/open-vsx.org/wiki/Publishing-Extensions>

### 9.2 Namespace ownership ≠ namespace creation

> "Creating a namespace does **not** automatically give you the exclusive publishing rights. Initially, everyone will be able to publish an extension with the new namespace."

Until ownership is claimed, published extensions carry the warning label *"That user account is not a verified publisher of the namespace."* Ownership is requested separately via the Managing Namespaces process.
Sources: <https://github.com/eclipse/openvsx/blob/master/cli/README.md> ("Create a Namespace"); <https://github.com/EclipseFdn/open-vsx.org/wiki/Publishing-Extensions> ("7. Namespace Creation and Ownership"); <https://github.com/EclipseFdn/open-vsx.org/wiki/Managing-Namespaces>

### 9.3 Publishing

```bash
npx ovsx publish -p <token>              # build + publish from source
npx ovsx publish <file.vsix> -p <token>  # publish a prebuilt VSIX
```

Token can be supplied via `--pat`/`-p` or the **`OVSX_PAT`** environment variable. `ovsx` "uses `vsce` internally to package extensions, which runs the `vscode:prepublish` script." Before uploading it checks the package size against the registry limit reported by `/api/version`, rejecting oversize packages locally.
Source: <https://github.com/eclipse/openvsx/blob/master/cli/README.md>

The wiki explicitly warns against hand-rolled VSIXes: "Using other methods to compress and package files to produce a `.vsix` file is unreliable and is not supported."
Source: <https://github.com/EclipseFdn/open-vsx.org/wiki/Publishing-Extensions>

### 9.4 ✅ Open VSX also supports OIDC trusted publishing

```yaml
permissions:
  contents: read
  id-token: write
jobs:
  publish:
    runs-on: ubuntu-latest
    environment: publish   # only if the trusted publisher pins an environment
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-node@v5
      - run: npm ci
      - run: npx ovsx publish --trusted-publishing
```

> "the registry only issues such a token if the workflow matches a trusted publisher that a namespace owner registered under [trusted publishers](https://open-vsx.org/user-settings/trusted-publishers). **No access token needs to be stored as a secret.**"

`--trusted-publishing` *requires* it and fails if no ID token can be obtained; without the flag, trusted publishing is used opportunistically and `--pat` / `OVSX_PAT` always wins. Issued tokens last "a few minutes only… but it does carry publishing rights, so treat CI logs accordingly."
Source: <https://github.com/eclipse/openvsx/blob/master/cli/README.md> ("Trusted Publishing")

→ **Both registries can be published from GitHub Actions with zero long-lived secrets.** That should be the target CI design.

### 9.5 Scanning, and identity across registries

Every upload is scanned: secret detection (suppressible per-line with `// secret-detector:ignore`), a file-hash blocklist, and **namespace-similarity / typosquatting** checks. Failures either reject the publish or quarantine the extension as "under review."
Source: <https://github.com/EclipseFdn/open-vsx.org/wiki/Publishing-Extensions> ("5. Extension scanning")

> "If you publish your extension on by the VS Code Marketplace and the Open VSX Registry, it is our strong desire to have you use the **same identifier between registries. I.e. same extension name and same publisher account/namespace.**"

Source: same page ("Preserving Identity Across Registries")
→ Reinforces settling on `fleet-vscode` as *both* the Marketplace publisher id and the Open VSX namespace, and locking the extension `name` before either is claimed.

Deletion on Open VSX is irreversible and reserves the version number permanently, same as the Marketplace.
Source: <https://github.com/eclipse/openvsx/blob/master/cli/README.md> ("Delete Extensions")

An alternative to self-publishing exists: open-source extensions can request **auto-publishing** from the Marketplace.
Source: <https://github.com/EclipseFdn/open-vsx.org/wiki/Auto-Publishing-Extensions>

---

## 10. Deltas against the current `editors/vscode/` manifest

For reference, today's manifest:

```jsonc
{
  "name": "fleet-cdisc",
  "displayName": "Fleet CDISC",
  "publisher": "fleet-cdisc",        // ← ticket says publisher must be `fleet-vscode`
  "version": "0.1.0",
  "license": "MIT",                   // ← no LICENSE file next to it → vsce prompt
  "repository": { "type": "git", "url": "https://github.com/RealSlimMahdi/fleet-cdisc" },
                                      // ← must point at the new repo
  "engines": { "vscode": "^1.75.0" }, // ← conflicts with vscode-languageclient@9 (^1.82.0)
  "categories": ["Programming Languages", "Linters"],   // ✅ valid
  "activationEvents": ["workspaceContains:**/define.yaml", "onLanguage:yaml"], // ✅ no warning
  "main": "./out/extension.js",       // ✅ paired with activationEvents
  "scripts": { "vscode:prepublish": "npm run compile" } // ✅ correct hook
}
```

And today's `.vscodeignore`:

```
.vscode/**
src/**
tsconfig.json
**/*.map
.gitignore
```

It does not exclude `node_modules`, `package-lock.json`, `out/**/*.test.js`, `.github/**`, or `.vscode-test*`. Since `vscode-languageclient` is a real runtime dependency, `node_modules` must ship **unless** the extension is bundled — which is also what makes it work in vscode.dev (§4.1).

---

## 11. Checklist

### Must exist before first publish

**Identity**
- [ ] Publisher `fleet-vscode` created at <https://marketplace.visualstudio.com/manage> (ID is permanent) — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)
- [ ] `package.json` `publisher` changed `fleet-cdisc` → `fleet-vscode`
- [ ] `name` and `displayName` confirmed unique in the Marketplace (both are global and unrecoverable) — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)
- [ ] `repository.url` repointed to `https://github.com/RealSlimMahdi/fleet-vscode`

**Manifest correctness (blocks `vsce package`)**
- [ ] `engines.vscode` raised to at least `^1.82.0` to match `vscode-languageclient@9` — [src](https://registry.npmjs.org/vscode-languageclient)
- [ ] `@types/vscode` major.minor ≤ `engines.vscode` — [src](https://github.com/microsoft/vscode-vsce/blob/main/src/validation.ts)
- [ ] `main` present alongside `activationEvents` (already true) — [src](https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts)
- [ ] No `"*"` activation event (already true) — [src](https://code.visualstudio.com/api/references/activation-events)

**Files at repo root**
- [ ] `LICENSE` (or `license: "SEE LICENSE IN <file>"`) — otherwise vsce prompts — [src](https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts)
- [ ] `README.md` with **no** template text, **no** relative links that can't resolve, **no** non-HTTPS or untrusted-SVG images — [src](https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts)
- [ ] `CHANGELOG.md` — rendered as its own Marketplace tab — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)
- [ ] `.vscodeignore` covering `node_modules` (if bundling), `src/**`, `out/test/**`, `**/*.map`, `.github/**`, `.vscode-test*`, `tsconfig.json` — and **no** `"files"` key in `package.json` (mutually exclusive) — [src](https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts)
- [ ] `icon` — PNG, ≥128×128, actually included in the package (missing file = hard error; SVG = hard error) — [src](https://code.visualstudio.com/api/references/extension-manifest)

**CI**
- [ ] Test matrix `[ubuntu-latest, macos-latest, windows-latest]` on **Node 22.x** — [src](https://registry.npmjs.org/@vscode/test-cli)
- [ ] `xvfb-run -a npm test` on Linux only — [src](https://code.visualstudio.com/api/working-with-extensions/continuous-integration)
- [ ] `@vscode/test-cli` + `@vscode/test-electron` devDependencies and a `.vscode-test.mjs` — [src](https://code.visualstudio.com/api/working-with-extensions/testing-extension)
- [ ] A `vsce package` (dry-run) step in PR CI so packaging errors surface before release
- [ ] Publish job pinned to `ubuntu-latest` (POSIX file attributes) and gated on a tag — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)

**Publish credentials (choose one, wire it, do not run it)**
- [ ] Preferred: Marketplace trusted-publishing policy for `RealSlimMahdi/fleet-vscode` + the exact publish workflow filename, and `permissions: id-token: write` in that job → `vsce publish --oidc` — [src](https://github.com/microsoft/vscode-vsce/blob/main/README.md)
- [ ] Fallback only: PAT with *All accessible organizations* + `Marketplace (Manage)`, stored as `VSCE_PAT` — **note this route dies 2026-12-01** — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)

### Nice to have

**Marketplace listing polish**
- [ ] `galleryBanner: { color, theme }` — [src](https://code.visualstudio.com/api/references/extension-manifest)
- [ ] `keywords` (≤30) for search — [src](https://code.visualstudio.com/api/references/extension-manifest)
- [ ] `bugs.url` and `homepage` for the Resources panel — [src](https://code.visualstudio.com/api/references/extension-manifest)
- [ ] `qna: false` (route support to GitHub Issues) — [src](https://code.visualstudio.com/api/references/extension-manifest)
- [ ] `pricing: "Free"` (explicit; requires vsce ≥ 2.10.0) — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)
- [ ] `badges` from the approved-host list only — [src](https://code.visualstudio.com/api/references/extension-manifest)
- [ ] `SUPPORT.md` — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)
- [ ] `sponsor.url` (requires vsce ≥ 2.9.1) — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)

**Engineering polish**
- [ ] Bundle with esbuild — required for vscode.dev/github.dev, and shrinks the VSIX — [src](https://code.visualstudio.com/api/working-with-extensions/bundling-extension)
- [ ] `capabilities.untrustedWorkspaces` / `virtualWorkspaces` declared, with trust-state test configs — [src](https://code.visualstudio.com/api/working-with-extensions/testing-extension)
- [ ] `--pre-release` channel using `major.ODD.patch` versions — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)
- [ ] `vsce ls --tree` recorded in CI output to watch package size drift — [src](https://github.com/microsoft/vscode-vsce/blob/main/src/main.ts)
- [ ] CONTRIBUTING.md note about "no other instance of Code is running" — [src](https://code.visualstudio.com/api/working-with-extensions/testing-extension)

**Reach**
- [ ] Eclipse account + Publisher Agreement, `ovsx create-namespace fleet-vscode`, ownership claim — [src](https://github.com/EclipseFdn/open-vsx.org/wiki/Publishing-Extensions)
- [ ] `ovsx publish --trusted-publishing` in the same release workflow — [src](https://github.com/eclipse/openvsx/blob/master/cli/README.md)

### Explicitly out of scope right now
- [ ] Verified publisher badge — needs ≥6 months of published extensions **and** a ≥6-month-old, non-subdomain, HTTPS domain — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)
- [ ] Platform-specific VSIX targets — only relevant with native node modules — [src](https://code.visualstudio.com/api/working-with-extensions/publishing-extension)

---

## Sources

**Official VS Code / Microsoft documentation**
- <https://code.visualstudio.com/api/working-with-extensions/publishing-extension>
- <https://code.visualstudio.com/api/references/extension-manifest>
- <https://code.visualstudio.com/api/references/activation-events>
- <https://code.visualstudio.com/api/working-with-extensions/testing-extension>
- <https://code.visualstudio.com/api/working-with-extensions/continuous-integration>
- <https://code.visualstudio.com/api/working-with-extensions/bundling-extension>
- <https://devblogs.microsoft.com/devops/retirement-of-global-personal-access-tokens-in-azure-devops/>

**First-party tool source and READMEs**
- <https://github.com/microsoft/vscode-vsce/blob/main/README.md>
- <https://github.com/microsoft/vscode-vsce/blob/main/src/main.ts>
- <https://github.com/microsoft/vscode-vsce/blob/main/src/package.ts>
- <https://github.com/microsoft/vscode-vsce/blob/main/src/publish.ts>
- <https://github.com/microsoft/vscode-vsce/blob/main/src/oidc.ts>
- <https://github.com/microsoft/vscode-vsce/blob/main/src/util.ts>
- <https://github.com/microsoft/vscode-vsce/blob/main/src/validation.ts>
- <https://github.com/microsoft/vscode-test-cli/blob/main/README.md>
- <https://github.com/microsoft/vscode-test-cli/blob/main/src/config.cts>

**Open VSX / Eclipse Foundation**
- <https://github.com/EclipseFdn/open-vsx.org/wiki/Publishing-Extensions>
- <https://github.com/EclipseFdn/open-vsx.org/wiki/Managing-Namespaces>
- <https://github.com/eclipse/openvsx/blob/master/cli/README.md>

**Registry / API probes (run 2026-08-26)**
- `https://registry.npmjs.org/@vscode/vsce`, `/@vscode/test-cli`, `/@vscode/test-electron`, `/ovsx`, `/vscode-languageclient`, `/@types/vscode`
- `https://marketplace.visualstudio.com/publishers/fleet-vscode`
- `https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery`
- `https://open-vsx.org/api/fleet-vscode`
