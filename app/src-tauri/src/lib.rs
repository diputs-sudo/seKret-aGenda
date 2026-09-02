mod hybrid;

use rusqlite::{Connection, Result as SqlResult};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::Manager;
use tauri_plugin_clipboard_manager::ClipboardExt;

const CARD_SEPARATOR_BYTES: &[u8] = include_bytes!(env!("CARD_SEPARATOR_BIN"));
const CARD_SEPARATOR_SOURCE: &str = env!("CARD_SEPARATOR_SOURCE");
const EMBEDDING_MODEL: &str = "nomic-embed-text";
const RERANK_MODEL: &str = "qwen3:4b";
#[cfg(target_os = "macos")]
const MANAGED_OLLAMA_DOWNLOAD: &str = "https://ollama.com/download/Ollama-darwin.zip";
#[cfg(target_os = "windows")]
const WINDOWS_OLLAMA_INSTALL_SCRIPT: &str = "https://ollama.com/install.ps1";

// Startup and search can request the runtime at nearly the same time. Serialize
// setup so we never launch two installers or two model downloads.
static OLLAMA_RUNTIME_LOCK: Mutex<()> = Mutex::new(());

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SearchQuery {
    text: String,
    limit: Option<usize>,
    mode: Option<String>,
    scope: Option<String>,
    include_diagnostics: Option<bool>,
    analysis_mode: Option<bool>,
    full_context_rerank: Option<bool>,
    model_rerank: Option<bool>,
    model_rerank_limit: Option<usize>,
    vector_limit: Option<usize>,
    lexical_limit: Option<usize>,
    citation_limit: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Highlight {
    text: String,
    color: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct EvidenceCard {
    id: String,
    title: String,
    author: Option<String>,
    year: Option<i64>,
    section: String,
    tag: String,
    citation: String,
    url: Option<String>,
    body: String,
    body_preview: String,
    highlights: Vec<Highlight>,
    score: f64,
    document_name: String,
    side: Option<String>,
    diagnostics: Option<SearchDiagnostics>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RoundSourceImportRequest {
    side: String,
    round_id: Option<String>,
    source_path: Option<String>,
    source_name: Option<String>,
    source_bytes: Option<Vec<u8>>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RoundSourceState {
    id: String,
    filename: String,
    path: String,
    side: String,
    status: String,
    card_count: usize,
    parse_progress: f64,
    index_progress: f64,
    error: String,
    diagnostics: Vec<String>,
}
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RoundLibraryBuildRequest {
    round_id: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct RoundLibraryBuildState {
    status: String,
    card_count: usize,
    fast_vectors: usize,
    deep_vectors: usize,
    diagnostics: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RoundEvidenceQuery {
    round_id: Option<String>,
    query: Option<String>,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RoundAskQuery {
    round_id: Option<String>,
    query: String,
    mode: Option<String>,
    limit: Option<usize>,
    generate_answer: Option<bool>,
    include_diagnostics: Option<bool>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct RoundSearchResult {
    card: EvidenceCard,
    score: f64,
    relationship: String,
    explanation: String,
    debug: Option<serde_json::Value>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct GeneratedResponse {
    text: String,
    sources: Vec<String>,
    grounded: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct RoundAskResponse {
    results: Vec<RoundSearchResult>,
    generated: Option<GeneratedResponse>,
    logs: Vec<String>,
    runtime: OllamaRuntimeStatus,
}
#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct OllamaRuntimeStatus {
    ready: bool,
    installed: bool,
    server_ready: bool,
    embedding_model: String,
    rerank_model: String,
    logs: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CardSeparatorRequest {
    docx_path: Option<String>,
    source_name: Option<String>,
    docx_bytes: Option<Vec<u8>>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct CardSeparatorResponse {
    output: String,
    stderr: String,
    source_file: String,
    executable_path: String,
    card_count: Option<usize>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SearchDiagnostics {
    retrieval: Vec<String>,
    concepts: Vec<String>,
    final_score: f64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AppPaths {
    app_data: String,
    cache: String,
    documents: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SettingsState {
    theme: String,
    density: String,
    scale: f64,
    search_result_count: usize,
    developer_search_diagnostics: bool,
}

impl Default for SettingsState {
    fn default() -> Self {
        Self {
            theme: "dark".into(),
            density: "comfortable".into(),
            scale: 1.0,
            search_result_count: 20,
            developer_search_diagnostics: false,
        }
    }
}

#[tauri::command]
fn platform_paths(app: tauri::AppHandle) -> Result<AppPaths, String> {
    let resolver = app.path();
    Ok(AppPaths {
        app_data: resolver
            .app_data_dir()
            .map_err(|error| error.to_string())?
            .to_string_lossy()
            .to_string(),
        cache: resolver
            .app_cache_dir()
            .map_err(|error| error.to_string())?
            .to_string_lossy()
            .to_string(),
        documents: resolver
            .document_dir()
            .map_err(|error| error.to_string())?
            .to_string_lossy()
            .to_string(),
    })
}

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    open::that(url).map_err(|error| error.to_string())
}

#[tauri::command]
fn reveal_path(path: String) -> Result<(), String> {
    open::that(path).map_err(|error| error.to_string())
}

#[tauri::command]
fn load_settings(app: tauri::AppHandle) -> Result<SettingsState, String> {
    read_json(app, "settings.json").map(|value| value.unwrap_or_default())
}

#[tauri::command]
fn save_settings(app: tauri::AppHandle, settings: SettingsState) -> Result<(), String> {
    write_json(app, "settings.json", &settings)
}

#[tauri::command]
fn load_workspace(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    read_json(app, "workspace.json").map(|value| value.unwrap_or_else(default_workspace_state))
}

#[tauri::command]
fn save_workspace(app: tauri::AppHandle, workspace: serde_json::Value) -> Result<(), String> {
    write_json(app, "workspace.json", &workspace)
}

#[tauri::command]
fn create_round_workspace() -> serde_json::Value {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    serde_json::json!({
        "id": format!("library-{nonce}"),
        "name": "Evidence Library",
        "status": "empty",
        "sources": [],
        "flows": [],
        "buildStages": []
    })
}

#[tauri::command]
fn search_evidence(app: tauri::AppHandle, query: SearchQuery) -> Result<Vec<EvidenceCard>, String> {
    let db_path = default_database_path(&app)?;
    let limit = query.limit.unwrap_or(20).clamp(1, 100);
    let trimmed = query.text.trim();

    if !trimmed.is_empty() && query.mode.as_deref() == Some("hybrid") {
        return hybrid::search(&db_path, &query).map(|response| response.cards);
    }

    let connection = Connection::open(db_path).map_err(|error| error.to_string())?;
    if trimmed.is_empty() {
        return recent_cards(
            &connection,
            limit,
            query.include_diagnostics.unwrap_or(false),
        )
        .map_err(|error| error.to_string());
    }

    let mut cards = fts_search(
        &connection,
        trimmed,
        limit,
        query.include_diagnostics.unwrap_or(false),
    )
    .map_err(|error| error.to_string())?;
    if cards.is_empty() && query.mode.as_deref() != Some("exact") {
        cards = like_search(
            &connection,
            trimmed,
            limit,
            query.include_diagnostics.unwrap_or(false),
        )
        .map_err(|error| error.to_string())?;
    }
    Ok(cards)
}

#[tauri::command]
fn import_round_source(
    app: tauri::AppHandle,
    request: RoundSourceImportRequest,
) -> Result<RoundSourceState, String> {
    if request.side != "ours" {
        return Err("This library accepts one evidence source. Use side: ours.".into());
    }

    let round_id = request.round_id.as_deref().unwrap_or("default-round");
    let source_path = materialize_round_upload(
        &app,
        round_id,
        request.source_path.as_deref(),
        request.source_name.as_deref(),
        request.source_bytes.as_deref(),
        "source.docx",
    )?;
    if source_path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| extension.eq_ignore_ascii_case("docx"))
        != Some(true)
    {
        return Err("The native library importer currently accepts DOCX files.".into());
    }

    let db_path = round_database_path(&app, round_id)?;
    let stats = hybrid::import_docx(
        &db_path,
        &source_path,
        include_str!("../../../backend/models/sqlite_schema.sql"),
    )?;
    let filename = source_path
        .file_name()
        .map(|name| name.to_string_lossy().to_string())
        .unwrap_or_else(|| source_path.to_string_lossy().to_string());

    Ok(RoundSourceState {
        id: "source-ours".into(),
        filename,
        path: source_path.to_string_lossy().to_string(),
        side: "ours".into(),
        status: "loaded".into(),
        card_count: stats.cards,
        parse_progress: 1.0,
        index_progress: 0.0,
        error: String::new(),
        diagnostics: vec![format!(
            "Native C++ imported {} sections, {} cards, {} citations, and {} highlights from {}.",
            stats.sections, stats.cards, stats.citations, stats.highlights, stats.document_name
        )],
    })
}

#[tauri::command]
fn build_round_library(
    app: tauri::AppHandle,
    request: RoundLibraryBuildRequest,
) -> Result<RoundLibraryBuildState, String> {
    let round_id = request.round_id.as_deref().unwrap_or("default-round");
    let runtime = ensure_ollama_runtime();
    if !runtime.ready {
        return Err(format!(
            "Ollama setup is incomplete; the library cannot be indexed yet. {}",
            runtime.logs.join(" ")
        ));
    }
    let db_path = round_database_path(&app, round_id)?;
    let stats = hybrid::build_vectors(&db_path)?;
    let connection = Connection::open(&db_path).map_err(|error| error.to_string())?;
    let card_count = connection
        .query_row("SELECT COUNT(*) FROM evidence_cards", [], |row| {
            row.get::<_, usize>(0)
        })
        .map_err(|error| error.to_string())?;
    let mut diagnostics = runtime.logs;
    diagnostics.push(format!(
        "Native C++ indexed {card_count} cards ({} fast, {} deep vectors).",
        stats.fast, stats.deep
    ));

    Ok(RoundLibraryBuildState {
        status: "ready".into(),
        card_count,
        fast_vectors: stats.fast,
        deep_vectors: stats.deep,
        diagnostics,
    })
}

#[tauri::command]
fn list_round_evidence(
    app: tauri::AppHandle,
    query: RoundEvidenceQuery,
) -> Result<Vec<EvidenceCard>, String> {
    let db_path = existing_round_database_path(&app, query.round_id.as_deref())?;
    let connection = Connection::open(db_path).map_err(|error| error.to_string())?;
    let limit = query.limit.unwrap_or(100).clamp(1, 300);
    let text = query.query.unwrap_or_default();
    let cards = if text.trim().is_empty() {
        round_cards(&connection, "ours", "", limit)
    } else {
        fallback_round_search(&connection, text.trim(), limit)
    };
    cards.map_err(|error| error.to_string())
}

#[tauri::command]
fn ask_round(app: tauri::AppHandle, request: RoundAskQuery) -> Result<RoundAskResponse, String> {
    let runtime = ensure_ollama_runtime();
    let db_path = existing_round_database_path(&app, request.round_id.as_deref())?;
    let scope = "ours";
    let mode = request.mode.as_deref().unwrap_or("smart");
    let limit = request.limit.unwrap_or(20).clamp(1, 100);
    let candidate_limit = (limit.saturating_mul(3)).clamp(50, 100);
    let trimmed = request.query.trim();
    let mut logs = runtime.logs.clone();
    if !runtime.ready {
        logs.push("WARNING: Ollama setup is incomplete; semantic retrieval may fall back to SQLite text search.".into());
    }
    logs.push(format!(
        "Search request: {limit} results from one-sided evidence library."
    ));

    let cards = if trimmed.is_empty() {
        logs.push("No query text supplied.".into());
        Vec::new()
    } else if matches!(mode, "smart" | "semantic" | "hybrid" | "advanced") {
        let query = SearchQuery {
            text: trimmed.to_string(),
            limit: Some(limit),
            mode: Some("hybrid".into()),
            scope: Some(scope.to_string()),
            include_diagnostics: request.include_diagnostics,
            analysis_mode: Some(false),
            full_context_rerank: Some(false),
            model_rerank: Some(true),
            model_rerank_limit: Some(limit.min(12)),
            vector_limit: Some(candidate_limit),
            lexical_limit: Some(candidate_limit),
            citation_limit: Some(20),
        };
        match hybrid::search(&db_path, &query) {
            Ok(response) => {
                logs.extend(response.logs);
                logs.push(format!("Native result: {}.", response.source_status));
                if let Some(uncertainty) = response.uncertainty {
                    logs.push(format!("WARNING: {uncertainty}"));
                }
                if let Some(total) = response.timings.get("total") {
                    logs.push(format!("Native pipeline time: {total:.0} ms."));
                }
                let cards = scoped_cards(response.cards, scope, limit);
                if cards.is_empty() {
                    logs.push("WARNING: Native semantic search returned no usable one-sided cards; using SQLite text fallback.".into());
                    let connection =
                        Connection::open(&db_path).map_err(|error| error.to_string())?;
                    fallback_round_search(&connection, trimmed, limit)
                        .map_err(|error| error.to_string())?
                } else {
                    cards
                }
            }
            Err(error) => {
                logs.push(format!("ERROR: Native semantic search failed: {error}"));
                logs.push("Fallback: SQLite full-text search only.".into());
                let connection = Connection::open(&db_path).map_err(|error| error.to_string())?;
                fallback_round_search(&connection, trimmed, limit)
                    .map_err(|error| error.to_string())?
            }
        }
    } else {
        logs.push(
            "SQLite text-search mode selected; vector retrieval and reranking were skipped.".into(),
        );
        let connection = Connection::open(&db_path).map_err(|error| error.to_string())?;
        fallback_round_search(&connection, trimmed, limit).map_err(|error| error.to_string())?
    };

    logs.push(format!("Returned {} card(s).", cards.len()));
    let results = cards
        .into_iter()
        .map(|card| round_result_for_card(card, mode))
        .collect::<Vec<_>>();
    let generated = request
        .generate_answer
        .unwrap_or(true)
        .then(|| grounded_summary(trimmed, &results));

    Ok(RoundAskResponse {
        results,
        generated,
        logs,
        runtime,
    })
}
#[tauri::command]
fn run_card_separator(
    app: tauri::AppHandle,
    request: CardSeparatorRequest,
) -> Result<CardSeparatorResponse, String> {
    let cache_dir = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?;
    run_card_separator_with_cache_dir(cache_dir, request)
}

fn run_card_separator_with_cache_dir(
    cache_dir: PathBuf,
    request: CardSeparatorRequest,
) -> Result<CardSeparatorResponse, String> {
    let docx_path = card_separator_docx_path(&cache_dir, &request)?;
    if docx_path.as_os_str().is_empty() {
        return Err("Choose a DOCX file first.".into());
    }
    if !docx_path.exists() {
        return Err(format!("DOCX file not found: {}", docx_path.display()));
    }
    if docx_path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(|extension| !extension.eq_ignore_ascii_case("docx"))
        .unwrap_or(true)
    {
        return Err(format!(
            "Card Separator requires a .docx file: {}",
            docx_path.display()
        ));
    }

    let executable = materialize_card_separator_binary(&cache_dir)?;
    let output = Command::new(&executable)
        .arg(&docx_path)
        .output()
        .map_err(|error| {
            format!(
                "Failed to run card separator {}: {error}",
                executable.display()
            )
        })?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    if !output.status.success() {
        return Err(format!(
            "Card separator exited with status {}.\n{}",
            output
                .status
                .code()
                .map(|code| code.to_string())
                .unwrap_or_else(|| "terminated by signal".into()),
            stderr.trim()
        ));
    }
    if !stderr.trim().is_empty() {
        return Err(format!(
            "Card separator wrote to stderr:\n{}",
            stderr.trim()
        ));
    }
    if stdout.trim().is_empty() {
        return Err("Card separator produced no usable output.".into());
    }

    Ok(CardSeparatorResponse {
        output: stdout,
        stderr,
        source_file: CARD_SEPARATOR_SOURCE.into(),
        executable_path: executable.to_string_lossy().to_string(),
        card_count: None,
    })
}

fn card_separator_docx_path(
    cache_dir: &Path,
    request: &CardSeparatorRequest,
) -> Result<PathBuf, String> {
    let provided_path = request.docx_path.as_deref().unwrap_or("").trim();
    if !provided_path.is_empty() {
        let path = PathBuf::from(provided_path);
        if path.exists() {
            return Ok(path);
        }
        if request.docx_bytes.is_none() {
            return Ok(path);
        }
    }

    let bytes = request
        .docx_bytes
        .as_ref()
        .filter(|bytes| !bytes.is_empty())
        .ok_or_else(|| "Choose a DOCX file first.".to_string())?;
    let filename = request
        .source_name
        .as_deref()
        .filter(|name| !name.trim().is_empty())
        .unwrap_or("card-separator.docx");
    let safe_name = safe_filename(filename);
    let upload_dir = cache_dir.join("uploads").join("card-separator");
    std::fs::create_dir_all(&upload_dir).map_err(|error| error.to_string())?;
    let path = upload_dir.join(safe_name);
    std::fs::write(&path, bytes).map_err(|error| error.to_string())?;
    Ok(path)
}

fn materialize_card_separator_binary(cache_dir: &Path) -> Result<PathBuf, String> {
    let bin_dir = cache_dir.join("bin");
    std::fs::create_dir_all(&bin_dir).map_err(|error| error.to_string())?;

    let executable = bin_dir.join(if cfg!(windows) {
        "card_separator.exe"
    } else {
        "card_separator"
    });

    let should_write = std::fs::read(&executable)
        .map(|existing| existing != CARD_SEPARATOR_BYTES)
        .unwrap_or(true);
    if should_write {
        std::fs::write(&executable, CARD_SEPARATOR_BYTES).map_err(|error| error.to_string())?;
    }

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = std::fs::metadata(&executable)
            .map_err(|error| error.to_string())?
            .permissions();
        permissions.set_mode(0o755);
        std::fs::set_permissions(&executable, permissions).map_err(|error| error.to_string())?;
    }

    Ok(executable)
}

#[tauri::command]
fn copy_evidence(app: tauri::AppHandle, card: EvidenceCard) -> Result<(), String> {
    let plain = format!(
        "{}\n{}\n\n{}\n\n{}",
        card.title,
        card.tag,
        card.citation,
        if card.body.is_empty() {
            card.body_preview
        } else {
            card.body
        }
    );
    let html = format!(
        "<article><p><strong>{}</strong></p><p><u>{}</u></p><p>{}</p><p>{}</p></article>",
        html_escape::encode_text(&card.title),
        html_escape::encode_text(&card.tag),
        html_escape::encode_text(&card.citation),
        html_escape::encode_text(&plain)
    );

    app.clipboard()
        .write_html(html, Some(plain))
        .map_err(|error| error.to_string())
}

#[cfg(target_os = "macos")]
fn managed_ollama_app_path() -> Option<PathBuf> {
    std::env::var_os("HOME").map(|home| {
        PathBuf::from(home)
            .join("Library")
            .join("Application Support")
            .join("Secret Agenda")
            .join("runtime")
            .join("Ollama.app")
    })
}

#[cfg(target_os = "macos")]
fn managed_ollama_executable() -> Option<PathBuf> {
    managed_ollama_app_path()
        .map(|app_path| app_path.join("Contents").join("Resources").join("ollama"))
}

#[cfg(target_os = "windows")]
fn windows_ollama_executable() -> Option<PathBuf> {
    std::env::var_os("LOCALAPPDATA").map(|local_app_data| {
        PathBuf::from(local_app_data)
            .join("Programs")
            .join("Ollama")
            .join("ollama.exe")
    })
}

fn find_ollama_executable() -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(path) = std::env::var_os("OLLAMA_BIN") {
        candidates.push(PathBuf::from(path));
    }
    #[cfg(target_os = "macos")]
    if let Some(path) = managed_ollama_executable() {
        candidates.push(path);
    }
    #[cfg(target_os = "windows")]
    if let Some(path) = windows_ollama_executable() {
        candidates.push(path);
    }
    #[cfg(not(target_os = "windows"))]
    candidates.extend([
        PathBuf::from("/usr/local/bin/ollama"),
        PathBuf::from("/opt/homebrew/bin/ollama"),
        PathBuf::from("/Applications/Ollama.app/Contents/Resources/ollama"),
    ]);
    let command_name = if cfg!(target_os = "windows") {
        "ollama.exe"
    } else {
        "ollama"
    };
    if let Some(path) = std::env::var_os("PATH") {
        candidates
            .extend(std::env::split_paths(&path).map(|directory| directory.join(command_name)));
    }
    candidates.into_iter().find(|candidate| candidate.is_file())
}

fn command_text(output: &std::process::Output) -> String {
    let text = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    text.trim().chars().take(600).collect()
}

fn list_ollama_models(binary: &Path) -> Result<String, String> {
    let output = Command::new(binary)
        .arg("list")
        .output()
        .map_err(|error| format!("Could not run {}: {error}", binary.display()))?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).into_owned())
    } else {
        Err(command_text(&output))
    }
}

fn ollama_has_model(models: &str, requested: &str) -> bool {
    let latest = format!("{requested}:latest");
    models.lines().skip(1).any(|line| {
        let name = line.split_whitespace().next().unwrap_or_default();
        name == requested || name == latest
    })
}

fn start_ollama_server(binary: &Path, logs: &mut Vec<String>) {
    #[cfg(target_os = "macos")]
    {
        let canonical = binary
            .canonicalize()
            .unwrap_or_else(|_| binary.to_path_buf());
        let app_bundle = canonical
            .ancestors()
            .find(|path| {
                path.extension()
                    .map(|extension| extension == "app")
                    .unwrap_or(false)
            })
            .map(Path::to_path_buf)
            .or_else(|| {
                let system_app = PathBuf::from("/Applications/Ollama.app");
                system_app.exists().then_some(system_app)
            });
        if let Some(app_bundle) = app_bundle {
            if Command::new("open").arg(&app_bundle).spawn().is_ok() {
                logs.push(format!(
                    "Ollama was installed but stopped; launched {}.",
                    app_bundle.display()
                ));
                return;
            }
        }
    }
    match Command::new(binary).arg("serve").spawn() {
        Ok(_) => logs.push("Ollama was installed but stopped; started its local server.".into()),
        Err(error) => logs.push(format!("ERROR: Could not start Ollama: {error}")),
    }
}

#[cfg(target_os = "macos")]
fn install_managed_ollama_macos(logs: &mut Vec<String>) -> Result<PathBuf, String> {
    let app_path = managed_ollama_app_path().ok_or_else(|| {
        "Could not locate this user's home folder for Ollama installation.".to_string()
    })?;
    let runtime_directory = app_path
        .parent()
        .ok_or_else(|| "Managed Ollama installation path is invalid.".to_string())?;
    fs::create_dir_all(runtime_directory).map_err(|error| {
        format!(
            "Could not create Secret Agenda's managed runtime directory {}: {error}",
            runtime_directory.display()
        )
    })?;

    if app_path.exists() {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_millis())
            .unwrap_or_default();
        let backup_path = runtime_directory.join(format!("Ollama.app.incomplete-{timestamp}"));
        fs::rename(&app_path, &backup_path).map_err(|error| {
            format!(
                "Could not preserve incomplete managed Ollama installation {}: {error}",
                app_path.display()
            )
        })?;
        logs.push(format!(
            "Preserved an incomplete managed Ollama install at {}.",
            backup_path.display()
        ));
    }

    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();
    let archive_path = std::env::temp_dir().join(format!("secret-agenda-ollama-{timestamp}.zip"));
    logs.push("Ollama was not found; downloading a managed local copy.".into());
    let download = Command::new("/usr/bin/curl")
        .args(["--fail", "--show-error", "--location", "--output"])
        .arg(&archive_path)
        .arg(MANAGED_OLLAMA_DOWNLOAD)
        .output()
        .map_err(|error| format!("Could not start the Ollama download: {error}"))?;
    if !download.status.success() {
        return Err(format!(
            "Ollama download failed: {}",
            command_text(&download)
        ));
    }

    logs.push("Installing Ollama into Secret Agenda's local runtime folder.".into());
    let extraction = Command::new("/usr/bin/unzip")
        .args(["-q"])
        .arg(&archive_path)
        .args(["-d"])
        .arg(runtime_directory)
        .output()
        .map_err(|error| format!("Could not start the Ollama extraction: {error}"))?;
    let _ = fs::remove_file(&archive_path);
    if !extraction.status.success() {
        return Err(format!(
            "Ollama extraction failed: {}",
            command_text(&extraction)
        ));
    }

    let executable = managed_ollama_executable()
        .filter(|path| path.is_file())
        .ok_or_else(|| "Ollama extracted but its local command was not found.".to_string())?;
    logs.push(format!(
        "Ollama installed locally at {}; no system-wide setup is required.",
        executable.display()
    ));
    Ok(executable)
}

fn install_ollama(logs: &mut Vec<String>) -> Result<PathBuf, String> {
    #[cfg(target_os = "macos")]
    {
        install_managed_ollama_macos(logs)
    }

    #[cfg(not(target_os = "macos"))]
    #[cfg(not(target_os = "windows"))]
    {
        logs.push("Ollama was not found; downloading the official Ollama installer.".into());
        let output = Command::new("sh")
            .args(["-lc", "curl -fsSL https://ollama.com/install.sh | sh"])
            .output()
            .map_err(|error| format!("Could not start the official Ollama installer: {error}"))?;
        if !output.status.success() {
            return Err(format!(
                "Official Ollama installation failed: {}",
                command_text(&output)
            ));
        }
        find_ollama_executable()
            .ok_or_else(|| "Ollama installed but its command was not found afterwards.".into())
    }

    #[cfg(target_os = "windows")]
    {
        logs.push("Ollama was not found; running its official per-user installer.".into());
        let command = format!(
            "$ErrorActionPreference = 'Stop'; Invoke-RestMethod '{}' | Invoke-Expression",
            WINDOWS_OLLAMA_INSTALL_SCRIPT
        );
        let output = Command::new("powershell.exe")
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
            ])
            .arg(command)
            .output()
            .map_err(|error| format!("Could not start the official Ollama installer: {error}"))?;
        if !output.status.success() {
            return Err(format!(
                "Official Ollama installation failed: {}",
                command_text(&output)
            ));
        }
        windows_ollama_executable()
            .filter(|path| path.is_file())
            .ok_or_else(|| "Ollama installed but its command was not found afterwards.".into())
    }
}

fn ensure_ollama_model(
    binary: &Path,
    models: &mut String,
    model: &str,
    logs: &mut Vec<String>,
) -> bool {
    if ollama_has_model(models, model) {
        logs.push(format!("Model ready: {model}."));
        return true;
    }
    logs.push(format!("Model missing: {model}; downloading it now."));
    let output = match Command::new(binary).args(["pull", model]).output() {
        Ok(output) => output,
        Err(error) => {
            logs.push(format!("ERROR: Could not download {model}: {error}"));
            return false;
        }
    };
    if !output.status.success() {
        logs.push(format!(
            "ERROR: Downloading {model} failed: {}",
            command_text(&output)
        ));
        return false;
    }
    match list_ollama_models(binary) {
        Ok(updated) => {
            *models = updated;
            let ready = ollama_has_model(models, model);
            logs.push(if ready {
                format!("Model ready: {model}.")
            } else {
                format!("ERROR: {model} download finished but the model is still unavailable.")
            });
            ready
        }
        Err(error) => {
            logs.push(format!(
                "ERROR: Could not verify {model} after download: {error}"
            ));
            false
        }
    }
}

#[tauri::command]
fn ensure_ollama_runtime() -> OllamaRuntimeStatus {
    let _setup_guard = OLLAMA_RUNTIME_LOCK
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let mut logs = vec!["Checking local Ollama runtime.".into()];
    let binary = match find_ollama_executable() {
        Some(binary) => binary,
        None => match install_ollama(&mut logs) {
            Ok(binary) => binary,
            Err(error) => {
                logs.push(format!("ERROR: {error}"));
                return OllamaRuntimeStatus {
                    ready: false,
                    installed: false,
                    server_ready: false,
                    embedding_model: EMBEDDING_MODEL.into(),
                    rerank_model: RERANK_MODEL.into(),
                    logs,
                };
            }
        },
    };
    logs.push(format!("Ollama command: {}", binary.display()));

    let mut models = match list_ollama_models(&binary) {
        Ok(models) => models,
        Err(error) => {
            logs.push(format!("Ollama server is not ready: {error}"));
            start_ollama_server(&binary, &mut logs);
            let mut ready_models = None;
            for _ in 0..120 {
                thread::sleep(Duration::from_millis(500));
                if let Ok(models) = list_ollama_models(&binary) {
                    ready_models = Some(models);
                    break;
                }
            }
            match ready_models {
                Some(models) => models,
                None => {
                    logs.push("ERROR: Ollama did not become ready within 60 seconds.".into());
                    return OllamaRuntimeStatus {
                        ready: false,
                        installed: true,
                        server_ready: false,
                        embedding_model: EMBEDDING_MODEL.into(),
                        rerank_model: RERANK_MODEL.into(),
                        logs,
                    };
                }
            }
        }
    };

    logs.push("Ollama server ready.".into());
    let embedding_ready = ensure_ollama_model(&binary, &mut models, EMBEDDING_MODEL, &mut logs);
    let rerank_ready = ensure_ollama_model(&binary, &mut models, RERANK_MODEL, &mut logs);
    OllamaRuntimeStatus {
        ready: embedding_ready && rerank_ready,
        installed: true,
        server_ready: true,
        embedding_model: EMBEDDING_MODEL.into(),
        rerank_model: RERANK_MODEL.into(),
        logs,
    }
}

fn default_database_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if let Ok(path) = std::env::var("SEKRET_DB_PATH") {
        return Ok(PathBuf::from(path));
    }

    let mut candidates = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("var/sekret-agenda.sqlite3"));
        candidates.push(cwd.join("../var/sekret-agenda.sqlite3"));
    }
    if let Ok(resource) = app.path().resource_dir() {
        candidates.push(resource.join("var/sekret-agenda.sqlite3"));
    }

    candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| {
            "Database not found. Set SEKRET_DB_PATH or build var/sekret-agenda.sqlite3.".to_string()
        })
}

