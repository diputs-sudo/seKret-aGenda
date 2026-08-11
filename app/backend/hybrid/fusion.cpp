#include "fusion.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace sekret::hybrid {
namespace {

bool missing(const std::string& value) {
    return value.empty();
}

void merge_card(RetrievedCard& existing, const RetrievedCard& incoming) {
    if (missing(existing.section) && !missing(incoming.section)) {
        existing.section = incoming.section;
    }
    if (missing(existing.tag) && !missing(incoming.tag)) {
        existing.tag = incoming.tag;
    }
    if (missing(existing.card_name) && !missing(incoming.card_name)) {
        existing.card_name = incoming.card_name;
    }
    if (missing(existing.argument_name) && !missing(incoming.argument_name)) {
        existing.argument_name = incoming.argument_name;
    }
    if (missing(existing.citation) && !missing(incoming.citation)) {
        existing.citation = incoming.citation;
    }
    if (!existing.author.has_value() && incoming.author.has_value()) {
        existing.author = incoming.author;
    }
    if (!existing.year.has_value() && incoming.year.has_value()) {
        existing.year = incoming.year;
    }
    if (missing(existing.document_name) && !missing(incoming.document_name)) {
        existing.document_name = incoming.document_name;
    }
    if (missing(existing.category) && !missing(incoming.category)) {
        existing.category = incoming.category;
    }
    if (missing(existing.topical) && !missing(incoming.topical)) {
        existing.topical = incoming.topical;
    }
    if (missing(existing.side) && !missing(incoming.side)) {
        existing.side = incoming.side;
    }
    if (missing(existing.source_path) && !missing(incoming.source_path)) {
        existing.source_path = incoming.source_path;
    }
    if (existing.highlights.empty() && !incoming.highlights.empty()) {
        existing.highlights = incoming.highlights;
    }
    if (missing(existing.body_preview) && !missing(incoming.body_preview)) {
        existing.body_preview = incoming.body_preview;
    }
    if (missing(existing.body) && !missing(incoming.body)) {
        existing.body = incoming.body;
    }
}

} // namespace

std::vector<RetrievedCard> reciprocal_rank_fusion(
    const SourceResults& source_results,
    int k
) {
    std::map<std::string, RetrievedCard> candidates;

    for (const auto& [source_name, rows] : source_results) {
        for (std::size_t index = 0; index < rows.size(); ++index) {
            const int rank = static_cast<int>(index + 1);
            const auto& row = rows[index];
            const auto card_id = row.card_id.empty() ? row.id : row.card_id;
            if (card_id.empty()) {
                continue;
            }

            auto [iterator, inserted] = candidates.emplace(card_id, row);
            auto& candidate = iterator->second;
            candidate.card_id = card_id;
            candidate.id = card_id;
            if (!inserted) {
                merge_card(candidate, row);
            }

            auto rank_iterator = candidate.source_ranks.find(source_name);
            if (rank_iterator == candidate.source_ranks.end()) {
                candidate.source_ranks[source_name] = rank;
            } else {
                rank_iterator->second = std::min(rank_iterator->second, rank);
            }
            candidate.source_scores[source_name] = row.score;
        }
    }

    std::vector<RetrievedCard> fused;
    fused.reserve(candidates.size());
    for (auto& [card_id, candidate] : candidates) {
        double retrieval_score = 0.0;
        int best_rank = std::numeric_limits<int>::max();
        for (const auto& [source_name, rank] : candidate.source_ranks) {
            (void)source_name;
            retrieval_score += 1.0 / static_cast<double>(k + rank);
            best_rank = std::min(best_rank, rank);
        }
        candidate.retrieval_score = std::round(retrieval_score * 1000000.0) / 1000000.0;
        candidate.score = candidate.retrieval_score;
        fused.push_back(candidate);
    }

    std::sort(fused.begin(), fused.end(), [](const RetrievedCard& left, const RetrievedCard& right) {
        if (left.retrieval_score != right.retrieval_score) {
            return left.retrieval_score > right.retrieval_score;
        }
        const auto left_rank = std::min_element(
            left.source_ranks.begin(),
            left.source_ranks.end(),
            [](const auto& a, const auto& b) { return a.second < b.second; }
        );
        const auto right_rank = std::min_element(
            right.source_ranks.begin(),
            right.source_ranks.end(),
            [](const auto& a, const auto& b) { return a.second < b.second; }
        );
        const int left_best = left_rank == left.source_ranks.end() ? 0 : left_rank->second;
        const int right_best = right_rank == right.source_ranks.end() ? 0 : right_rank->second;
        return left_best < right_best;
    });
    return fused;
}

} // namespace sekret::hybrid
