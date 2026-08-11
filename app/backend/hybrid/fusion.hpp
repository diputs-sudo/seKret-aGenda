#pragma once

#include "sqlite_store.hpp"

#include <map>
#include <string>
#include <vector>

namespace sekret::hybrid {

using SourceResults = std::map<std::string, std::vector<RetrievedCard>>;

std::vector<RetrievedCard> reciprocal_rank_fusion(
    const SourceResults& source_results,
    int k = 60
);

} // namespace sekret::hybrid