fn default_workspace_state() -> serde_json::Value {
    serde_json::json!({
        "workspaceName": "Default Workspace",
        "tabs": [],
        "activeTabId": null,
        "activeActivity": "round"
    })
}

fn scoped_cards(cards: Vec<EvidenceCard>, scope: &str, limit: usize) -> Vec<EvidenceCard> {
    cards
        .into_iter()
        .filter(|card| scope == "both" || card.side.as_deref() == Some(scope))
        .take(limit)
        .collect()
}

fn round_result_for_card(card: EvidenceCard, mode: &str) -> RoundSearchResult {
    let relationship = if mode == "exact" {
        "EXACT".to_string()
    } else {
        "EVIDENCE".to_string()
    };
    let explanation = if let Some(diagnostics) = &card.diagnostics {
        if diagnostics.retrieval.is_empty() {
            "Matched by the local backend.".to_string()
        } else {
            format!("Matched by {}.", diagnostics.retrieval.join(", "))
        }
    } else if mode == "exact" {
        "Matched by exact local evidence search.".to_string()
    } else {
        "Matched by the local round backend.".to_string()
    };
    let score = if card.score > 0.0 { card.score } else { 0.45 };
    let debug = card.diagnostics.as_ref().map(|diagnostics| {
        serde_json::json!({
            "retrieval": &diagnostics.retrieval,
            "concepts": &diagnostics.concepts,
            "finalScore": diagnostics.final_score
        })
    });

    RoundSearchResult {
        card,
        score,
        relationship,
        explanation,
        debug,
    }
}

