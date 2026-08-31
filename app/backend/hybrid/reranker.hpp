#pragma once

#include "candidate_assessment.hpp"
#include "query_intent.hpp"
#include "sqlite_store.hpp"

#include <string>
#include <vector>

namespace sekret::hybrid {

struct RerankedCard {
    RetrievedCard card;
    CandidateAssessment assessment;
    std::string reranker_input;
};

class FullContextReranker {
public:
    std::vector<RerankedCard> rerank(
        const QueryIntent& intent,
        const std::vector<RetrievedCard>& cards,
        std::optional<std::size_t> limit = std::nullopt
    ) const;

    CandidateAssessment assess(const QueryIntent& intent, const RetrievedCard& card) const;
};

// Mirrors the Python reference RelevanceReranker. It intentionally considers
// only query terms plus a card's section, tag, and human highlights. This is
// the default production query scorer; parsing full card bodies and mechanisms
// belongs to explicit analysis mode.
class LightweightRelevanceReranker {
public:
    explicit LightweightRelevanceReranker(double threshold = 2.0);

    std::vector<RerankedCard> rerank(
        const std::string& query,
        const std::vector<RetrievedCard>& cards,
        std::size_t limit = 3
    ) const;

private:
    double threshold_;
};

std::string reranker_input(const QueryIntent& intent, const RetrievedCard& card);

} // namespace sekret::hybrid
