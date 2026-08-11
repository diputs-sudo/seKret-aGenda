use super::{EvidenceCard, SearchQuery};
use serde::Deserialize;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::path::Path;

#[repr(C)]
struct NativeJsonResult {
    json: *mut c_char,
    error: *mut c_char,
}

unsafe extern "C" {
    fn sekret_hybrid_search_json(
        db_path: *const c_char,
        chroma_path: *const c_char,
        request_json: *const c_char,
    ) -> NativeJsonResult;
    fn sekret_hybrid_free_string(value: *mut c_char);
    fn sekret_import_opponent_dsl_json(
        db_path: *const c_char,
        source_path: *const c_char,
        grammar_path: *const c_char,
    ) -> NativeJsonResult;
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NativeHybridResponse {
    cards: Vec<EvidenceCard>,
    #[allow(dead_code)]
    source_status: String,
    #[allow(dead_code)]
    main_claim: String,
    #[allow(dead_code)]
    uncertainty: Option<String>,
}

pub(super) fn search(db_path: &Path, query: &SearchQuery) -> Result<Vec<EvidenceCard>, String> {
    let db_path = CString::new(db_path.to_string_lossy().as_bytes())
        .map_err(|_| "Database path contained an interior NUL byte.".to_string())?;
    let chroma_path = CString::new("var/chroma").expect("static string has no NUL bytes");
    let request_json = CString::new(request_payload(query)?.as_bytes())
        .map_err(|_| "Hybrid request contained an interior NUL byte.".to_string())?;

    let result = unsafe {
        sekret_hybrid_search_json(db_path.as_ptr(), chroma_path.as_ptr(), request_json.as_ptr())
    };
    let error = take_native_string(result.error);
    if let Some(error) = error {
        return Err(error);
    }

    let json = take_native_string(result.json)
        .ok_or_else(|| "Native hybrid backend returned no JSON response.".to_string())?;
    let response: NativeHybridResponse =
        serde_json::from_str(&json).map_err(|error| error.to_string())?;
    Ok(response.cards)
}

pub(super) fn import_opponent_dsl<T>(
    db_path: &Path,
    source_path: &Path,
    grammar_path: &Path,
) -> Result<T, String>
where
    T: for<'de> Deserialize<'de>,
{
    let db_path = CString::new(db_path.to_string_lossy().as_bytes())
        .map_err(|_| "Database path contained an interior NUL byte.".to_string())?;
    let source_path = CString::new(source_path.to_string_lossy().as_bytes())
        .map_err(|_| "Source path contained an interior NUL byte.".to_string())?;
    let grammar_path = CString::new(grammar_path.to_string_lossy().as_bytes())
        .map_err(|_| "Grammar path contained an interior NUL byte.".to_string())?;

    let result = unsafe {
        sekret_import_opponent_dsl_json(db_path.as_ptr(), source_path.as_ptr(), grammar_path.as_ptr())
    };
    let error = take_native_string(result.error);
    if let Some(error) = error {
        return Err(error);
    }

    let json = take_native_string(result.json)
        .ok_or_else(|| "Native opponent importer returned no JSON response.".to_string())?;
    serde_json::from_str(&json).map_err(|error| error.to_string())
}

fn request_payload(query: &SearchQuery) -> Result<String, String> {
    serde_json::to_string(&serde_json::json!({
        "query": query.text,
        "mode": query.mode.as_deref().unwrap_or("hybrid"),
        "scope": query.scope.as_deref().unwrap_or("both"),
        "limit": query.limit.unwrap_or(20).clamp(1, 100),
        "includeDiagnostics": query.include_diagnostics.unwrap_or(false),
    }))
    .map_err(|error| error.to_string())
}

fn take_native_string(value: *mut c_char) -> Option<String> {
    if value.is_null() {
        return None;
    }
    let text = unsafe { CStr::from_ptr(value).to_string_lossy().into_owned() };
    unsafe {
        sekret_hybrid_free_string(value);
    }
    Some(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_payload_maps_tauri_query_to_native_query() {
        let query = SearchQuery {
            text: "Hashem".into(),
            limit: Some(3),
            mode: Some("hybrid".into()),
            scope: None,
            include_diagnostics: Some(true),
        };

        let payload = request_payload(&query).unwrap();

        assert!(payload.contains("\"query\":\"Hashem\""));
        assert!(payload.contains("\"mode\":\"hybrid\""));
        assert!(payload.contains("\"limit\":3"));
        assert!(payload.contains("\"includeDiagnostics\":true"));
    }

    #[test]
    fn bridge_returns_native_cards_when_repo_db_is_present() {
        let db_path = std::path::PathBuf::from("../../var/sekret-agenda.sqlite3");
        if !db_path.exists() {
            return;
        }

        let query = SearchQuery {
            text: "Hashem".into(),
            limit: Some(3),
            mode: Some("hybrid".into()),
            scope: None,
            include_diagnostics: Some(true),
        };

        let cards = search(&db_path, &query).unwrap();

        assert!(!cards.is_empty());
        assert!(cards.iter().any(|card| {
            card.author.as_deref() == Some("Hashem") || card.title.contains("Hashem")
        }));
        assert!(cards.iter().any(|card| card.diagnostics.is_some()));
    }
}
