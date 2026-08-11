# Secret Agenda Desktop App

Tauri desktop workspace for the seKret aGenda prototype.

## Stack

- Tauri 2 for native macOS and Windows packaging
- HTML/CSS/JavaScript for the interface
- Rust for desktop commands, settings persistence, platform actions, clipboard integration, and C++ hybrid retrieval bridging
- C++ for native hybrid retrieval orchestration, SQLite evidence retrieval, reranking, argument selection, and native vector-cache search
- SQLite for local evidence/card storage
- Python scripts for document parsing, data/index build steps, and prototype comparison tooling

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
src-tauri/src/lib.rs  commands, settings/workspace persistence
src-tauri/src/hybrid.rs
                      Rust FFI bridge to the native hybrid backend
backend/hybrid/       C++ native hybrid retrieval backend
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
- native hybrid evidence search through Rust/Tauri + C++ backend
- SQLite FTS fallback paths for exact/non-hybrid search
- native vector-cache search when `native_card_vectors` has been built
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

Build the native vector cache used by desktop hybrid search:

```bash
../run.sh build-native-vector
```

The app no longer calls the Python hybrid prototype for `search_evidence`.
Python remains useful for parser/index build steps and parity checks.

## Next App Milestones

- Add native vector-cache build progress/status to the app.
- Add DOCX import through Tauri commands and the existing parser pipeline.
- Split frontend modules by shell/views/state once the product flow stabilizes.
- Add app-level tests for Rust commands and frontend state reducers.
