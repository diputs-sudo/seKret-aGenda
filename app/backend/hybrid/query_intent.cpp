#include "query_intent.hpp"

#include "mechanism.hpp"
#include "relevance.hpp"

#include <algorithm>
#include <cctype>
#include <regex>
#include <set>
#include <sstream>

namespace sekret::hybrid {
namespace {

std::string trim(const std::string& text) {
    auto begin = text.begin();
    while (begin != text.end() && std::isspace(static_cast<unsigned char>(*begin))) {
        ++begin;
    }
    auto end = text.end();
    while (end != begin && std::isspace(static_cast<unsigned char>(*(end - 1)))) {
        --end;
    }
    return std::string(begin, end);
}

std::string trim_dots_spaces(const std::string& text) {
    auto value = trim(text);
    while (!value.empty() && (value.back() == '.' || std::isspace(static_cast<unsigned char>(value.back())))) {
        value.pop_back();
    }
    return trim(value);
}

std::string squeeze_spaces(const std::string& text) {
    std::ostringstream output;
    bool previous_space = true;
    for (const unsigned char character : text) {
        if (std::isspace(character)) {
            if (!previous_space) {
                output << ' ';
            }
            previous_space = true;
            continue;
        }
        output << static_cast<char>(character);
        previous_space = false;
    }
    return trim(output.str());
}

std::string regex_strip(std::string text, const std::regex& pattern) {
    return std::regex_replace(text, pattern, "");
}

std::optional<std::string> first_group(const std::regex& pattern, const std::string& text) {
    std::smatch match;
    if (!std::regex_search(text, match, pattern) || match.size() < 2) {
        return std::nullopt;
    }
    return match[1].str();
}

std::optional<std::string> section_filter(const std::string& text) {
    static const std::regex pattern(R"REGEX(\bsection:(?:"([^"]+)"|([^\s]+)))REGEX", std::regex::icase);
    std::smatch match;
    if (!std::regex_search(text, match, pattern)) {
        return std::nullopt;
    }
    if (match[1].matched) {
        return match[1].str();
    }
    return match[2].str();
}

std::pair<std::optional<int>, std::optional<int>> year_filter(const std::string& text) {
    static const std::regex pattern(R"(\byear:(\d{4})(?:-(\d{4}))?)", std::regex::icase);
    std::smatch match;
    if (!std::regex_search(text, match, pattern)) {
        return {std::nullopt, std::nullopt};
    }
    const int start = std::stoi(match[1].str());
    const int end = match[2].matched ? std::stoi(match[2].str()) : start;
    return {start, end};
}

std::optional<bool> topical_filter(const std::string& text) {
    static const std::regex pattern(R"(\btopical:(true|false|yes|no|1|0))", std::regex::icase);
    std::smatch match;
    if (!std::regex_search(text, match, pattern)) {
        return std::nullopt;
    }
    auto value = match[1].str();
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value == "true" || value == "yes" || value == "1";
}

std::optional<int> count_filter(const std::string& text) {
    static const std::regex pattern(R"(\bcount:(\d{1,2}))", std::regex::icase);
    std::smatch match;
    if (!std::regex_search(text, match, pattern)) {
        return std::nullopt;
    }
    return std::max(1, std::min(std::stoi(match[1].str()), 50));
}

std::string strip_filters(const std::string& query) {
    std::string text = query;
    for (const auto& pattern : {
        std::regex(R"(\bauthor:([A-Za-z][\w'’-]*))", std::regex::icase),
        std::regex(R"(\byear:(\d{4})(?:-(\d{4}))?)", std::regex::icase),
        std::regex(R"REGEX(\bsection:(?:"([^"]+)"|([^\s]+)))REGEX", std::regex::icase),
        std::regex(R"(\bcategory:([A-Za-z][\w-]*))", std::regex::icase),
        std::regex(R"(\btopical:(true|false|yes|no|1|0))", std::regex::icase),
        std::regex(R"(\bcount:(\d{1,2}))", std::regex::icase),
    }) {
        text = regex_strip(text, pattern);
    }
    return squeeze_spaces(text);
}

std::optional<std::string> opponent_claim(const std::string& text) {
    static const std::regex pattern(
        R"(^\s*(?:(?:the\s+)?opposing\s+team|opponent|they|other\s+team)\s+(?:says?|argues?|claims?)\s+(?:that\s+)?)",
        std::regex::icase
    );
    const auto stripped = std::regex_replace(text, pattern, "");
    if (trim_dots_spaces(stripped) != trim_dots_spaces(text) && !trim_dots_spaces(stripped).empty()) {
        return trim_dots_spaces(stripped);
    }
    return std::nullopt;
}

int normalize_year(std::string value) {
    value.erase(
        std::remove_if(value.begin(), value.end(), [](unsigned char character) {
            return std::isdigit(character) == 0;
        }),
        value.end()
    );
    if (value.size() == 4) {
        return std::stoi(value);
    }
    const int year = std::stoi(value);
    return year < 70 ? 2000 + year : 1900 + year;
}

SearchMode detect_search_mode(
    const std::string& search_text,
    const std::optional<std::string>& claim,
    const std::optional<std::string>& author,
    const std::optional<int>& year_min,
    const std::optional<std::string>& section,
    bool citation_match
) {
    static const std::regex section_lookup(R"(^\s*(?:AT:|OV\b|Overview\b).+)", std::regex::icase);
    static const std::regex author_only(R"(^\s*[A-Za-z][A-Za-z'’-]{2,}\s*$)");
    if (claim.has_value()) {
        return SearchMode::Argument;
    }
    if (section.has_value() && std::regex_match(*section, section_lookup)) {
        return SearchMode::Section;
    }
    if (author.has_value() && year_min.has_value()) {
        return SearchMode::Citation;
    }
    if (author.has_value()) {
        return SearchMode::Author;
    }
    if (citation_match) {
        return SearchMode::Citation;
    }
    if (std::regex_match(search_text, author_only)) {
        return SearchMode::Author;
    }
    return SearchMode::General;
}

std::vector<std::string> sorted_vector(const std::set<std::string>& values) {
    return {values.begin(), values.end()};
}

std::vector<std::string> concepts_for_text(const std::string& text) {
    auto values = terms(text);
    auto phrases = extract_phrase_concepts(text);
    values.insert(phrases.begin(), phrases.end());
    return sorted_vector(values);
}

} // namespace

QueryIntent parse_query_intent(const std::string& query, const std::string& mode) {
    static const std::regex author_re(R"(\bauthor:([A-Za-z][\w'’-]*))", std::regex::icase);
    static const std::regex category_re(R"(\bcategory:([A-Za-z][\w-]*))", std::regex::icase);
    static const std::regex card_citation_re(R"(^\s*([A-Za-z][A-Za-z'’-]{1,})\s+(\d{4}|[‘'’]\d{2}|\d{2})\s*$)");
    static const std::regex author_only_re(R"(^\s*[A-Za-z][A-Za-z'’-]{2,}\s*$)");
    static const std::regex section_lookup_re(R"(^\s*(?:AT:|OV\b|Overview\b).+)", std::regex::icase);

    QueryIntent intent;
    intent.raw_query = query;
    intent.mode = mode;
    intent.author_filter = first_group(author_re, query);
    intent.section_filter = section_filter(query);
    intent.category_filter = first_group(category_re, query);
    intent.topical_filter = topical_filter(query);
    intent.requested_count = count_filter(query);
    auto years = year_filter(query);
    intent.year_min = years.first;
    intent.year_max = years.second;
    intent.search_text = strip_filters(query);
    intent.opponent_claim = opponent_claim(intent.search_text);

    std::smatch citation_match;
    const bool is_citation = std::regex_match(intent.search_text, citation_match, card_citation_re);
    if (is_citation && !intent.author_filter.has_value()) {
        intent.author_filter = citation_match[1].str();
        const int normalized = normalize_year(citation_match[2].str());
        intent.year_min = normalized;
        intent.year_max = normalized;
    }
    if (std::regex_match(intent.search_text, section_lookup_re) && !intent.section_filter.has_value()) {
        intent.section_filter = intent.search_text;
    }
    if (std::regex_match(intent.search_text, author_only_re) && !intent.author_filter.has_value()) {
        intent.author_filter = intent.search_text;
    }

    intent.search_mode = detect_search_mode(
        intent.search_text,
        intent.opponent_claim,
        intent.author_filter,
        intent.year_min,
        intent.section_filter,
        is_citation
    );
    const auto concept_text = intent.opponent_claim.value_or(intent.search_text);
    intent.concepts = concepts_for_text(concept_text);
    intent.phrase_concepts = sorted_vector(extract_phrase_concepts(concept_text));
    intent.ignored_stopwords = sorted_vector(ignored_stopwords(query));
    return intent;
}

std::string search_mode_name(SearchMode mode) {
    switch (mode) {
        case SearchMode::Argument:
            return "argument";
        case SearchMode::Author:
            return "author";
        case SearchMode::Citation:
            return "citation";
        case SearchMode::Section:
            return "section";
        case SearchMode::General:
            return "general";
    }
    return "general";
}

std::string retrieval_text(const QueryIntent& intent) {
    if (intent.opponent_claim.has_value()) {
        return *intent.opponent_claim;
    }
    if (!intent.search_text.empty()) {
        return intent.search_text;
    }
    return intent.raw_query;
}

} // namespace sekret::hybrid