fn grounded_summary(query: &str, results: &[RoundSearchResult]) -> GeneratedResponse {
    let sources = results
        .iter()
        .take(3)
        .map(|result| result.card.id.clone())
        .collect::<Vec<_>>();
    let citations = results
        .iter()
        .take(3)
        .map(|result| result.card.title.clone())
        .collect::<Vec<_>>();
    let text = if results.is_empty() {
        format!("No local evidence matched \"{query}\". Try a broader question or use different wording.")
    } else {
        format!(
            "Found {} local card{} for \"{}\". Start with {}. This response is grounded in the returned evidence; full AI drafting can plug into the same source list later.",
            results.len(),
            if results.len() == 1 { "" } else { "s" },
            query,
            citations.join(", ")
        )
    };

    GeneratedResponse {
        text,
        sources,
        grounded: !results.is_empty(),
    }
}

fn round_database_path(app: &tauri::AppHandle, round_id: &str) -> Result<PathBuf, String> {
    let safe_round = safe_filename(round_id);
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("rounds")
        .join(safe_round);
    std::fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    Ok(dir.join("round.sqlite3"))
}

fn existing_round_database_path(
    app: &tauri::AppHandle,
    round_id: Option<&str>,
) -> Result<PathBuf, String> {
    let round_id = round_id
        .filter(|value| !value.trim().is_empty())
        .ok_or_else(|| "No evidence library is open.".to_string())?;
    let path = round_database_path(app, round_id)?;
    if !path.exists() {
        return Err("Build the library before searching it.".into());
    }
    Ok(path)
}

