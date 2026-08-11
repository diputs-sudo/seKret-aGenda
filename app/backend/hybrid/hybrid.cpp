#include "hybrid.hpp"

#include "argument_builder.hpp"
#include "fusion.hpp"
#include "query_intent.hpp"
#include "reranker.hpp"
#include "sqlite_store.hpp"
#include "vector_store.hpp"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <map>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace sekret::hybrid {
namespace {

std::string json_escape(const std::string& value) {
    std::ostringstream output;
    for (const unsigned char character : value) {
        switch (character) {
            case '"':
                output << "\\\"";
                break;
            case '\\':
                output << "\\\\";
                break;
            case '\b':
                output << "\\b";
                break;
            case '\f':
                output << "\\f";
                break;
            case '\n':
                output << "\\n";
                break;
            case '\r':
                output << "\\r";
                break;
            case '\t':
                output << "\\t";
                break;
            default:
                if (character < 0x20) {
                    output << "\\u";
                    output << "00";
                    constexpr char hex[] = "0123456789abcdef";
                    output << hex[(character >> 4) & 0x0f];
                    output << hex[character & 0x0f];
                } else {
                    output << character;
                }
                break;
        }
    }
    return output.str();
}

char* copy_c_string(const std::string& value) {
    const auto byte_count = value.size() + 1;
    auto* buffer = static_cast<char*>(std::malloc(byte_count));
    if (buffer == nullptr) {
        return nullptr;
    }
    std::memcpy(buffer, value.c_str(), byte_count);
    return buffer;
}

std::string response_to_json(const HybridSearchResponse& response) {
    std::ostringstream output;
    output << "{";
    output << "\"cards\":[";
    for (std::size_t index = 0; index < response.cards.size(); ++index) {
        const auto& card = response.cards[index];
        if (index != 0) {
            output << ",";
        }
        output << "{";
        output << "\"id\":\"" << json_escape(card.id) << "\",";
        output << "\"title\":\"" << json_escape(card.title) << "\",";
        output << "\"author\":";
        if (card.author.has_value()) {
            output << "\"" << json_escape(*card.author) << "\"";
        } else {
            output << "null";
        }
        output << ",\"year\":";
        if (card.year.has_value()) {
            output << *card.year;
        } else {
            output << "null";
        }
        output << ",\"section\":\"" << json_escape(card.section) << "\",";
        output << "\"tag\":\"" << json_escape(card.tag) << "\",";
        output << "\"citation\":\"" << json_escape(card.citation) << "\",";
        output << "\"url\":";
        if (card.url.has_value()) {
            output << "\"" << json_escape(*card.url) << "\"";
        } else {
            output << "null";
        }
        output << ",\"body\":\"" << json_escape(card.body) << "\",";
        output << "\"bodyPreview\":\"" << json_escape(card.body_preview) << "\",";
        output << "\"highlights\":[";
        for (std::size_t highlight_index = 0; highlight_index < card.highlights.size(); ++highlight_index) {
            const auto& highlight = card.highlights[highlight_index];
            if (highlight_index != 0) {
                output << ",";
            }
            output << "{\"text\":\"" << json_escape(highlight.text) << "\",\"color\":";
            if (highlight.color.has_value()) {
                output << "\"" << json_escape(*highlight.color) << "\"";
            } else {
                output << "null";
            }
            output << "}";
        }
        output << "],";
        output << "\"score\":" << card.score << ",";
        output << "\"documentName\":\"" << json_escape(card.document_name) << "\",";
        output << "\"diagnostics\":";
        if (card.diagnostics.has_value()) {
            output << "{";
            output << "\"retrieval\":[";
            for (std::size_t source_index = 0; source_index < card.diagnostics->retrieval_sources.size(); ++source_index) {
                if (source_index != 0) {
                    output << ",";
                }
                output << "\"" << json_escape(card.diagnostics->retrieval_sources[source_index]) << "\"";
            }
            output << "],\"concepts\":[";
            for (std::size_t concept_index = 0; concept_index < card.diagnostics->concepts.size(); ++concept_index) {
                if (concept_index != 0) {
                    output << ",";
                }
                output << "\"" << json_escape(card.diagnostics->concepts[concept_index]) << "\"";
            }
            output << "],\"retrievalScore\":" << card.diagnostics->retrieval_score;
            output << ",\"rerankerScore\":" << card.diagnostics->reranker_score;
            output << ",\"finalScore\":" << card.diagnostics->final_score;
            output << "}";
        } else {
            output << "null";
        }
        output << "}";
    }
    output << "],";
    output << "\"sourceStatus\":\"" << json_escape(response.source_status) << "\",";
    output << "\"mainClaim\":\"" << json_escape(response.main_claim) << "\",";
    output << "\"uncertainty\":";
    if (response.uncertainty.has_value()) {
        output << "\"" << json_escape(*response.uncertainty) << "\"";
    } else {
        output << "null";
    }
    output << "}";
    return output.str();
}

std::string lower_copy(const std::string& text) {
    std::string lowered;
    lowered.reserve(text.size());
    for (const unsigned char character : text) {
        lowered.push_back(static_cast<char>(std::tolower(character)));
    }
    return lowered;
}

std::string unescape_json_string(const std::string& value) {
    std::string output;
    output.reserve(value.size());
    for (std::size_t index = 0; index < value.size(); ++index) {
        if (value[index] != '\\' || index + 1 >= value.size()) {
            output.push_back(value[index]);
            continue;
        }
        const char escaped = value[++index];
        switch (escaped) {
            case '"':
                output.push_back('"');
                break;
            case '\\':
                output.push_back('\\');
                break;
            case 'n':
                output.push_back('\n');
                break;
            case 'r':
                output.push_back('\r');
                break;
            case 't':
                output.push_back('\t');
                break;
            default:
                output.push_back(escaped);
                break;
        }
    }
    return output;
}

std::optional<std::string> json_string_field(const std::string& json, const std::string& name) {
    const std::regex pattern("\"" + name + R"JSON("\s*:\s*"((?:\\.|[^"\\])*)")JSON");
    std::smatch match;
    if (!std::regex_search(json, match, pattern)) {
        return std::nullopt;
    }
    return unescape_json_string(match[1].str());
}

