#include "candidate_assessment.hpp"

#include <algorithm>
#include <cmath>
#include <set>

namespace sekret::hybrid {
namespace {

bool set_overlaps(const std::set<std::string>& left, const std::set<std::string>& right) {
    for (const auto& value : left) {
        if (right.count(value) != 0) {
            return true;
        }
    }
    return false;
}

std::set<std::string> core_terms(const Mechanism& mechanism) {
    std::set<std::string> result;
    result.insert(mechanism.cause_groups.begin(), mechanism.cause_groups.end());
    result.insert(mechanism.effect_groups.begin(), mechanism.effect_groups.end());
    result.insert(mechanism.object_groups.begin(), mechanism.object_groups.end());
    for (const auto& generic : mechanism.generic_terms) {
        result.erase(generic);
    }
    return result;
}

bool polarity_overlap(const Mechanism& query, const Mechanism& card) {
    return set_overlaps(core_terms(query), core_terms(card));
}

bool opposes_claim(const Mechanism& query, const Mechanism& card) {
    return query.polarity != 0 && card.polarity != 0 && query.polarity != card.polarity;
}

bool supports_claim(const Mechanism& query, const Mechanism& card) {
    return query.polarity != 0 && card.polarity != 0 && query.polarity == card.polarity;
}

bool direct_mechanism_match(const Mechanism& query, const Mechanism& card, double match) {
    if (match < 0.25) {
        return false;
    }
    const bool actor = query.actor_groups.empty() || set_overlaps(query.actor_groups, card.actor_groups);
    std::set<std::string> card_effect_object = card.effect_groups;
    card_effect_object.insert(card.object_groups.begin(), card.object_groups.end());
    std::set<std::string> card_cause_object = card.cause_groups;
    card_cause_object.insert(card.object_groups.begin(), card.object_groups.end());
    const bool effect = query.effect_groups.empty() || set_overlaps(query.effect_groups, card_effect_object);
    const bool cause = query.cause_groups.empty() || set_overlaps(query.cause_groups, card_cause_object);
    return actor && effect && (cause || match >= 0.45);
}

bool partial_mechanism_match(const Mechanism& query, const Mechanism& card, double match) {
    if (match < 0.12) {
        return false;
    }
    std::set<std::string> card_effect_object = card.effect_groups;
    card_effect_object.insert(card.object_groups.begin(), card.object_groups.end());
    std::set<std::string> card_cause_object = card.cause_groups;
    card_cause_object.insert(card.object_groups.begin(), card.object_groups.end());
    return set_overlaps(query.cause_groups, card_cause_object)
        || set_overlaps(query.effect_groups, card_effect_object);
}

double dynamic_min_relevance(const std::vector<CandidateAssessment>& assessments, double floor) {
    if (assessments.empty()) {
        return floor;
    }
    double top = 0.0;
    for (const auto& assessment : assessments) {
        top = std::max(top, assessment.relevance_score);
    }
    if (top >= 0.75) {
        return std::max(floor, top * 0.35);
    }
    if (top >= 0.45) {
        return std::max(floor, top * 0.45);
    }
    return std::max(0.16, std::min(floor, top * 0.65));
}

double dynamic_min_confidence(const std::vector<CandidateAssessment>& assessments, double floor) {
    if (assessments.empty()) {
        return floor;
    }
    double top = 0.0;
    for (const auto& assessment : assessments) {
        top = std::max(top, assessment.confidence);
    }
    if (top >= 0.7) {
        return std::max(floor, top * 0.35);
    }
    return std::max(0.16, std::min(floor, top * 0.55));
}

std::optional<std::string> gate_rejection_reason(
    const CandidateAssessment& assessment,
    double min_relevance,
    double min_confidence,
    bool allow_background
) {
    if (assessment.rejection_reason.has_value()) {
        return assessment.rejection_reason;
    }
    if (assessment.relationship == Relationship::Irrelevant) {
        return "topic and mechanism mismatch";
    }
    if (assessment.relationship == Relationship::Background && !allow_background) {
        return "background evidence excluded by gate";
    }
    if (assessment.relevance_score < min_relevance) {
        return "low relevance score";
    }
    if (assessment.confidence < min_confidence) {
        return "low confidence";
    }
    return std::nullopt;
}

} // namespace

std::string relationship_name(Relationship relationship) {
    switch (relationship) {
        case Relationship::Supports:
            return "SUPPORTS";
        case Relationship::Contradicts:
            return "CONTRADICTS";
        case Relationship::Qualifies:
            return "QUALIFIES";
        case Relationship::Background:
            return "BACKGROUND";
        case Relationship::Irrelevant:
            return "IRRELEVANT";
    }
    return "IRRELEVANT";
}

Relationship classify_relationship(
    const Mechanism& query_mechanism,
    const Mechanism& card_mechanism,
    double topic_match,
    double mechanism_match_value,
    double warrant_match
) {
    const bool direct = direct_mechanism_match(query_mechanism, card_mechanism, mechanism_match_value);
    const bool partial = partial_mechanism_match(query_mechanism, card_mechanism, mechanism_match_value);
    const bool polarity = polarity_overlap(query_mechanism, card_mechanism);

    if (mechanism_match_value < 0.08 && topic_match < 0.15) {
        return Relationship::Irrelevant;
    }
    if (polarity && opposes_claim(query_mechanism, card_mechanism)) {
        return Relationship::Contradicts;
    }
    if (polarity && supports_claim(query_mechanism, card_mechanism)) {
        return Relationship::Supports;
    }
    if (!direct && !partial) {
        if (mechanism_match_value >= 0.08 || topic_match >= 0.18) {
            return Relationship::Background;
        }
        return Relationship::Irrelevant;
    }
    if (!direct) {
        if (warrant_match >= 0.15 || mechanism_match_value >= 0.45) {
            return Relationship::Qualifies;
        }
        return Relationship::Background;
    }
    if (opposes_claim(query_mechanism, card_mechanism)) {
        return Relationship::Contradicts;
    }
    if (supports_claim(query_mechanism, card_mechanism)) {
        return Relationship::Supports;
    }
    if (warrant_match >= 0.15 || mechanism_match_value >= 0.45) {
        return Relationship::Qualifies;
    }
    return Relationship::Background;
}

std::optional<std::string> rejection_reason(
    Relationship relationship,
    double relevance_score,
    double mechanism_match_value,
    bool same_section_only
) {
    if (same_section_only) {
        return "matches section but not card mechanism";
    }
    if (relationship == Relationship::Irrelevant) {
        return "topic and mechanism mismatch";
    }
    if (relationship == Relationship::Background) {
        return "background topic overlap without usable mechanism match";
    }
    if (relevance_score < 0.18) {
        return "low relevance score";
    }
    (void)mechanism_match_value;
    return std::nullopt;
}

double confidence_score(
    double relevance_score,
    double mechanism_match_value,
    double warrant_match,
    double evidence_strength,
    Relationship relationship
) {
    double confidence = (
        relevance_score * 0.35
        + mechanism_match_value * 0.3
        + warrant_match * 0.2
        + evidence_strength * 0.15
    );
    if (relationship == Relationship::Irrelevant) {
        confidence = std::min(confidence, 0.2);
    } else if (relationship == Relationship::Background) {
        confidence = std::min(confidence, 0.55);
    }
    return std::round(std::clamp(confidence, 0.0, 1.0) * 1000.0) / 1000.0;
}

GateResult split_by_relevance_gate(
    const std::vector<CandidateAssessment>& assessments,
    double min_relevance,
    double min_confidence,
    bool allow_background
) {
    GateResult result;
    const double relevance_floor = dynamic_min_relevance(assessments, min_relevance);
    const double confidence_floor = dynamic_min_confidence(assessments, min_confidence);
    for (std::size_t index = 0; index < assessments.size(); ++index) {
        auto assessment = assessments[index];
        auto reason = gate_rejection_reason(assessment, relevance_floor, confidence_floor, allow_background);
        if (reason.has_value()) {
            assessment.rejection_reason = reason;
            assessment.reasons.push_back("rejected: " + *reason);
            result.rejected_assessments.push_back(assessment);
            result.rejected_indexes.push_back(index);
        } else {
            result.accepted_assessments.push_back(assessment);
            result.accepted_indexes.push_back(index);
        }
    }
    return result;
}

} // namespace sekret::hybrid