fn materialize_round_upload(
    app: &tauri::AppHandle,
    round_id: &str,
    path: Option<&str>,
    name: Option<&str>,
    bytes: Option<&[u8]>,
    fallback_name: &str,
) -> Result<PathBuf, String> {
    if let Some(path) = path.filter(|value| !value.trim().is_empty()) {
        return Ok(PathBuf::from(path));
    }
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("rounds")
        .join(safe_filename(round_id))
        .join("uploads");
    std::fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let filename = safe_filename(
        name.filter(|value| !value.trim().is_empty())
            .unwrap_or(fallback_name),
    );
    let upload_path = dir.join(filename);
    let bytes = bytes
        .filter(|bytes| !bytes.is_empty())
        .ok_or_else(|| format!("Missing uploaded DOCX bytes for {fallback_name}."))?;
    std::fs::write(&upload_path, bytes).map_err(|error| error.to_string())?;
    Ok(upload_path)
}

fn safe_filename(value: &str) -> String {
    let sanitized = value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric()
                || character == '.'
                || character == '-'
                || character == '_'
            {
                character
            } else {
                '_'
            }
        })
        .collect::<String>();
    if sanitized.trim_matches('_').is_empty() {
        "round".into()
    } else {
        sanitized
    }
}

fn recent_cards(
    connection: &Connection,
    limit: usize,
    diagnostics: bool,
) -> SqlResult<Vec<EvidenceCard>> {
    let sql = format!(
        "{} ORDER BY sections.order_index, evidence_cards.paragraph_start LIMIT ?1",
        select_cards_sql()
    );
    let mut statement = connection.prepare(&sql)?;
    let rows = statement.query_map([limit as i64], |row| {
        card_from_row(connection, row, 0.0, diagnostics)
    })?;
    rows.collect()
}

