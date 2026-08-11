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

std::string reranker_input(const QueryIntent& intent, const RetrievedCard& card);

} // namespace sekret::hybrid
