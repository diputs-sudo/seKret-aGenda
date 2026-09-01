#pragma once

#include "sqlite_store.hpp"

#include <cstddef>
#include <string>
#include <vector>

namespace sekret::hybrid {

struct NativeDocumentStats {
    std::string document_name;
    std::size_t sections = 0;
    std::size_t cards = 0;
    std::size_t citations = 0;
    std::size_t highlights = 0;
};

struct NativeVectorBuildStats {
    std::size_t fast = 0;
    std::size_t deep = 0;
};

struct NativeVectorQueryStats {
    double vector_availability_ms = 0.0;
    double embedding_ms = 0.0;
    double vector_search_ms = 0.0;
    double hydration_ms = 0.0;
};

NativeDocumentStats import_docx_to_sqlite_with_schema_text(
    const std::string& docx_path,
    const std::string& db_path,
    const std::string& schema_sql
);

NativeDocumentStats import_docx_to_sqlite(
    const std::string& docx_path,
    const std::string& db_path,
    const std::string& schema_path
);

NativeVectorBuildStats build_native_vector_cache(
    const std::string& db_path,
    const std::string& kind,
    bool reset,
    std::size_t max_chars
);

std::vector<RetrievedCard> query_native_vectors(
    const std::string& db_path,
    const std::string& query,
    std::size_t limit,
    NativeVectorQueryStats* stats = nullptr
);

} // namespace sekret::hybrid

extern "C" {

struct SekretNativePipelineJsonResult {
    char* json;
    char* error;
};

SekretNativePipelineJsonResult sekret_native_import_docx_json(
    const char* docx_path,
    const char* db_path,
    const char* schema_sql
);

SekretNativePipelineJsonResult sekret_native_build_vectors_json(
    const char* db_path,
    const char* kind,
    int reset
);

} // extern "C"
