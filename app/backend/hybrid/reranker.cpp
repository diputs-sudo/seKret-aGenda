#include "reranker.hpp"

#include "relevance.hpp"

#include <algorithm>
#include <cmath>
#include <map>
#include <utility>
#include <set>
#include <sstream>

namespace sekret::hybrid {
namespace {

std::set<std::string> set_intersection_values(const std::set<std::string>& left, const std::set<std::string>& right) {
    std::set<std::string> result;
    for (const auto& value : left) {
        if (right.count(value) != 0) {
            result.insert(value);
        }
    }
    return result;
}

std::set<std::string> set_union_values(std::initializer_list<std::set<std::string>> sets) {
    std::set<std::string> result;
    for (const auto& values : sets) {
        result.insert(values.begin(), values.end());
    }
    return result;
}

double ratio(const std::set<std::string>& matches, const std::set<std::string>& total) {
    if (total.empty()) {
        return 0.0;
    }
    return std::round((static_cast<double>(matches.size()) / static_cast<double>(total.size())) * 1000.0) / 1000.0;
}

std::set<std::string> text_terms(const std::string& text) {
    auto values = terms(text);
    auto phrases = extract_phrase_concepts(text);
    values.insert(phrases.begin(), phrases.end());
    return values;
}

std::string citation_label(const RetrievedCard& card) {
    std::ostringstream output;
    bool first = true;
    auto append = [&](const std::string& value) {
        if (value.empty()) {
            return;
        }
        if (!first) {
            output << ' ';
        }
        output << value;
        first = false;
    };
    append(card.card_name);
    if (card.author.has_value()) {
        append(*card.author);
    }
    if (card.year.has_value()) {
        append(std::to_string(*card.year));
    }
    append(card.citation);
    return output.str();
}

std::map<std::string, std::set<std::string>> field_terms(const RetrievedCard& card) {
    return {
        {"section", text_terms(card.section)},
        {"tag", text_terms(card.tag)},
        {"citation", terms(citation_label(card))},
        {"highlights", text_terms(highlight_text(card))},
        {"body", text_terms(card.body.empty() ? card.body_preview : card.body)},
    };
}

std::string card_mechanism_text(const RetrievedCard& card) {
    std::ostringstream output;
    for (const auto& part : {card.section, card.tag, highlight_text(card), card.body.empty() ? card.body_preview : card.body}) {
        if (part.empty()) {
            continue;
        }
        if (output.tellp() > 0) {
            output << '\n';
        }
        output << part;
    }
    return output.str();
}

double evidence_strength(const RetrievedCard& card) {
    double score = 0.0;
    if (!card.highlights.empty() || !highlight_text(card).empty()) {
        score += 0.45;
    }
    if (!card.citation.empty()) {
        score += 0.2;
    }
    if (!card.card_name.empty()) {
        score += 0.15;
    }
    if (card.author.has_value()) {
        score += 0.1;
    }
    if (card.year.has_value()) {
        score += 0.1;
    }
    return std::round(std::min(score, 1.0) * 1000.0) / 1000.0;
}

bool low_signal_term(const std::string& term) {
    return term.size() <= 2 || std::all_of(term.begin(), term.end(), [](unsigned char character) {
        return std::isdigit(character) != 0;
    });
}

double term_weight(const std::string& term) {
    if (term.find('_') != std::string::npos) {
        return 2.5;
    }
    if (low_signal_term(term)) {
        return 0.35;
    }
    if (term == "ai") {
        return 0.6;
    }
    return 1.0;
}

double hit_score(const std::set<std::string>& hits) {
    double score = 0.0;
    for (const auto& hit : hits) {
        score += term_weight(hit);
    }
    return std::round(score * 1000.0) / 1000.0;
}

double weighted_ratio(const std::set<std::string>& hits, const std::set<std::string>& query_terms) {
    const double total = hit_score(query_terms);
    if (total == 0.0) {
        return 0.0;
    }
    return std::round(std::min(hit_score(hits) / total, 1.0) * 1000.0) / 1000.0;
}

double calibrated_relevance(double raw_score) {
    if (raw_score <= 0.0) {
        return 0.0;
    }
    return std::round(std::min(raw_score / (raw_score + 5.0), 0.98) * 1000.0) / 1000.0;
}

void add_reason(std::vector<std::string>& reasons, const std::string& label, const std::set<std::string>& hits) {
    if (hits.empty()) {
        return;
    }
    std::ostringstream output;
    output << label << " matched: ";
    bool first = true;
    for (const auto& hit : hits) {
        if (!first) {
            output << ", ";
        }
        output << hit;
        first = false;
    }
    reasons.push_back(output.str());
}

std::size_t intersection_size(const std::set<std::string>& left, const std::set<std::string>& right) {
    std::size_t result = 0;
    for (const auto& value : left) {
        if (right.count(value) != 0) {
            ++result;
        }
    }
    return result;
}

} // namespace

LightweightRelevanceReranker::LightweightRelevanceReranker(double threshold)
    : threshold_(threshold) {}

std::vector<RerankedCard> LightweightRelevanceReranker::rerank(
    const std::string& query,
    const std::vector<RetrievedCard>& cards,
    std::size_t limit
) const {
    const auto query_terms = terms(query);
    if (query_terms.empty() || limit == 0) {
        return {};
    }

    std::vector<RerankedCard> scored;
    scored.reserve(cards.size());
    for (auto card : cards) {
        const auto tag_terms = terms(card.tag);
        const auto section_terms = terms(card.section);
        const auto highlight_terms = terms(highlight_text(card));

        auto card_terms = tag_terms;
        card_terms.insert(section_terms.begin(), section_terms.end());
        card_terms.insert(highlight_terms.begin(), highlight_terms.end());
        if (intersection_size(query_terms, card_terms) == 0) {
            continue;
        }

        const double score = static_cast<double>(intersection_size(query_terms, tag_terms)) * 3.0
            + static_cast<double>(intersection_size(query_terms, highlight_terms)) * 1.5
            + static_cast<double>(intersection_size(query_terms, section_terms)) * 0.5;
        if (score < threshold_) {
            continue;
        }

        CandidateAssessment assessment;
        assessment.card_id = card.card_id.empty() ? card.id : card.card_id;
        assessment.relevance_score = score;
        assessment.topic_match = static_cast<double>(intersection_size(query_terms, card_terms))
            / static_cast<double>(query_terms.size());
        assessment.relationship = Relationship::Qualifies;
        assessment.confidence = 1.0;
        assessment.reasons = {
            "lightweight tag/section/highlight relevance",
            "score: " + std::to_string(score),
        };
        card.reranker_score = score;
        scored.push_back({std::move(card), std::move(assessment), {}});
    }

    std::stable_sort(scored.begin(), scored.end(), [](const RerankedCard& left, const RerankedCard& right) {
        if (left.assessment.relevance_score != right.assessment.relevance_score) {
            return left.assessment.relevance_score > right.assessment.relevance_score;
        }
        return left.card.score > right.card.score;
    });

    std::set<std::pair<std::string, std::string>> seen;
    std::vector<RerankedCard> selected;
    selected.reserve(std::min(limit, scored.size()));
    for (auto& row : scored) {
        const auto key = std::make_pair(row.card.section, row.card.tag);
        if (seen.count(key) != 0) {
            continue;
        }
        seen.insert(key);
        selected.push_back(std::move(row));
        if (selected.size() >= limit) {
            break;
        }
    }
    return selected;
}

std::vector<RerankedCard> FullContextReranker::rerank(
    const QueryIntent& intent,
    const std::vector<RetrievedCard>& cards,
    std::optional<std::size_t> limit
) const {
    std::vector<RerankedCard> assessed;
    assessed.reserve(cards.size());
    for (auto card : cards) {
        auto assessment = assess(intent, card);
        card.reranker_score = assessment.relevance_score;
        card.score = assessment.relevance_score;
        assessed.push_back({std::move(card), std::move(assessment), reranker_input(intent, card)});
    }
    std::sort(assessed.begin(), assessed.end(), [](const RerankedCard& left, const RerankedCard& right) {
        if (left.assessment.relevance_score != right.assessment.relevance_score) {
            return left.assessment.relevance_score > right.assessment.relevance_score;
        }
        return left.card.retrieval_score > right.card.retrieval_score;
    });
    if (limit.has_value() && assessed.size() > *limit) {
        assessed.resize(*limit);
    }
    return assessed;
}

CandidateAssessment FullContextReranker::assess(const QueryIntent& intent, const RetrievedCard& card) const {
    const auto query_text = retrieval_text(intent);
    const auto query_mechanism = parse_mechanism(query_text);
    auto query_terms = terms(query_text);
    query_terms.insert(query_mechanism.phrase_concepts.begin(), query_mechanism.phrase_concepts.end());
    query_terms.insert(query_mechanism.object_groups.begin(), query_mechanism.object_groups.end());
    for (const auto& generic : query_mechanism.generic_terms) {
        query_terms.erase(generic);
    }

    const auto card_mechanism = parse_mechanism(card_mechanism_text(card));
    const auto concepts = mechanism_concepts(query_mechanism, card_mechanism);
    const auto fields = field_terms(card);
    const auto section_hits = set_intersection_values(query_terms, fields.at("section"));
    const auto tag_hits = set_intersection_values(query_terms, fields.at("tag"));
    const auto citation_hits = set_intersection_values(query_terms, fields.at("citation"));
    const auto highlight_hits = set_intersection_values(query_terms, fields.at("highlights"));
    const auto body_hits = set_intersection_values(query_terms, fields.at("body"));

    CandidateAssessment assessment;
    assessment.card_id = card.card_id.empty() ? card.id : card.card_id;
    assessment.query_mechanism = query_mechanism;
    assessment.card_mechanism = card_mechanism;
    assessment.matched_concepts = concepts.first;
    assessment.missing_concepts = concepts.second;

    if (query_terms.empty()) {
        assessment.rejection_reason = "empty query";
        assessment.reasons = {"empty-query"};
        return assessment;
    }

    const auto useful_terms = set_union_values({fields.at("tag"), fields.at("highlights"), fields.at("body"), fields.at("citation")});
    const auto useful_hits = set_intersection_values(query_terms, useful_terms);
    const double mechanism = mechanism_match(query_mechanism, card_mechanism);
    const double topic_match = ratio(
        set_intersection_values(query_terms, set_union_values({fields.at("tag"), fields.at("highlights")})),
        query_terms
    );
    const double warrant_match = ratio(
        set_intersection_values(query_terms, set_union_values({fields.at("highlights"), fields.at("body")})),
        query_terms
    );
    const bool same_section_only = !section_hits.empty() && useful_hits.empty();

    double score = (
        weighted_ratio(tag_hits, query_terms) * 4.0
        + weighted_ratio(highlight_hits, query_terms) * 3.0
        + weighted_ratio(body_hits, query_terms) * 1.25
        + weighted_ratio(citation_hits, query_terms) * 0.75
        + static_cast<double>(section_hits.size()) * 0.15
        + mechanism * 10.0
        + evidence_strength(card) * 2.0
        + card.retrieval_score * 5.0
    );
    if (same_section_only) {
        score *= 0.2;
    }
    if (mechanism < 0.12) {
        score *= 0.45;
    }
    if (tag_hits.empty() && highlight_hits.empty() && body_hits.empty()) {
        score *= 0.4;
    }

    assessment.relevance_score = calibrated_relevance(score);
    assessment.topic_match = topic_match;
    assessment.mechanism_match = mechanism;
    assessment.warrant_match = warrant_match;
    assessment.evidence_strength = evidence_strength(card);
    assessment.relationship = classify_relationship(
        query_mechanism,
        card_mechanism,
        topic_match,
        mechanism,
        warrant_match
    );
    assessment.supports_claim = assessment.relationship == Relationship::Supports;
    assessment.contradicts_claim = assessment.relationship == Relationship::Contradicts;
    assessment.rejection_reason = rejection_reason(
        assessment.relationship,
        assessment.relevance_score,
        mechanism,
        same_section_only
    );
    assessment.confidence = confidence_score(
        assessment.relevance_score,
        mechanism,
        warrant_match,
        assessment.evidence_strength,
        assessment.relationship
    );

    add_reason(assessment.reasons, "tag", tag_hits);
    add_reason(assessment.reasons, "highlights", highlight_hits);
    add_reason(assessment.reasons, "body", body_hits);
    add_reason(assessment.reasons, "citation", citation_hits);
    add_reason(assessment.reasons, "section", section_hits);
    assessment.reasons.push_back("mechanism match: " + std::to_string(mechanism));
    assessment.reasons.push_back("relationship: " + relationship_name(assessment.relationship));
    if (assessment.rejection_reason.has_value()) {
        assessment.reasons.push_back("rejected: " + *assessment.rejection_reason);
    }
    return assessment;
}

std::string reranker_input(const QueryIntent& intent, const RetrievedCard& card) {
    std::ostringstream output;
    output
        << "Query:\n" << retrieval_text(intent)
        << "\n\nCard:\nSection:\n" << card.section
        << "\n\nTag:\n" << card.tag
        << "\n\nCitation:\n" << citation_label(card)
        << "\n\nHighlights:\n" << highlight_text(card)
        << "\n\nBody:\n" << (card.body.empty() ? card.body_preview : card.body);
    return output.str();
}

} // namespace sekret::hybrid