std::optional<std::size_t> json_size_field(const std::string& json, const std::string& name) {
    const std::regex pattern("\"" + name + R"("\s*:\s*(\d+))");
    std::smatch match;
    if (!std::regex_search(json, match, pattern)) {
        return std::nullopt;
    }
    return static_cast<std::size_t>(std::stoul(match[1].str()));
}

std::optional<bool> json_bool_field(const std::string& json, const std::string& name) {
    const std::regex pattern("\"" + name + R"("\s*:\s*(true|false))", std::regex::icase);
    std::smatch match;
    if (!std::regex_search(json, match, pattern)) {
        return std::nullopt;
    }
    return lower_copy(match[1].str()) == "true";
}

HybridSearchRequest request_from_json_or_text(const std::string& request_json) {
    HybridSearchRequest request;
    if (!request_json.empty() && request_json.front() == '{') {
        auto query = json_string_field(request_json, "query");
        if (!query.has_value()) {
            query = json_string_field(request_json, "text");
        }
        request.query = query.value_or("");
        request.mode = json_string_field(request_json, "mode").value_or(request.mode);
        request.limit = json_size_field(request_json, "limit").value_or(request.limit);
        request.vector_limit = json_size_field(request_json, "vectorLimit").value_or(request.vector_limit);
        request.lexical_limit = json_size_field(request_json, "lexicalLimit").value_or(request.lexical_limit);
        request.citation_limit = json_size_field(request_json, "citationLimit").value_or(request.citation_limit);
        auto include_diagnostics = json_bool_field(request_json, "includeDiagnostics");
        if (!include_diagnostics.has_value()) {
            include_diagnostics = json_bool_field(request_json, "include_diagnostics");
        }
        request.include_diagnostics = include_diagnostics.value_or(false);
    } else {
        request.query = request_json;
    }
    request.limit = std::max<std::size_t>(1, std::min<std::size_t>(request.limit, 100));
    return request;
}

