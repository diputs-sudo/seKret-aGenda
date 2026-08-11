#include "mechanism.hpp"

#include "relevance.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <regex>
#include <sstream>

namespace sekret::hybrid {
namespace {

const std::set<std::string> positive_causal_terms = {
    "cause", "causes", "caused", "create", "creates", "created", "drive",
    "drives", "fuel", "fuels", "increase", "increases", "lead", "leads",
    "result", "results", "worsen", "worsens",
};

const std::set<std::string> negative_causal_terms = {
    "avoid", "avoids", "decrease", "decreases", "defuse", "defuses", "lower",
    "lowers", "mitigate", "mitigates", "prevent", "prevents", "reduce",
    "reduces", "stabilize", "stabilizes", "stop", "stops",
};

std::string lower_copy(const std::string& text) {
    std::string lowered;
    lowered.reserve(text.size());
    for (const unsigned char character : text) {
        lowered.push_back(static_cast<char>(std::tolower(character)));
    }
    return lowered;
}

std::string replace_char(std::string text, char from, char to) {
    std::replace(text.begin(), text.end(), from, to);
    return text;
}

bool has_suffix(const std::string& text, const std::string& suffix) {
    return text.size() >= suffix.size()
        && text.compare(text.size() - suffix.size(), suffix.size(), suffix) == 0;
}

std::set<std::string> normalized_terms_from_terms(const std::set<std::string>& values) {
    std::set<std::string> normalized;
    for (const auto& value : values) {
        auto lowered = replace_char(lower_copy(value), '-', '_');
        if (!lowered.empty()) {
            normalized.insert(lowered);
        }
        auto canonical = canonical_term(value);
        if (!canonical.empty()) {
            normalized.insert(canonical);
        }
    }
    return normalized;
}

std::set<std::string> normalized_terms(const std::string& text) {
    return normalized_terms_from_terms(terms(text));
}

std::vector<std::string> tokenize(const std::string& text, bool allow_apostrophe) {
    std::vector<std::string> tokens;
    std::string current;
    for (char character : text) {
        const bool allowed = std::isalnum(static_cast<unsigned char>(character))
            || character == '-'
            || (allow_apostrophe && character == '\'');
        if (allowed) {
            current.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(character))));
            continue;
        }
        if (!current.empty()) {
            tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) {
        tokens.push_back(current);
    }
    return tokens;
}

std::set<std::string> surface_terms(const std::string& text) {
    std::set<std::string> result;
    for (const auto& token : tokenize(text, false)) {
        if (stopwords().count(token) == 0) {
            result.insert(token);
        }
    }
    return result;
}

std::vector<std::string> ordered_terms(const std::string& text) {
    std::vector<std::string> result;
    for (const auto& token : tokenize(text, false)) {
        if (stopwords().count(token) != 0 || semantic_stopwords().count(token) != 0) {
            continue;
        }
        result.push_back(token);
    }
    return result;
}

std::set<std::string> first_clause_terms(const std::string& text) {
    static const std::regex splitter(
        R"(\b(?:causes?|creates?|drives?|fuels?|leads?|results?|increases?|reduces?|lowers?|prevents?|stops?|defuses?|mitigates?|stabilizes?|worsens?|because)\b)",
        std::regex::icase
    );
    std::smatch match;
    std::string prefix = text;
    if (std::regex_search(text, match, splitter)) {
        prefix = text.substr(0, static_cast<std::size_t>(match.position()));
    }
    const auto ordered = ordered_terms(prefix);
    std::set<std::string> result;
    for (std::size_t index = 0; index < ordered.size() && index < 2; ++index) {
        result.insert(ordered[index]);
    }
    return result;
}

struct MechanismParts {
    std::set<std::string> actors;
    std::set<std::string> causes;
    std::set<std::string> effects;
};

MechanismParts split_mechanism_terms(const std::string& text) {
    static const std::regex because_re(R"(\bbecause\s+(?:of\s+)?(.+)$)", std::regex::icase);
    static const std::regex cause_re(
        R"((.+?)\b(?:causes?|creates?|drives?|fuels?|leads?\s+to|results?\s+in|increases?|reduces?|lowers?|prevents?|stops?|defuses?|mitigates?|stabilizes?|worsens?)\b(.+))",
        std::regex::icase
    );

    std::smatch match;
    if (std::regex_search(text, match, because_re)) {
        const auto before = text.substr(0, static_cast<std::size_t>(match.position()));
        const auto after = match[1].str();
        const auto before_terms = ordered_terms(before);
        std::set<std::string> actors;
        if (!before_terms.empty()) {
            actors.insert(before_terms.front());
        }
        auto effects = terms(before);
        for (const auto& actor : actors) {
            effects.erase(actor);
        }
        return {actors, terms(after), effects};
    }

    if (std::regex_search(text, match, cause_re)) {
        const auto left = match[1].str();
        const auto right = match[2].str();
        return {first_clause_terms(left), terms(left), terms(right)};
    }

    return {first_clause_terms(text), {}, terms(text)};
}