fn fallback_round_search(
    connection: &Connection,
    text: &str,
    limit: usize,
) -> SqlResult<Vec<EvidenceCard>> {
    let mut cards = fts_search(connection, text, limit, false)?;
    if cards.is_empty() {
        cards = like_search(connection, text, limit, false)?;
    }
    Ok(cards
        .into_iter()
        .filter(|card| card.side.as_deref() == Some("ours"))
        .take(limit)
        .collect())
}

fn round_cards(
    connection: &Connection,
    scope: &str,
    text: &str,
    limit: usize,
) -> SqlResult<Vec<EvidenceCard>> {
    let side_clause = if scope == "ours" || scope == "opponent" {
        "WHERE evidence_cards.side = ?1"
    } else {
        "WHERE 1 = ?1"
    };
    let text_clause = if text.is_empty() {
        ""
    } else {
        " AND (evidence_cards.tag LIKE ?2 OR evidence_cards.card_name LIKE ?2 OR evidence_cards.body LIKE ?2 OR citations.raw LIKE ?2)"
    };
    let sql = format!(
        "{} {} {} ORDER BY sections.order_index, evidence_cards.paragraph_start LIMIT ?3",
        select_cards_sql(),
        side_clause,
        text_clause
    );
    let side_value = if scope == "ours" || scope == "opponent" {
        scope
    } else {
        "1"
    };
    let pattern = format!("%{}%", text);
    let mut statement = connection.prepare(&sql)?;
    let rows = statement.query_map((side_value, pattern.as_str(), limit as i64), |row| {
        card_from_row(connection, row, 0.0, false)
    })?;
    rows.collect()
}

