#pragma once

#include <map>
#include <string>
#include <vector>

namespace sekret::hybrid {

struct ParsedDslCard {
    std::map<std::string, std::string> fields;
    std::size_t block_start = 0;
    std::size_t block_end = 0;
    double confidence = 1.0;
};

struct DslParseResult {
    std::vector<ParsedDslCard> cards;
    std::vector<std::string> diagnostics;
    std::map<std::string, std::string> defaults;
};

DslParseResult parse_evidence_dsl(const std::string& text, const std::string& grammar_source);

} // namespace sekret::hybrid