int polarity(const std::string& text, const std::set<std::string>& raw_terms) {
    std::set<std::string> canonical_terms;
    for (const auto& term : raw_terms) {
        canonical_terms.insert(canonical_term(term));
    }

    std::set<std::string> positive;
    std::set<std::string> negative;
    for (const auto& term : positive_causal_terms) {
        positive.insert(canonical_term(term));
    }
    for (const auto& term : negative_causal_terms) {
        negative.insert(canonical_term(term));
    }

    const bool has_positive = std::any_of(canonical_terms.begin(), canonical_terms.end(), [&](const auto& term) {
        return positive.count(term) != 0;
    });
    const bool has_negative = std::any_of(canonical_terms.begin(), canonical_terms.end(), [&](const auto& term) {
        return negative.count(term) != 0;
    });

    if (has_negative && !has_positive) {
        return -1;
    }
    if (has_positive && !has_negative) {
        return 1;
    }
    if (has_negative && has_positive) {
        return -1;
    }
    static const std::regex because_re(R"(\bbecause\s+(?:of\s+)?(.+)$)", std::regex::icase);
    return std::regex_search(text, because_re) ? 1 : 0;
}

double overlap_score(const std::set<std::string>& query_values, const std::set<std::string>& card_values) {
    if (query_values.empty()) {
        return 0.0;
    }
    std::size_t overlap = 0;
    for (const auto& value : query_values) {
        if (card_values.count(value) != 0) {
            ++overlap;
        }
    }
    return static_cast<double>(overlap) / static_cast<double>(query_values.size());
}

std::set<std::string> set_union_all(std::initializer_list<std::set<std::string>> sets) {
    std::set<std::string> result;
    for (const auto& values : sets) {
        result.insert(values.begin(), values.end());
    }
    return result;
}

std::set<std::string> without_generic(const std::set<std::string>& values, const std::set<std::string>& generic) {
    std::set<std::string> result;
    for (const auto& value : values) {
        if (generic.count(value) == 0) {
            result.insert(value);
        }
    }
    return result;
}

bool generic_only_match(const Mechanism& query, const Mechanism& card) {
    auto query_specific = without_generic(
        set_union_all({query.actor_groups, query.cause_groups, query.effect_groups, query.object_groups, query.phrase_concepts}),
        query.generic_terms
    );
    auto card_specific = without_generic(
        set_union_all({card.actor_groups, card.cause_groups, card.effect_groups, card.object_groups, card.phrase_concepts}),
        card.generic_terms
    );
    for (const auto& value : query_specific) {
        if (card_specific.count(value) != 0) {
            return false;
        }
    }
    for (const auto& value : query.generic_terms) {
        if (card.generic_terms.count(value) != 0) {
            return true;
        }
    }
    return false;
}

} // namespace

std::string canonical_term(const std::string& term) {
    auto token = replace_char(lower_copy(term), '-', '_');
    while (!token.empty() && token.front() == '_') {
        token.erase(token.begin());
    }
    while (!token.empty() && token.back() == '_') {
        token.pop_back();
    }
    if (token.size() <= 3) {
        return token;
    }
    for (const std::string suffix : {"ization", "isation", "ations", "ments", "ition"}) {
        if (has_suffix(token, suffix) && token.size() > suffix.size() + 3) {
            return token.substr(0, token.size() - suffix.size());
        }
    }
    if (has_suffix(token, "ation") && token.size() > 8) {
        return token.substr(0, token.size() - 3);
    }
    for (const std::string suffix : {"ing", "ers", "ies", "ied", "ed", "es", "s"}) {
        if (has_suffix(token, suffix) && token.size() > suffix.size() + 3) {
            return token.substr(0, token.size() - suffix.size());
        }
    }
    return token;
}

bool is_generic_term(const std::string& term) {
    if (term.size() <= 2) {
        return true;
    }
    if (std::all_of(term.begin(), term.end(), [](unsigned char character) {
        return std::isdigit(character) != 0;
    })) {
        return true;
    }
    if (term == "artificial_intelligence" || term == "ai") {
        return true;
    }
    return stopwords().count(term) != 0 || semantic_stopwords().count(term) != 0;
}