fn fts_search(
    connection: &Connection,
    text: &str,
    limit: usize,
    diagnostics: bool,
) -> SqlResult<Vec<EvidenceCard>> {
    let fts = fts_query(text);
    if fts.is_empty() {
        return Ok(Vec::new());
    }

    let sql = r#"
SELECT
    bm25(evidence_cards_fts) AS rank,
    evidence_cards.id,
    debate_documents.name AS document_name,
    sections.name AS section_name,
    evidence_cards.tag,
    evidence_cards.card_name,
    citations.author,
    citations.year,
    citations.raw AS citation,
    citations.source_url,
    evidence_cards.source_path,
    evidence_cards.side,
    substr(evidence_cards.body, 1, 1200) AS body_preview,
    evidence_cards.body
FROM evidence_cards_fts
JOIN evidence_cards ON evidence_cards.id = evidence_cards_fts.card_id
JOIN sections ON sections.id = evidence_cards.section_id
JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
LEFT JOIN citations ON citations.card_id = evidence_cards.id
WHERE evidence_cards_fts MATCH ?1
ORDER BY rank
LIMIT ?2
"#;
    let mut statement = connection.prepare(sql)?;
    let rows = statement.query_map((&fts, limit as i64), |row| {
        let rank: f64 = row.get("rank")?;
        card_from_row(connection, row, 1.0 / (1.0 + rank.abs()), diagnostics)
    })?;
    rows.collect()
}

