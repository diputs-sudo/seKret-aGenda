mod hybrid;

use rusqlite::{Connection, Result as SqlResult};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Command;
use tauri::Manager;
use tauri_plugin_clipboard_manager::ClipboardExt;

const CARD_SEPARATOR_BYTES: &[u8] = include_bytes!(env!("CARD_SEPARATOR_BIN"));
const CARD_SEPARATOR_SOURCE: &str = env!("CARD_SEPARATOR_SOURCE");

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SearchQuery {
    text: String,
    limit: Option<usize>,
    mode: Option<String>,
    scope: Option<String>,
    include_diagnostics: Option<bool>,
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
    source_text: Option<String>,
    grammar_path: Option<String>,
    grammar_name: Option<String>,
    grammar_text: Option<String>,
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
struct RoundEvidenceQuery {
    round_id: Option<String>,
    scope: Option<String>,
    query: Option<String>,
    limit: Option<usize>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RoundAskQuery {
    round_id: Option<String>,
    query: String,
    scope: Option<String>,
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
fn search_evidence(app: tauri::AppHandle, query: SearchQuery) -> Result<Vec<EvidenceCard>, String> {
    let db_path = default_database_path(&app)?;
    let limit = query.limit.unwrap_or(20).clamp(1, 100);
    let trimmed = query.text.trim();

    if !trimmed.is_empty() && query.mode.as_deref() == Some("hybrid") {
        return hybrid::search(&db_path, &query);
    }

    let connection = Connection::open(db_path).map_err(|error| error.to_string())?;
    if trimmed.is_empty() {
        return recent_cards(&connection, limit, query.include_diagnostics.unwrap_or(false))
            .map_err(|error| error.to_string());
    }

    let mut cards = fts_search(&connection, trimmed, limit, query.include_diagnostics.unwrap_or(false))
        .map_err(|error| error.to_string())?;
    if cards.is_empty() && query.mode.as_deref() != Some("exact") {
        cards = like_search(&connection, trimmed, limit, query.include_diagnostics.unwrap_or(false))
            .map_err(|error| error.to_string())?;
    }
    Ok(cards)
}

#[tauri::command]
fn import_round_source(app: tauri::AppHandle, request: RoundSourceImportRequest) -> Result<RoundSourceState, String> {
    let round_id = request.round_id.as_deref().unwrap_or("default-round");
    let source_path = materialize_round_upload(
        &app,
        round_id,
        request.source_path.as_deref(),
        request.source_name.as_deref(),
        request.source_text.as_deref(),
        "source.docx",
    )?;
    let db_path = round_database_path(&app, round_id)?;
    initialize_round_database(&db_path)?;

    if request.side != "opponent" {
        return Ok(RoundSourceState {
            id: format!("source-{}", request.side),
            filename: PathBuf::from(&source_path)
                .file_name()
                .map(|name| name.to_string_lossy().to_string())
                .unwrap_or_else(|| source_path.to_string_lossy().to_string()),
            path: source_path.to_string_lossy().to_string(),
            side: request.side,
            status: "loaded".into(),
            card_count: 0,
            parse_progress: 0.0,
            index_progress: 0.0,
            error: String::new(),
            diagnostics: vec!["Native import currently registers our-side files; opponent DOCX plus SA parsing is active.".into()],
        });
    }

    let grammar_path = materialize_round_upload(
        &app,
        round_id,
        request.grammar_path.as_deref(),
        request.grammar_name.as_deref(),
        request.grammar_text.as_deref(),
        "grammar.sa",
    )?;
    let parser_source_path = materialize_docx_text_if_needed(&app, round_id, &source_path)?;
    let mut state: RoundSourceState = hybrid::import_opponent_dsl(&db_path, &parser_source_path, &grammar_path)?;
    state.filename = source_path
        .file_name()
        .map(|name| name.to_string_lossy().to_string())
        .unwrap_or_else(|| state.filename.clone());
    state.path = source_path.to_string_lossy().to_string();
    state.diagnostics.push("Opponent DOCX was converted to parser text before SA matching.".into());
    Ok(state)
}

#[tauri::command]
fn list_round_evidence(app: tauri::AppHandle, query: RoundEvidenceQuery) -> Result<Vec<EvidenceCard>, String> {
    let db_path = round_database_path_or_default(&app, query.round_id.as_deref())?;
    let connection = Connection::open(db_path).map_err(|error| error.to_string())?;
    let limit = query.limit.unwrap_or(100).clamp(1, 300);
    let scope = query.scope.unwrap_or_else(|| "both".into());
    let text = query.query.unwrap_or_default();
    round_cards(&connection, &scope, text.trim(), limit).map_err(|error| error.to_string())
}

#[tauri::command]
fn ask_round(app: tauri::AppHandle, request: RoundAskQuery) -> Result<RoundAskResponse, String> {
    let db_path = round_database_path_or_default(&app, request.round_id.as_deref())?;
    let scope = normalize_scope(request.scope.as_deref());
    let mode = request.mode.as_deref().unwrap_or("smart");
    let limit = request.limit.unwrap_or(20).clamp(1, 100);
    let trimmed = request.query.trim();

    let cards = if trimmed.is_empty() {
        Vec::new()
    } else if matches!(mode, "smart" | "semantic" | "hybrid" | "advanced") {
        let query = SearchQuery {
            text: trimmed.to_string(),
            limit: Some(limit),
            mode: Some("hybrid".into()),
            scope: Some(scope.to_string()),
            include_diagnostics: request.include_diagnostics,
        };
        match hybrid::search(&db_path, &query) {
            Ok(cards) => scoped_cards(cards, scope, limit),
            Err(_) => {
                let connection = Connection::open(&db_path).map_err(|error| error.to_string())?;
                round_cards(&connection, scope, trimmed, limit).map_err(|error| error.to_string())?
            }
        }
    } else {
        let connection = Connection::open(&db_path).map_err(|error| error.to_string())?;
        round_cards(&connection, scope, trimmed, limit).map_err(|error| error.to_string())?
    };

    let results = cards
        .into_iter()
        .map(|card| round_result_for_card(card, mode))
        .collect::<Vec<_>>();
    let generated = request
        .generate_answer
        .unwrap_or(true)
        .then(|| grounded_summary(trimmed, &results));

    Ok(RoundAskResponse { results, generated })
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
        return Err(format!("Card Separator requires a .docx file: {}", docx_path.display()));
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
        return Err(format!("Card separator wrote to stderr:\n{}", stderr.trim()));
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
    let upload_dir = cache_dir
        .join("uploads")
        .join("card-separator");
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
        if card.body.is_empty() { card.body_preview } else { card.body }
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
        .ok_or_else(|| "Database not found. Set SEKRET_DB_PATH or build var/sekret-agenda.sqlite3.".to_string())
}

fn default_workspace_state() -> serde_json::Value {
    serde_json::json!({
        "workspaceName": "Default Workspace",
        "tabs": [],
        "activeTabId": null,
        "activeActivity": "round"
    })
}

fn normalize_scope(scope: Option<&str>) -> &'static str {
    match scope {
        Some("ours") => "ours",
        Some("opponent") => "opponent",
        _ => "both",
    }
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
    } else if card.side.as_deref() == Some("opponent") {
        "OPPONENT".to_string()
    } else {
        "ANSWER".to_string()
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
        format!("No local evidence matched \"{query}\". Try a broader question or switch sides.")
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

fn round_database_path_or_default(app: &tauri::AppHandle, round_id: Option<&str>) -> Result<PathBuf, String> {
    if let Some(round_id) = round_id.filter(|value| !value.trim().is_empty()) {
        let path = round_database_path(app, round_id)?;
        if path.exists() {
            return Ok(path);
        }
    }
    default_database_path(app)
}

fn initialize_round_database(path: &PathBuf) -> Result<(), String> {
    let connection = Connection::open(path).map_err(|error| error.to_string())?;
    connection
        .execute_batch(include_str!("../../../backend/models/sqlite_schema.sql"))
        .map_err(|error| error.to_string())
}

fn materialize_round_upload(
    app: &tauri::AppHandle,
    round_id: &str,
    path: Option<&str>,
    name: Option<&str>,
    text: Option<&str>,
    fallback_name: &str,
) -> Result<PathBuf, String> {
    if let Some(path) = path.filter(|value| !value.trim().is_empty()) {
        return Ok(PathBuf::from(path));
    }
    let text = text.ok_or_else(|| format!("Missing uploaded file content for {fallback_name}."))?;
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("rounds")
        .join(safe_filename(round_id))
        .join("uploads");
    std::fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let filename = safe_filename(name.filter(|value| !value.trim().is_empty()).unwrap_or(fallback_name));
    let upload_path = dir.join(filename);
    std::fs::write(&upload_path, text).map_err(|error| error.to_string())?;
    Ok(upload_path)
}

fn materialize_docx_text_if_needed(
    app: &tauri::AppHandle,
    round_id: &str,
    source_path: &Path,
) -> Result<PathBuf, String> {
    if source_path.extension().and_then(|value| value.to_str()).map(|value| value.eq_ignore_ascii_case("docx")) != Some(true) {
        return Ok(source_path.to_path_buf());
    }

    let text = extract_docx_text(source_path)?;
    if text.trim().is_empty() {
        return Err("DOCX contained no readable text.".into());
    }

    let dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("rounds")
        .join(safe_filename(round_id))
        .join("uploads");
    std::fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let stem = source_path
        .file_stem()
        .map(|value| value.to_string_lossy().to_string())
        .unwrap_or_else(|| "opponent".into());
    let text_path = dir.join(format!("{}-docx-text.txt", safe_filename(&stem)));
    std::fs::write(&text_path, text).map_err(|error| error.to_string())?;
    Ok(text_path)
}

fn extract_docx_text(path: &Path) -> Result<String, String> {
    const SCRIPT: &str = r#"
import sys
import zipfile
import xml.etree.ElementTree as ET

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{%s}" % WORD_NS["w"]

with zipfile.ZipFile(sys.argv[1]) as archive:
    root = ET.fromstring(archive.read("word/document.xml"))

for paragraph in root.findall(".//w:body/w:p", WORD_NS):
    parts = []
    for node in paragraph.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "tab":
            parts.append(" ")
        elif node.tag in {W + "br", W + "cr"}:
            parts.append("\n")
    text = "".join(parts).strip()
    if text:
        print(text)
"#;

    for python in ["python3", "python"] {
        let output = Command::new(python)
            .arg("-c")
            .arg(SCRIPT)
            .arg(path)
            .output();
        let Ok(output) = output else {
            continue;
        };
        if output.status.success() {
            return String::from_utf8(output.stdout).map_err(|error| error.to_string());
        }
    }
    Err("DOCX import requires Python to extract document text in this alpha build.".into())
}

fn safe_filename(value: &str) -> String {
    let sanitized = value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '.' || character == '-' || character == '_' {
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

fn recent_cards(connection: &Connection, limit: usize, diagnostics: bool) -> SqlResult<Vec<EvidenceCard>> {
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

fn round_cards(connection: &Connection, scope: &str, text: &str, limit: usize) -> SqlResult<Vec<EvidenceCard>> {
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
    let side_value = if scope == "ours" || scope == "opponent" { scope } else { "1" };
    let pattern = format!("%{}%", text);
    let mut statement = connection.prepare(&sql)?;
    let rows = statement.query_map((side_value, pattern.as_str(), limit as i64), |row| {
        card_from_row(connection, row, 0.0, false)
    })?;
    rows.collect()
}

fn fts_search(connection: &Connection, text: &str, limit: usize, diagnostics: bool) -> SqlResult<Vec<EvidenceCard>> {
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

fn like_search(connection: &Connection, text: &str, limit: usize, diagnostics: bool) -> SqlResult<Vec<EvidenceCard>> {
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
        "SELECT text, coalesce(color, highlight_color, '') AS color FROM highlights WHERE card_id = ?1 ORDER BY order_index LIMIT 8",
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
        (Some(author), Some(year)) if !author.contains(&year.to_string()) => format!("{author} {year}"),
        (Some(author), _) if !author.trim().is_empty() => author.to_string(),
        _ => citation.chars().take(80).collect(),
    }
}

fn state_file(app: &tauri::AppHandle, name: &str) -> Result<PathBuf, String> {
    let dir = app.path().app_data_dir().map_err(|error| error.to_string())?;
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
    serde_json::from_str(&text).map(Some).map_err(|error| error.to_string())
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
        let dir = std::env::temp_dir().join(format!(
            "secret-agenda-{name}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("create test cache dir");
        dir
    }

    #[test]
    fn card_separator_runs_authoritative_cpp_from_path() {
        let response = run_card_separator_with_cache_dir(
            test_cache_dir("card-separator-path"),
            CardSeparatorRequest {
                docx_path: Some("/Users/kevingao/Developer/local/scripts/test.docx".into()),
                source_name: None,
                docx_bytes: None,
            },
        )
        .expect("card separator should run against test.docx");

        assert!(response
            .output
            .starts_with("NL - Chinese leadership is guaranteed."));
        assert!(response.output.contains("T - Quantum will break all encryption"));
        assert!(response.stderr.is_empty());
        assert_eq!(response.source_file, CARD_SEPARATOR_SOURCE);
    }

    #[test]
    fn card_separator_runs_authoritative_cpp_from_uploaded_bytes() {
        let bytes = std::fs::read("/Users/kevingao/Developer/local/scripts/test.docx")
            .expect("read test docx");
        let response = run_card_separator_with_cache_dir(
            test_cache_dir("card-separator-bytes"),
            CardSeparatorRequest {
                docx_path: None,
                source_name: Some("test.docx".into()),
                docx_bytes: Some(bytes),
            },
        )
        .expect("card separator should run against uploaded bytes");

        assert!(response
            .output
            .starts_with("NL - Chinese leadership is guaranteed."));
        assert!(response.output.contains("Matt Swayne ‘26."));
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
            search_evidence,
            import_round_source,
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