EvidenceCard to_evidence_card(const RerankedCard& row, const QueryIntent& intent, bool diagnostics) {
    EvidenceCard card = row.card;
    card.id = row.card.card_id.empty() ? row.card.id : row.card.card_id;
    card.score = row.assessment.relevance_score != 0.0 ? row.assessment.relevance_score : row.card.score;
    if (diagnostics) {
        SearchDiagnostics info;
        for (const auto& [source, rank] : row.card.source_ranks) {
            (void)rank;
            info.retrieval_sources.push_back(source);
        }
        info.concepts = intent.phrase_concepts.empty() ? intent.concepts : intent.phrase_concepts;
        info.retrieval_score = row.card.retrieval_score;
        info.reranker_score = row.assessment.relevance_score;
        info.final_score = card.score;
        card.diagnostics = info;
    }
    return card;
}

std::string lookup_source_name(const QueryIntent& intent) {
    if (intent.search_mode == SearchMode::Citation) {
        return "citation_lookup";
    }
    if (intent.search_mode == SearchMode::Author) {
        return "author_lookup";
    }
    if (intent.search_mode == SearchMode::Section) {
        return "section_lookup";
    }
    return "lookup";
}

std::vector<RerankedCard> lookup_to_reranked(
    std::vector<RetrievedCard> rows,
    const QueryIntent& intent,
    const std::string& source_name
) {
    std::vector<RerankedCard> results;
    for (std::size_t index = 0; index < rows.size(); ++index) {
        auto& row = rows[index];
        const int rank = static_cast<int>(index + 1);
        row.retrieval_score = 1.0 / static_cast<double>(rank);
        row.reranker_score = row.retrieval_score;
        row.score = row.retrieval_score;
        row.source_ranks[source_name] = rank;
        row.source_scores[source_name] = 1.0;

        CandidateAssessment assessment;
        assessment.card_id = row.card_id;
        assessment.relevance_score = row.retrieval_score;
        assessment.topic_match = 1.0;
        assessment.relationship = Relationship::Qualifies;
        assessment.evidence_strength = 1.0;
        assessment.confidence = 1.0;
        assessment.reasons = {"direct " + source_name + " lookup"};
        results.push_back({row, assessment, reranker_input(intent, row)});
    }
    return results;
}

std::optional<std::string> citation_lookup_query(const QueryIntent& intent) {
    if (intent.author_filter.has_value()) {
        auto query = *intent.author_filter;
        if (intent.year_min.has_value()) {
            query += " " + std::to_string(*intent.year_min);
        }
        return query;
    }
    static const std::regex citation_re(R"(\b[A-Z][A-Za-z'’-]{2,}\s+(?:\d{4}|[‘'’]\d{2}|\d{2})\b)");
    if (std::regex_search(intent.raw_query, citation_re)) {
        return intent.raw_query;
    }
    const auto word_count = static_cast<std::size_t>(
        std::count_if(intent.search_text.begin(), intent.search_text.end(), [](char c) { return std::isspace(static_cast<unsigned char>(c)); })
    ) + (intent.search_text.empty() ? 0 : 1);
    if (word_count <= 4 && std::regex_search(intent.search_text, std::regex(R"(\d{2,4}|[‘'’]\d{2})"))) {
        return intent.search_text;
    }
    return std::nullopt;
}

std::optional<std::vector<RerankedCard>> direct_lookup(
    const HybridEngineOptions& options,
    const QueryIntent& intent,
    const HybridSearchRequest& request
) {
    const auto limit = intent.requested_count.value_or(static_cast<int>(request.limit));
    std::vector<RetrievedCard> rows;
    if (intent.search_mode == SearchMode::Citation && intent.author_filter.has_value() && intent.year_min.has_value()) {
        rows = lookup_citation_cards(options.db_path, *intent.author_filter, *intent.year_min, static_cast<std::size_t>(limit));
    } else if (intent.search_mode == SearchMode::Author && intent.author_filter.has_value()) {
        rows = lookup_author_cards(options.db_path, *intent.author_filter, static_cast<std::size_t>(limit));
    } else if (intent.search_mode == SearchMode::Section && intent.section_filter.has_value()) {
        rows = lookup_section_cards(options.db_path, *intent.section_filter, static_cast<std::size_t>(limit));
    } else {
        return std::nullopt;
    }
    if (rows.empty() && intent.search_mode == SearchMode::Author && !intent.search_text.empty()) {
        const auto explicit_author = "author:" + *intent.author_filter;
        if (lower_copy(intent.raw_query).find(lower_copy(explicit_author)) == std::string::npos) {
            return std::nullopt;
        }
    }
    return lookup_to_reranked(std::move(rows), intent, lookup_source_name(intent));
}

