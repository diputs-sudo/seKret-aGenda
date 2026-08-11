#pragma once

#include "mechanism.hpp"

#include <optional>
#include <string>
#include <vector>

namespace sekret::hybrid {

enum class Relationship {
    Supports,
    Contradicts,
    Qualifies,
    Background,
    Irrelevant,
};

struct CandidateAssessment {
    std::string card_id;
    double relevance_score = 0.0;
    double topic_match = 0.0;
    double mechanism_match = 0.0;
    double warrant_match = 0.0;
    Relationship relationship = Relationship::Irrelevant;
    bool supports_claim = false;
    bool contradicts_claim = false;
    double evidence_strength = 0.0;
    double confidence = 0.0;
    std::optional<std::string> rejection_reason;
    std::vector<std::string> matched_concepts;
    std::vector<std::string> missing_concepts;
    std::vector<std::string> reasons;
    Mechanism query_mechanism;
    Mechanism card_mechanism;
};

struct GateResult {
    std::vector<CandidateAssessment> accepted_assessments;
    std::vector<CandidateAssessment> rejected_assessments;
    std::vector<std::size_t> accepted_indexes;
    std::vector<std::size_t> rejected_indexes;
};

std::string relationship_name(Relationship relationship);

Relationship classify_relationship(
    const Mechanism& query_mechanism,
    const Mechanism& card_mechanism,
    double topic_match,
    double mechanism_match,
    double warrant_match
);

std::optional<std::string> rejection_reason(
    Relationship relationship,
    double relevance_score,
    double mechanism_match,
    bool same_section_only
);

double confidence_score(
    double relevance_score,
    double mechanism_match,
    double warrant_match,
    double evidence_strength,
    Relationship relationship
);

GateResult split_by_relevance_gate(
    const std::vector<CandidateAssessment>& assessments,
    double min_relevance = 0.22,
    double min_confidence = 0.2,
    bool allow_background = false
);

} // namespace sekret::hybrid
