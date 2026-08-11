#pragma once

#include <cstddef>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace sekret::hybrid {

struct Highlight {
    std::string text;
    std::optional<std::string> color;
};

struct SearchDiagnostics {
    std::vector<std::string> retrieval_sources;
    std::vector<std::string> concepts;
    double retrieval_score = 0.0;
    double reranker_score = 0.0;
    double final_score = 0.0;
};

struct EvidenceCard {
    std::string id;
    std::string title;
    std::optional<std::string> author;
    std::optional<int> year;
    std::string section;
    std::string tag;
    std::string citation;
    std::optional<std::string> url;
    std::string body;
    std::string body_preview;
    std::vector<Highlight> highlights;
    double score = 0.0;
    std::string document_name;
    std::optional<SearchDiagnostics> diagnostics;
};

struct HybridSearchRequest {
    std::string query;
    std::string mode = "search";
    std::size_t limit = 10;
    std::size_t vector_limit = 50;
    std::size_t lexical_limit = 50;
    std::size_t citation_limit = 20;
    bool include_diagnostics = false;
};

struct HybridSearchResponse {
    std::vector<EvidenceCard> cards;
    std::string source_status;
    std::string main_claim;
    std::optional<std::string> uncertainty;
};

struct HybridEngineOptions {
    std::string db_path;
    std::string chroma_path;
};

class HybridEngine {
public:
    explicit HybridEngine(HybridEngineOptions options);
    ~HybridEngine();

    HybridEngine(const HybridEngine&) = delete;
    HybridEngine& operator=(const HybridEngine&) = delete;
    HybridEngine(HybridEngine&&) noexcept;
    HybridEngine& operator=(HybridEngine&&) noexcept;

    HybridSearchResponse search(const HybridSearchRequest& request) const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace sekret::hybrid

extern "C" {

struct SekretHybridJsonResult {
    char* json;
    char* error;
};

SekretHybridJsonResult sekret_hybrid_search_json(
    const char* db_path,
    const char* chroma_path,
    const char* request_json
);

void sekret_hybrid_free_string(char* value);

} // extern "C"
