use rusqlite::{Connection, Result as SqlResult};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::Manager;
use tauri_plugin_clipboard_manager::ClipboardExt;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SearchQuery {
    text: String,
    limit: Option<usize>,
    mode: Option<String>,
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
    diagnostics: Option<SearchDiagnostics>,
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

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct WorkspaceState {
    workspace_name: String,
    tabs: serde_json::Value,
    active_tab_id: Option<String>,
    active_activity: String,
}

impl Default for WorkspaceState {
    fn default() -> Self {
        Self {
            workspace_name: "Default Workspace".into(),
            tabs: serde_json::json!([]),
            active_tab_id: None,
            active_activity: "search".into(),
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
fn load_workspace(app: tauri::AppHandle) -> Result<WorkspaceState, String> {
    read_json(app, "workspace.json").map(|value| value.unwrap_or_default())
}

#[tauri::command]
fn save_workspace(app: tauri::AppHandle, workspace: WorkspaceState) -> Result<(), String> {
    write_json(app, "workspace.json", &workspace)
}

#[tauri::command]
fn search_evidence(app: tauri::AppHandle, query: SearchQuery) -> Result<Vec<EvidenceCard>, String> {
    let db_path = default_database_path(&app)?;
    let connection = Connection::open(db_path).map_err(|error| error.to_string())?;
    let limit = query.limit.unwrap_or(20).clamp(1, 100);
    let trimmed = query.text.trim();

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
            copy_evidence,
            open_external_url,
            reveal_path
        ])
        .run(tauri::generate_context!())
        .expect("error while running Secret Agenda");
}
