#pragma once

#include "hybrid.hpp"

#include <map>
#include <string>
#include <vector>

namespace sekret::hybrid {

struct RetrievedCard : EvidenceCard {
    std::string card_id;
    std::string card_name;
    std::string argument_name;
    std::string source_path;
    std::string category;
    std::string topical;
    double retrieval_score = 0.0;
    double reranker_score = 0.0;
    std::map<std::string, int> source_ranks;
    std::map<std::string, double> source_scores;
};

std::vector<RetrievedCard> search_cards(
    const std::string& db_path,
    const std::string& query,
    std::size_t limit
);

std::vector<RetrievedCard> search_author_citation_cards(
    const std::string& db_path,
    const std::string& query,
    std::size_t limit
);

std::vector<RetrievedCard> lookup_author_cards(
    const std::string& db_path,
    const std::string& author,
    std::size_t limit
);

std::vector<RetrievedCard> lookup_citation_cards(
    const std::string& db_path,
    const std::string& author,
    int year,
    std::size_t limit
);

std::vector<RetrievedCard> lookup_section_cards(
    const std::string& db_path,
    const std::string& section,
    std::size_t limit
);

std::map<std::string, RetrievedCard> load_cards_by_ids(
    const std::string& db_path,
    const std::vector<std::string>& card_ids
);

std::vector<Highlight> card_highlights(const std::string& db_path, const std::string& card_id);

std::string plain_fts_query(const std::string& query);

} // namespace sekret::hybrid
