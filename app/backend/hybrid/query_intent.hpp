#pragma once

#include <optional>
#include <string>
#include <vector>

namespace sekret::hybrid {

enum class SearchMode {
    Argument,
    Author,
    Citation,
    Section,
    General,
};

struct QueryIntent {
    std::string raw_query;
    std::string mode = "search";
    SearchMode search_mode = SearchMode::General;
    std::string search_text;
    std::optional<std::string> opponent_claim;
    std::vector<std::string> concepts;
    std::vector<std::string> phrase_concepts;
    std::vector<std::string> ignored_stopwords;
    std::optional<std::string> author_filter;
    std::optional<int> year_min;
    std::optional<int> year_max;
    std::optional<std::string> section_filter;
    std::optional<std::string> category_filter;
    std::optional<bool> topical_filter;
    std::optional<int> requested_count;
};

QueryIntent parse_query_intent(const std::string& query, const std::string& mode = "search");

std::string search_mode_name(SearchMode mode);

std::string retrieval_text(const QueryIntent& intent);

} // namespace sekret::hybrid