fn like_search(
    connection: &Connection,
    text: &str,
    limit: usize,
    diagnostics: bool,
) -> SqlResult<Vec<EvidenceCard>> {
    let sql = format!(
        "{} WHERE evidence_cards.tag LIKE ?1 OR evidence_cards.card_name LIKE ?1 OR evidence_cards.body LIKE ?1 OR citations.raw LIKE ?1 ORDER BY sections.order_index, evidence_cards.paragraph_start LIMIT ?2",
        select_cards_sql()
    );
    let pattern = format!("%{}%", text);
    let mut statement = connection.prepare(&sql)?;
    let rows = statement.query_map((&pattern, limit as i64), |row| {
        card_from_row(connection, row, 0.25, diagnostics)
    })?;
    rows.collect()
}

fn card_from_row(
    connection: &Connection,
    row: &rusqlite::Row<'_>,
    score: f64,
    diagnostics: bool,
) -> SqlResult<EvidenceCard> {
    let id: String = row.get("id")?;
    let author: Option<String> = row.get("author")?;
    let year: Option<i64> = row.get("year")?;
    let citation: String = row.get("citation")?;
    let title = title_for_card(author.as_deref(), year, &citation);
    let final_score = if score <= 0.0 { 0.0 } else { score };
    Ok(EvidenceCard {
        id: id.clone(),
        title,
        author,
        year,
        section: row.get("section_name")?,
        tag: row.get("tag")?,
        citation,
        url: row.get("source_url")?,
        body: row.get("body")?,
        body_preview: row.get("body_preview")?,
        highlights: highlights_for_card(connection, &id)?,
        score: final_score,
        document_name: row.get("document_name")?,
        side: row.get("side")?,
        diagnostics: diagnostics.then(|| SearchDiagnostics {
            retrieval: vec!["sqlite_fts".into(), "like_fallback_when_needed".into()],
            concepts: vec![],
            final_score,
        }),
    })
}

