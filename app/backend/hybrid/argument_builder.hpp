#pragma once

#include "reranker.hpp"

#include <optional>
#include <string>
#include <vector>

namespace sekret::hybrid {

struct ArgumentCluster {
    std::string id;
    std::string section;
    std::string thesis;
    std::vector<RerankedCard> cards;
    std::vector<std::string> supporting_claims;
    double confidence = 0.0;
};

struct ArgumentBundle {
    std::string query;
    std::optional<std::string> opponent_claim;
    std::string main_claim;
    std::vector<std::string> warrants;
    std::vector<RerankedCard> cards;
    std::vector<ArgumentCluster> clusters;
    std::string source_status;
    std::optional<std::string> uncertainty;
};

class ArgumentBuilder {
public:
    ArgumentBundle build(
        const QueryIntent& intent,
        const std::vector<RerankedCard>& cards,
        std::size_t limit = 5
    ) const;
};

std::vector<ArgumentCluster> cluster_arguments(
    const std::vector<RerankedCard>& cards,
    const QueryIntent* intent = nullptr
);

std::vector<RerankedCard> select_diverse_cards(
    const std::vector<ArgumentCluster>& clusters,
    std::size_t limit = 5,
    double lambda_relevance = 0.75
);

} // namespace sekret::hybrid
