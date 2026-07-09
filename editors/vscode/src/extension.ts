// Fleet CDISC — VS Code shell around `fleet lsp --stdio`.
//
// The extension is a thin launcher: all semantic logic (diagnostics,
// completions, hover) lives in the Python language server shipped with
// the fleet-cdisc package (`lsp` extra). Server discovery order:
//   1. FLEET_LSP env var — path to a `fleet` executable (overrides all)
//   2. <workspace>/.venv/bin/fleet   (standard `uv sync` layout)
//   3. `uv run fleet`                (fallback, resolves the project env)

import * as fs from "fs";
import * as path from "path";
import { ExtensionContext, workspace } from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

interface ServerCommand {
  command: string;
  args: string[];
}

function discoverServer(workspaceRoot: string | undefined): ServerCommand {
  const override = process.env.FLEET_LSP;
  if (override) {
    return { command: override, args: ["lsp", "--stdio"] };
  }
  if (workspaceRoot) {
    const bin =
      process.platform === "win32"
        ? path.join(workspaceRoot, ".venv", "Scripts", "fleet.exe")
        : path.join(workspaceRoot, ".venv", "bin", "fleet");
    if (fs.existsSync(bin)) {
      return { command: bin, args: ["lsp", "--stdio"] };
    }
  }
  return { command: "uv", args: ["run", "fleet", "lsp", "--stdio"] };
}

export function activate(context: ExtensionContext): void {
  const root = workspace.workspaceFolders?.[0]?.uri.fsPath;
  const server = discoverServer(root);

  const serverOptions: ServerOptions = {
    command: server.command,
    args: server.args,
    options: { cwd: root },
  };
  const clientOptions: LanguageClientOptions = {
    // The server only speaks define.yaml; scope to those files.
    documentSelector: [{ language: "yaml", pattern: "**/define*.yaml" }],
  };

  client = new LanguageClient(
    "fleet-lsp",
    "Fleet CDISC",
    serverOptions,
    clientOptions
  );
  client.start();
  context.subscriptions.push({ dispose: () => void client?.stop() });
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}