bool card_matches_filters(const RetrievedCard& card, const QueryIntent& intent) {
    if (intent.author_filter.has_value()) {
        const auto expected = lower_copy(*intent.author_filter);
        const auto author = lower_copy(card.author.value_or(""));
        const auto card_name = lower_copy(card.card_name);
        if (author.find(expected) == std::string::npos && card_name.find(expected) == std::string::npos) {
            return false;
        }
    }
    if (intent.year_min.has_value() && (!card.year.has_value() || *card.year < *intent.year_min)) {
        return false;
    }
    if (intent.year_max.has_value() && (!card.year.has_value() || *card.year > *intent.year_max)) {
        return false;
    }
    if (intent.section_filter.has_value() && lower_copy(card.section).find(lower_copy(*intent.section_filter)) == std::string::npos) {
        return false;
    }
    if (intent.category_filter.has_value() && lower_copy(card.category) != lower_copy(*intent.category_filter)) {
        return false;
    }
    if (intent.topical_filter.has_value()) {
        const auto topical = lower_copy(card.topical);
        const bool value = topical == "true" || topical == "yes" || topical == "1";
        if (value != *intent.topical_filter) {
            return false;
        }
    }
    return true;
}

double general_threshold(const std::vector<RerankedCard>& rows) {
    if (rows.empty()) {
        return 0.18;
    }
    double top = 0.0;
    for (const auto& row : rows) {
        top = std::max(top, row.assessment.relevance_score);
    }
    if (top >= 0.75) {
        return std::max(0.18, top * 0.35);
    }
    if (top >= 0.45) {
        return std::max(0.18, top * 0.45);
    }
    return std::max(0.18, top * 0.7);
}

std::vector<RerankedCard> general_accept(const std::vector<RerankedCard>& rows) {
    const auto threshold = general_threshold(rows);
    std::vector<RerankedCard> accepted;
    for (const auto& row : rows) {
        if (row.assessment.relevance_score >= threshold) {
            accepted.push_back(row);
        }
    }
    return accepted;
}

void add_vector_sources_if_available(
    SourceResults& sources,
    const HybridEngineOptions& options,
    const std::string& query_text,
    const HybridSearchRequest& request
) {
    const OllamaEmbedder embedder;
    NativeSqliteVectorStore store(options.db_path);
    const bool has_fast = store.has_vectors(kFastVectorKind, embedder.model());
    const bool has_deep = store.has_vectors(kDeepVectorKind, embedder.model());
    if (!has_fast && !has_deep) {
        sources["fast_vector"] = {};
        sources["deep_vector"] = {};
        return;
    }

    const auto query_embedding = embedder.embed(query_text);
    sources["fast_vector"] = has_fast
        ? store.search(query_embedding, kFastVectorKind, embedder.model(), request.vector_limit)
        : std::vector<RetrievedCard>{};
    sources["deep_vector"] = has_deep
        ? store.search(query_embedding, kDeepVectorKind, embedder.model(), request.vector_limit)
        : std::vector<RetrievedCard>{};
}

std::vector<RetrievedCard> expand_cards(
    const HybridEngineOptions& options,
    std::vector<RetrievedCard> rows
) {
    std::vector<std::string> card_ids;
    for (const auto& row : rows) {
        const auto id = row.card_id.empty() ? row.id : row.card_id;
        if (!id.empty()) {
            card_ids.push_back(id);
        }
    }
    auto full_cards = load_cards_by_ids(options.db_path, card_ids);
    for (auto& row : rows) {
        const auto id = row.card_id.empty() ? row.id : row.card_id;
        auto found = full_cards.find(id);
        if (found == full_cards.end()) {
            continue;
        }
        auto full = found->second;
        full.retrieval_score = row.retrieval_score;
        full.reranker_score = row.reranker_score;
        full.score = row.score;
        full.source_ranks = row.source_ranks;
        full.source_scores = row.source_scores;
        row = std::move(full);
    }
    return rows;
}

} // namespace

