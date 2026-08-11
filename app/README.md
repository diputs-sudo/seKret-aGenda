# Secret Agenda Desktop App

Tauri desktop workspace for the seKret aGenda prototype.

## Stack

- Tauri 2 for native macOS and Windows packaging
- HTML/CSS/JavaScript for the interface
- Rust for desktop commands, SQLite access, settings persistence, platform actions, and clipboard integration
- SQLite for local evidence/card storage
- Python worker process reserved for future AI/ML sidecar work

## Architecture Direction

The frontend is organized around the debate workspace primitives:

```text
Workspace -> Tabs -> Panels -> Views -> Commands
```

Current source layout:

```text
src/                  HTML/CSS/JS frontend
src/styles/           theme tokens and shell styling
src-tauri/            Rust/Tauri desktop backend
src-tauri/src/lib.rs  commands, SQLite bridge, settings/workspace persistence
python/               future AI worker sidecar
```

The frontend does not issue SQLite queries directly. It invokes Tauri commands.

## Current Slice

This frontend reads the existing prototype database at:

```bash
var/sekret-agenda.sqlite3
```

It supports:

- IDE-like shell with top bar, activity bar, sidebar, tab strip, panel area, and status bar
- universal tabs for search, evidence, browser/research, draft, round, document, and database views
- centralized CSS theme tokens with Dark, Natural White, and Follow System modes
- centralized settings persisted through Tauri/Rust
- workspace tab/activity persistence
- `Cmd+K` / `Ctrl+K` command palette
- evidence search through the existing SQLite FTS index with fallback text search
- evidence detail tabs
- developer search diagnostics toggle
- rich clipboard export through Tauri as `text/plain` and `text/html`
- external URL/path opening through a platform command

## Browser Note

The old Qt plan used Qt WebEngine/Chromium. Tauri uses the operating system WebView, so embedded browser behavior is different. For this Tauri alpha, research tabs keep URL controls and an external-browser escape hatch. We can decide later whether to use additional WebViews, external browser workflows, or a dedicated browser integration.

## Requirements

- Node.js and npm
- Rust toolchain with Cargo
- Platform prerequisites for Tauri 2

## Build

From this `app/` directory:

```bash
npm install
npm run dev
```

Build a macOS `.app`:

```bash
npm run build
```

Build a Windows `.exe` installer on Windows:

```bash
npm run build:windows
```

Useful frontend-only check:

```bash
npm run check
```

Run the frontend as a normal webpage without Tauri:

```bash
npm run dev:frontend -- --port 1420
```

In browser-only mode, Tauri commands are mocked. Settings and workspace state
persist to `localStorage`, search returns preview data, external links open in a
new browser tab, and copy uses the browser clipboard API.

## Environment

Override the evidence database location:

```bash
SEKRET_DB_PATH=/path/to/sekret-agenda.sqlite3 npm run dev
```

## Next App Milestones

- Install Rust/Cargo in the local dev environment and compile the Tauri shell.
- Wire the existing Python hybrid retrieval engine behind `search_evidence`.
- Add DOCX import through Tauri commands and the existing parser pipeline.
- Split frontend modules by shell/views/state once the product flow stabilizes.
- Add app-level tests for Rust commands and frontend state reducers.
