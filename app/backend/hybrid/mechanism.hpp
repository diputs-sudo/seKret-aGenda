#pragma once

#include <set>
#include <string>
#include <utility>
#include <vector>

namespace sekret::hybrid {

struct Mechanism {
    std::string raw_text;
    std::set<std::string> actor_groups;
    std::set<std::string> cause_groups;
    std::set<std::string> effect_groups;
    std::set<std::string> object_groups;
    std::set<std::string> phrase_concepts;
    std::set<std::string> ignored_stopwords;
    std::set<std::string> generic_terms;
    int polarity = 0;
    std::set<std::string> terms;
};

Mechanism parse_mechanism(const std::string& text);
double mechanism_match(const Mechanism& query, const Mechanism& card);
std::pair<std::vector<std::string>, std::vector<std::string>> mechanism_concepts(
    const Mechanism& query,
    const Mechanism& card
);
std::set<std::string> extract_phrase_concepts(const std::string& text);
std::set<std::string> ignored_stopwords(const std::string& text);
std::string canonical_term(const std::string& term);
bool is_generic_term(const std::string& term);

} // namespace sekret::hybrid