class HybridEngine::Impl {
public:
    explicit Impl(HybridEngineOptions options) : options_(std::move(options)) {
        if (options_.db_path.empty()) {
            throw std::invalid_argument("HybridEngine requires a SQLite database path.");
        }
    }

    HybridSearchResponse search(const HybridSearchRequest& request) const {
        const auto intent = parse_query_intent(request.query, request.mode);
        const auto limit = static_cast<std::size_t>(intent.requested_count.value_or(static_cast<int>(request.limit)));

        std::vector<RerankedCard> selected;
        if (auto lookup = direct_lookup(options_, intent, request); lookup.has_value()) {
            selected = std::move(*lookup);
        } else {
            SourceResults sources;
            const auto text = retrieval_text(intent);
            add_vector_sources_if_available(sources, options_, text, request);
            sources["sqlite_fts"] = search_cards(options_.db_path, text, request.lexical_limit);
            if (auto citation_query = citation_lookup_query(intent); citation_query.has_value()) {
                sources["author_citation"] = search_author_citation_cards(
                    options_.db_path,
                    *citation_query,
                    request.citation_limit
                );
            } else {
                sources["author_citation"] = {};
            }

            auto fused = expand_cards(options_, reciprocal_rank_fusion(sources));
            std::vector<RetrievedCard> filtered;
            for (const auto& card : fused) {
                if (card_matches_filters(card, intent)) {
                    filtered.push_back(card);
                }
            }

            auto reranked = FullContextReranker().rerank(intent, filtered);
            if (intent.search_mode == SearchMode::Argument) {
                std::vector<CandidateAssessment> assessments;
                for (const auto& row : reranked) {
                    assessments.push_back(row.assessment);
                }
                const auto gate = split_by_relevance_gate(assessments);
                for (const auto index : gate.accepted_indexes) {
                    selected.push_back(reranked[index]);
                }
            } else {
                selected = general_accept(reranked);
            }
        }

        const auto bundle = ArgumentBuilder().build(intent, selected, limit);
        HybridSearchResponse response;
        response.source_status = bundle.source_status;
        response.main_claim = bundle.main_claim;
        response.uncertainty = bundle.uncertainty;
        for (const auto& card : bundle.cards) {
            response.cards.push_back(to_evidence_card(card, intent, request.include_diagnostics));
        }
        return response;
    }

private:
    HybridEngineOptions options_;
};

HybridEngine::HybridEngine(HybridEngineOptions options)
    : impl_(std::make_unique<Impl>(std::move(options))) {}

HybridEngine::~HybridEngine() = default;

HybridEngine::HybridEngine(HybridEngine&&) noexcept = default;

HybridEngine& HybridEngine::operator=(HybridEngine&&) noexcept = default;

HybridSearchResponse HybridEngine::search(const HybridSearchRequest& request) const {
    return impl_->search(request);
}

} // namespace sekret::hybrid

extern "C" {

SekretHybridJsonResult sekret_hybrid_search_json(
    const char* db_path,
    const char* chroma_path,
    const char* request_json
) {
    try {
        if (db_path == nullptr || request_json == nullptr) {
            throw std::invalid_argument("db_path and request_json are required.");
        }

        sekret::hybrid::HybridEngine engine({
            std::string(db_path),
            chroma_path == nullptr ? std::string() : std::string(chroma_path),
        });
        auto request = sekret::hybrid::request_from_json_or_text(request_json);

        const auto response = engine.search(request);
        return {
            sekret::hybrid::copy_c_string(sekret::hybrid::response_to_json(response)),
            nullptr,
        };
    } catch (const std::exception& error) {
        return {nullptr, sekret::hybrid::copy_c_string(error.what())};
    } catch (...) {
        return {
            nullptr,
            sekret::hybrid::copy_c_string("Unknown C++ hybrid backend error."),
        };
    }
}

void sekret_hybrid_free_string(char* value) {
    std::free(value);
}

} // extern "C"