fn highlights_for_card(connection: &Connection, card_id: &str) -> SqlResult<Vec<Highlight>> {
    let mut statement = connection.prepare(
        "SELECT text, coalesce(color, highlight_color, '') AS color FROM highlights WHERE card_id = ?1 ORDER BY order_index",
    )?;
    let rows = statement.query_map([card_id], |row| {
        let color: String = row.get("color")?;
        Ok(Highlight {
            text: row.get("text")?,
            color: if color.is_empty() { None } else { Some(color) },
        })
    })?;
    rows.collect()
}

fn select_cards_sql() -> &'static str {
    r#"
SELECT
    evidence_cards.id,
    debate_documents.name AS document_name,
    sections.name AS section_name,
    evidence_cards.tag,
    evidence_cards.card_name,
    citations.author,
    citations.year,
    citations.raw AS citation,
    citations.source_url,
    evidence_cards.source_path,
    evidence_cards.side,
    substr(evidence_cards.body, 1, 1200) AS body_preview,
    evidence_cards.body
FROM evidence_cards
JOIN sections ON sections.id = evidence_cards.section_id
JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
LEFT JOIN citations ON citations.card_id = evidence_cards.id
"#
}

fn fts_query(text: &str) -> String {
    text.split(|character: char| !character.is_ascii_alphanumeric() && character != '\'')
        .filter(|token| token.len() >= 2)
        .map(|token| format!("{}*", token))
        .collect::<Vec<_>>()
        .join(" OR ")
}

fn title_for_card(author: Option<&str>, year: Option<i64>, citation: &str) -> String {
    match (author, year) {
        (Some(author), Some(year)) if !author.contains(&year.to_string()) => {
            format!("{author} {year}")
        }
        (Some(author), _) if !author.trim().is_empty() => author.to_string(),
        _ => citation.chars().take(80).collect(),
    }
}

fn state_file(app: &tauri::AppHandle, name: &str) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    Ok(dir.join(name))
}

fn read_json<T>(app: tauri::AppHandle, name: &str) -> Result<Option<T>, String>
where
    T: for<'de> Deserialize<'de>,
{
    let path = state_file(&app, name)?;
    if !path.exists() {
        return Ok(None);
    }
    let text = std::fs::read_to_string(path).map_err(|error| error.to_string())?;
    serde_json::from_str(&text)
        .map(Some)
        .map_err(|error| error.to_string())
}

fn write_json<T>(app: tauri::AppHandle, name: &str, value: &T) -> Result<(), String>
where
    T: Serialize,
{
    let path = state_file(&app, name)?;
    let text = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    std::fs::write(path, text).map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_cache_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("secret-agenda-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("create test cache dir");
        dir
    }

    fn card_separator_fixture() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../data/ex-tech-AFF-APR.docx")
    }

    #[test]
    fn card_separator_runs_authoritative_cpp_from_path() {
        let response = run_card_separator_with_cache_dir(
            test_cache_dir("card-separator-path"),
            CardSeparatorRequest {
                docx_path: Some(card_separator_fixture().to_string_lossy().into_owned()),
                source_name: None,
                docx_bytes: None,
            },
        )
        .expect("card separator should run against test.docx");

        assert!(response.output.contains("US-Iran talks have failed"));
        assert!(response.stderr.is_empty());
        assert_eq!(response.source_file, CARD_SEPARATOR_SOURCE);
    }

    #[test]
    fn card_separator_runs_authoritative_cpp_from_uploaded_bytes() {
        let bytes = std::fs::read(card_separator_fixture()).expect("read bundled test docx");
        let response = run_card_separator_with_cache_dir(
            test_cache_dir("card-separator-bytes"),
            CardSeparatorRequest {
                docx_path: None,
                source_name: Some("test.docx".into()),
                docx_bytes: Some(bytes),
            },
        )
        .expect("card separator should run against uploaded bytes");

        assert!(response.output.contains("US-Iran talks have failed"));
        assert!(response.stderr.is_empty());
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![
            platform_paths,
            load_settings,
            save_settings,
            load_workspace,
            save_workspace,
            create_round_workspace,
            ensure_ollama_runtime,
            search_evidence,
            import_round_source,
            build_round_library,
            list_round_evidence,
            ask_round,
            run_card_separator,
            copy_evidence,
            open_external_url,
            reveal_path
        ])
        .run(tauri::generate_context!())
        .expect("error while running Secret Agenda");
}
