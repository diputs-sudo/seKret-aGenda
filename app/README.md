# Secret Agenda Desktop App

Native desktop shell for the seKret aGenda prototype.

## Stack

- Qt 6 Widgets for the native desktop UI
- C++20 for the app shell, search repository, and performance-sensitive local logic
- SQLite through QtSql for local evidence/card storage
- Python worker process for future AI/ML features
- CMake for macOS `.app` and Windows `.exe` builds

## Current Slice

This first frontend reads the existing prototype database at:

```bash
var/sekret-agenda.sqlite3
```

It supports:

- opening a different SQLite database
- searching cards through the existing FTS index
- fallback text search when FTS returns no rows
- card detail inspection with citation, highlights, and body preview
- mode sidebar placeholders for Search, Explain, Draft Rebuttal, Summary, and Final Focus
- Python worker health check

## Build

Install Qt 6 and CMake, then from the repo root:

```bash
cmake -S app -B app/build -DCMAKE_BUILD_TYPE=Release
cmake --build app/build --config Release
```

If CMake cannot find Qt, point it at your Qt install:

```bash
cmake -S app -B app/build -DCMAKE_PREFIX_PATH="$HOME/Qt/6.7.0/macos"
```

On macOS, the app bundle is produced as `app/build/Secret Agenda.app`.
On Windows, the executable is produced as `app/build/Release/Secret Agenda.exe` when using a multi-config generator such as Visual Studio.

## Run

```bash
open "app/build/Secret Agenda.app"
```

or run the binary directly:

```bash
"app/build/Secret Agenda.app/Contents/MacOS/Secret Agenda"
```

You can override the database location:

```bash
SEKRET_DB_PATH=/path/to/sekret-agenda.sqlite3 "app/build/Secret Agenda.app/Contents/MacOS/Secret Agenda"
```

## Next App Milestones

- Replace mode placeholders with real C++ service objects.
- Port parser and SQLite import flows into the app.
- Call the Python worker for embeddings/reranking/generation.
- Add packaging rules using `macdeployqt` and `windeployqt`.
- Add app-level tests for repository queries and worker invocation.