std::set<std::string> extract_phrase_concepts(const std::string& text) {
    std::vector<std::string> raw_tokens;
    for (auto token : tokenize(text, true)) {
        token = replace_char(token, '-', '_');
        if (!token.empty() && stopwords().count(token) == 0 && semantic_stopwords().count(token) == 0) {
            raw_tokens.push_back(token);
        }
    }

    std::vector<std::string> canonical_tokens;
    for (const auto& token : raw_tokens) {
        auto canonical = canonical_term(token);
        if (!canonical.empty() && stopwords().count(canonical) == 0 && semantic_stopwords().count(canonical) == 0) {
            canonical_tokens.push_back(canonical);
        }
    }

    std::set<std::string> phrases;
    for (const auto& tokens : {canonical_tokens, raw_tokens}) {
        for (std::size_t size : {std::size_t{2}, std::size_t{3}}) {
            if (tokens.size() < size) {
                continue;
            }
            for (std::size_t index = 0; index + size <= tokens.size(); ++index) {
                bool generic = false;
                std::ostringstream phrase;
                for (std::size_t offset = 0; offset < size; ++offset) {
                    const auto& token = tokens[index + offset];
                    generic = generic || is_generic_term(token);
                    if (offset != 0) {
                        phrase << '_';
                    }
                    phrase << token;
                }
                if (!generic) {
                    phrases.insert(phrase.str());
                }
            }
        }
    }
    return phrases;
}

std::set<std::string> ignored_stopwords(const std::string& text) {
    std::set<std::string> ignored;
    for (const auto& token : tokenize(text, true)) {
        if (stopwords().count(token) != 0) {
            ignored.insert(token);
        }
    }
    return ignored;
}

Mechanism parse_mechanism(const std::string& text) {
    const auto raw_terms = surface_terms(text);
    const auto normalized = normalized_terms(text);
    auto phrases = extract_phrase_concepts(text);
    const auto parts = split_mechanism_terms(text);

    Mechanism mechanism;
    mechanism.raw_text = text;
    mechanism.actor_groups = normalized_terms_from_terms(parts.actors);
    mechanism.cause_groups = normalized_terms_from_terms(parts.causes);
    mechanism.effect_groups = normalized_terms_from_terms(parts.effects);
    mechanism.object_groups = normalized;
    mechanism.object_groups.insert(phrases.begin(), phrases.end());
    mechanism.phrase_concepts = std::move(phrases);
    mechanism.ignored_stopwords = ignored_stopwords(text);
    for (const auto& term : normalized) {
        if (is_generic_term(term)) {
            mechanism.generic_terms.insert(term);
        }
    }
    mechanism.polarity = polarity(text, raw_terms);
    mechanism.terms = normalized;
    return mechanism;
}

double mechanism_match(const Mechanism& query, const Mechanism& card) {
    double actor = overlap_score(query.actor_groups, card.actor_groups);
    double cause = overlap_score(query.cause_groups, card.cause_groups);
    double effect = overlap_score(query.effect_groups, card.effect_groups);
    const double objects = overlap_score(query.object_groups, card.object_groups);
    const double phrases = overlap_score(query.phrase_concepts, card.phrase_concepts);

    if (query.cause_groups.empty()) {
        cause = objects;
    }
    if (query.effect_groups.empty()) {
        effect = objects;
    }

    const double generic_penalty = generic_only_match(query, card) ? 0.25 : 1.0;
    const double score = (
        actor * 0.15 + cause * 0.3 + effect * 0.35 + phrases * 0.15 + objects * 0.05
    ) * generic_penalty;
    return std::round(score * 1000.0) / 1000.0;
}

std::pair<std::vector<std::string>, std::vector<std::string>> mechanism_concepts(
    const Mechanism& query,
    const Mechanism& card
) {
    const auto card_all = set_union_all({
        card.actor_groups, card.cause_groups, card.effect_groups, card.object_groups, card.phrase_concepts,
    });
    auto query_concepts = set_union_all({
        query.actor_groups, query.cause_groups, query.effect_groups, query.phrase_concepts,
    });
    if (query_concepts.empty()) {
        query_concepts = query.object_groups;
    }

    std::vector<std::string> matched;
    std::vector<std::string> missing;
    for (const auto& concept : query_concepts) {
        (card_all.count(concept) == 0 ? missing : matched).push_back(concept);
    }
    return {matched, missing};
}

} // namespace sekret::hybrid
