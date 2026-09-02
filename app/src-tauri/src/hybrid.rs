use super::{EvidenceCard, SearchQuery};
use serde::Deserialize;
use std::collections::BTreeMap;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::path::Path;

#[repr(C)]
struct NativeJsonResult {
    json: *mut c_char,
    error: *mut c_char,
}

#[repr(C)]
struct NativePipelineJsonResult {
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
    fn sekret_native_import_docx_json(
        docx_path: *const c_char,
        db_path: *const c_char,
        schema_sql: *const c_char,
    ) -> NativePipelineJsonResult;
    fn sekret_native_build_vectors_json(
        db_path: *const c_char,
        kind: *const c_char,
        reset: i32,
    ) -> NativePipelineJsonResult;
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct NativeImportStats {
    pub(super) document_name: String,
    pub(super) sections: usize,
    pub(super) cards: usize,
    pub(super) citations: usize,
    pub(super) highlights: usize,
}

#[derive(Debug, Deserialize)]
pub(super) struct NativeVectorBuildStats {
    pub(super) fast: usize,
    pub(super) deep: usize,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct NativeSearchResponse {
    pub(super) cards: Vec<EvidenceCard>,
    pub(super) source_status: String,
    pub(super) main_claim: String,
    pub(super) uncertainty: Option<String>,
    pub(super) timings: BTreeMap<String, f64>,
    pub(super) logs: Vec<String>,
}

pub(super) fn search(db_path: &Path, query: &SearchQuery) -> Result<NativeSearchResponse, String> {
    let db_path = c_string(db_path, "Database path")?;
    let chroma_path = CString::new("var/chroma").expect("static string has no NUL bytes");
    let request_json = CString::new(request_payload(query)?.as_bytes())
        .map_err(|_| "Hybrid request contained an interior NUL byte.".to_string())?;
    let result = unsafe {
        sekret_hybrid_search_json(
            db_path.as_ptr(),
            chroma_path.as_ptr(),
            request_json.as_ptr(),
        )
    };
    decode_native_result(result.json, result.error, "Native C++ search")
}

pub(super) fn import_docx(
    db_path: &Path,
    source_path: &Path,
    schema_sql: &str,
) -> Result<NativeImportStats, String> {
    let db_path = c_string(db_path, "Database path")?;
    let source_path = c_string(source_path, "Source path")?;
    let schema_sql = CString::new(schema_sql)
        .map_err(|_| "Embedded SQLite schema contained an interior NUL byte.".to_string())?;
    let result = unsafe {
        sekret_native_import_docx_json(source_path.as_ptr(), db_path.as_ptr(), schema_sql.as_ptr())
    };
    decode_native_result(result.json, result.error, "Native C++ importer")
}

pub(super) fn build_vectors(db_path: &Path) -> Result<NativeVectorBuildStats, String> {
    let db_path = c_string(db_path, "Database path")?;
    let kind = CString::new("all").expect("static string has no NUL bytes");
    let result = unsafe { sekret_native_build_vectors_json(db_path.as_ptr(), kind.as_ptr(), 1) };
    decode_native_result(result.json, result.error, "Native C++ vector indexer")
}

fn c_string(path: &Path, label: &str) -> Result<CString, String> {
    CString::new(path.to_string_lossy().as_bytes())
        .map_err(|_| format!("{label} contained an interior NUL byte."))
}

fn request_payload(query: &SearchQuery) -> Result<String, String> {
    serde_json::to_string(&serde_json::json!({
        "query": query.text,
        "mode": query.mode.as_deref().unwrap_or("hybrid"),
        "scope": query.scope.as_deref().unwrap_or("both"),
        "limit": query.limit.unwrap_or(20).clamp(1, 100),
        "includeDiagnostics": query.include_diagnostics.unwrap_or(false),
        "analysisMode": query.analysis_mode.unwrap_or(false),
        "fullContextRerank": query.full_context_rerank.unwrap_or(false),
        "modelRerank": query.model_rerank.unwrap_or(false),
        "modelRerankLimit": query.model_rerank_limit.unwrap_or(24).clamp(1, 40),
        "vectorLimit": query.vector_limit.unwrap_or(50).clamp(1, 100),
        "lexicalLimit": query.lexical_limit.unwrap_or(50).clamp(1, 100),
        "citationLimit": query.citation_limit.unwrap_or(20).clamp(1, 100),
    }))
    .map_err(|error| error.to_string())
}

fn decode_native_result<T>(
    json: *mut c_char,
    error: *mut c_char,
    operation: &str,
) -> Result<T, String>
where
    T: for<'de> Deserialize<'de>,
{
    if let Some(error) = take_native_string(error) {
        return Err(format!("{operation} failed: {error}"));
    }
    let json = take_native_string(json)
        .ok_or_else(|| format!("{operation} returned no JSON response."))?;
    serde_json::from_str(&json)
        .map_err(|error| format!("{operation} returned invalid JSON: {error}"))
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
            analysis_mode: Some(false),
            full_context_rerank: Some(true),
            model_rerank: Some(true),
            model_rerank_limit: Some(12),
            vector_limit: Some(50),
            lexical_limit: Some(50),
            citation_limit: Some(20),
        };
        let payload = request_payload(&query).unwrap();
        assert!(payload.contains("\"query\":\"Hashem\""));
        assert!(payload.contains("\"mode\":\"hybrid\""));
        assert!(payload.contains("\"limit\":3"));
        assert!(payload.contains("\"includeDiagnostics\":true"));
        assert!(payload.contains("\"fullContextRerank\":true"));
        assert!(payload.contains("\"modelRerank\":true"));
        assert!(payload.contains("\"modelRerankLimit\":12"));
        assert!(payload.contains("\"vectorLimit\":50"));
    }
}
